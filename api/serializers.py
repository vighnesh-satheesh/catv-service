import os
import time
import re
from collections import OrderedDict

from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.contrib.auth.hashers import (check_password, make_password)
from django.core.validators import validate_email
from django.db import transaction, IntegrityError
from django.db.models import Q, Value, BooleanField
from django.db.models.signals import post_save
from django.utils import timezone
from web3 import Web3

from rest_framework import serializers

import boto3
import json
from requests.exceptions import ReadTimeout

from . import validates
from . import exceptions
from . import models
from . import fields
from . import utils
from .settings import api_settings
from .multitoken.tokens_auth import MultiToken
from .multitoken.crypto import decrypt_message
from .constants import Constants
from .cache.uppward import UppwardCache
from indicatorlib import Pattern
from .cache import DefaultCache
from .catvutils.tracking_results import (
    TrackingResults, BTCTrackingResults,
    BTCCoinpathTrackingResults, EthPathResults,
    BtcPathResults
)
from .catvutils.vendor_api import LyzeAPIInterface
from .tasks import CaseMessageTask, UserRoleUpdateTask


class NonNullModelSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        result = super(NonNullModelSerializer,
                       self).to_representation(instance)
        return OrderedDict([(key, result[key]) for key in result if result[key] is not None])


class UserRelatedField(serializers.RelatedField):
    def to_representation(self, value):
        return {
            "email": value.email,
            "nickname": value.nickname,
            "uid": value.uid
        }

    def to_internal_value(self, data):
        try:
            user_uid = data
            return models.User.objects.get(uid=user_uid)
        except ValueError:
            raise serializers.ValidationError(
                'administrator uid must be a string')
        except models.User.DoesNotExist:
            raise serializers.ValidationError('user does not exist')


