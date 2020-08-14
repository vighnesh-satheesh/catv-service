import uuid
import hashlib
from functools import partial
from io import BytesIO
from enum import Enum, IntEnum, unique
from urllib.parse import urlparse, urlunparse, ParseResult

from django.db import models
from django.contrib.auth.hashers import (
    check_password, make_password,
)
from django.contrib.postgres.fields import ArrayField, JSONField
from django.contrib.postgres.indexes import GistIndex, GinIndex
from django.utils.safestring import mark_safe
from django.template.defaultfilters import truncatechars
from django.utils.timezone import now
from django.db.models.lookups import IContains
from django_bulk_update.manager import BulkUpdateManager

import random
import string
import magic
from PIL import Image
from enumfields import EnumField
from indicatorlib import Pattern

from .settings import api_settings
from .storages.s3 import StaticS3Storage
from .fields import LtreeField
from . import validates
from .managers import CustomManager

ImageStorage = StaticS3Storage(
    region=api_settings.S3_REGION,
    key=api_settings.S3_ICO_IMAGE_KEY_PREFIX,
    resize=True
)

UserImageStorage = StaticS3Storage(
    region=api_settings.S3_REGION,
    key=api_settings.S3_USER_IMAGE_KEY_PREFIX,
    resize=True
)


def get_file_meta(file, uid, block_size=65536):
    hasher = hashlib.md5()
    size = 0
    mimetype = "application/octet-stream"
    index = 0
    total_buf = b''
    for buf in iter(partial(file.read, block_size), b''):
        total_buf += buf
        hasher.update(buf)
        size += len(buf)

        if index == 0:
            mimetype = magic.from_buffer(buf, mime=True)

    return (hasher.hexdigest(), size, mimetype)


def resize_image(file, block_size=65536):
    total_buf = b''
    for buf in iter(partial(file.read, block_size), b''):
        total_buf += buf

    with BytesIO() as output:
        with Image.open(BytesIO(total_buf)) as im:
            im.resize((64, 64), Image.ANTIALIAS)
            im.save(output, format=im.format)
        return output
    return None


def file_upload_path(instance, filename):
    uid = uuid.uuid4()
    instance.uid = uid
    (hash, size, mimetype) = get_file_meta(instance.file, instance.uid)
    instance.hash = hash
    instance.size = size
    instance.type = mimetype
    instance.name = filename
    return str(uid)


def image_upload_path(instance, filename):
    uid = uuid.uuid4()
    instance.image = resize_image(instance.image)
    return str(uid)


def add_trailing_slash(url):
    parsed = urlparse(url)

    if parsed.scheme not in ["http", "https", "ftp"]:
        return url

    if parsed.netloc == "":
        return url

    if parsed.path == "":
        return urlunparse(ParseResult(parsed.scheme, parsed.netloc, "/",
                                      parsed.params, parsed.query, parsed.fragment))
    elif parsed.path[-1] == "/":
        return url
    else:
        last_path = parsed.path.rsplit("/", 1)[-1]
        if last_path.find(".") > 0:
            return url
        else:
            return urlunparse(ParseResult(parsed.scheme, parsed.netloc, parsed.path + "/",
                                          parsed.params, parsed.query, parsed.fragment))


def generate_api_key():
    return "".join(random.choice(string.ascii_letters) for x in range(40))


def get_default_role():
    return Role.objects.filter(role_name='communityuser').values_list('id', flat=True)[0]


def get_permission_from_status(status):
    return {
        CaseStatus.NEW.value: PermissionList.CHANGE_NEW,
        CaseStatus.PROGRESS.value: PermissionList.CHANGE_PROGRESS,
        CaseStatus.REJECTED.value: PermissionList.CHANGE_REJECT,
        CaseStatus.CONFIRMED.value: PermissionList.CHANGE_CONFIRM,
        CaseStatus.RELEASED.value: PermissionList.CHANGE_RELEASE
    }[status]


class UserRoles(Enum):
    COMMUNITY = 'communityuser'
    PAID = 'paiduser'
    ORG = 'organization'
    ORG_TRIAL = 'organization-trial'
    SENTINEL = 'sentinel'
    SUPERSENTINEL = 'supersentinel'
    COMMUNITY_VERIFIED = 'communityuser-verified'


class UserPermission(Enum):
    USER = 'user'
    EXCHANGE = 'exchange'
    SENTINEL = 'sentinel'
    SUPERSENTINEL = 'supersentinel'


class ProductType(Enum):
    CATV = 'catv'
    CARA = 'cara'
    ICF = 'api'


class PermissionList(Enum):
    CHANGE_CONFIRM = 'change_confirm'
    CHANGE_NAME = 'change_name'
    CHANGE_PROGRESS = 'change_progress'
    CHANGE_REJECT = 'change_reject'
    CHANGE_RELEASE = 'change_release'
    CREATE_CASE = 'create_case'
    CREATE_INDICATOR = 'create_indicator'
    EDIT_CASE = 'edit_case'
    MODIFY_ALL = 'modify_all'
    MODIFY_TEAM = 'modify_team'
    RENEW_KEY = 'renew_key'
    RESET_PASSWORD = 'reset_password'
    SEARCH_CASE = 'search_case'
    SEARCH_INDICATOR = 'search_indicator'
    VIEW_ALL = 'view_all'
    VIEW_KEY = 'view_key'
    VIEW_CASE = 'view_case'
    CHANGE_NEW = 'change_new'
    QUICKVIEW_ALL_INDICATORS = 'view_shortcut'
    CATV_EXPORT_DATA = 'export_data'
    CATV_EXPORT_IMAGE = 'export_image'
    CARA_EXPORT_REPORT = 'export_report'
    VIEW_ORG_CASES = 'view_org_cases'
    ACCESS_CATV = 'access_catv'
    ACCESS_CARA = 'access_cara'
    ACCESS_API = 'access_api'


