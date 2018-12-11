import os
import time
from collections import OrderedDict

from django.contrib.auth.hashers import (check_password, make_password)
from django.core.validators import validate_email
from django.db.models import Q
from django.db import transaction, IntegrityError
from django.utils import timezone
from datetime import timedelta

from rest_framework import serializers

import boto3
import json

from . import validates
from . import exceptions
from . import models
from . import fields
from . import utils
from .settings import api_settings
from .multitoken.tokens_auth import MultiToken
from .multitoken.crypto import decrypt_message
from .constants import Constants

class NonNullModelSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        result = super(NonNullModelSerializer, self).to_representation(instance)
        return OrderedDict([(key, result[key]) for key in result if result[key] is not None])


class CaseSimpleSerializer(NonNullModelSerializer):
    status = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("id", "uid", "status", "created", "title")
        read_only_fields = ("id", "uid", "status", "created", "title")

    def get_status(self, obj):
        return obj.status.value


class IndicatorSimpleListSerializer(NonNullModelSerializer):
    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern")
        read_only_fields = ("id", "uid", "pattern")


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    password = serializers.CharField(required=False, write_only=True, style={'input_type': 'password'})

    def __create_success_response(self, user, token):
        return {
            "accessToken": token.key if user.status == models.UserStatus.APPROVED else "",
            "user": {
                "email": user.email,
                "id": user.uid,
                "nickname": user.nickname,
                "permission": user.permission.value,
                "image": user.image.url if bool(user.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "status": user.status.value
            }
        }

    def validate_email(self, email):
        try:
            validate_email(email)
        except Exception:
            raise exceptions.EmailFormatError()
        return email

    def validate_password(self, password):
        return password

    def validate(self, data):
        request = self.context.get("request", None)
        if request is None:
            raise exceptions.AuthenticationCheckError()

        user = request.user
        token = request.auth

        if user and token:
            return self.__create_success_response(user, token)

        email = data.get("email", None)
        encrypted_pw = data.get("password", None)

        if email is None or encrypted_pw is None:
            raise exceptions.AuthenticationValidationError()

        timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP', None)

        password = decrypt_message(encrypted_pw, timestamp)
        if password is None:
            raise exceptions.AuthenticationValidationError()

        try:
            user = models.User.objects.get(email__iexact=email)
            ret = user.check_password(password)
            if ret is False:
                raise exceptions.AuthenticationCheckError()
        except models.User.DoesNotExist:
            raise exceptions.AuthenticationCheckError()

        if user.status == models.UserStatus.APPROVED:
            token, _ = MultiToken.create_token(user)
        else:
            token = ""
        return self.__create_success_response(user, token)


class ChangePasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})

    class Meta:
        fields = ('new_password')

    def _validate_new_password(self, user, new_pw):
        validates.validate_password(user, new_pw)

    def validate(self, data):
        request = self.context.get("request", None)
        if request is None:
            raise exceptions.DataIntegrityError("no request found")
        enc_new_pw = data.get("new_password", None)
        if enc_new_pw is None:
            raise exceptions.ValidationError("new password is required.")
        timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP', None)
        new_pw = decrypt_message(enc_new_pw, timestamp)
        return {
            "new_pw": new_pw
        }

    def update(self, user, validated_data):
        new_pw = validated_data.get("new_pw", "")
        self._validate_new_password(user, new_pw)
        user.password =  make_password(new_pw)
        user.save()
        return {}


class UserDetailSerializer(serializers.ModelSerializer):
    permission = fields.EnumField(enum=models.UserPermission)
    uid = serializers.UUIDField(required=False, read_only=True)
    created = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()

    class Meta:
        model = models.User
        fields = ("id", "uid", "nickname", "permission", "image", "created")

    def get_queryset(self):
        uuid = self.kwargs["id"]
        return self.model.objects.get(uid__iexact=uuid)

    def get_image(self, obj):
        if bool(obj.image) is False:
            return api_settings.S3_USER_IMAGE_DEFAULT
        else:
            return obj.image.url

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())


