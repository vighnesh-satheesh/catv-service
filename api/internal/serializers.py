import os
import time
from collections import OrderedDict
from django.db import transaction, IntegrityError
from django.db.models import Q
from rest_framework import serializers

import boto3
import json

from .. import validates
from .. import exceptions
from .. import models
from .. import fields
from ..settings import api_settings
from ..constants import Constants
from indicatorlib import Pattern
from ..serializers import CaseTRDBSerializer
from .. import utils

class NonNullModelSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        result = super(NonNullModelSerializer, self).to_representation(instance)
        return OrderedDict([(key, result[key]) for key in result if result[key] is not None])


class IndicatorSimpleListSerializer(NonNullModelSerializer):
    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern")
        read_only_fields = ("id", "uid", "pattern")


class IndicatorDetailSerializer(NonNullModelSerializer):
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory, required=False)
    detail = fields.TruncatedCharField(truncate_len=api_settings.INDICATOR_LIST_DETAIL_LEN,
                                       required=False, allow_blank=True, allow_null=True)
    security_tags = serializers.ListField(child=serializers.CharField(), required=False)
    vector = serializers.ListField(child=fields.EnumField(enum=models.IndicatorVector), required=False)
    environment = serializers.ListField(child=fields.EnumField(enum=models.IndicatorEnvironment), required=False)
    pattern = serializers.CharField(required=False)
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType, required=False)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype, required=False)
    annotation = serializers.CharField(required=False)
    annotations = serializers.SerializerMethodField()
    uid = serializers.UUIDField(required=False)
    id = serializers.PrimaryKeyRelatedField(queryset=models.Indicator.objects.all(), required=False)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags", "vector",
                  "environment", "detail", "pattern", "annotation", "reporter_info", "annotations")
        read_only_fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags",
                            "vector", "environment", "detail", "pattern", "annotation", "reporter_info", "annotations")

    def validate(self, attrs):
        id = attrs.get("id")
        if id:
            return super(IndicatorDetailSerializer, self).validate(attrs)
        pattern_type = attrs.get("pattern_type")
        pattern_subtype = attrs.get("pattern_subtype", None)
        validates.validate_pattern_type_subtype(pattern_type, pattern_subtype)

        security_category = attrs.get("security_category")
        security_tags = attrs.get("security_tags", None)
        validates.validate_security_type_tag(security_category, security_tags)

        return super(IndicatorDetailSerializer, self).validate(attrs)

    def get_annotations(self, obj):
        data = []
        annotations = obj.annotations.all()
        for annotation in annotations:
            data.append(annotation.annotation)
        return data