class UserStatus(Enum):
    SIGNED_UP = 'signedup'
    EMAIL_CONFIRMED = 'emailconfirmed'
    SUSPENDED = 'suspended'
    APPROVED = 'approved'


class CaseStatus(Enum):
    NEW = 'new'
    PROGRESS = 'progress'
    REJECTED = 'rejected'
    CONFIRMED = 'confirmed'
    RELEASED = 'released'


class IndicatorPatternType(Enum):
    NETWORKADDR = 'addr'
    CRYPTOADDR = 'cryptoaddr'
    FILEHASH = 'filehash'
    SOCIALMEDIA = 'socialmedia'
    OTHER = 'other'


class IndicatorPatternSubtype(Enum):
    # cryptoaddr subtype
    ETH = 'ETH'
    ETC = 'ETC'
    EOS = 'EOS'
    BTC = 'BTC'
    BCH = 'BCH'
    LTC = 'LTC'
    DASH = 'DASH'
    ZEC = 'ZEC'
    XMR = 'XMR'
    NEO = 'NEO'
    XRP = 'XRP'
    NA = 'NA'
    KLAY = 'KLAY'
    TRON = 'TRX'
    XLM = 'XLM'
    BNB = 'BNB'
    ADA = 'ADA'
    PHON = 'PHON'
    # network address
    URL = 'url'
    EMAIL = 'email'
    DOMAIN = 'domain'
    HOSTNAME = 'hostname'
    IPV4 = 'ipv4'
    # file hash
    SHA256 = 'sha256'
    MD5 = 'md5'
    # social media
    TWITTER = 'twitter'
    FACEBOOK = 'facebook'
    YOUTUBE = 'youtube'
    TELEGRAM = 'telegram'

    # other
    OTHER = 'other'

    @classmethod
    def cryptoaddr_subtypes(cls):
        return [cls.ETH, cls.ETC, cls.EOS, cls.BTC, cls.BCH,
                cls.LTC, cls.DASH, cls.ZEC, cls.XMR, cls.NEO, cls.XRP, cls.NA,
                cls.KLAY, cls.TRON, cls.XLM, cls.BNB, cls.ADA, cls.PHON]

    @classmethod
    def networkaddr_subtypes(cls):
        return [cls.URL, cls.EMAIL, cls.DOMAIN, cls.HOSTNAME, cls.IPV4, cls.OTHER]

    @classmethod
    def filehash_subtypes(cls):
        return [cls.SHA256, cls.MD5]

    @classmethod
    def socialmedia_subtypes(cls):
        return [cls.TWITTER, cls.FACEBOOK, cls.YOUTUBE, cls.TELEGRAM]


class IndicatorVector(Enum):
    EMAIL = 'email'
    WEBSITE = 'website'
    SOCIAL_MEDIA = 'social_media'
    OTHER = 'other'

    @classmethod
    def indicator_vector_type(cls):
        return [cls.EMAIL, cls.WEBSITE, cls.SOCIAL_MEDIA, cls.OTHER]


class IndicatorEnvironment(Enum):
    WINDOWS = 'windows'
    MACOS = 'macos'
    IOS = 'ios'
    ANDROID = 'android'

    @classmethod
    def indicator_environment_type(cls):
        return [cls.WINDOWS, cls.MACOS, cls.IOS, cls.ANDROID]


class IndicatorSecurityCategory(Enum):
    WHITELIST = 'whitelist'
    BLACKLIST = 'blacklist'
    GRAYLIST = 'graylist'


class APIKeyType(Enum):
    UNLIMITED = 0
    LIMITED = 1


class ExchangeStatus(Enum):
    PENDING = 'PENDING_APPROVAL'
    APPROVED = 'APPROVED'
    TRANSFERRED = 'TRANSFERRED'
    REJECTED = 'REJECTED'


class EmailSentType(Enum):
    REGISTER = 'REGISTER'
    VERIFICATION_RESEND = 'VERIFICATION_RESEND'
    PASSWORD_RESET = 'PASSWORD_RESET'
    VERIFIED = 'VERIFIED'
    NOTIFICATION = 'NOTIFICATION'
    INVITATION = 'INVITATION'
    EXCHANGE_SUBMIT = 'EXCHANGE_SUBMIT'


class NotificationType(Enum):
    CASE_STATUS_UPDATED_TO_NEW = 'case_status_updated_to_new'
    CASE_STATUS_UPDATED_TO_PROGRESS = 'case_status_updated_to_progress'
    CASE_STATUS_UPDATED_TO_REJECTED = 'case_status_updated_to_rejected'
    CASE_STATUS_UPDATED_TO_CONFIRMED = 'case_status_updated_to_confirmed'
    CASE_STATUS_UPDATED_TO_RELEASED = 'case_status_updated_to_released'
    CASE_UPDATED = 'case_updated'
    CASE_DELETED = 'case_deleted'
    COMMENT = 'comment'
    COMMENT_MENTIONED = 'comment_mentioned'
    ADDED_TO_ORG = 'added_to_org'


