import os
import time
from collections import OrderedDict
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.db.models.functions import Lower
from django.db.models.signals import post_save
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
from ..serializers import CATVSerializer
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
    security_tags = serializers.ListField(child=serializers.CharField(), required=False, source='s_tags', default=list)
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
    security_tags = serializers.ListField(child=serializers.CharField(), required=False, source='s_tags', default=list)
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
        if pattern_type == models.IndicatorPatternType.CRYPTOADDR \
            and pattern_subtype == models.IndicatorPatternSubtype.ETH:
            data["pattern"] = validates.get_validated_checksum_addr(
                data["pattern"], api_settings.MAINNET_URL)
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

class CATVInternalSerializer(CATVSerializer):
    source_depth = serializers.IntegerField(required=False, min_value=1, max_value=30)
    distribution_depth = serializers.IntegerField(required=False, min_value=1, max_value=30)