class UserPostSerializer(serializers.ModelSerializer):
    permission = fields.EnumField(enum=models.UserPermission, required=False)
    email = serializers.CharField(required=False)
    nickname = serializers.CharField(required=True)
    password = serializers.CharField(allow_blank=True, required=False, write_only=True, style={'input_type': 'password'})
    old_password = serializers.CharField(allow_blank=True, required=False, write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(allow_blank=True, required=False, write_only=True, style={'input_type': 'password'})
    image = serializers.ImageField(required=False,
                                   max_length=10000000,
                                   allow_empty_file=True,
                                   use_url=False)
    class Meta:
        model = models.User
        fields = ("uid", "permission", "email", "nickname", "image", "password", "old_password", "new_password")


    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())

    def validate_email(self, email):
        try:
            validate_email(email)
        except Exception:
            raise exceptions.EmailFormatError()
        return email

    def _validate_old_password(self, user, old_pw):
        ret = user.check_password(old_pw)
        if ret is False:
            raise exceptions.AuthenticationCheckError()

    def _validate_new_password(self, user, new_pw):
        validates.validate_password(user, new_pw)

    def validate(self, data):
        request = self.context.get("request", None)
        if request is None:
            raise exceptions.AuthenticationCheckError()
        if request.method == "POST":
            timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP', None)
            encrypted_pw = data.get("password", None)
            email = data.get("email", None)
            nickname = data.get("nickname", None)
            password = decrypt_message(encrypted_pw, timestamp)
            permission = data.get("permission", None)
            if not timestamp or not password or not email or not permission:
                raise exceptions.ValidationError("invalid data")
            # temporary code: accept only exchanges TODO: remove later
            if permission is not models.UserPermission.EXCHANGE:
                raise exceptions.ValidationError("invalid data")
            # eof temporary code
            self._validate_new_password(user = None, new_pw = password)
            data['password'] = password
            data["status"] = models.UserStatus.SIGNED_UP

        if request.method == "PUT":
            user = request.user
            token = request.auth
            image = request.data.get("image", None)
            if image == "":
                data["image"] = ""
            enc_old_pw = data.get("old_password", None)
            enc_new_pw = data.get("new_password", None)
            if enc_old_pw is not None and enc_new_pw is not None:
                timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP', None)
                old_pw = decrypt_message(enc_old_pw, timestamp)
                new_pw = decrypt_message(enc_new_pw, timestamp)
                if old_pw == new_pw:
                    raise exceptions.ValidationError("old and new password are same.")
                self._validate_old_password(user, old_pw)
                self._validate_new_password(user, new_pw)
                data["new_password"] = new_pw
                try:
                    MultiToken.expire_token(token)
                except self.model.DoesNotExist:
                    pass
                new_token, _ = MultiToken.create_token(user)
                data["token"] = new_token.key
            else:
                data["token"] = token.key
            data["id"] = user.uid

        if len(data["nickname"]) < 4 or len(data["nickname"]) > 32:
            raise exceptions.ValidationError("invalid nickname length")
        return data

    def create(self, validated_data):
        try:
            new_pw = make_password(validated_data["password"])
            validated_data["password"] = new_pw
            instance = models.User.objects.create(**validated_data)
        except IntegrityError as e:
            if "nickname" in str(e):
                raise exceptions.DataIntegrityError("duplicate: nickname")
            elif "email" in str(e):
                raise exceptions.DataIntegrityError("duplicate: email")
            else:
                raise exceptions.DataIntegrityError("")
        return instance


    def update(self, instance, validated_data, *args, **kwargs):
        try:
            instance.update(
                password = validated_data.get("new_password", None),
                image = validated_data.get("image"),
                nickname = validated_data["nickname"]
            )
        except IntegrityError as e:
            if "nickname" in str(e):
                raise exceptions.DataIntegrityError("duplicate: nickname")
            else:
                raise exceptions.DataIntegrityError()
        return instance


class ICFDetailSerializer(NonNullModelSerializer):
    domain = serializers.SerializerMethodField()
    type_id = serializers.SerializerMethodField()

    class Meta:
        model = models.Key
        fields = ("api_key",
                  "request_assign",
                  "request_current",
                  "type_id",
                  "uid",
                  "name",
                  "domain",
                  "domain_restricted",
                  "created",
                  "expire_datetime")

    def get_type_id(self, obj):
        return obj.type_id.value

    def get_domain(self, obj):
        if not obj.domain:
            return []
        return obj.domain