class OrganizationUserStatus(Enum):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    PENDING = 'pending'


class OrganizationInviteStatus(str, Enum):
    EMAIL_SENT = 'Email sent'
    PENDING_APPROVAL = 'Pending system approval'
    APPROVED = 'Approved'
    SUSPENDED = 'Suspended'
    REJECTED = 'Rejected'
    EXPIRED = 'Expired'


class InviteType(str, Enum):
    EMAIL = 'EMAIL',
    NOTIFICATION = 'NOTIFICATION'


class CatvTokens(Enum):
    ETH = 'ETH'
    BTC = 'BTC'
    TRON = 'TRX'
    LTC = 'LTC'


class CatvSearchType(Enum):
    PATH = 'path'
    FLOW = 'flow'


class CatvTaskStatusType(Enum):
    PROGRESS = 'progress'
    RELEASED = 'released'
    FAILED = 'failed'


class UpgradeVerifyStatus(Enum):
    PENDING = 'pending'
    VERIFIED = 'verified'
    FAILED = 'failed'
    EXPIRED = 'expired'


@unique
class FileStatus(IntEnum):
    NEW = 0
    COMPLETED = 1000


class PostgresILike(IContains):
    lookup_name = 'ilike'

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = lhs_params + rhs_params
        return '%s ILIKE %s' % (lhs, rhs), params


class PostgresArrayILike(IContains):
    lookup_name = 'arrayilike'

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = lhs_params + rhs_params
        return 'array_to_text(%s) ILIKE %s' % (lhs, rhs), params


class CustomGinIndex(GinIndex):
    def create_sql(self, model, schema_editor, using=''):
        statement = super().create_sql(model, schema_editor)
        statement.template = "CREATE INDEX %(name)s ON %(table)s%(using)s (%(columns)s gin_trgm_ops)%(extra)s"
        return statement


models.CharField.register_lookup(PostgresILike)
models.TextField.register_lookup(PostgresILike)
ArrayField.register_lookup(PostgresArrayILike)


class RewardSetting(models.Model):
    min_token = models.BigIntegerField(null=True, blank=True)
    token_abi = models.CharField(null=True, blank=True, max_length=5196)
    token_address = models.CharField(null=True, blank=True, max_length=512)
    sentinel_point_reward = models.BigIntegerField(null=True, blank=True)
    upp_reward = models.BigIntegerField(null=True, blank=True)
    sp_required = models.BigIntegerField(null=True, blank=True)

    def __int__(self):
        return self.min_token


class ExchangeToken(models.Model):
    sp_amount = models.IntegerField(null=True, blank=True)
    status = EnumField(enum=ExchangeStatus, default=ExchangeStatus.PENDING)
    req_time = models.CharField(null=True, blank=True, max_length=1024)
    app_time = models.CharField(null=True, blank=True, max_length=1024)
    upp = models.IntegerField(null=True, blank=True)
    user_id = models.CharField(null=True, blank=True, max_length=1024)

    def __str__(self):
        return self.user_id

    class Meta:
        db_table = 'api_exchange_token'


class Role(models.Model):
    role_name = models.CharField(max_length=128, unique=True)
    display_name = models.CharField(max_length=128, null=True)

    def __str__(self):
        return self.role_name


class Action(models.Model):
    resourceid = models.IntegerField(null=True, blank=True)
    resource = models.CharField(max_length=128, null=True, blank=True)
    action = models.CharField(max_length=500, null=False, blank=False)
    codename = models.CharField(max_length=128, null=False, blank=False)

    def __str__(self):
        return self.action


class RolePermissionQuerySet(models.query.QuerySet):
    def get_permission_matrix_queryset(self, role_id, action_name=None):
        if action_name:
            query_set = self.all().values_list('role__display_name', 'action__codename', 'allowed'). \
                filter(role__id=role_id, action__codename=action_name)
        else:
            query_set = self.all().values_list('role__display_name', 'action__codename', 'allowed'). \
                filter(role__id=role_id)

        return query_set


class RolePermissionManager(models.Manager):
    use_for_related_fields = True

    def get_queryset(self):
        return RolePermissionQuerySet(self.model)

    def get_permission_matrix(self, role_id, action_name=None):
        query_set = self.get_queryset().get_permission_matrix_queryset(role_id, action_name)
        role_name = query_set[0][0]
        query_set = dict([(r[1], r[2]) for r in query_set])
        return query_set, role_name


class RolePermission(models.Model):
    role = models.ForeignKey(
        Role, null=False, blank=False, on_delete=models.CASCADE, related_name='role')
    action = models.ForeignKey(Action, null=False, blank=False,
                               on_delete=models.CASCADE, related_name='role_action')
    allowed = models.BooleanField(default=False)
    objects = RolePermissionManager()

    def __str__(self):
        return self.role.role_name + '-' + self.action.resource + '-' + self.action.action

    class Meta:
        db_table = 'api_role_permission'


