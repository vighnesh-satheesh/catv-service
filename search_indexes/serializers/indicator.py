import uuid

from django.utils.dateparse import parse_datetime
from django.utils.dateformat import format
from rest_framework import serializers

from ..documents import IndicatorDocument

__all__ = ('IndicatorDocumentSerializer',)


class IndicatorDocumentSerializer(serializers.Serializer):
    """
    Serializer for the Indicator Elasticsearch document.
    """

    id = serializers.IntegerField(read_only=True)
    uid = serializers.SerializerMethodField()
    security_category = serializers.CharField(read_only=True)
    security_tags = serializers.SerializerMethodField()
    vector = serializers.SerializerMethodField()
    environment = serializers.SerializerMethodField()
    pattern_type = serializers.CharField(read_only=True)
    pattern_subtype = serializers.CharField(read_only=True)
    pattern = serializers.CharField(read_only=True)
    detail = serializers.CharField(read_only=True)
    created = serializers.SerializerMethodField()
    cases = serializers.SerializerMethodField()
    annotations = serializers.CharField(read_only=True)

    class Meta(object):

        document = IndicatorDocument

        fields = (
            'id',
            'uid',
            'security_category',
            'security_tags',
            'vector',
            'environment',
            'pattern_type',
            'pattern_subtype',
            'pattern',
            'detail',
            'created',
            'cases',
            'annotations',
        )

    def get_uid(self, obj):
        if obj.uid:
            return uuid.UUID(obj.uid.hex)
        return uuid.uuid4()

    def get_security_tags(self, obj):
        if obj.security_tags:
            return obj.security_tags.split(", ")
        return []

    def get_vector(self, obj):
        if obj.vector:
            return obj.vector.split(", ")
        return []

    def get_environment(self, obj):
        if obj.environment:
            return obj.environment.split(", ")
        return []

    def get_cases(self, obj):
        if obj.cases:
            return obj.cases.split(", ")
        return []

    def get_created(self, obj):
        if obj.created:
            created_datetime = parse_datetime(obj.created)
            return format(created_datetime, 'U')
