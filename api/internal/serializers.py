import os
import time
from collections import OrderedDict
from django.db import transaction, IntegrityError
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
    uid = serializers.UUIDField(required=False)
    id = serializers.PrimaryKeyRelatedField(queryset=models.Indicator.objects.all(), required=False)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags", "vector",
                  "environment", "detail", "pattern", "annotation", "reporter_info")
        read_only_fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags",
                            "vector", "environment", "detail", "pattern", "annotation", "reporter_info")

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
    force = serializers.BooleanField(required=False)
    deleted = serializers.BooleanField(required=False)
    uid = serializers.UUIDField(required=False)
    cases = serializers.ListField(required=False)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags", "environment",
                  "vector", "detail", "pattern", "force", "deleted", "cases", "annotation", "reporter_info")
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
        dup = models.Indicator.objects.filter(security_category = data["security_category"],
                                              pattern = data["pattern"],
                                              pattern_type = data["pattern_type"],
                                              pattern_subtype = data["pattern_subtype"])
        cases = data.pop("cases", [])
        force = data.pop("force", False)

        if len(dup) > 0 and not force:
            raise exceptions.DataIntegrityError("duplicate indicator")
        try:
            with transaction.atomic():
                indicator = models.Indicator.objects.create(**data)
                for case in cases:
                    case_instance = models.Case.objects.get(id=case["id"])
                    if case_instance.status not in [models.CaseStatus.NEW, models.CaseStatus.PROGRESS]:
                        raise exceptions.DataIntegrityError("case's status is not 'new' or 'in progress'")
                    models.CaseIndicator.objects.create(case=case_instance, indicator=indicator)
        except IntegrityError:
            raise exceptions.DataIntegrityError("data integrity error")
        except exceptions.DataIntegrityError as err:
            raise err
        except models.Case.DoesNotExist:
            raise exceptions.DataIntegrityError("case does not exist")
        return indicator

    def update(self, instance, data):
        indi_objs = models.Indicator.objects.filter(security_category = data["security_category"],
                                                    pattern = data["pattern"],
                                                    pattern_type = data["pattern_type"],
                                                    pattern_subtype = data["pattern_subtype"])
        cases = data.pop("cases", [])
        force = data.pop("force", False)

        if len(indi_objs) > 0 and not force:
            for indicator in  indi_objs:
                if instance.pk != indicator.pk:
                    raise exceptions.DataIntegrityError("duplicate indicator")

        try:
            with transaction.atomic():
                for case in cases:
                    case_instance = models.Case.objects.get(id=case["id"])
                    if "deleted" in case:
                        models.CaseIndicator.objects.filter(case=case_instance, indicator=instance)
                    if "added" in case:
                        models.CaseIndicator.objects.create(case=case_instance, indicator=instance)
                instance = super().update(instance, data)
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err

        return instance


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
    ico = serializers.PrimaryKeyRelatedField(queryset=models.ICO.objects.all(), required=False)
    indicators = IndicatorPostSerializer(required=False, many=True)
    files = FileItemSerializer(required=False, many=True)

    class Meta:
        model = models.Case
        fields = ("title", "detail", "reporter_info", "ico", "indicators", "files")
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
        try:
            with transaction.atomic():
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
                        if indi["security_category"] is models.IndicatorSecurityCategory.BLACKLIST:
                            ic = models.Indicator.objects.filter(pattern = indi["pattern"]).order_by('-pk').first()
                            if ic and ic.security_category is models.IndicatorSecurityCategory.BLACKLIST:
                                continue
                        new_indicators.append(models.Indicator(**indi))
                indicator_bulk = indicator_bulk + models.Indicator.objects.bulk_create(new_indicators)
                for indicator in indicator_bulk:
                    m2m_bulk.append(models.CaseIndicator(case=case, indicator=indicator))
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

                # save history.
                history_log = Constants.HISTORY_LOG
                history_log["msg"] = models.CaseStatus.NEW.value
                history_log["type"] = "status"

                data = {"log": json.dumps(history_log),
                        "case": case.pk,
                        "initiator": case.reporter.pk if case.reporter is not None else None
                        }
                ch_serializer = CaseHistoryPostSerializer(data=data)
                ch_serializer.is_valid(raise_exception=True)
                ch_serializer.save()
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err
        return case

    def update(self, instance, validated_data):
        indicators_data = validated_data.pop("indicators", [])
        files_data = validated_data.pop("files", [])
        ico = validated_data.pop("ico", None)

        history_log = Constants.HISTORY_LOG
        history_log["type"] = "content"
        history_log["indicatorAdded"] = False
        history_log["indicatorRemoved"] = False
        history_log["indicatorUpdated"] = False
        history_log["fileAdded"] = False
        history_log["fileRemoved"] = False
        history_log["titleUpdated"] = instance.title != validated_data['title']
        history_log["detailUpdated"] = instance.detail != validated_data['detail']
        history_log["relatedProjectUpdated"] = instance.ico != ico

        if history_log["relatedProjectUpdated"]:
            validated_data["ico"] = ico

        try:
            with transaction.atomic():
                # indicators
                for indi_item in indicators_data:
                    if "uid" in indi_item:
                        indicator = models.Indicator.objects.get(uid=indi_item["uid"])
                        if "deleted" in indi_item and indi_item["deleted"] is True:
                            models.CaseIndicator.objects.filter(case=instance, indicator=indicator).delete()
                            history_log['indicatorRemoved'] = True
                    else:
                        indi_item["case"] = instance
                        indicator = models.Indicator.objects.create(**indi_item)
                        models.CaseIndicator.objects.create(case=instance, indicator=indicator)
                        history_log['indicatorAdded'] = True
                # files
                for file_item in files_data:
                    if "uid" not in file_item:  # ignored. file item always has uid.
                        continue
                    if "deleted" in file_item and file_item["deleted"] is True:  # deleted
                        try:
                            file_obj = models.AttachedFile.objects.get(uid=file_item["uid"])
                            file_obj.delete()
                        except models.AttachedFile.DoesNotExist:
                            pass
                        history_log['fileRemoved'] = True
                        continue
                    file_obj = models.AttachedFile.objects.get(uid=file_item["uid"])
                    if not file_obj:
                        continue
                    if file_obj.case is not None and file_obj.case != instance:  # raise exception when file is for other case.
                        raise exceptions.DataIntegrityError("file already included in other cases.")
                    if file_obj.case == instance:
                        continue
                    history_log["fileAdded"] = True
                    file_obj.case = instance
                    file_obj.save()
                # case items
                instance = super().update(instance, validated_data)
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err
        except models.Indicator.DoesNotExist:
            raise exceptions.DataIntegrityError("indicator does not exist")
        except TypeError:
            raise exceptions.DataIntegrityError("TypeError")

        for key, value in history_log.items():
            if isinstance(value, bool) and value == True:
                data = {"log": json.dumps(history_log),
                        "case": instance.pk,
                        "initiator": self.context["request"].user.pk}
                ch_serializer = CaseHistoryPostSerializer(data=data)
                ch_serializer.is_valid(raise_exception=True)
                ch_serializer.save()
                break

        return instance

