import uuid

from django.utils.dateparse import parse_datetime
from django.utils.dateformat import format as formatdate
from rest_framework import serializers

from api.cache import DefaultCache
from api.models import User
from api.settings import api_settings

from ..documents import CaseDocument

__all__ = ('CaseDocumentSerializer',)


class CaseDocumentSerializer(serializers.Serializer):
    """
    Serializer for the Case Elasticsearch document.
    """

    id = serializers.IntegerField(read_only=True)
    uid = serializers.SerializerMethodField()
    title = serializers.CharField(read_only=True)
    created = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    reporter = serializers.SerializerMethodField()
    owned_by = serializers.SerializerMethodField()
    indicators = serializers.SerializerMethodField()

    class Meta(object):

        document = CaseDocument

        fields = (
            'id',
            'uid',
            'title',
            'created',
            'status',
            'reporter',
            'owned_by',
            'indicators'
        )

    def get_uid(self, obj):
        if obj.uid:
            return uuid.UUID(obj.uid.hex)
        return uuid.uuid4()

    def get_created(self, obj):
        if obj.created:
            created_datetime = parse_datetime(obj.created)
            return formatdate(created_datetime, 'U')
        
    def get_reporter(self, obj):
        if obj.reporter:
            cache = DefaultCache()
            cached = cache.get("user_" + str(obj.reporter))
            if cached:
                return {
                    "nickname": cached.nickname,
                    "image": cached.image.url if bool(cached.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                    "uid": cached.uid
                }
            reporter = User.objects.filter(pk=obj.reporter)[:1]
            if reporter:
                return {
                    "nickname": reporter[0].nickname,
                    "image": reporter[0].image.url if bool(reporter[0].image) else api_settings.S3_USER_IMAGE_DEFAULT,
                    "uid": reporter[0].uid
                }
        elif obj.reporter_info:
            return {
                "nickname": obj.reporter_info,
                "image": api_settings.S3_USER_IMAGE_DEFAULT
            }
        return None
    
    def get_owned_by(self, obj):
        if obj.owner:
            cache = DefaultCache()
            cached = cache.get("user_" + str(obj.owner))
            if cached:
                return {
                    "nickname": cached.nickname,
                    "image": cached.image.url if bool(cached.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                    "uid": cached.uid
                }
            owner = User.objects.filter(pk=obj.reporter)[:1]
            if owner:
                return {
                    "nickname": owner[0].nickname,
                    "image": owner[0].image.url if bool(owner[0].image) else api_settings.S3_USER_IMAGE_DEFAULT,
                    "uid": owner[0].uid
                }
        return None

    def get_indicators(self, obj):
        return []