class OrganizationRelatedField(serializers.RelatedField):
    def to_representation(self, value):
        return value.uid

    def to_internal_value(self, data):
        try:
            org_uid = data
            return models.Organization.objects.get(uid=org_uid)
        except ValueError:
            raise serializers.ValidationError(
                'organization uid must be a string')
        except models.Organization.DoesNotExist:
            return models.Organization.objects.none()


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
    password = serializers.CharField(required=False, write_only=True, style={
        'input_type': 'password'})

    def __create_success_response(self, user, token):
        organization_id, is_admin = self.check_organization(user)
        reward_setting = models.RewardSetting.objects.filter(id=1).values()
        bal = 0
        if user.address != "" and user.address is not None:
            web3_client = Web3(Web3.HTTPProvider(api_settings.MAINNET_URL))
            address_c = web3_client.toChecksumAddress(api_settings.TOKEN_ADDRESS)
            token_abi = json.loads(reward_setting[0].get('token_abi'))
            token_upp = web3_client.eth.contract(address_c, abi=token_abi)
            bal = (token_upp.call().balanceOf(
                user.address)) / 1000000000000000000
        api_details = user.key_set.values('api_key', 'expire_datetime')
        api_details = api_details[0] if api_details else {
            "api_key": None, "expire_datetime": None}
        if bal < api_settings.MAB_USER_UPGRADE and user.role == models.Role.objects.get(role_name=models.UserRoles.COMMUNITY_VERIFIED.value):
            community_role = models.Role.objects.get(role_name=models.UserRoles.COMMUNITY.value)
            role_matrix, role_name = models.RolePermission.objects.get_permission_matrix(community_role.id)
            UserRoleUpdateTask().delay(user_id=user.id, new_role=community_role.role_name)
        else:
            role_matrix, role_name = models.RolePermission.objects.get_permission_matrix(user.role.id)
        return {
            "accessToken": token.key if user.status == models.UserStatus.APPROVED else "",
            "user": {
                "email": user.email,
                "id": user.uid,
                "nickname": user.nickname,
                "address": user.address,
                "permission": user.permission.value,
                "rolepermissions": role_matrix,
                "image": user.image.url if bool(user.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "status": user.status.value,
                "catv_history": [],
                "points": user.points,
                "balance": bal,
                "email_notification": user.email_notification,
                "role_name": role_name,
                "organization_id": organization_id,
                "is_admin": is_admin,
                "last_logged_out": user.last_logged_out,
                "api_details": api_details
            }
        }

    def check_organization(self, user):
        organization_id = ''
        is_admin = False
        org_admin = models.Organization.objects.filter(
            administrator=user).annotate(is_admin=Value(True, BooleanField()))[:1]
        org_user = models.OrganizationUser.objects.filter(user=user).select_related('organization'). \
                       annotate(is_admin=Value(False, BooleanField()))[:1]
        org_user = list(org_user)
        if org_admin:
            organization_id = str(org_admin[0].uid)
            is_admin = org_admin[0].is_admin
        elif org_user:
            organization_id = str(org_user[0].organization.uid)
            is_admin = org_user[0].is_admin
        elif user.role.role_name == models.UserRoles.ORG.value or \
                user.role.role_name == models.UserRoles.ORG_TRIAL.value:
            is_admin = True
        return organization_id, is_admin

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
            c = DefaultCache()
            c.set("user_" + str(user.id), user, 0)
            if ret is False:
                raise exceptions.AuthenticationCheckError()
        except models.User.DoesNotExist:
            raise exceptions.AuthenticationCheckError()

        if user.status == models.UserStatus.APPROVED:
            token, _ = MultiToken.create_token(user)
        else:
            token = ""

        user.timestamp = timezone.now()
        user.save()
        return self.__create_success_response(user, token)

    def generate_oauth_login_response(self, user):
        if user.status == models.UserStatus.APPROVED:
            token, _ = MultiToken.create_token(user)
        else:
            token = ""
        user.timestamp = timezone.now()
        user.save()
        return self.__create_success_response(user, token)

    def generate_proxy_login_response(self, user):
        if user.status == models.UserStatus.APPROVED:
            token, _ = MultiToken.create_token(user)
        else:
            token = ""
        return token.key


class ChangePasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(
        required=True, write_only=True, style={'input_type': 'password'})

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
        user.password = make_password(new_pw)
        user.save()
        return {}


class UserDetailSerializer(serializers.ModelSerializer):
    permission = fields.EnumField(enum=models.UserPermission)
    uid = serializers.UUIDField(required=False, read_only=True)
    created = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = models.User
        fields = ("id", "uid", "nickname", "permission", "image",
                  "email_notification", "created", "points", "role", "email")

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

    def get_role(self, obj):
        return obj.role.display_name


class UserPostSerializer(serializers.ModelSerializer):
    permission = fields.EnumField(enum=models.UserPermission, required=False)
    email = serializers.CharField(required=False)
    nickname = serializers.CharField(required=True)
    address = serializers.CharField(allow_blank=True, required=False)
    email_notification = serializers.BooleanField(required=False)
    password = serializers.CharField(
        allow_blank=True, required=False, write_only=True, style={'input_type': 'password'})
    old_password = serializers.CharField(
        allow_blank=True, required=False, write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(
        allow_blank=True, required=False, write_only=True, style={'input_type': 'password'})
    image = serializers.ImageField(required=False,
                                   max_length=10000000,
                                   allow_empty_file=True,
                                   use_url=False)
    points = serializers.IntegerField(required=False)
    organization = OrganizationRelatedField(required=False, write_only=True, queryset=models.Organization.objects.all(),
                                            allow_null=True)
    invitation_code = serializers.CharField(
        required=False, write_only=True, max_length=40)

    class Meta:
        model = models.User
        fields = ("uid", "permission", "email", "nickname", "image", "password", "old_password", "new_password",
                  "email_notification", "address", "points", "organization", "invitation_code")

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
            timestamp = request.META.get(
                'HTTP_X_AUTHORIZATION_TIMESTAMP', None)
            encrypted_pw = data.get("password", None)
            email = data.get("email", None)
            nickname = data.get("nickname", None)
            password = decrypt_message(encrypted_pw, timestamp)
            permission = data.get("permission", None)
            invitation_code = data.get("invitation_code", None)
            if invitation_code:
                invite = models.OrganizationInvites.objects.get(
                    invite_hash=invitation_code)
                referred_email = invite.inviter_key.split('-invite-')[1]
                if referred_email != data['email']:
                    raise exceptions.ValidationError("User email and email invite sent to do not match."
                                                     "Cannot sign up with this invitation code.")

            if not timestamp or not password or not email or not permission:
                raise exceptions.ValidationError("invalid data")
            # temporary code: accept only exchanges TODO: remove later
            if permission not in [models.UserPermission.EXCHANGE, models.UserPermission.USER]:
                raise exceptions.ValidationError("invalid data")

            if permission is models.UserPermission.EXCHANGE:
                data['role'] = models.Role.objects.get(
                    role_name='organization-trial')

            # eof temporary code
            self._validate_new_password(user=None, new_pw=password)
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
                timestamp = request.META.get(
                    'HTTP_X_AUTHORIZATION_TIMESTAMP', None)
                old_pw = decrypt_message(enc_old_pw, timestamp)
                new_pw = decrypt_message(enc_new_pw, timestamp)
                if old_pw == new_pw:
                    raise exceptions.ValidationError(
                        "old and new password are same.")
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
            address = request.data.get("address", None)
            # Don't know what comparing it to 'empty' string value does here
            # Is it passed from the frontend? comparisons redundant
            if address and address != "empty":
                web3_client = Web3(Web3.HTTPProvider(api_settings.MAINNET_URL))
                data["address"] = web3_client.toChecksumAddress(address)
            else:
                # Conflicts with unique constraint if empty string values are used when user updates profile
                data["address"] = None
            points = request.data.get("points", None)
            if points != "":
                data["points"] = points

        if len(data["nickname"]) < 4 or len(data["nickname"]) > 32:
            raise exceptions.ValidationError("invalid nickname length")
        return data

    def create(self, validated_data):
        try:
            validated_data.pop("invitation_code", None)
            organization = validated_data.pop("organization", None)
            new_pw = make_password(validated_data["password"])
            validated_data["password"] = new_pw
            instance = models.User.objects.create(**validated_data)
            if organization:
                models.OrganizationInvites.objects.filter(organization=organization, email=validated_data['email']). \
                    update(status=models.OrganizationInviteStatus.PENDING_APPROVAL)
        except IntegrityError as e:
            if "nickname" in str(e):
                raise exceptions.DataIntegrityError("duplicate: nickname")
            elif "email" in str(e):
                raise exceptions.DataIntegrityError("duplicate: email")
            else:
                raise exceptions.DataIntegrityError("")

        c = DefaultCache()
        c.set("user_" + str(instance.id), instance, 0)
        return instance

    def update(self, instance, validated_data, *args, **kwargs):
        try:
            with transaction.atomic():
                # Invalidate verification challenge if user changed wallet address after generating a challenge
                if instance.address and instance.address != validated_data["address"]:
                    models.UserUpgrade.objects.\
                    filter(user=instance, status=models.UpgradeVerifyStatus.PENDING.value).\
                    update(status=models.UpgradeVerifyStatus.FAILED)
                instance.update(
                    password=validated_data.get("new_password", None),
                    image=validated_data.get("image"),
                    nickname=validated_data["nickname"],
                    email_notification=validated_data["email_notification"],
                    address=validated_data["address"],
                    points=validated_data["points"]
                )
        except IntegrityError as e:
            if "nickname" in str(e):
                raise exceptions.DataIntegrityError("duplicate: nickname")
            else:
                if "address" in str(e):
                    raise exceptions.DataIntegrityError("duplicate: address")
                raise exceptions.DataIntegrityError()

        c = DefaultCache()
        c.set("user_" + str(instance.id), instance, 0)
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
            obj = models.Key.objects.filter(user=user.pk)
            if obj.exists() == True:
                raise exceptions.ICFAlreadyExist()
            data["user"] = user
            data["expire_datetime"] = timezone.now() + relativedelta(years=+1)
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
        while (True):
            new_key = models.generate_api_key()
            if new_key != prev_key:
                obj.api_key = new_key
                break
        if obj.expire_datetime.date() < timezone.now().date():
            obj.expire_datetime = timezone.now() + relativedelta(years=+1)
        obj.save()
        return obj


class AttachedFileSerializer(NonNullModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = models.AttachedFile
        fields = ("uid", "type", "hash", "size", "uploader", "name", "url",)
        read_only_fields = ("uid", "type", "hash", "size",
                            "uploader", "name", "url")

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
            raise exceptions.ValidationError({"file": "maximum number of upload files is {0}".format(
                api_settings.ATTACHED_FILE_UPLOAD_NUM_LIMIT)})
        allowed_file_types = list(
            map(lambda x: x.lower(), api_settings.ATTACHED_FILE_ALLOWED_TYPES.split("|")))
        for file in files:
            file_ext = file.name.split('.')[-1]
            if file_ext.lower() not in allowed_file_types:
                raise exceptions.FileNotAllowed("Only the following file types are allowed: {0}".
                                                format(",".join(allowed_file_types)))
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
    security_category = fields.EnumField(
        enum=models.IndicatorSecurityCategory, required=False)
    detail = fields.TruncatedCharField(truncate_len=api_settings.INDICATOR_LIST_DETAIL_LEN,
                                       required=False, allow_blank=True, allow_null=True)
    security_tags = serializers.ListField(
        child=serializers.CharField(), required=False)
    vector = serializers.ListField(child=fields.EnumField(
        enum=models.IndicatorVector), required=False)
    environment = serializers.ListField(child=fields.EnumField(
        enum=models.IndicatorEnvironment), required=False)
    pattern = serializers.CharField(required=False)
    pattern_type = fields.EnumField(
        enum=models.IndicatorPatternType, required=False)
    pattern_subtype = fields.EnumField(
        enum=models.IndicatorPatternSubtype, required=False)
    annotation = serializers.CharField(required=False)
    annotations = serializers.SerializerMethodField()
    reported_by = serializers.SerializerMethodField()
    uid = serializers.UUIDField(required=False)
    id = serializers.PrimaryKeyRelatedField(
        queryset=models.Indicator.objects.all(), required=False)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "security_tags", "vector",
                  "environment", "detail", "pattern", "annotation", "reported_by", "annotations")
        read_only_fields = ("id", "uid", "reported_by", "annotations")

    def __init__(self, *args, **kwargs):
        is_authenticated = False
        if "is_authenticated" in kwargs:
            is_authenticated = kwargs.pop("is_authenticated")

        super(IndicatorDetailSerializer, self).__init__(*args, **kwargs)

        if is_authenticated:
            self.fields["cases"] = CaseSimpleSerializer(
                read_only=True, many=True)

    def get_reported_by(self, obj):
        c = DefaultCache()
        cached = c.get("user_" + str(obj.user_id))
        if cached:
            return {
                "nickname": cached.nickname,
                "image": cached.image.url if bool(cached.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "uid": cached.uid
            }

        if obj.user:
            return {
                "nickname": obj.user.nickname,
                "uid": obj.user.uid
            }
        elif obj.reporter_info:
            return {
                "email": obj.reporter_info
            }
        return None

    def get_annotations(self, obj):
        data = []
        annotations = obj.annotations.all()
        for annotation in annotations:
            data.append(annotation.annotation)
        return data


class IndicatorListSerializer(NonNullModelSerializer):
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype)
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "security_category", "security_tags", "pattern",
                  "pattern_type", "pattern_subtype", "created", "annotation")
        read_only_fields = ("id", "uid", "security_category", "security_tags",
                            "pattern", "pattern_type", "pattern_subtype", "created")

    def __init__(self, *args, **kwargs):
        is_authenticated = False
        if "is_authenticated" in kwargs:
            is_authenticated = kwargs.pop("is_authenticated")

        super(IndicatorListSerializer, self).__init__(*args, **kwargs)


class IndicatorLatestRecordSerializer(NonNullModelSerializer):
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory)
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype)

    class Meta:
        model = models.Indicator
        fields = ("id", "uid", "pattern", "security_category",
                  "pattern_type", "pattern_subtype")
        read_only_fields = (
            "id", "uid", "pattern", "security_category", "pattern_type", "pattern_subtype")