class ICFPostSerializer(serializers.ModelSerializer):
    domain = serializers.SerializerMethodField()
    type_id = serializers.SerializerMethodField()

    class Meta:
        model = models.Key
        fields = ("api_key",
                  "request_assign",
                  "request_current",
                  "type_id",
                  "uid",
                  "name",
                  "domain",
                  "domain_restricted",
                  "created",
                  "expire_datetime")

    def get_type_id(self, obj):
        return obj.type_id.value

    def get_domain(self, obj):
        if not obj.domain:
            return []
        return obj.domain

    def get_object(self, pk):
        try:
            return self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            raise exceptions.ICFNotFound()

    def validate(self, data):
        request = self.context.get("request", None)
        if request is None or request.user is None or request.auth is None:
            raise exceptions.NotAllowedError()
        user = request.user
        if request.method == 'POST':
            obj = models.Key.objects.filter(user = user.pk)
            if obj.exists() == True:
                raise exceptions.ICFAlreadyExist()
            data["user"] = user
            data["expire_datetime"] = timezone.now() + timedelta(days=30)
        return data

    def create(self, validated_data):
        try:
            instance = models.Key.objects.create(**validated_data)
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err
        return instance

    def update(self, obj, request, pk=None):
        prev_key = obj.api_key
        while(True):
            new_key = models.generate_api_key()
            if new_key != prev_key:
                obj.api_key = new_key
                break
        obj.save()
        return obj


class AttachedFileSerializer(NonNullModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = models.AttachedFile
        fields = ("uid", "type", "hash", "size", "uploader", "name", "url",)
        read_only_fields = ("uid", "type", "hash", "size", "uploader", "name", "url")

    def get_url(self, obj):
        if bool(obj.file) is False:
            return None
        return obj.file.url


class AttachedFileTRDBSerializer(NonNullModelSerializer):
    id = serializers.SerializerMethodField()

    class Meta:
        model = models.AttachedFile
        fields = ("id", "type", "hash", "size")
        read_only_fields = ("id", "type", "hash", "size")

    def get_id(self, obj):
        if obj.uid:
            return str(obj.uid)
        else:
            return None


class AttachedFilePostSerializer(NonNullModelSerializer):
    file = serializers.ListField(child=serializers.FileField(max_length=10000000,
                                                             allow_empty_file=False,
                                                             use_url=False))
    rid = serializers.CharField()

    class Meta:
        model = models.AttachedFile
        fields = ("uid", "type", "file", "size", "rid")
        read_only_fields = ("uid", "type", "size")

    def validate_file(self, files):
        if len(files) > api_settings.ATTACHED_FILE_UPLOAD_NUM_LIMIT:
            raise exceptions.ValidationError({"file": "maximum number of upload files is {0}".format(api_settings.ATTACHED_FILE_UPLOAD_NUM_LIMIT)})

        for file in files:
            if len(file.name) > api_settings.ATTACHED_FILE_NAME_MAX_LEN:
                raise exceptions.FileNameTooLong()
            if file.size < api_settings.ATTACHED_FILE_MIN_SIZE:
                raise exceptions.FileSizeTooSmall()
        return files

    def create(self, validated_data):
        filelist = validated_data.pop("file")
        instances = []
        files = []
        for file in filelist:
            instance = models.AttachedFile.objects.create(file=file)
            instances.append(instance)
            files.append(instance.id)
        return instances


class IndicatorDetailSerializer(NonNullModelSerializer):
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory, required=False)
    detail = fields.TruncatedCharField(truncate_len=api_settings.INDICATOR_LIST_DETAIL_LEN,
                                       required=False, allow_blank=True, allow_null=True)
    security_tags = serializers.ListField(child=serializers.CharField(), required=False)
    pattern = serializers.CharField(required=False)
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType, required=False)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype, required=False)
    icos = serializers.SerializerMethodField()
    uid = serializers.UUIDField(required=False)
    id = serializers.PrimaryKeyRelatedField(queryset=models.Indicator.objects.all(), required=False)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags", "detail", "pattern", "icos")
        read_only_fields = ("id", "uid", "icos")

    def __init__(self, *args, **kwargs):
        is_authenticated = False
        if "is_authenticated" in kwargs:
            is_authenticated = kwargs.pop("is_authenticated")

        super(IndicatorDetailSerializer, self).__init__(*args, **kwargs)

        if is_authenticated:
            self.fields["cases"] = CaseSimpleSerializer(read_only=True, many=True)

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

    def get_icos(self, obj):
        ico_objs = []
        for c in obj.cases.all():
            if c.ico is not None:
                ico_objs.append(c.ico)
        ico_serializer = ICOListSerializer(ico_objs, many=True)
        return ico_serializer.data


class IndicatorListSerializer(NonNullModelSerializer):
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype)
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory)
    cases = CaseSimpleSerializer(many=True)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "security_category", "security_tags", "pattern", "pattern_type", "pattern_subtype", "cases", "created")
        read_only_fields = ("id", "uid", "security_category", "security_tags", "pattern", "pattern_type", "pattern_subtype", "cases", "created")

    def __init__(self, *args, **kwargs):
        is_authenticated = False
        if "is_authenticated" in kwargs:
            is_authenticated = kwargs.pop("is_authenticated")

        super(IndicatorListSerializer, self).__init__(*args, **kwargs)

        if is_authenticated:
            self.fields["cases"] = CaseSimpleSerializer(read_only=True, many=True)


