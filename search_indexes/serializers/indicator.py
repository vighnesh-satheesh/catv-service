import uuid

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
    security_tags = serializers.ListField(read_only=True)
    vector = serializers.ListField(read_only=True)
    environment = serializers.ListField(read_only=True)
    pattern_type = serializers.CharField(read_only=True)
    pattern_subtype = serializers.CharField(read_only=True)
    pattern = serializers.CharField(read_only=True)
    detail = serializers.CharField(read_only=True)
    created = serializers.DateTimeField(read_only=True)
    cases = serializers.ListField(read_only=True)
    annotations = serializers.SerializerMethodField()

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

    def get_annotations(self, obj):
        if obj.annotations:
            return ", ".join(obj.annotations)
        return ""