# models
class User(models.Model):
    email = models.EmailField(unique=True)
    address = models.CharField(unique=True, null=True, max_length=128)
    nickname = models.CharField(max_length=128, unique=True)
    password = models.CharField(max_length=128)
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    timestamp = models.DateTimeField(default=now)
    created = models.DateTimeField(default=now)
    last_logged_out = models.DateTimeField(default=now)
    permission = EnumField(enum=UserPermission,
                           default=UserPermission.SENTINEL, max_length=16)
    email_notification = models.BooleanField(default=True)
    image = models.ImageField(
        null=True, blank=True, storage=UserImageStorage, upload_to=image_upload_path)
    status = EnumField(
        enum=UserStatus, default=UserStatus.APPROVED, max_length=16)
    role = models.ForeignKey(Role, on_delete=models.PROTECT,
                             default=get_default_role)
    points = models.BigIntegerField(null=False, blank=False, default=0)

    def is_authenticated(self, *args, **kwargs):
        return True

    def set_password(self, raw_password):
        self.password = make_password(raw_password)
        self._password = raw_password

    def check_password(self, raw_password):
        """
        Return a boolean of whether the raw_password was correct. Handles
        hashing formats behind the scenes.
        """
        def setter(raw_password):
            self.set_password(raw_password)
            # Password hash upgrades shouldn't be considered password changes.
            self._password = None
            self.save(update_fields=["password"])
        return check_password(raw_password, self.password)  # , setter)

    def update(self, *arg, **kwargs):
        try:
            if kwargs["password"] is not None:
                self.set_password(kwargs["password"])
        except KeyError:
            pass
        try:
            if kwargs["address"] is not None:
                self.address = kwargs["address"]
        except KeyError:
            pass
        try:
            if kwargs["points"] is not None:
                self.points = kwargs["points"]
        except KeyError:
            pass
        try:
            if kwargs["image"] is not None:
                self.image = kwargs["image"]
        except KeyError:
            pass
        try:
            if kwargs["status"] is not None:
                self.status = kwargs["status"]
        except KeyError:
            pass
        try:
            if kwargs["nickname"] is not None:
                self.nickname = kwargs["nickname"]
        except KeyError:
            pass
        try:
            if kwargs["email_notification"] is not None:
                self.email_notification = kwargs["email_notification"]
        except KeyError:
            pass
        return super(User, self).save()

    def clean(self):
        validates.validate_password(self, self.password, model=True)
        return super(User, self).clean()

    @property
    def role_indexing(self):
        if self.role is not None:
            return self.role.role_name

    @property
    def permission_indexing(self):
        if self.permission is not None:
            return self.permission.value

    @property
    def status_indexing(self):
        if self.status is not None:
            return self.status.value


class RoleUsageLimit(models.Model):
    role = models.ForeignKey(Role, null=False, blank=False,
                             on_delete=models.CASCADE, related_name='usage_role')
    api_limit = models.IntegerField(null=True, default=5)
    catv_limit = models.IntegerField(null=True, default=5)
    cara_limit = models.IntegerField(null=True, default=5)
    org_invite_limit = models.IntegerField(null=True, default=0)

    class Meta:
        db_table = 'api_role_usage_limit'

    def __str__(self):
        return self.role.role_name


class Case(models.Model):
    # user generated info
    title = models.CharField(
        max_length=api_settings.CASE_TITLE_MAX_LEN, default='')
    detail = models.TextField(
        default='', max_length=api_settings.CASE_DETAIL_MAX_LEN)
    rich_text_detail = models.CharField(
        default='', max_length=api_settings.CASE_DETAIL_MAX_LEN)
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # auto generated info
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)
    status = EnumField(enum=CaseStatus, default=CaseStatus.NEW)
    reporter_info = models.CharField(
        max_length=api_settings.CASE_REPORTER_MAX_LEN, null=True, blank=True)
    reporter = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='reporter')
    owner = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='owner')
    verifier = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='verifier')

    block_num = models.IntegerField(null=True, blank=True)
    # block_id = models.CharField(max_length=64, null=True, blank=True)
    transaction_id = models.CharField(max_length=64, null=True, blank=True)

    ico = models.ForeignKey('ICO', null=True, blank=True,
                            on_delete=models.DO_NOTHING)
    related_case = models.ForeignKey(
        'RelatedCase', null=True, blank=True, on_delete=models.DO_NOTHING)
    indicators = models.ManyToManyField('Indicator', through='CaseIndicator')

    @property
    def status_indexing(self):
        if self.status is not None:
            return self.status.value

    @property
    def indicator_indexing(self):
        if self.indicators is not None:
            return [
                {
                    'id': indicator.id,
                    'uid': indicator.uid,
                    'security_type': indicator.security_category,
                    'pattern_type': indicator.pattern_type,
                    'pattern_subtype': indicator.pattern_subtype,
                    'annotation': indicator.annotation,
                    'pattern': indicator.pattern
                } for indicator in self.indicator_set.all()
            ]

    class Meta:
        indexes = [
            models.Index(fields=['uid']),
            models.Index(fields=['status', ]),
            models.Index(fields=['owner', ]),
            models.Index(fields=['created', ]),
            CustomGinIndex(fields=['title', ]),
        ]

    def save(self, *args, **kargs):
        return super(Case, self).save(*args, **kargs)

    def clean(self):
        validates.validate_max_length(
            self.detail, model=True, limit=api_settings.CASE_DETAIL_MAX_LEN, field_name="detail")
        return super(Case, self).clean()