class IndicatorPostSerializer(NonNullModelSerializer):
    pattern = serializers.CharField(required=False)
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType, required=False)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype, required=False)
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory, required=False)
    detail = fields.TruncatedCharField(truncate_len=api_settings.INDICATOR_LIST_DETAIL_LEN,
                                       required=False, allow_blank=True, allow_null=True)
    security_tags = serializers.ListField(child=serializers.CharField(), required=False)
    force = serializers.BooleanField(required=False)
    deleted = serializers.BooleanField(required=False)
    uid = serializers.UUIDField(required=False)
    cases = serializers.ListField(required=False)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags", "detail", "pattern", "force", "deleted", "cases")
        read_only_fields = ("id", "uid", "force", "deleted")

    def validate(self, data):
        pattern_type = data.get("pattern_type")
        pattern_subtype = data.get("pattern_subtype", None)
        validates.validate_pattern_type_subtype(pattern_type, pattern_subtype)

        security_category = data.get("security_category")
        security_tags = data.get("security_tags", None)
        validates.validate_security_type_tag(security_category, security_tags)
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
                    case_instance.indicators.add(indicator)
                    indicator.cases.add(case_instance)
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
                        instance.cases.remove(case_instance)
                        case_instance.indicators.remove(instance)
                    if "added" in case:
                        instance.cases.add(case_instance)
                        case_instance.indicators.add(instance)
                instance = super().update(instance, data)
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err

        return instance


class IndicatorTRDBSerializer(NonNullModelSerializer):
    id = serializers.SerializerMethodField()
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype)
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory)

    class Meta:
        model = models.Indicator
        fields = ("id", "security_category", "security_tags", "pattern", "pattern_type", "pattern_subtype")
        read_only_fields = ("id", "security_category", "security_tags", "pattern", "pattern_type", "pattern_subtype")

    def get_id(self, obj):
        if obj.uid:
            return str(obj.uid)
        else:
            return None


class ICOSerializer(NonNullModelSerializer):
    uid = serializers.UUIDField(required=False, read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = models.ICO
        fields = ("id", "uid", "name", "symbol", "image_url", "detail")

    def get_image_url(self, obj):
        if bool(obj.image) is False:
            return api_settings.S3_ICO_IMAGE_DEFAULT
        else:
            return obj.image.url


class ICOTRDBSerializer(NonNullModelSerializer):
    id = serializers.SerializerMethodField()

    class Meta:
        model = models.ICO
        fields = ("id", "name", "symbol")

    def get_id(self, obj):
        if obj.uid:
            return str(obj.uid)
        else:
            return None


class ICOListSerializer(NonNullModelSerializer):
    detail = fields.TruncatedCharField(truncate_len=api_settings.ICO_LIST_DETAIL_LEN)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = models.ICO
        fields = ("id", "uid", "name", "symbol", "image_url", "type",
                  "detail", "category", "opened", "closed")
        read_only_fields = ("id", "uid", "name", "symbol", "image_url",
                            "type", "detail", "category", "opened", "closed")

    def get_image_url(self, obj):
        if bool(obj.image) is False:
            return api_settings.S3_ICO_IMAGE_DEFAULT
        else:
            return obj.image.url


class ICODetailSerializer(NonNullModelSerializer):
    indicators = serializers.SerializerMethodField()
    opened = serializers.SerializerMethodField()
    closed = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = models.ICO
        fields = ("id", "uid", "name", "detail", "symbol", "image_url", "subtitle", "indicators",
                  "platform", "category", "country", "opened", "closed", "type", "website")
        read_only_fields = ("id", "uid", "indicators")

    @property
    def blacklist_limit(self):
        return api_settings.ICO_BLACKLIST_LIMIT

    def get_image_url(self, obj):
        if bool(obj.image) is False:
            return api_settings.S3_ICO_IMAGE_DEFAULT
        else:
            return obj.image.url

    def get_opened(self, obj):
        if obj.opened is None:
            return None
        return time.mktime(obj.opened.timetuple())

    def get_closed(self, obj):
        if obj.closed is None:
            return None
        return time.mktime(obj.closed.timetuple())

    def get_indicators(self, obj):
        try:
            case_queryset = models.Case.objects.filter(Q(ico=obj.pk) & Q(status=models.CaseStatus.RELEASED))
            if len(case_queryset) > 0:
                blacklist = []
                whitelist = []
                for case in case_queryset:
                    blacklist.extend(case.indicators.filter(security_category=models.IndicatorSecurityCategory.BLACKLIST))
                    whitelist.extend(case.indicators.filter(security_category=models.IndicatorSecurityCategory.WHITELIST))

                white_se = IndicatorListSerializer(whitelist, many=True)
                black_se = IndicatorListSerializer(blacklist, many=True)

                return {"whitelist": white_se.data,
                        "blacklist": black_se.data}
            else:
                return {
                    "whitelist": [],
                    "blacklist": []
                }
        except models.Case.DoesNotExist:
            pass
        except models.Indicator.DoesNotExist:
            pass
        return {}


class TRDBCaseTransactionSerializer(NonNullModelSerializer):
    class Meta:
        model = models.TRDBCaseTransaction
        fields = ("block_num", "transaction_id")
        read_only_fields = ("block_num", "transaction_id")


class CaseSimpleListSerializer(NonNullModelSerializer):
    status = fields.EnumField(enum=models.CaseStatus)
    ico = ICOSerializer(read_only=True)
    created = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("id", "uid", "title", "ico", "created", "status")
        read_only_fields = ("id", "uid", "title", "ico", "created", "status")

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())