class IndicatorPostSerializer(NonNullModelSerializer):
    pattern = serializers.CharField(required=False)
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType, required=False)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype, required=False)
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory, required=False)
    detail = fields.TruncatedCharField(truncate_len=api_settings.INDICATOR_LIST_DETAIL_LEN,
                                       required=False, allow_blank=True, allow_null=True)
    security_tags = serializers.ListField(child=serializers.CharField(), required=False)
    vector = serializers.ListField(child=fields.EnumField(enum=models.IndicatorVector), required=False)
    environment = serializers.ListField(child=fields.EnumField(enum=models.IndicatorEnvironment), required=False)
    annotation = serializers.CharField(required=False)
    reporter_info = serializers.CharField(required=False)
    user = serializers.CharField(required=False)
    force = serializers.BooleanField(required=False)
    deleted = serializers.BooleanField(required=False)
    uid = serializers.UUIDField(required=False)
    cases = serializers.ListField(required=False)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags", "environment",
                  "vector", "detail", "pattern", "force", "deleted", "cases", "annotation", "reporter_info", "user")
        read_only_fields = ("id", "uid", "force", "deleted")

    def validate(self, data):
        pattern_type = data.get("pattern_type")
        pattern_subtype = data.get("pattern_subtype", None)
        validates.validate_pattern_type_subtype(pattern_type, pattern_subtype)

        security_category = data.get("security_category")
        security_tags = data.get("security_tags", None)
        vector = data.get("vector", None)
        environment = data.get("environment", None)
        validates.validate_security_type_tag(security_category, security_tags)
        validates.validate_indicator_vector(vector)
        validates.validate_indicator_environment(environment)
        return data

    def create(self, data):
        cases = data.pop("cases", [])
        force = data.pop("force", None)


        if not force:
            dup = models.Indicator.objects.filter(pattern = data["pattern"]).order_by('-id')[:1]
            if len(dup) > 0 and dup[0].security_category == data["security_category"]:
                raise exceptions.DataIntegrityError("duplicate indicator")

        try:
            with transaction.atomic():
                user = data.pop("user", None)
                if user is not None:
                    data["user"] = models.User.objects.get(id=user)
                indicator = models.Indicator.objects.create(**data)
                for case in cases:
                    case_instance = models.Case.objects.get(id=case["id"])
                    if case_instance.status not in [models.CaseStatus.NEW, models.CaseStatus.PROGRESS]:
                        raise exceptions.DataIntegrityError("case's status is not 'new' or 'in progress'")
                    models.CaseIndicator.objects.create(case=case_instance, indicator=indicator)

                if "annotation" in data:
                    for annotation in [x.strip() for x in data["annotation"].split(",")]:
                        if len(annotation) == 0:
                            continue
                        anno = models.Annotation.objects.filter(annotation=annotation)
                        if len(anno) > 0:
                            anno = anno[0]
                        else:
                            anno = models.Annotation.objects.create(annotation=annotation)
                        models.IndicatorAnnotation.objects.create(indicator=indicator, annotation=anno)

        except IntegrityError:
            raise exceptions.DataIntegrityError("data integrity error")
        except exceptions.DataIntegrityError as err:
            raise err
        except models.User.DoesNotExist:
            raise exceptions.DataIntegrityError("user does not exist")
        except models.Case.DoesNotExist:
            raise exceptions.DataIntegrityError("case does not exist")
        return indicator


class CaseHistoryPostSerializer(serializers.ModelSerializer):
    created = serializers.SerializerMethodField()

    class Meta:
        model = models.CaseHistory
        fields = ("id", "log", "created", "case", "initiator")
        read_only_fields = ("id", "created")

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())


class FileItemSerializer(serializers.Serializer):
    uid = serializers.UUIDField()
    deleted = serializers.BooleanField(required=False)