class CaseHistory(models.Model):
    case = models.ForeignKey(Case, on_delete=models.CASCADE)
    initiator = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DO_NOTHING)
    log = models.TextField()
    created = models.DateTimeField(default=now)

    class Meta:
        indexes = [
            models.Index(fields=['case', ]),
            models.Index(fields=['created', ]),
        ]


class RelatedCase(models.Model):
    related = models.ForeignKey(Case, on_delete=models.DO_NOTHING)

    class Meta:
        db_table = 'api_related_case'


class Annotation(models.Model):
    annotation = models.CharField(max_length=256, blank=True, null=True)
    created = models.DateTimeField(default=now)


class Indicator(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(User, null=True, blank=True,
                             on_delete=models.DO_NOTHING, related_name='indicator_user')
    cases = models.ManyToManyField(Case, through='CaseIndicator')

    security_category = EnumField(enum=IndicatorSecurityCategory)
    security_tags = ArrayField(models.CharField(
        max_length=32, blank=False), blank=True, null=True)
    vector = ArrayField(EnumField(enum=IndicatorVector,
                                  max_length=32), blank=True, null=True)
    environment = ArrayField(
        EnumField(enum=IndicatorEnvironment, max_length=32), blank=True, null=True)

    pattern = models.CharField(max_length=256)
    pattern_type = EnumField(enum=IndicatorPatternType,
                             blank=False, null=False, max_length=32)
    pattern_subtype = EnumField(
        enum=IndicatorPatternSubtype, blank=True, null=True)
    pattern_tree = LtreeField(blank=False, null=False)

    detail = models.TextField(default='', blank=True, null=True,
                              max_length=api_settings.INDICATOR_DETAIL_MAX_LEN)
    annotation = models.CharField(max_length=256, blank=True, null=True)
    annotations = models.ManyToManyField(
        Annotation, through='IndicatorAnnotation')
    reporter_info = models.CharField(
        max_length=api_settings.CASE_REPORTER_MAX_LEN, null=True, blank=True)

    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)
    objects = CustomManager()

    @property
    def security_category_indexing(self):
        if self.security_category is not None:
            return self.security_category.value

    @property
    def pattern_type_indexing(self):
        if self.pattern_type is not None:
            return self.pattern_type.value

    @property
    def pattern_subtype_indexing(self):
        if self.pattern_subtype is not None:
            return self.pattern_subtype.value

    @property
    def security_tags_indexing(self):
        s_tags = []
        if self.security_tags:
            for tag in self.security_tags:
                s_tags.append(tag)
        return s_tags

    @property
    def vector_indexing(self):
        vectors = []
        if self.vector:
            for vector in self.vector:
                vectors.append(vector.value)
        return vectors

    @property
    def environment_indexing(self):
        environs = []
        if self.environment:
            for environ in self.environment:
                environs.append(environ.value)
        return environs

    @property
    def cases_indexing(self):
        status_list = []
        if self.cases.count():
            enum_status_list = self.cases.all().values_list('status', flat=True)
            for enum_status in enum_status_list:
                status_list.append(enum_status.value)
        return ", ".join(status_list)

    @property
    def annotations_indexing(self):
        return self.annotation

    @property
    def latest_case_indexing(self):
        if self.cases.count():
            latest_case = self.cases.latest('id')
            return latest_case.uid
        return ""

    @property
    def user_id_indexing(self):
        return self.user_id if self.user_id else 0

    class Meta:
        indexes = [
            GistIndex(fields=['pattern_tree', ]),
            models.Index(fields=['uid']),
            models.Index(fields=['pattern_tree', ]),
            models.Index(fields=['user']),
            CustomGinIndex(fields=['pattern', ]),
            CustomGinIndex(fields=['pattern_subtype', ]),
            models.Index(fields=['annotation', ]),
            models.Index(fields=['pattern', ]),
        ]

    @property
    def short_pattern(self):
        return truncatechars(self.pattern, 50)

    def save(self, *args, **kwargs):
        # removing trailing slash
        if self.pattern[-1] == '/':
            self.pattern = self.pattern[:-1]
        self.pattern_tree = Pattern.getMaterializedPathForInsert(
            self.pattern.lower())
        return super(Indicator, self).save(*args, **kwargs)

    def clean(self):
        validates.validate_max_length(
            self.pattern, model=True, limit=api_settings.INDICATOR_PATTERN_MAX_LEN, field_name="pattern")
        validates.validate_max_length(
            self.detail, model=True, limit=api_settings.CASE_DETAIL_MAX_LEN, field_name="detail")
        validates.validate_pattern_type_subtype(
            self.pattern_type, self.pattern_subtype, model=True)
        validates.validate_security_type_tag(
            self.security_category, self.security_tags, model=True)
        validates.validate_indicator_vector(self.vector, model=True)
        validates.validate_indicator_environment(self.vector, model=True)
        return super(Indicator, self).clean()