class CaseListSerializer(NonNullModelSerializer):
    status = fields.EnumField(enum=models.CaseStatus)
    ico = ICOSerializer(read_only=True)
    detail = fields.TruncatedCharField(truncate_len=api_settings.CASE_LIST_DETAIL_LEN)
    owned_by = serializers.SerializerMethodField()
    indicator_summary = serializers.SerializerMethodField()
    created = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("id", "uid", "title", "detail", "created", "status", "owned_by", "ico", "indicator_summary")
        read_only_fields = ("id", "uid", "title", "detail", "created", "status", "owned_by", "ico", "indicator_summary")

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())

    def get_owned_by(self, obj):
        if obj.owner:
            return {
                "nickname": obj.owner.nickname,
                "image": obj.owner.image.url if bool(obj.owner.image) else api_settings.S3_USER_IMAGE_DEFAULT
            }
        return None

    def get_indicator_summary(self, obj):
        indicator_summary = {}
        net_objs = obj.indicators.filter(pattern_type = models.IndicatorPatternType.NETWORKADDR).order_by('-created')
        crypto_objs = obj.indicators.filter(pattern_type = models.IndicatorPatternType.CRYPTOADDR).order_by('-created')
        indicator_summary["network_address_count"] = len(net_objs)
        indicator_summary["crypto_address_count"] = len(crypto_objs)
        if net_objs:
            indicator_summary["network_address"] = IndicatorSimpleListSerializer(net_objs[:3], many=True).data
        else:
            indicator_summary["network_address"] = []
        if crypto_objs:
            indicator_summary["crypto_address"] = IndicatorSimpleListSerializer(crypto_objs[:3], many=True).data
        else:
            indicator_summary["crypto_address"] = []
        return indicator_summary


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


class CaseHistoryListSerializer(serializers.ModelSerializer):
    created = serializers.SerializerMethodField()
    initiator = serializers.SerializerMethodField()

    class Meta:
        model = models.CaseHistory
        fields = ("log", "created", "initiator")
        read_only_fields = ("log", "created")

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())

    def get_initiator(self, obj):
        if obj.initiator is not None:
            return {
                "nickname": obj.initiator.nickname,
                "uid": obj.initiator.uid
            }
        else:
            return ""

class FileItemSerializer(serializers.Serializer):
    uid = serializers.UUIDField()
    deleted = serializers.BooleanField(required=False)


class CasePostSerializer(serializers.ModelSerializer):
    title = serializers.CharField(required=True, max_length=api_settings.CASE_TITLE_MAX_LEN)
    detail = serializers.CharField(required=True, max_length=api_settings.CASE_DETAIL_MAX_LEN)
    reporter_info = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=api_settings.CASE_REPORTER_MAX_LEN)
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
                for indi in indicators_data:
                    if "uid" in indi:
                        indicator = models.Indicator.objects.get(uid=indi["uid"])
                    else:
                        indicator = models.Indicator.objects.create(case=case, **indi)
                    indicator.cases.add(case)
                    case.indicators.add(indicator)

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
                            indicator.cases.remove(instance)
                            instance.indicators.remove(indicator)
                            history_log['indicatorRemoved'] = True
                    else:
                        indi_item["case"] = instance
                        indicator = models.Indicator.objects.create(**indi_item)
                        indicator.cases.add(instance)
                        instance.indicators.add(indicator)
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