class IndicatorPostSerializer(NonNullModelSerializer):
    pattern = serializers.CharField(required=False)
    pattern_type = fields.EnumField(
        enum=models.IndicatorPatternType, required=False)
    pattern_subtype = fields.EnumField(
        enum=models.IndicatorPatternSubtype, required=False)
    security_category = fields.EnumField(
        enum=models.IndicatorSecurityCategory, required=False)
    detail = fields.TruncatedCharField(truncate_len=api_settings.INDICATOR_LIST_DETAIL_LEN,
                                       required=False, allow_blank=True, allow_null=True)
    security_tags = serializers.ListField(
        child=serializers.CharField(), required=False)
    vector = serializers.ListField(child=fields.EnumField(
        enum=models.IndicatorVector), required=False)
    environment = serializers.ListField(child=fields.EnumField(
        enum=models.IndicatorEnvironment), required=False)
    force = serializers.BooleanField(required=False)
    reporter_info = serializers.CharField(required=False)
    deleted = serializers.BooleanField(required=False)
    annotation = serializers.CharField(
        required=False, allow_blank=True, allow_null=True)
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
        dup = models.Indicator.objects.filter(security_category=data["security_category"],
                                              pattern=data["pattern"],
                                              pattern_type=data["pattern_type"],
                                              pattern_subtype=data["pattern_subtype"])
        cases = data.pop("cases", [])
        force = data.pop("force", False)

        if "annotation" in data and self.context["request"].user.permission != models.UserPermission.SUPERSENTINEL:
            data.pop("annotation")

        if len(dup) > 0 and not force:
            raise exceptions.DataIntegrityError("duplicate indicator")
        try:
            with transaction.atomic():
                indicator = models.Indicator.objects.create(**data)
                for case in cases:
                    case_instance = models.Case.objects.get(id=case["id"])
                    if case_instance.status not in [models.CaseStatus.NEW, models.CaseStatus.PROGRESS]:
                        raise exceptions.DataIntegrityError(
                            "case's status is not 'new' or 'in progress'")
                    models.CaseIndicator.objects.create(
                        case=case_instance, indicator=indicator)
                if "annotation" in data:
                    for annotation in [x.strip() for x in data["annotation"].split(",")]:
                        if len(annotation) == 0:
                            continue
                        anno = models.Annotation.objects.filter(
                            annotation=annotation)
                        if len(anno) > 0:
                            anno = anno[0]
                        else:
                            anno = models.Annotation.objects.create(
                                annotation=annotation)
                        models.IndicatorAnnotation.objects.create(
                            indicator=indicator, annotation=anno)

        except IntegrityError:
            raise exceptions.DataIntegrityError("data integrity error")
        except exceptions.DataIntegrityError as err:
            raise err
        except models.Case.DoesNotExist:
            raise exceptions.DataIntegrityError("case does not exist")
        return indicator

    def update(self, instance, data):
        indi_objs = models.Indicator.objects.filter(security_category=data["security_category"],
                                                    pattern=data["pattern"],
                                                    pattern_type=data["pattern_type"],
                                                    pattern_subtype=data["pattern_subtype"])
        cases = data.pop("cases", [])
        force = data.pop("force", False)

        if data["annotation"] and self.context["request"].user.permission != models.UserPermission.SUPERSENTINEL:
            data.pop("annotation")

        if len(indi_objs) > 0 and not force:
            for indicator in indi_objs:
                if instance.pk != indicator.pk:
                    raise exceptions.DataIntegrityError("duplicate indicator")

        try:
            with transaction.atomic():
                for case in cases:
                    case_instance = models.Case.objects.get(id=case["id"])
                    if "deleted" in case:
                        models.CaseIndicator.objects.filter(
                            case=case_instance, indicator=instance).delete()
                    if "added" in case:
                        models.CaseIndicator.objects.create(
                            case=case_instance, indicator=instance)

                if "annotation" in data:
                    new_annotations = [x.strip()
                                       for x in data["annotation"].split(",")]
                    prev_annotations = [
                        annotation.annotation for annotation in instance.annotations.all()]
                    if new_annotations != prev_annotations:
                        instance.annotations.clear()
                        for annotation in new_annotations:
                            if len(annotation) == 0:
                                continue
                            anno = models.Annotation.objects.filter(
                                annotation=annotation)
                            if len(anno) > 0:
                                anno = anno[0]
                            else:
                                anno = models.Annotation.objects.create(
                                    annotation=annotation)
                            models.IndicatorAnnotation.objects.create(
                                indicator=instance, annotation=anno)

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
    vector = serializers.ListField(
        child=fields.EnumField(enum=models.IndicatorVector))
    environment = serializers.ListField(
        child=fields.EnumField(enum=models.IndicatorEnvironment))

    class Meta:
        model = models.Indicator
        fields = ("id", "security_category", "security_tags", "vector", "environment", "pattern",
                  "pattern_type", "pattern_subtype", "annotation")
        read_only_fields = ("id", "security_category", "security_tags", "vector", "environment", "pattern",
                            "pattern_type", "pattern_subtype", "annotation")

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
    detail = fields.TruncatedCharField(
        truncate_len=api_settings.ICO_LIST_DETAIL_LEN)
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
            case_queryset = models.Case.objects.filter(
                Q(ico=obj.pk) & Q(status=models.CaseStatus.RELEASED))
            if len(case_queryset) > 0:
                blacklist = []
                whitelist = []
                graylist = []
                for case in case_queryset:
                    blacklist.extend(case.indicators.filter(
                        security_category=models.IndicatorSecurityCategory.BLACKLIST))
                    whitelist.extend(case.indicators.filter(
                        security_category=models.IndicatorSecurityCategory.WHITELIST))
                    graylist.extend(case.indicators.filter(
                        security_category=models.IndicatorSecurityCategory.GRAYLIST))

                white_se = IndicatorListSerializer(whitelist, many=True)
                black_se = IndicatorListSerializer(blacklist, many=True)
                graylist_se = IndicatorListSerializer(graylist, many=True)

                return {"whitelist": white_se.data,
                        "blacklist": black_se.data,
                        "graylist": graylist_se.data}
            else:
                return {
                    "whitelist": [],
                    "blacklist": [],
                    "graylist": []
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


class RelatedCaseSerializer(serializers.ModelSerializer):
    related_id = serializers.PrimaryKeyRelatedField(queryset=models.Case.objects.all())
   # uid = serializers.SerializerMethodField()

    class Meta:
        model = models.RelatedCase
        fields = ("id", "related_id")

    def create(self, validated_data):
        return models.RelatedCase.objects.create(**validated_data)

   # def get_uid(self, obj):




class CaseSimpleListSerializer(NonNullModelSerializer):
    status = fields.EnumField(enum=models.CaseStatus)
    ico = ICOSerializer(read_only=True)
    related = RelatedCaseSerializer(read_only=True)
    created = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("id", "uid", "title", "ico", "created", "status", "related")
        read_only_fields = ("id", "uid", "title", "ico", "created", "status", "related")

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())