class CaseIndicator(models.Model):
    case = models.ForeignKey(Case, on_delete=models.CASCADE)
    indicator = models.ForeignKey(Indicator, on_delete=models.CASCADE)

    class Meta:
        db_table = 'api_m2m_case_indicator'


class IndicatorAnnotation(models.Model):
    indicator = models.ForeignKey(Indicator, on_delete=models.CASCADE)
    annotation = models.ForeignKey(Annotation, on_delete=models.CASCADE)

    class Meta:
        db_table = 'api_m2m_indicator_annotation'


class ICO(models.Model):
    name = models.CharField(max_length=128, default='')
    symbol = models.CharField(max_length=128, default='')
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    verifier = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='%(class)s_verifier')
    image = models.ImageField(
        null=True, blank=True, storage=ImageStorage, upload_to=image_upload_path)
    type = models.TextField(null=True, blank=True)
    subtitle = models.TextField(null=True, blank=True)
    website = models.TextField(null=True, blank=True)
    detail = models.TextField(null=True, blank=True)
    platform = models.TextField(null=True, blank=True)
    category = models.TextField(null=True, blank=True)
    country = models.TextField(null=True, blank=True)
    opened = models.DateTimeField(null=True, blank=True)
    closed = models.DateTimeField(null=True, blank=True)

    user = models.ForeignKey(User, null=True, blank=True,
                             on_delete=models.DO_NOTHING, related_name='ico_user')
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "{0}({1})".format(self.name, self.symbol)


class AttachedFile(models.Model):
    file = models.FileField(upload_to=file_upload_path, default='')
    name = models.TextField(null=True, blank=True)
    hash = models.TextField(null=True, blank=True)
    type = models.TextField(null=True, blank=True)
    size = models.IntegerField(null=True, blank=True)
    status = EnumField(enum=FileStatus, default=FileStatus.NEW)
    created = models.DateTimeField(default=now)
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    uploader = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='uploader')
    case = models.ForeignKey(Case, null=True, blank=True,
                             on_delete=models.CASCADE, related_name='case')
    indicator = models.ForeignKey(
        Indicator, null=True, blank=True, on_delete=models.CASCADE, related_name='indicator')

    class Meta:
        db_table = "api_file"
        indexes = [
            models.Index(fields=['case', 'indicator', ]),
        ]

    @property
    def link(self):
        return mark_safe("<a href={url}>Download</a>".format(url=self.file.url))


class TRDBCaseTransaction(models.Model):
    case_uid = models.UUIDField(default=uuid.uuid4, editable=False)
    action = models.TextField()
    payload = models.TextField()
    created = models.DateTimeField(default=now)
    status = models.IntegerField(default=0)
    head_block_num = models.IntegerField(null=True, blank=True)
    transaction_id = models.CharField(max_length=64, null=True, blank=True)
    block_num = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "trdb_case_transaction"
        indexes = [
            models.Index(fields=['case_uid', ]),
            models.Index(fields=['status', ]),
            models.Index(fields=['created', ]),
        ]


class UppwardRewardInfo(models.Model):
    aid = models.CharField(max_length=100)
    uid = models.CharField(max_length=100)
    cid = models.CharField(max_length=100)
    referral_code = models.CharField(max_length=100)
    token_addr = models.CharField(max_length=100)
    created = models.DateTimeField(default=now)

    class Meta:
        db_table = "uppward_reward_info"
        indexes = [
            models.Index(fields=['created', ]),
        ]


class CaseInvalidateCandidates(models.Model):
    case = models.ForeignKey(Case, on_delete=models.DO_NOTHING)
    old_status = EnumField(enum=CaseStatus)
    new_status = EnumField(enum=CaseStatus)
    created = models.DateTimeField(default=now)
    status = models.IntegerField(default=0)

    class Meta:
        db_table = "case_invalidate_candidates"
        indexes = [
            models.Index(fields=['case', ]),
            models.Index(fields=['created', ]),
        ]


class Key(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    api_key = models.CharField(
        default=generate_api_key, max_length=40, blank=True, null=True, unique=True)
    request_assign = models.IntegerField(
        default=10000000, blank=True, null=True)
    request_current = models.IntegerField(default=0, blank=True, null=True)
    type_id = EnumField(enum=APIKeyType, default=APIKeyType.LIMITED)
    name = models.CharField(default="", max_length=128, blank=True, null=True)
    domain = ArrayField(models.CharField(
        max_length=256, blank=True), blank=True, null=True)
    domain_restricted = models.NullBooleanField(
        default=False, blank=True, null=True)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE)
    created = models.DateTimeField(default=now)
    expire_datetime = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', ]),
            models.Index(fields=['created', ]),
        ]

    def save(self, *args, **kargs):
        return super(Key, self).save(*args, **kargs)


class EmailSent(models.Model):
    email = models.EmailField(unique=False)
    created = models.DateTimeField(default=now)
    type = EnumField(enum=EmailSentType, max_length=20)


class Comment(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    body = models.TextField(
        max_length=api_settings.COMMENT_BODY_MAX_LEN, default="")
    writer = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE)
    case = models.ForeignKey(
        Case, null=True, blank=True, on_delete=models.CASCADE)
    indicator = models.ForeignKey(
        Indicator, null=True, blank=True, on_delete=models.CASCADE)
    ico = models.ForeignKey(ICO, null=True, blank=True,
                            on_delete=models.CASCADE)
    deleted = models.BooleanField(default=False)
    created = models.DateTimeField(default=now)

    class Meta:
        indexes = [
            models.Index(fields=['writer']),
            models.Index(fields=['case']),
            models.Index(fields=['indicator']),
            models.Index(fields=['ico'])
        ]