class CaseDetailSerializer(NonNullModelSerializer):
    status = fields.EnumField(enum=models.CaseStatus, required=False)
    uid = serializers.UUIDField(required=False, read_only=True)
    ico = ICOSerializer(read_only=True)
    owned_by = serializers.SerializerMethodField()
    verified_by = serializers.SerializerMethodField()
    reported_by = serializers.SerializerMethodField()
    histories = serializers.SerializerMethodField()
    indicators = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()
    created = serializers.SerializerMethodField()
    trdb = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("id", "uid", "title", "detail", "created", "status", "reported_by",
                  "owned_by", "verified_by", "trdb", "ico", "histories", "indicators", "files")

    def get_queryset(self):
        uuid = self.kwargs["id"]
        return self.model.objects.get(uid__iexact=uuid)

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())

    def get_histories(self, obj):
        try:
            queryset = models.CaseHistory.objects.filter(case=obj.pk).order_by("-created")
            history_serializer = CaseHistoryListSerializer(queryset, many=True)
            return history_serializer.data
        except models.CaseHistory.DoesNotExist:
            pass
        return []

    def get_indicators(self, obj):
        try:
            queryset = obj.indicators.all()
            indicator_serializer = IndicatorListSerializer(queryset, many=True)
            return indicator_serializer.data
        except models.Indicator.DoesNotExist:
            pass
        return []

    def get_files(self, obj):
        files = []
        file_objs = models.AttachedFile.objects.filter(case=obj.pk).order_by("pk")
        if len(file_objs) > 0:
            file_serializer = AttachedFileSerializer(file_objs, many=True, context=self.context)
            files = file_serializer.data
        return files

    def get_trdb(self, obj):
        trdb_objs = models.TRDBCaseTransaction.objects.filter(case_uid=obj.uid).order_by('-pk')
        if len(trdb_objs) == 0:
            return None

        trdb_obj = trdb_objs[0]
        if trdb_obj.block_num is None or trdb_obj.transaction_id is None:
            return None
        serializer = TRDBCaseTransactionSerializer(trdb_obj)
        return serializer.data

    def get_owned_by(self, obj):
        if obj.owner:
            return {
                "nickname": obj.owner.nickname,
                "uid": obj.owner.uid
            }
        return None

    def get_reported_by(self, obj):
        if obj.reporter:
            return {
                "nickname": obj.reporter.nickname,
                "uid": obj.reporter.uid
            }
        return None

    def get_verified_by(self, obj):
        if obj.verifier:
            return {
                "nickname": obj.verifier.nickname,
                "uid": obj.verifier.uid
            }
        return None


class CaseTRDBSerializer(NonNullModelSerializer):
    id = serializers.SerializerMethodField()
    ico = ICOTRDBSerializer(read_only=True)
    owned_by = serializers.SerializerMethodField()
    verified_by = serializers.SerializerMethodField()
    reported_by = serializers.SerializerMethodField()
    indicators = serializers.SerializerMethodField()
    created = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("id", "title", "created", "reported_by",
                  "owned_by", "verified_by", "ico", "indicators")

    def get_id(self, obj):
        if obj.uid:
            return str(obj.uid)
        else:
            return None

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())

    def get_indicators(self, obj):
        try:
            queryset = obj.indicators.all()
            indicator_serializer = IndicatorTRDBSerializer(queryset, many=True)
            return indicator_serializer.data
        except models.Indicator.DoesNotExist:
            pass
        return []

    def get_files(self, obj):
        files = []
        file_objs = models.AttachedFile.objects.filter(case=obj.pk).order_by("pk")
        if len(file_objs) > 0:
            file_serializer = AttachedFileTRDBSerializer(file_objs, many=True, context=self.context)
            files = file_serializer.data
        return files

    def get_owned_by(self, obj):
        if obj.owner:
            return {"id": str(obj.owner.uid)}
        return None

    def get_reported_by(self, obj):
        if obj.reporter:
            return {"id": str(obj.reporter.uid)}
        return None

    def get_verified_by(self, obj):
        if obj.verifier:
            return {"id": str(obj.verifier.uid)}
        return None