class CaseListSerializer(NonNullModelSerializer):
    status = fields.EnumField(enum=models.CaseStatus)
    reporter = serializers.SerializerMethodField()
    owned_by = serializers.SerializerMethodField()
    created = serializers.SerializerMethodField()
    indicators = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("id", "uid", "title", "created", "status",
                  "reporter", "owned_by", "indicators")
        read_only_fields = ("id", "uid", "title", "created",
                            "status", "reporter", "owned_by", "indicators")

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())

    def get_reporter(self, obj):
        c = DefaultCache()
        cached = c.get("user_" + str(obj.reporter_id))
        if cached:
            return {
                "nickname": cached.nickname,
                "image": cached.image.url if bool(cached.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "uid": cached.uid
            }

        if obj.reporter:
            return {
                "nickname": obj.reporter.nickname,
                "image": obj.reporter.image.url if bool(obj.reporter.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "uid": obj.reporter.uid
            }
        elif obj.reporter_info:
            return {
                "nickname": obj.reporter_info,
                "image": api_settings.S3_USER_IMAGE_DEFAULT
            }
        return None

    def get_owned_by(self, obj):
        c = DefaultCache()
        cached = c.get("user_" + str(obj.owner_id))
        if cached:
            return {
                "nickname": cached.nickname,
                "image": cached.image.url if bool(cached.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "uid": cached.uid
            }
        if obj.owner:
            return {
                "nickname": obj.owner.nickname,
                "image": obj.owner.image.url if bool(obj.owner.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "uid": obj.owner.uid
            }
        return None

    def get_indicators(self, obj):
        try:
            queryset = obj.indicators.all()
            indicator_serializer = IndicatorListSerializer(queryset, many=True)
            return indicator_serializer.data
        except models.Indicator.DoesNotExist:
            pass
        return []


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
    title = serializers.CharField(
        required=True, max_length=api_settings.CASE_TITLE_MAX_LEN)
    detail = serializers.CharField(
        required=True, max_length=api_settings.CASE_DETAIL_MAX_LEN)
    rich_text_detail = serializers.CharField(
        required=False, max_length=api_settings.CASE_DETAIL_MAX_LEN)
    reporter_info = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=api_settings.CASE_REPORTER_MAX_LEN)
    ico = serializers.PrimaryKeyRelatedField(
        queryset=models.ICO.objects.all(), required=False)
    indicators = IndicatorPostSerializer(required=False, many=True)
    files = FileItemSerializer(required=False, many=True)
    related_case = serializers.PrimaryKeyRelatedField(queryset=models.Case.objects.all(), allow_null=True, required=False)

    class Meta:
        model = models.Case
        fields = ("title", "detail", "rich_text_detail", "reporter_info",
                  "ico", "indicators", "files", "related_case")
        read_only_fields = ("id", "uid", "created")

    def validate_files(self, data):
        return data

    def validate_inidcators(self, data):  # TODO: more specific error message.
        return data

    def validate_related_case(self, data):
        return data

    def __upload_files(self, files):
        s3 = boto3.resource('s3')
        bucket_name = api_settings.ATTACHED_FILE_S3_BUCKET_NAME
        for obj in files:
            full_path = os.path.join(
                api_settings.ATTACHED_FILE_SAVE_PATH, str(obj.uid))
            key_name = api_settings.ATTACHED_FILE_S3_KEY_PREFIX + str(obj.uid)
            try:
                f = open(full_path, "rb")
                s3.Bucket(bucket_name).put_object(
                    ACL='private', Key=key_name, Body=f)
            except IOError as err:
                raise err
            else:
                f.close()

    def create(self, validated_data):
        indicators_data = validated_data.pop("indicators", [])
        files_data = validated_data.pop("files", [])
        related_data = validated_data.pop("related_case", [])
        try:
            with transaction.atomic():
                if related_data:
                    related_case = models.RelatedCase.objects.create(related=related_data)
                    if related_case:
                        validated_data["related_case"] = related_case
                case = models.Case.objects.create(**validated_data)
                m2m_bulk = []
                indicator_bulk = []
                new_indicators = []
                for indi in indicators_data:
                    if "uid" in indi:
                        indicator = models.Indicator.objects.get(
                            uid=indi["uid"])
                        indicator_bulk.append(indicator)
                    else:
                        if not hasattr(self.context["request"].user, "is_anonymous"):
                            indi["user"] = self.context["request"].user
                        reporter_info = validated_data.get(
                            "reporter_info", None)
                        if not reporter_info:
                            indi["reporter_info"] = reporter_info
                        if indi["pattern_type"] in [models.IndicatorPatternType.NETWORKADDR,
                                                    models.IndicatorPatternType.SOCIALMEDIA]:
                            indi["pattern_tree"] = Pattern.getMaterializedPathForInsert(
                                indi["pattern"].lower().rstrip('/'))
                        indicator = models.Indicator(**indi)
                        new_indicators.append(indicator)

                indicator_bulk = indicator_bulk + \
                                 models.Indicator.objects.bulk_create(new_indicators)
                # annotation
                for indicator in indicator_bulk:
                    if indicator.annotation:
                        for annotation in [x.strip() for x in indicator.annotation.split(",")]:
                            if len(annotation) == 0:
                                continue
                            anno = models.Annotation.objects.filter(
                                annotation=annotation)
                            if len(anno) > 0:
                                anno = anno[0]
                            else:
                                anno = models.Annotation.objects.create(
                                    annotation=annotation)
                            models.IndicatorAnnotation.objects.create(
                                indicator=indicator, annotation=anno)
                    # case
                    m2m_bulk.append(models.CaseIndicator(
                        case=case, indicator=indicator))

                models.CaseIndicator.objects.bulk_create(m2m_bulk)

                if len(files_data) > api_settings.CASE_ATTACHED_FILE_MAX_LIMIT:
                    raise exceptions.ValidationError(
                        {"files": "one case cannot have more than 20 files."})

                # save file.
                for file_item in files_data:
                    file_obj = models.AttachedFile.objects.using(
                        'default').get(uid=file_item["uid"])
                    if file_obj.case is not None:
                        raise exceptions.DataIntegrityError(
                            "file already included in other cases.")
                    file_obj.case = case
                    file_obj.save()
            case_task = CaseMessageTask(api_settings.KAFKA_PORTAL_CASE_TOPIC, action=Constants.CASE_ACTIONS["CREATE"])
            case_task.related_ids = case.id
            case_task.run()
        except IntegrityError:
            raise exceptions.DataIntegrityError()
        except exceptions.DataIntegrityError as err:
            raise err
        except Exception as err:
            raise err

        return case

    def update(self, instance, validated_data):
        indicators_data = validated_data.pop("indicators", [])
        files_data = validated_data.pop("files", [])
        ico = validated_data.pop("ico", None)
        related_data = validated_data.pop("related_case", None)

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
        if related_data is not None and instance.related_case is not None:
            history_log["relatedCaseUpdated"] = instance.related_case_id != related_data.id
        if related_data is None and instance.related_case is not None:
            history_log["relatedCaseDeleted"] = True
        if related_data is not None and instance.related_case is None:
            history_log["relatedCaseAdded"] = True
        if history_log["relatedCaseUpdated"]:
            related_case = models.RelatedCase.objects.filter(id=instance.related_case_id)
            related_case.update(related=related_data)
        if history_log["relatedCaseDeleted"]:
            related_case = models.RelatedCase.objects.filter(id=instance.related_case_id)
            related_case.delete()
            validated_data["related_case"] = None
        if history_log["relatedCaseAdded"]:
            related_case = models.RelatedCase.objects.create(related=related_data)
            if related_case:
                validated_data["related_case"] = related_case

        if history_log["relatedProjectUpdated"]:
            validated_data["ico"] = ico

        try:
            with transaction.atomic():
                # indicators
                for indi_item in indicators_data:
                    if "uid" in indi_item:
                        indicator = models.Indicator.objects.get(
                            uid=indi_item["uid"])
                        if "deleted" in indi_item and indi_item["deleted"] is True:
                            models.CaseIndicator.objects.filter(
                                case=instance, indicator=indicator).delete()
                            history_log['indicatorRemoved'] = True
                    else:
                        indi_item["case"] = instance
                        indi_item["user"] = self.context["request"].user
                        indicator = models.Indicator.objects.create(
                            **indi_item)
                        models.CaseIndicator.objects.create(
                            case=instance, indicator=indicator)
                        history_log['indicatorAdded'] = True
                        for annotation in [x.strip() for x in indicator.annotation.split(",")]:
                            if len(annotation) == 0:
                                continue
                            anno = models.Annotation.objects.filter(
                                annotation=annotation)
                            if len(anno) > 0:
                                anno = anno[0]
                            else:
                                anno = models.Annotation.objects.create(
                                    annotation=annotation)
                            models.IndicatorAnnotation.objects.create(
                                indicator=indicator, annotation=anno)

                # files
                for file_item in files_data:
                    if "uid" not in file_item:  # ignored. file item always has uid.
                        continue
                    # deleted
                    if "deleted" in file_item and file_item["deleted"] is True:
                        try:
                            file_obj = models.AttachedFile.objects.get(
                                uid=file_item["uid"])
                            file_obj.delete()
                        except models.AttachedFile.DoesNotExist:
                            pass
                        history_log['fileRemoved'] = True
                        continue
                    file_obj = models.AttachedFile.objects.using(
                        'default').get(uid=file_item["uid"])
                    if not file_obj:
                        continue
                    # raise exception when file is for other case.
                    if file_obj.case is not None and file_obj.case != instance:
                        raise exceptions.DataIntegrityError(
                            "file already included in other cases.")
                    if file_obj.case == instance:
                        continue
                    history_log["fileAdded"] = True
                    file_obj.case = instance
                    file_obj.save()
                # case items
                instance = super().update(instance, validated_data)
            case_task = CaseMessageTask(api_settings.KAFKA_PORTAL_CASE_TOPIC, action=Constants.CASE_ACTIONS["UPDATE"])
            case_task.related_ids = instance.id
            case_task.run()
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
    owned_by = serializers.SerializerMethodField()
    verified_by = serializers.SerializerMethodField()
    reported_by = serializers.SerializerMethodField()
    histories = serializers.SerializerMethodField()
    indicators = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()
    created = serializers.SerializerMethodField()
    trdb = serializers.SerializerMethodField()
    related_case = serializers.SerializerMethodField()
    #case = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("id", "uid", "title", "detail", "rich_text_detail", "created", "status", "reported_by",
                  "owned_by", "verified_by", "trdb", "histories", "indicators", "files", "related_case")

    def get_queryset(self):
        uuid = self.kwargs["id"]
        return self.model.objects.get(uid__iexact=uuid)

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple())

    def get_histories(self, obj):
        try:
            queryset = models.CaseHistory.objects.filter(
                case=obj.pk).order_by("-created")
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
        file_objs = models.AttachedFile.objects.filter(
            case=obj.pk).order_by("pk")
        if len(file_objs) > 0:
            file_serializer = AttachedFileSerializer(
                file_objs, many=True, context=self.context)
            files = file_serializer.data
        return files

    def get_trdb(self, obj):
        trdb_objs = models.TRDBCaseTransaction.objects.filter(
            case_uid=obj.uid).order_by('-pk')
        if len(trdb_objs) == 0:
            return None

        trdb_obj = trdb_objs[0]
        if trdb_obj.block_num is None or trdb_obj.transaction_id is None:
            return None
        serializer = TRDBCaseTransactionSerializer(trdb_obj)
        return serializer.data

    def get_owned_by(self, obj):
        c = DefaultCache()
        cached = c.get("user_" + str(obj.owner_id))
        if cached:
            return {
                "nickname": cached.nickname,
                "image": cached.image.url if bool(cached.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "uid": cached.uid,
                "points": cached.points,
                "email_notification": cached.email_notification
            }
        if obj.owner:
            return {
                "nickname": obj.owner.nickname,
                "uid": obj.owner.uid
            }
        return None

    def get_reported_by(self, obj):
        c = DefaultCache()
        cached = c.get("user_" + str(obj.reporter_id))
        if cached:
            return {
                "nickname": cached.nickname,
                "image": cached.image.url if bool(cached.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "uid": cached.uid
            }

        if obj.reporter:
            return {
                "nickname": obj.reporter.nickname,
                "uid": obj.reporter.uid
            }
        elif obj.reporter_info:
            return {
                "email": obj.reporter_info
            }
        return None

    def get_verified_by(self, obj):
        c = DefaultCache()
        cached = c.get("user_" + str(obj.verifier_id))
        if cached:
            return {
                "nickname": cached.nickname,
                "image": cached.image.url if bool(cached.image) else api_settings.S3_USER_IMAGE_DEFAULT,
                "uid": cached.uid
            }

        if obj.verifier:
            return {
                "nickname": obj.verifier.nickname,
                "uid": obj.verifier.uid
            }
        return None

   # def get_related_cases(self, obj):
   #     indicators = models.CaseIndicator.objects.filter(
   #         case=obj).values('indicator')
   #     related_cases = models.Case.objects.exclude(pk=obj.id).filter(indicators__in=indicators).distinct('pk'). \
   #         order_by('-pk')
   #     rc_serialized = CaseSimpleListSerializer(related_cases, many=True)
   #     return rc_serialized.data

    def get_related_case(self, obj):
        if obj.related_case_id:
            related_case = obj.related_case
            related_id = obj.related_case_id
            ser = RelatedCaseSerializer(related_case)
            case = models.Case.objects.filter(id=ser.data['related_id']).first()
            if case:
                ser.data['uid'] = case.uid
                ser.data['title'] = case.title
                new_dict = {'uid': case.uid, 'title': case.title, 'created': time.mktime(case.created.timetuple()), 'status': case.status.value}
                new_dict.update(ser.data)
                return new_dict
        else:
            return {}




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
        file_objs = models.AttachedFile.objects.filter(
            case=obj.pk).order_by("pk")
        if len(file_objs) > 0:
            file_serializer = AttachedFileTRDBSerializer(
                file_objs, many=True, context=self.context)
            files = file_serializer.data
        return files

    def get_owned_by(self, obj):
        if obj.owner:
            return {"id": str(obj.owner.uid)}
        else:
            return {"id": ""}

    def get_reported_by(self, obj):
        if obj.reporter:
            return {"id": str(obj.reporter.uid)}
        else:
            return {"id": ""}

    def get_verified_by(self, obj):
        if obj.verifier:
            return {"id": str(obj.verifier.uid)}
        return {"id": ""}


class CasePatchSerializer(NonNullModelSerializer):
    status = fields.EnumField(enum=models.CaseStatus, required=True)
    reporter = serializers.SerializerMethodField()

    class Meta:
        model = models.Case
        fields = ("status", "reporter")
        read_only_fields = ("id", "uid", "created")

    def validate_status(self, status):
        request = self.context["request"]
        user_permission = getattr(request.user, "permission", None)
        is_super = True if user_permission == models.UserPermission.SUPERSENTINEL else False
        is_owner = True if request.user == self.instance.owner else False

        utils.CASE_STATUS_FSM.check_access(status, request.user.role.id)
        utils.CASE_STATUS_FSM.validate(
            self.instance.status, status, is_super, is_owner)
        return status

    def validate_reporter(self, reporter):
        return reporter

    def get_reporter(self, obj):
        try:
            queryset = obj.reporter
            reporter_serializer = UserDetailSerializer(queryset)
            print("reporter-ser=", reporter_serializer.data)
            return reporter_serializer.data
        except models.User.DoesNotExist:
            pass
        return None

    def update(self, instance, validated_data):
        if validated_data["status"] == models.CaseStatus.NEW:
            instance.owner = None
        elif validated_data["status"] == models.CaseStatus.PROGRESS:
            instance.owner = self.context["request"].user
        # confirmed status should contain at least one indicator.
        elif validated_data["status"] == models.CaseStatus.CONFIRMED:
            if not instance.indicators:
                raise exceptions.ValidationError(
                    "at least one indicator should be contained.")
        elif validated_data["status"] == models.CaseStatus.RELEASED:
            instance.verifier = self.context["request"].user
            i = 0
            # indicators = IndicatorListSerializer(instance.indicators.all)
            for ind in instance.indicators.all():
                ind_list = models.Indicator.objects.exclude(
                    pattern_type='filehash').filter(pattern=ind.pattern)
                if ind_list.all().count() == 1:
                    indicator_points = IndicatorPointsSerializer(
                        data={"user_id": instance.reporter.id, "indicator_id": ind.id, "points": True})
                    indicator_points.is_valid(raise_exception=True)
                    indicator_points.save()
                    i = i + 1
            if instance.reporter:
                instance.reporter.points = int(instance.reporter.points or 0) + (10 * i)
                UserPointsSerializer().update(instance.reporter, {"points": instance.reporter.points})
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

                if validated_data["status"] == models.CaseStatus.RELEASED or \
                        (instance.status == models.CaseStatus.RELEASED and
                         validated_data["status"] == models.CaseStatus.REJECTED):
                    c = UppwardCache()
                    indicators = instance.indicators.all()
                    for indicator in indicators:
                        c.invalidate_cache(indicator.pattern)

                ch_serializer.save()
                updated_instance = super(CasePatchSerializer, self).update(instance, validated_data)
            case_task = CaseMessageTask(api_settings.KAFKA_PORTAL_CASE_TOPIC, action=Constants.CASE_ACTIONS["UPDATE"])
            case_task.related_ids = updated_instance.id
            case_task.run()
            return updated_instance
        except IntegrityError:
            raise exceptions.DataIntegrityError("data integrity error")
        except Exception as e:
            print(e)
            raise exceptions.DataIntegrityError('exception error')
        return {}


class UserPointsSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.User
        fields = ("points",)

    def update(self, instance, validated_data):
        print("rep-data=", validated_data)
        return super(UserPointsSerializer, self).update(instance, validated_data)


class IndicatorPointsSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.IndicatorPoint
        fields = ["user_id", "indicator_id", "points"]
    user_id = serializers.IntegerField()
    indicator_id = serializers.IntegerField()
    points = serializers.BooleanField()


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
        if auto_type.lower() not in ["ico", "indicator", "indicator_tag", "case", "user"]:
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

            ico_objs = models.ICO.objects.filter(
                filter_queries)[:self.result_limit]

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

            if query.startswith('0x') and len(query) < 4:
                return {"indicators": indicators}
            elif len(query) < 3:
                return {"indicators": indicators}

            indicator_objs = models.Indicator.objects.filter(
                pattern__istartswith=query)
            if indicator_objs:
                indicator_serializer = IndicatorListSerializer(
                    indicator_objs, many=True)
                indicators = indicator_serializer.data
            return {"indicators": indicators}

        elif auto_type == "indicator_tag":
            indicator_objs = models.Indicator.objects.filter(
                security_tags__arrayilike=query)
            if indicator_objs:
                __tags = []
                indicator_tags = []
                for o in indicator_objs:
                    __tags.extend(
                        t for t in o.security_tags if t not in __tags)
                for tag in __tags:
                    if tag[:len(query)].lower() == query.lower():
                        indicator_tags.append({
                            'tag': tag
                        })
                indicator_tags = sorted(indicator_tags, key=lambda k: k["tag"])
                return {"indicator_tags": indicator_tags}

        elif auto_type == "user":
            users = []
            if re.match(r"[^@]+@[^@]+\.[^@]+", query):
                users_objs = models.User.objects.filter(email=query)
            else:
                users_objs = models.User.objects.filter(
                    nickname__istartswith=query)
            if users_objs:
                user_serializer = UserDetailSerializer(users_objs, many=True)
                users = user_serializer.data
            return {"users": users}

        elif auto_type == 'case':
            cases = []
            filter_queries = Q(status__in=filter)
            if query.isdigit():
                filter_queries &= Q(id=int(query))
            elif len(query) > 1:
                filter_queries &= Q(title__icontains=query)
            case_objs = models.Case.objects.filter(
                filter_queries).order_by('-created')[:self.result_limit]
            if case_objs:
                case_serializer = CaseSimpleListSerializer(
                    case_objs, many=True)
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


class CommentSerializer(NonNullModelSerializer):
    body = serializers.SerializerMethodField()
    writer = serializers.SerializerMethodField()
    editable = serializers.SerializerMethodField()

    class Meta:
        model = models.Comment
        fields = ("id", "uid", "writer", "body",
                  "created", "deleted", "editable")
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
    case = serializers.PrimaryKeyRelatedField(
        queryset=models.Case.objects.all(), required=False)
    indicator = serializers.PrimaryKeyRelatedField(
        queryset=models.Indicator.objects.all(), required=False)
    ico = serializers.PrimaryKeyRelatedField(
        queryset=models.ICO.objects.all(), required=False)

    class Meta:
        model = models.Comment
        fields = ("id", "uid", "case", "indicator", "ico",
                  "writer", "body", "created", "deleted")
        read_only_fields = ("id", "uid", "created")

    def validate(self, data):
        request = self.context["request"]
        body = data.get("body", "")
        if len(body) > api_settings.COMMENT_BODY_MAX_LEN:
            raise exceptions.ValidationError(
                "the maximum length for the comment body exceeds")
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
        fields = ("uid", "user", "initiator",
                  "target", "read", "created", "type")

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
            "image": api_settings.S3_USER_IMAGE_DEFAULT if bool(
                obj.initiator.image) is False else obj.initiator.image.url,
            "uid": obj.initiator.uid
        }

    def get_type(self, obj):
        return obj.type.value


class RewardSettingSerializer(NonNullModelSerializer):
    min_token = serializers.IntegerField(required=True)
    token_abi = serializers.JSONField(required=True)
    token_address = serializers.CharField(required=True)
    id = serializers.IntegerField(required=True)
    sentinel_point_reward = serializers.IntegerField(required=True)
    upp_reward = serializers.IntegerField(required=True)
    sp_required = serializers.IntegerField(required=True)

    class Meta:
        model = models.RewardSetting
        fields = ("id", "min_token", "token_abi", "token_address",
                  "sentinel_point_reward", "upp_reward", "sp_required")


class CATVSerializer(serializers.Serializer):
    wallet_address = serializers.CharField(required=True)
    source_depth = serializers.IntegerField(
        required=False, min_value=1, max_value=10)
    distribution_depth = serializers.IntegerField(
        required=False, min_value=1, max_value=10)
    transaction_limit = serializers.IntegerField(
        required=True, min_value=100, max_value=100000)
    from_date = serializers.CharField(required=True)
    to_date = serializers.CharField(required=True)
    token_address = serializers.CharField(required=False)
    force_lookup = serializers.BooleanField(required=False, default=False)

    def validate(self, data):
        if 'source_depth' in data or 'distribution_depth' in data:
            return data
        else:
            raise serializers.ValidationError(
                "Either of source_depth or distribution_depth is needed.")

    def validate_wallet_address(self, value):
        pattern = re.compile("^0x[a-fA-F0-9]{40}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Token address is not a valid ethereum address.")
        return value

    def validate_from_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def validate_to_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def get_tracking_results(self, tx_limit=10000, limit=10000, save_to_db=True, build_lossy_graph=True):
        tracking_results = TrackingResults(**self.data)
        try:
            tracking_results.get_tracking_data(tx_limit, limit, save_to_db)
            tracking_results.create_graph_data(build_lossy_graph)
            tracking_results.set_annotations_from_db(
                token_type=models.CatvTokens.ETH.value)
            return {
                "graph": tracking_results.make_graph_dict(),
                "api_calls": tracking_results.ext_api_calls,
                "messages": tracking_results.error_messages
            }
        except ReadTimeout:
            raise exceptions.FileNotFound("Timeout exceeded while fetching/processing data.")
        except Exception as e:
            err_msg = "Incorrect or missing transactions. Please try adjusting your search criteria."
            if tracking_results.error:
                err_msg = tracking_results.error
            elif e:
                err_msg = "Oops! Something went wrong while getting results for this address. Please try again later."
            raise exceptions.FileNotFound(err_msg)


class CATVBTCSerializer(CATVSerializer):
    tx_hash = serializers.CharField(required=True)

    def validate_wallet_address(self, value):
        pattern = re.compile("^([13]|bc1).*[a-zA-Z0-9]{26,35}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address is an invalid Bitcoin address")
        return value

    def valid_tx_hash(self, value):
        pattern = re.compile("^[a-fA-F0-9]{64}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Transaction hash is an invalid Bitcoin transaction hash")
        return value

    def get_tracking_results(self, tx_limit=10, limit=10, save_to_db=True, build_lossy_graph=True):
        serializer_data = self.data
        tracking_results = BTCTrackingResults(**serializer_data)
        try:
            tracking_results.get_tracking_data(tx_limit, limit, save_to_db)
            tracking_results.create_graph_data(
                serializer_data["wallet_address"], build_lossy_graph)
            tracking_results.set_annotations_from_db(
                token_type=models.CatvTokens.BTC.value)
            return {
                "graph": tracking_results.make_graph_dict(),
                "api_calls": tracking_results.ext_api_calls,
                "messages": tracking_results.error_messages
            }
        except ReadTimeout:
            raise exceptions.FileNotFound("Timeout exceeded while fetching/processing data.")
        except Exception as e:
            err_msg = "Incorrect or missing transactions. Please try adjusting your search criteria."
            if tracking_results.error:
                err_msg = tracking_results.error
            elif e:
                err_msg = "Oops! Something went wrong while getting results for this address. Please try again later."
            raise exceptions.FileNotFound(err_msg)


class CATVBTCTxlistSerializer(serializers.Serializer):
    wallet_address = serializers.CharField(required=True)
    from_date = serializers.CharField(required=True)
    to_date = serializers.CharField(required=True)

    def validate_wallet_address(self, value):
        pattern = re.compile("^([13]|bc1).*[a-zA-Z0-9]{26,35}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address is an invalid Bitcoin address")
        return value

    def validate_from_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def validate_to_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def get_btc_txlist(self):
        txlist_client = LyzeAPIInterface(api_settings.LYZE_API_KEY)
        data = self.data
        resp = txlist_client.get_txlist(
            data['wallet_address'], data['from_date'], data['to_date'])
        txlist = []
        seen_txid = []
        for tx in resp:
            tx_dict = {}
            if tx['tx_id'].lower() not in seen_txid:
                for k, v in tx.items():
                    if k == 'tx_id' or k == 'ts':
                        tx_dict[k] = v
                txlist.append(tx_dict)
                seen_txid.append(tx['tx_id'].lower())
        return txlist


class CATVBTCCoinpathSerializer(CATVSerializer):
    def validate_wallet_address(self, value):
        pattern = re.compile("^([13]|bc1).*[a-zA-Z0-9]{26,35}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address is an invalid Bitcoin address")
        return value

    def get_tracking_results(self, tx_limit=10000, limit=10000, save_to_db=True, build_lossy_graph=True):
        serializer_data = self.data
        tracking_results = BTCCoinpathTrackingResults(**serializer_data)
        try:
            tracking_results.get_tracking_data(tx_limit, limit, save_to_db)
            tracking_results.create_graph_data(build_lossy_graph)
            tracking_results.set_annotations_from_db(
                token_type=models.CatvTokens.BTC.value)
            return {
                "graph": tracking_results.make_graph_dict(),
                "api_calls": tracking_results.ext_api_calls,
                "messages": tracking_results.error_messages
            }
        except ReadTimeout:
            raise exceptions.FileNotFound("Timeout exceeded while fetching/processing data.")
        except Exception as e:
            err_msg = "Incorrect or missing transactions. Please try adjusting your search criteria."
            if tracking_results.error:
                err_msg = tracking_results.error
            elif e:
                err_msg = "Oops! Something went wrong while getting results for this address. Please try again later."
            raise exceptions.FileNotFound(err_msg)


class OrganizationUserPostSerializer(serializers.ModelSerializer):
    user = UserRelatedField(queryset=models.User.objects.all())
    organization = OrganizationRelatedField(
        queryset=models.Organization.objects.all())
    status = fields.EnumField(
        required=True, enum=models.OrganizationUserStatus)

    class Meta:
        model = models.OrganizationUser
        fields = ('user', 'organization', 'status')

    def validate(self, data):
        request = self.context.get("request", None)
        if request is None:
            raise exceptions.AuthenticationCheckError()
        current_user = request.user
        if data["organization"].administrator != current_user \
                and data["status"] != models.OrganizationUserStatus.ACTIVE:
            raise exceptions.OwnerRequiredError("You are not the owner of this organization")
        return data

    def create(self, validated_data):
        user = validated_data["user"]
        organization = validated_data["organization"]
        status = validated_data["status"]
        org_user_count = models.OrganizationUser.objects.filter(
            user=user).exclude(organization=organization).count()
        org_admin_count = models.Organization.objects.filter(
            administrator=user).count()
        if org_user_count > 0 or org_admin_count > 0:
            raise exceptions.DataIntegrityError(
                "User %s is already part of another organization".format(user.nickname))
        org_user = models.OrganizationUser.objects.update_or_create(user=user, organization=organization,
                                                                    defaults={'status': status})
        return org_user

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        return instance


class OrganizationSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Organization
        fields = ('uid', 'name', 'image', 'administrator', 'users',
                  'invites_left', 'domains', 'pending_invites')
        read_only_fields = ('uid', 'name', 'image', 'administrator',
                            'users', 'invites_left', 'pending_invites')

    uid = serializers.UUIDField(required=True)
    name = serializers.CharField(max_length=100, required=False)
    image = serializers.SerializerMethodField()
    administrator = UserRelatedField(queryset=models.User.objects.all())
    users = OrganizationUserPostSerializer(
        read_only=True, many=True, source='organizationuser_set')
    invites_left = serializers.SerializerMethodField()
    domains = serializers.ListField(
        child=serializers.CharField(), read_only=True, max_length=2)
    pending_invites = serializers.ReadOnlyField(required=False)

    def get_image(self, obj):
        if bool(obj.image) is False:
            return api_settings.S3_USER_IMAGE_DEFAULT
        else:
            return obj.image.url

    def get_invites_left(self, obj):
        invite_limit = obj.administrator.role.usage_role.values_list(
            'org_invite_limit', flat=True)
        invite_limit = invite_limit[0] if invite_limit else 20
        members_invited = models.OrganizationInvites.objects.filter(organization=obj). \
            exclude(status=models.OrganizationInviteStatus.APPROVED.value).count()
        existing_members = obj.organizationuser_set.count()
        return invite_limit - (members_invited + existing_members)


class OrganizationPostSerializer(serializers.ModelSerializer):
    uid = serializers.UUIDField(required=False, read_only=True)
    name = serializers.CharField(max_length=100, required=True)
    image = serializers.ImageField(
        required=False, max_length=10000000, allow_empty_file=True, use_url=False)
    administrator = UserRelatedField(queryset=models.User.objects.all())
    users = OrganizationUserPostSerializer(
        read_only=True, required=False, many=True, source='organizationuser_set')
    invites_left = serializers.SerializerMethodField()
    domains = serializers.ListField(
        child=serializers.CharField(), required=False, max_length=2)
    pending_invites = serializers.ReadOnlyField(required=False)

    class Meta:
        model = models.Organization
        fields = ('uid', 'name', 'image', 'administrator', 'users',
                  'invites_left', 'domains', 'pending_invites')

    def get_invites_left(self, obj):
        invite_limit = obj.administrator.role.usage_role.values_list(
            'org_invite_limit', flat=True)
        invite_limit = invite_limit[0] if invite_limit else 20
        members_invited = models.OrganizationInvites.objects.filter(organization=obj). \
            exclude(status=models.OrganizationInviteStatus.APPROVED.value).count()
        existing_members = obj.organizationuser_set.count()
        return invite_limit - (members_invited + existing_members)

    def validate_domains(self, data):
        if data:
            domain_list = data
            if len(domain_list) > 1 and domain_list[0] == domain_list[1]:
                raise exceptions.ValidationError(
                    "Both the domains cannot be the same")
            for domain in domain_list:
                if not re.match(r"(?!-)[A-Z\d.-]{1,63}(?<!-)$", domain, re.IGNORECASE):
                    raise exceptions.ValidationError("Invalid domain name")
        return data

    def validate(self, data):
        request = self.context.get("request", None)
        if request is None:
            raise exceptions.AuthenticationCheckError()

        if request.user.organizationuser_set.count() > 0:
            raise exceptions.ValidationError("You are already part of a different organization and cannot make a new "
                                             "organization")

        if request.method == "PUT":
            if self.instance.administrator != request.user:
                raise exceptions.OwnerRequiredError(
                    "You are not the owner of this organization")
            data["uid"] = request.data.get('uid', None)
            data["name"] = request.data.get('name', None)
            image = request.data.get("image", None)
            if image == "":
                data["image"] = ""
            return data

        if request.method == "POST":
            try:
                data["uid"] = request.data["uid"]
                data["name"] = request.data["name"]
                image = request.data.get("image", None)
                if image == "":
                    data["image"] = ""
            except KeyError:
                raise exceptions.ValidationError("Missing input fields")
        return data

    def create(self, validated_data):
        try:
            validated_data.pop('uid', None)
            validated_data.pop('users', [])
            user = self.context["request"].user
            if user:
                validated_data['domains'] = [user.email.split("@")[-1]]
            organization = models.Organization.objects.create(**validated_data)
            return organization
        except models.RoleUsageLimit.DoesNotExist:
            raise exceptions.ValidationError(
                "Invalid user (no role detected).")

    def update(self, instance, validated_data):
        try:
            instance_domain_set = set(instance.domains)
            updated_domain_set = set(validated_data['domains'])
            changed_domain = list(
                updated_domain_set.symmetric_difference(instance_domain_set))
            changed_domain = changed_domain[0] if changed_domain else None
            if changed_domain:
                models.OrganizationUser.objects.filter(organization=instance,
                                                       user__email__icontains='@{}'.format(changed_domain)).delete()
            instance = super().update(instance, validated_data)
            return instance
        except IntegrityError:
            raise exceptions.DataIntegrityError()


class InvitationSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    organization = serializers.UUIDField(required=True)
    type = fields.EnumField(enum=models.InviteType, required=False, default=models.InviteType.EMAIL)

    def get_invites_left(self, obj):
        invite_limit = obj.administrator.role.usage_role.values_list(
            'org_invite_limit', flat=True)
        invite_limit = invite_limit[0] if invite_limit else 20
        members_invited = models.OrganizationInvites.objects.filter(organization=obj). \
            exclude(status=models.OrganizationInviteStatus.APPROVED.value).count()
        existing_members = obj.organizationuser_set.count()
        return invite_limit - (members_invited + existing_members)

    def validate(self, data):
        try:
            request = self.context.get("request", None)
            if not request:
                exceptions.AuthenticationCheckError()
            uid = data['organization']
            invited_domain = data['email'].split("@")[-1]
            user = request.user

            if not user:
                raise exceptions.AuthenticationCheckError()

            org = models.Organization.objects.get(uid=uid, administrator=user)
            already_invited = models.OrganizationInvites.objects. \
                filter(email=data['email'], organization=org, status=models.OrganizationInviteStatus.EMAIL_SENT).count()

            if already_invited:
                raise exceptions.ValidationError("You have already sent an invitation to this email. Please wait for "
                                                 "72 hours before retrying")

            user_count = models.User.objects.filter(
                email=data['email']).count()
            invites_left = self.get_invites_left(org)
            if invites_left == 0:
                raise exceptions.ValidationError(
                    "Out of invites, cannot invite more.")
            if invited_domain not in org.domains:
                raise exceptions.ValidationError("You can only invite people based on your domain list.")
            if user_count > 0 and data['type'] == models.InviteType.EMAIL.value:
                raise exceptions.ValidationError("Cannot send invite as user is already signed up for Sentinel Portal. "
                                                 "Use the 'Add a member' option instead.")
            return data
        except models.Organization.DoesNotExist:
            raise exceptions.ValidationError(
                "Organization does not exist or you do not have invitation rights.")

    def save(self, data):
        raise NotImplementedError(
            "save is not implemented yet for this serializer")


class SocialSerializer(serializers.Serializer):
    access_token = serializers.CharField(
        allow_blank=False, trim_whitespace=True, required=True)


class CATVHistorySerializer(serializers.Serializer):
    token_type = fields.EnumField(enum=models.CatvTokens, required=True)
    path_search = serializers.BooleanField(default=False, required=False)

    def validate_token_type(self, data):
        if not data or data.value.upper() not in models.CatvTokens.__members__.keys():
            raise serializers.ValidationError("Token type unsupported.")
        return data


class CATVEthPathSerializer(serializers.Serializer):
    address_from = serializers.CharField(required=True)
    address_to = serializers.CharField(required=True)
    token_address = serializers.CharField(
        required=False, default='0x0000000000000000000000000000000000000000')
    depth = serializers.IntegerField(
        required=False, min_value=1, max_value=10, default=5)
    from_date = serializers.CharField(
        required=False, default=timezone.datetime(2015, 1, 1).strftime('%Y-%m-%d'))
    to_date = serializers.CharField(
        required=False, default=timezone.now().strftime('%Y-%m-%d'))
    min_tx_amount = serializers.FloatField(required=False, default=0.0)
    limit_address_tx = serializers.IntegerField(required=False, default=100000)
    force_lookup = serializers.BooleanField(required=False, default=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._token_type = models.CatvTokens.ETH.value
        self._tracker = EthPathResults

    def validate_address_from(self, value):
        pattern = re.compile("^0x[a-fA-F0-9]{40}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address 'address_form' is not a valid ethereum address.")
        return value

    def validate_address_to(self, value):
        pattern = re.compile("^0x[a-fA-F0-9]{40}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address 'address_to' is not a valid ethereum address.")
        return value

    def validate_from_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def validate_to_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def validate(self, data):
        if data['address_from'].lower() == data['address_to'].lower():
            raise serializers.ValidationError("Source and destination addresses cannot be same. Perhaps you meant to "
                                              "use the '/catv' resource?")
        return data

    def get_tracking_results(self, save_to_db=False):
        tracking_instance = self._tracker(**self.data)
        try:
            tracking_instance.get_tracking_data()
            tracking_instance.create_graph_data()
            tracking_instance.set_annotations_from_db(
                token_type=self._token_type)
            return {
                "graph": tracking_instance.make_graph_dict(),
                "api_calls": tracking_instance.ext_api_calls,
                "messages": tracking_instance.error_messages
            }
        except ReadTimeout:
            raise exceptions.FileNotFound("Timeout exceeded while fetching/processing data.")
        except Exception as e:
            err_msg = "Incorrect or missing transactions. Please try adjusting your search criteria."
            if tracking_instance.error:
                err_msg = tracking_instance.error
            elif e:
                err_msg = "Oops! Something went wrong while getting results for this address. Please try again later."
            raise exceptions.FileNotFound(err_msg)


class CatvBtcPathSerializer(CATVEthPathSerializer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._token_type = models.CatvTokens.BTC.value
        self._tracker = BtcPathResults

    def validate_address_from(self, value):
        pattern = re.compile("^([13]|bc1).*[a-zA-Z0-9]{26,35}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address 'address_form' is not a valid bitcoin address.")
        return value

    def validate_address_to(self, value):
        pattern = re.compile("^([13]|bc1).*[a-zA-Z0-9]{26,35}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address 'address_to' is not a valid bitcoin address.")
        return value

class UserIndicatorSerializer(NonNullModelSerializer):
    security_category = fields.EnumField(enum=models.IndicatorSecurityCategory)
    pattern_subtype = fields.EnumField(enum=models.IndicatorPatternSubtype)
    pattern_type = fields.EnumField(enum=models.IndicatorPatternType)

    class Meta:
        model = models.UserIndicator
        fields = ("id", "uid", "security_category", "pattern", "pattern_subtype",
                  "pattern_type", "security_tags", "created", "points", "status")
        read_only_fields = ("id", "uid", "security_category", "pattern", "pattern_subtype",
                  "pattern_type", "security_tags", "created", "points", "status")

class CATVRequestListSerializer(NonNullModelSerializer):
    wallet_address = serializers.SerializerMethodField()
    address_type = serializers.SerializerMethodField()
    date_range = serializers.SerializerMethodField()
    depth = serializers.SerializerMethodField()
    status = fields.EnumField(enum=models.CatvTaskStatusType)
    created = serializers.SerializerMethodField()
    token_address = serializers.SerializerMethodField()

    class Meta:
        model = models.CatvRequestStatus
        fields = ("id", "uid", "created", "status", "wallet_address",
                  "address_type", "date_range", "depth", "token_address")
        read_only_fields = ("id", "uid", "created", "status", "wallet_address",
                            "address_type", "date_range", "depth", "token_address")
        
    def get_wallet_address(self, obj):
        if obj.params:
            if obj.params.get("address_from", ""):
                return obj.params["address_from"]
            return obj.params.get("wallet_address", "")
        return ""
    
    def get_address_type(self, obj):
        if obj.params:
            address_from = obj.params.get("address_from", "")
            if address_from:
                return utils.determine_wallet_type(address_from)
            return utils.determine_wallet_type(obj.params.get("wallet_address", ""))
        return "Ethereum"
    
    def get_date_range(self, obj):
        if obj.params:
            from_date = parser.parse(obj.params.get("from_date", "2015-01-01")).strftime("%d/%m/%Y")
            to_date = parser.parse(obj.params.get("to_date", "2020-01-01")).strftime("%d/%m/%Y")
            return f"{from_date} - {to_date}"
        return ""
    
    def get_depth(self, obj):
        if obj.params:
            if obj.params.get("depth", 0) > 0:
                return obj.params["depth"]
            else:
                source_depth = obj.params.get("source_depth", 0)
                distribution_depth = obj.params.get("distribution_depth", 0)
                return f"{source_depth} / {distribution_depth}"
        return ""

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple()) * 1000
    
    def get_token_address(self, obj):
        if obj.params:
            return obj.params.get("token_address", "")
        return ""