class Notification(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(User, null=True, blank=True,
                             on_delete=models.CASCADE, related_name='user')
    initiator = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE, related_name='initiator')
    target = JSONField(default={})
    read = models.BooleanField(default=False)
    created = models.DateTimeField(default=now)
    type = EnumField(enum=NotificationType, max_length=64)

    class Meta:
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['created'])
        ]


class BloxyDistribution(models.Model):
    address = models.CharField(null=False, max_length=50)
    depth_limit = models.IntegerField(null=True)
    transaction_limit = models.IntegerField(null=True)
    from_time = models.DateTimeField(null=True)
    till_time = models.DateTimeField(null=True)
    result = JSONField(default=list)
    token_address = models.CharField(null=True, max_length=50)
    updated = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    class Meta:
        db_table = 'api_bloxy_distribution'
        indexes = [
            models.Index(fields=['address', 'depth_limit',
                                 'from_time', 'till_time'])
        ]


class BloxySource(models.Model):
    address = models.CharField(null=False, max_length=50)
    depth_limit = models.IntegerField(null=True)
    transaction_limit = models.IntegerField(null=True)
    from_time = models.DateTimeField(null=True)
    till_time = models.DateTimeField(null=True)
    result = JSONField(default=list)
    token_address = models.CharField(null=True, max_length=50)
    updated = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    class Meta:
        db_table = 'api_bloxy_source'
        indexes = [
            models.Index(fields=['address', 'depth_limit',
                                 'from_time', 'till_time'])
        ]


class CatvHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    wallet_address = models.CharField(null=False, max_length=50)
    token_address = models.CharField(null=True, max_length=50)
    source_depth = models.IntegerField(default=0)
    distribution_depth = models.IntegerField(default=0)
    transaction_limit = models.IntegerField(null=False)
    from_date = models.CharField(null=False, max_length=10)
    to_date = models.CharField(null=False, max_length=10)
    token_type = EnumField(CatvTokens, default=CatvTokens.ETH)
    logged_time = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_catv_history'
        indexes = [
            models.Index(fields=['user', ]),
        ]


class Usage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    api_calls_left = models.IntegerField(default=0)
    catv_calls_left = models.IntegerField(default=0)
    cara_calls_left = models.IntegerField(default=0)
    last_renewal_at = models.DateTimeField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', ]),
        ]


class ICFHistory(models.Model):
    api_key = models.CharField(max_length=40)
    request_endpoint = models.CharField(max_length=100)
    request_type = models.CharField(max_length=10)
    request_data = models.TextField(null=True)
    logged_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'api_icf_history'
        indexes = [
            models.Index(fields=['api_key', ]),
        ]


class Organization(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=100, null=False, blank=False)
    image = models.ImageField(
        null=True, blank=True, storage=UserImageStorage, upload_to=image_upload_path)
    administrator = models.ForeignKey(
        User, null=False, blank=False, on_delete=models.CASCADE, related_name='org_admin')
    users = models.ManyToManyField('User', through='OrganizationUser')
    domains = ArrayField(models.CharField(
        max_length=100), size=2, default=list)

    class Meta:
        indexes = [
            models.Index(fields=['administrator', ]),
        ]

    @property
    def pending_invites(self):
        return OrganizationInvites.objects.filter(organization=self). \
            exclude(status=OrganizationInviteStatus.APPROVED.value).values(
                'email', 'status')