class CasePatchSerializer(NonNullModelSerializer):
    status = fields.EnumField(enum=models.CaseStatus, required=True)

    class Meta:
        model = models.Case
        fields = ("status",)
        read_only_fields = ("id", "uid", "created")

    def validate_status(self, status):
        request = self.context["request"]
        user_permission = getattr(request.user, "permission", None)
        is_super = True if user_permission == models.UserPermission.SUPERSENTINEL else False
        is_owner = True if request.user == self.instance.owner else False

        utils.CASE_STATUS_FSM.validate(self.instance.status, status, is_super, is_owner)
        return status

    def update(self, instance, validated_data):
        if validated_data["status"] == models.CaseStatus.NEW:
            instance.owner = None
        elif validated_data["status"] == models.CaseStatus.PROGRESS:
            instance.owner = self.context["request"].user
        elif validated_data["status"] == models.CaseStatus.CONFIRMED:  # confirmed status should contain at least one indicator.
            if not instance.indicators:
                raise exceptions.ValidationError("at least one indicator should be contained.")
        elif validated_data["status"] == models.CaseStatus.RELEASED:
            instance.verifier = self.context["request"].user
        elif validated_data["status"] == models.CaseStatus.REJECTED:
            instance.verifier = self.context["request"].user

        history_log = Constants.HISTORY_LOG
        history_log["type"] = "status"
        history_log["msg"] = validated_data["status"].value

        data = {"log": json.dumps(history_log),
                "case": instance.pk,
                "initiator": self.context["request"].user.pk}

        ch_serializer = CaseHistoryPostSerializer(data=data)
        ch_serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                if validated_data["status"] == models.CaseStatus.RELEASED:  # activate case
                    case_serializer = CaseTRDBSerializer(instance)
                    data = case_serializer.data
                    utils.TRDB_CLIENT.push_case("activateCase", data)
                elif (instance.status == models.CaseStatus.RELEASED and
                      validated_data["status"] == models.CaseStatus.REJECTED):  # deactivate case
                    case_serializer = CaseTRDBSerializer(instance)
                    data = case_serializer.data
                    utils.TRDB_CLIENT.push_case("deactivateCase", data)
                ch_serializer.save()
                return super(CasePatchSerializer, self).update(instance, validated_data)
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        return {}


class AutoCompleteSerializer(serializers.Serializer):
    q = serializers.CharField(required=True)
    type = serializers.CharField(required=True)
    filter = serializers.ListField(required=False)

    class Meta:
        fields = ("q", "type", "filter")

    @property
    def result_limit(self):
        return api_settings.AUTO_COMPLETE_LIMIT

    def _validate_type(self, auto_type):
        if auto_type.lower() not in  ["ico", "indicator", "case", "user"]:
            raise exceptions.ValidationError("not supported type")

    def validate(self, data):
        query = data.get("q", None)
        auto_type = data.get("type", None)
        filter = data.get("filter", None)

        self._validate_type(auto_type)

        if auto_type == "ico":
            icos = []
            filter_queries = Q(symbol__istartswith=query)
            if len(query) > 1:
                filter_queries |= Q(name__icontains=query)

            ico_objs = models.ICO.objects.filter(filter_queries)[:self.result_limit]

            if ico_objs:
                ico_serializer = ICOListSerializer(ico_objs, many=True)
                icos = ico_serializer.data
            return {"icos": icos}

        elif auto_type == "indicator":
            indicators = []
            suffix = ("https://www.", "http://www.", "www.", "0x", "0X")
            idx = -1
            for s in suffix:
                try:
                    idx = s.index(query)
                    if idx == 0:
                        break
                except ValueError:
                    continue
            if idx == 0:
                return {"indicators": indicators}

            if len(query) < 3:
                return {"indaicators": indicators}

            indicator_objs = models.Indicator.objects.filter(pattern__istartswith=query)
            if indicator_objs:
                indicator_serializer = IndicatorListSerializer(indicator_objs, many=True)
                indicators = indicator_serializer.data
            return {"indicators": indicators}

        elif auto_type == "user":
            users = []
            users_objs = models.User.objects.filter(nickname__istartswith=query)
            if users_objs:
                user_serializer = UserDetailSerializer(users_objs, many=True)
                users = user_serializer.data
            return {"users": users}

        elif auto_type == 'case':
            cases = []
            filter_queries = Q(status__in = filter)
            if query.isdigit():
                filter_queries &= Q(id=int(query))
            elif len(query) > 1:
                filter_queries &= Q(title__icontains=query)
            case_objs = models.Case.objects .filter(filter_queries).order_by('-created')
            if case_objs:
                case_serializer = CaseSimpleListSerializer(case_objs, many=True)
                cases = case_serializer.data
            return {
                "cases": cases
            }
        return {}