class CasePostSerializer(serializers.ModelSerializer):
    title = serializers.CharField(required=True, max_length=api_settings.CASE_TITLE_MAX_LEN)
    detail = serializers.CharField(required=True, max_length=api_settings.CASE_DETAIL_MAX_LEN)
    reporter_info = serializers.CharField(required=False,
                                          allow_blank=True,
                                          allow_null=True,
                                          max_length=api_settings.CASE_REPORTER_MAX_LEN)
    reporter = serializers.CharField(required=False)
    release = serializers.BooleanField(required=False)
    ico = serializers.PrimaryKeyRelatedField(queryset=models.ICO.objects.all(), required=False)
    indicators = IndicatorPostSerializer(required=False, many=True)
    files = FileItemSerializer(required=False, many=True)

    class Meta:
        model = models.Case
        fields = ("title", "detail", "reporter_info", "reporter", "ico", "indicators", "files", "release")
        read_only_fields = ("id", "uid", "created")

    def validate_files(self, data):
        return data

    def validate_inidcators(self, data):  # TODO: more specific error message.
        return data

    def __upload_files(self, files):
        s3 = boto3.resource('s3')
        bucket_name = api_settings.ATTACHED_FILE_S3_BUCKET_NAME
        for obj in files:
            full_path = os.path.join(api_settings.ATTACHED_FILE_SAVE_PATH, str(obj.uid))
            key_name = api_settings.ATTACHED_FILE_S3_KEY_PREFIX + str(obj.uid)
            try:
                f = open(full_path, "rb")
                s3.Bucket(bucket_name).put_object(ACL='private', Key=key_name, Body=f)
            except IOError as err:
                raise err
            else:
                f.close()

    def create(self, validated_data):
        indicators_data = validated_data.pop("indicators", [])
        files_data = validated_data.pop("files", [])
        release = validated_data.pop("release", False)

        try:
            reporter = validated_data.pop("reporter", None)
            if reporter:
                validated_data["reporter"] = models.User.objects.get(id=reporter)
        except models.User.DoesNotExist:
            raise exceptions.DataIntegrityError("invalid user id")
        except ValueError:
            raise exceptions.DataIntegrityError("invalid user id")

        try:
            with transaction.atomic():
                if release:
                    validated_data["status"] = models.CaseStatus.RELEASED
                case = models.Case.objects.create(**validated_data)
                m2m_bulk = []
                indicator_bulk = []
                new_indicators = []
                for indi in indicators_data:
                    if "uid" in indi:
                        indicator = models.Indicator.objects.get(uid=indi["uid"])
                        indicator_bulk.append(indicator)
                    else:
                        if indi["pattern_type"] in [models.IndicatorPatternType.NETWORKADDR, models.IndicatorPatternType.SOCIALMEDIA]:
                            indi["pattern_tree"] = Pattern.getMaterializedPathForInsert(indi["pattern"].lower().rstrip('/'))

                        # inherit from the case
                        if reporter is not None:
                            indi["user"] = validated_data["reporter"]
                        else:
                            user = indi.pop("user", None)
                            if user is not None:
                                indi["user"] = models.User.objects.get(id=user)

                        if "reporter_info" in validated_data:
                            indi["reporter_info"] = validated_data["reporter_info"]

                        force = indi.pop("force", None)
                        dup = []
                        if not force:
                            if indi["pattern_subtype"] == "ETH":
                                filter_queries = Q(pattern__iexact=indi["pattern"])
                            else:
                                filter_queries = Q(pattern=indi["pattern"])
                            dup = models.Indicator.objects.filter(filter_queries).order_by("-id")[:1]

                        if len(dup) > 0 and (dup[0].security_category == indi["security_category"] or dup[0].security_category is models.IndicatorSecurityCategory.WHITELIST):
                            if force is False:
                                raise exceptions.DataIntegrityError("duplicate indicator")
                            else:
                                continue
                        else:
                            new_indicators.append(models.Indicator(**indi))

                indicator_bulk = indicator_bulk + models.Indicator.objects.bulk_create(new_indicators)

                if len(indicator_bulk) == 0:
                    raise exceptions.DataIntegrityError("Posted case has no valid indicator to be added. ")

                for indicator in indicator_bulk:
                    m2m_bulk.append(models.CaseIndicator(case=case, indicator=indicator))
                    # annotation
                    if indicator.annotation:
                        for annotation in [x.strip() for x in indicator.annotation.split(",")]:
                            if len(annotation) == 0:
                                continue
                            anno = models.Annotation.objects.filter(annotation=annotation)
                            if len(anno) > 0:
                                anno = anno[0]
                            else:
                                anno = models.Annotation.objects.create(annotation=annotation)
                            models.IndicatorAnnotation.objects.create(indicator=indicator, annotation=anno)

                models.CaseIndicator.objects.bulk_create(m2m_bulk)

                if len(files_data) > api_settings.CASE_ATTACHED_FILE_MAX_LIMIT:
                    raise exceptions.ValidationError({"files": "one case cannot have more than 20 files."})

                # save file.
                for file_item in files_data:
                    file_obj = models.AttachedFile.objects.get(uid=file_item["uid"])
                    if file_obj.case is not None:
                        raise exceptions.DataIntegrityError("file already included in other cases.")
                    file_obj.case = case
                    file_obj.save()


                if release:
                    case_serializer = CaseTRDBSerializer(case)
                    data = case_serializer.data
                    utils.TRDB_CLIENT.push_case("activateCase", data)

        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err
        except models.User.DoesNotExist:
            raise exceptions.DataIntegrityError("invalid user/reporter id")
        except Exception as err:
            raise err
        return case