class OrganizationUser(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    status = EnumField(OrganizationUserStatus, max_length=50)


class OrganizationInvites(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    email = models.EmailField(unique=False)
    invite_hash = models.CharField(max_length=40)
    inviter_key = models.CharField(max_length=100)
    sent = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    status = EnumField(OrganizationInviteStatus, max_length=50)

    class Meta:
        indexes = [
            models.Index(fields=['organization', ]),
            models.Index(fields=['user', ])
        ]


class IndicatorMView(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    security_category = models.CharField(max_length=10)
    security_tags = ArrayField(models.CharField(
        max_length=32, blank=False), blank=True, null=True)
    vector = ArrayField(models.CharField(
        max_length=32, blank=False), blank=True, null=True)
    environment = ArrayField(models.CharField(
        max_length=32, blank=False), blank=True, null=True)

    pattern_type = models.CharField(blank=False, null=False, max_length=32)
    pattern_subtype = models.CharField(blank=True, null=True, max_length=10)
    pattern = models.CharField(max_length=256, blank=False, null=False)

    detail = models.TextField(default='', blank=True, null=True,
                              max_length=api_settings.INDICATOR_DETAIL_MAX_LEN)
    created = models.DateTimeField(default=now)
    cases = models.TextField(blank=True, null=True)
    annotations = models.CharField(max_length=256, blank=True, null=True)
    latest_case = models.UUIDField(null=True, editable=False)
    user_id = models.IntegerField()
    pattern_tree = ArrayField(models.CharField(
        max_length=256, blank=False), blank=True, null=True)
    updated = models.DateTimeField(default=now)

    @property
    def pattern_tree_count(self):
        if not self.pattern_tree:
            return 0
        else:
            return len(self.pattern_tree)

    class Meta:
        managed = False
        db_table = 'matvw_indicator_search'


class CatvPathHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    address_from = models.CharField(null=False, max_length=100)
    address_to = models.CharField(null=False, max_length=100)
    token_address = models.CharField(null=True, max_length=100)
    depth = models.IntegerField(default=0)
    min_tx_amount = models.FloatField(default=0.0)
    from_date = models.CharField(null=False, max_length=10)
    to_date = models.CharField(null=False, max_length=10)
    limit_address_tx_count = models.IntegerField(default=0)
    token_type = EnumField(CatvTokens, default=CatvTokens.ETH)
    logged_time = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_catv_path_history'
        indexes = [
            models.Index(fields=['user', 'token_type', ]),
        ]


class ConsumerErrorLogs(models.Model):
    topic = models.CharField(max_length=100)
    message = JSONField(default={})
    error_trace = models.TextField()
    logged_time = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_consumer_error_logs'
        indexes = [
            models.Index(fields=['topic'])
        ]


class IndicatorPoint(models.Model):
    user = models.ForeignKey(Indicator, on_delete=models.DO_NOTHING)
    indicator_id = models.IntegerField(null=False)
    points = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'api_indicator_point'


class UserIndicator(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    security_category = EnumField(enum=IndicatorSecurityCategory)
    pattern = models.CharField(max_length=256)
    pattern_subtype = EnumField(
        enum=IndicatorPatternSubtype, blank=True, null=True)
    pattern_type = EnumField(enum=IndicatorPatternType,
                             blank=False, null=False, max_length=32)
    security_tags = ArrayField(models.CharField(
        max_length=32, blank=False), blank=True, null=True)
    created = models.DateTimeField(default=now)
    points = models.IntegerField(default=0)
    status = models.CharField(max_length=10, null=True)

    class Meta:
        managed = False


class CatvRequestStatus(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    params = JSONField(default=dict)
    status = EnumField(enum=CatvTaskStatusType,
                       default=CatvTaskStatusType.PROGRESS)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'api_catv_request_status'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['user']),
            models.Index(fields=['uid']),
        ]


class IndicatorExtraAnnotation(models.Model):
    pattern = models.CharField(max_length=256)
    annotation = models.TextField(blank=True, null=True)
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)
    objects = BulkUpdateManager()

    class Meta:
        db_table = 'api_indicator_extra_annotation'
        indexes = [
            CustomGinIndex(fields=['pattern', ]),
            models.Index(fields=['annotation', ]),
            models.Index(fields=['pattern', ]),
        ]


class CatvResult(models.Model):
    request = models.ForeignKey(CatvRequestStatus, null=False,
                                blank=False, on_delete=models.CASCADE, related_name='request')
    result_file = models.ForeignKey(
        AttachedFile, null=True, blank=True, on_delete=models.CASCADE, related_name='result_file')

    class Meta:
        db_table = 'api_catv_result'
        indexes = [
            models.Index(fields=['request'])
        ]


class CatvJobQueue(models.Model):
    message = JSONField(default={})
    retries_remaining = models.IntegerField(default=3)
    created = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_catv_job_queue'
        indexes = [
            models.Index(fields=['retries_remaining']),
            models.Index(fields=['created'])
        ]


class CaseMView(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(
        max_length=api_settings.CASE_TITLE_MAX_LEN, default='')
    detail = models.TextField(
        default='', max_length=api_settings.CASE_DETAIL_MAX_LEN)
    rich_text_detail = models.CharField(
        default='', max_length=api_settings.CASE_DETAIL_MAX_LEN)
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=32)
    reporter_info = models.CharField(
        max_length=api_settings.CASE_REPORTER_MAX_LEN, null=True, blank=True)
    reporter_id = models.IntegerField(null=True)
    owner_id = models.IntegerField(null=True)
    verifier_id = models.IntegerField(null=True)
    security_category = ArrayField(
        models.CharField(max_length=32, null=True), null=True)
    pattern_type = ArrayField(models.CharField(
        max_length=32, null=True), null=True)
    pattern_subtype = ArrayField(models.CharField(
        max_length=32, null=True), null=True)

    class Meta:
        managed = False
        db_table = 'matvw_case_search'


class UserUpgrade(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='upgrade_user')
    asked_tokens = models.FloatField(null=True)
    status = EnumField(enum=UpgradeVerifyStatus, null=True)
    tx_hash = models.CharField(max_length=100, null=True)
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'api_user_upgrade'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['created'])
        ]


class RoleInfo(models.Model):
    class Meta:
        db_table = 'api_role_info'
    icf_rate_limit = models.CharField(default='5/s', max_length=32, null=False)
    cara_rate_limit = models.CharField(
        default='5/s', max_length=32, null=False)
    cara_submit_rate_limit = models.CharField(
        default='5/m', max_length=32, null=False)
    catv_rate_limit = models.CharField(
        default='5/s', max_length=32, null=False)
    org_access = models.BooleanField(default=False)
    role = models.ForeignKey(
        Role, null=False, blank=False, on_delete=models.CASCADE, related_name='info_role')