class UppwardRewardInfoPostSerializer(serializers.ModelSerializer):
    aid = serializers.CharField(required=True, max_length=100)
    uid = serializers.CharField(required=True, max_length=100)
    cid = serializers.CharField(required=True, max_length=100)
    referral_code = serializers.CharField(required=True, max_length=100)
    token_addr = serializers.CharField(required=True, max_length=100)

    class Meta:
        model = models.UppwardRewardInfo
        fields = ("aid", "uid", "cid", "referral_code", "token_addr")

    def create(self, validated_data):
        try:
            with transaction.atomic():
                obj = models.UppwardRewardInfo.objects.create(**validated_data)
                return obj
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err
        return None


class ProjectPostSerializer(NonNullModelSerializer):
    name = serializers.CharField()
    type = serializers.CharField()
    subtitle = serializers.CharField()
    detail = serializers.CharField()
    category = serializers.CharField()
    cases = serializers.ListField(required=False)

    class Meta:
        model = models.ICO
        fields = ("id", "uid", "name", "symbol", "type", "subtitle", "detail", "category", "website", "opened", "closed", "image", "cases",)
        read_only_field = ("cases", "image")

    def validate(self, data):
        return data

    def create(self, validated_data):
        cases = validated_data.pop("cases", [])
        try:
            with transaction.atomic():
                obj = models.ICO.objects.create(**validated_data)
                if cases:
                    for id in cases:
                        case = models.Case.objects.get(id=id)
                        if case.status == models.CaseStatus.RELEASED:
                            raise exceptions.DataIntegrityError("case " + str(id) + " is in released status")
                        case.ico = obj
                        case.save()
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err
        except models.Case.DoesNotExist:
            raise exceptions.DataIntegrityError("case does not exist")
        return obj


class CommentSerializer(NonNullModelSerializer):
    body = serializers.SerializerMethodField()
    writer = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()

    class Meta:
        model = models.Comment
        fields = ("id", "uid", "writer", "body", "created", "deleted", "editable")
        read_only_fields = ("id", "uid", "created", "editable", "writer")

    def get_body(self, obj):
        if obj.deleted:
            return ""
        else:
            return obj.body

    def get_writer(self, obj):
        if not obj.writer:
            return {}
        return {
            "nickname": obj.writer.nickname,
            "image": api_settings.S3_USER_IMAGE_DEFAULT if bool(obj.writer.image) is False else obj.writer.image.url,
            "uid": obj.writer.uid
        }

    def get_editable(self, obj):
        request = self.context["request"]
        if not obj:
            return ""
        if request.user == obj.writer and not obj.deleted:
            return True
        else:
            return False


class CommentPostSerializer(NonNullModelSerializer):
    case = serializers.PrimaryKeyRelatedField(queryset=models.Case.objects.all(), required=False)
    indicator = serializers.PrimaryKeyRelatedField(queryset=models.Indicator.objects.all(), required=False)
    ico = serializers.PrimaryKeyRelatedField(queryset=models.ICO.objects.all(), required=False)

    class Meta:
        model = models.Comment
        fields = ("id", "uid", "case", "indicator", "ico", "writer", "body", "created", "deleted")
        read_only_fields = ("id", "uid", "created")

    def validate(self, data):
        request = self.context["request"]
        body = data.get("body", "")
        if len(body) > api_settings.COMMENT_BODY_MAX_LEN:
            raise exceptions.ValidationError("the maximum length for the comment body exceeds")
        if len(body) == 0:
            raise exceptions.ValidationError("empty body")
        data["writer"] = request.user
        return data

    def create(self, data):
        try:
            with transaction.atomic():
                obj = models.Comment.objects.create(**data)
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err
        return obj


class NotificationSerializer(NonNullModelSerializer):
    user = serializers.SerializerMethodField()
    initiator = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = models.Notification
        fields = ("uid", "user", "initiator", "target", "read", "created", "type")

    def get_user(self, obj):
        if not obj.user:
            return {}
        return {
            "nickname": obj.user.nickname,
            "image": api_settings.S3_USER_IMAGE_DEFAULT if bool(obj.user.image) is False else obj.user.image.url,
            "uid": obj.user.uid
        }

    def get_initiator(self, obj):
        if not obj:
            return {}
        return {
            "nickname": obj.initiator.nickname,
            "image": api_settings.S3_USER_IMAGE_DEFAULT if bool(obj.initiator.image) is False else obj.initiator.image.url,
            "uid": obj.initiator.uid
        }

    def get_type(self, obj):
        return obj.type.value
