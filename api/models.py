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
from django.contrib.postgres.indexes import GistIndex
from django.utils.safestring import mark_safe
from django.template.defaultfilters import truncatechars
from django.utils.timezone import now

import random, string
import magic
from PIL import Image
from enumfields import EnumField
from indicatorlib import Pattern

from .settings import api_settings
from .storages.s3 import StaticS3Storage
from .fields import LtreeField
from . import validates

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


class UserPermission(Enum):
    EXCHANGE = 'exchange'
    SENTINEL = 'sentinel'
    SUPERSENTINEL = 'supersentinel'


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
    OTHER = 'other'


class IndicatorPatternSubtype(Enum):
    # cryptoaddr subtype
    ETH = 'ETH'
    ERC20 = 'ERC20'
    ETC = 'ETC'
    EOS = 'EOS'
    BTC = 'BTC'
    BCH = 'BCH'
    LTC = 'LTC'
    DASH = 'DASH'
    ZEC = 'ZEC'
    XMR = 'XMR'
    NEO = 'NEO'
    NA = 'NA'
    # network address
    URL = 'url'
    EMAIL = 'email'
    DOMAIN = 'domain'
    HOSTNAME = 'hostname'
    IPV4 = 'ipv4'
    # other
    OTHER = 'other'

    @classmethod
    def cryptoaddr_subtypes(cls):
        return [cls.ETH, cls.ERC20, cls.ETC, cls.EOS, cls.BTC, cls.BCH,
                cls.LTC, cls.DASH, cls.ZEC, cls.XMR, cls.NEO, cls.NA]

    @classmethod
    def networkaddr_subtypes(cls):
        return [cls.URL, cls.EMAIL, cls.DOMAIN, cls.HOSTNAME, cls.IPV4, cls.OTHER]


class IndicatorSecurityCategory(Enum):
    WHITELIST = 'whitelist'
    BLACKLIST = 'blacklist'


class APIKeyType(Enum):
    UNLIMITED = 0
    LIMITED = 1


class EmailSentType(Enum):
    REGISTER = 'REGISTER'
    VERIFICATION_RESEND = 'VERIFICATION_RESEND'
    PASSWORD_RESET = 'PASSWORD_RESET'
    VERIFIED = 'VERIFIED'
    NOTIFICATION = 'NOTIFICATION'


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


@unique
class FileStatus(IntEnum):
    NEW = 0
    COMPLETED = 1000


# models
class User(models.Model):
    email = models.EmailField(unique=True)
    nickname = models.CharField(max_length=128, unique=True)
    password = models.CharField(max_length=128)
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created = models.DateTimeField(default=now)
    permission = EnumField(enum=UserPermission, default=UserPermission.SENTINEL, max_length=16)
    image = models.ImageField(null=True, blank=True, storage=UserImageStorage, upload_to=image_upload_path)
    status = EnumField(enum=UserStatus, default=UserStatus.APPROVED, max_length = 16)

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
        return super(User, self).save()

    def clean(self):
        validates.validate_password(self, self.password, model=True)
        return super(User, self).clean()


class Case(models.Model):
    # user generated info
    title = models.CharField(max_length=api_settings.CASE_TITLE_MAX_LEN, default='')
    detail = models.TextField(default='', max_length=api_settings.CASE_DETAIL_MAX_LEN)
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # auto generated info
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)
    status = EnumField(enum=CaseStatus, default=CaseStatus.NEW)
    reporter_info = models.CharField(max_length=api_settings.CASE_REPORTER_MAX_LEN, null=True, blank=True)  # blockchain에 사용되면 안된다.
    reporter = models.ForeignKey(User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='reporter')
    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='owner')
    verifier = models.ForeignKey(User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='verifier')

    block_num = models.IntegerField(null=True, blank=True)
    # block_id = models.CharField(max_length=64, null=True, blank=True)
    transaction_id = models.CharField(max_length=64, null=True, blank=True)

    ico = models.ForeignKey('ICO', null=True, blank=True, on_delete=models.DO_NOTHING)
    indicators = models.ManyToManyField('Indicator', related_name="case_indicators")

    class Meta:
        indexes = [
            models.Index(fields=['status', ]),
            models.Index(fields=['owner', ]),
            models.Index(fields=['created', ]),
        ]

    def save(self, *args, **kargs):
        # TODO: detect status field. and insert into history.
        # history.log = "status changed to {dst status}"
        return super(Case, self).save(*args, **kargs)

    def clean(self):
        validates.validate_max_length(self.detail, model=True, limit=api_settings.CASE_DETAIL_MAX_LEN, field_name="detail")
        return super(Case, self).clean()


class CaseHistory(models.Model):
    case = models.ForeignKey(Case, on_delete=models.CASCADE)
    initiator = models.ForeignKey(User, null=True, blank=True, on_delete=models.DO_NOTHING)
    log = models.TextField()
    created = models.DateTimeField(default=now)

    class Meta:
        indexes = [
            models.Index(fields=['case', ]),
            models.Index(fields=['created', ]),
        ]


class Indicator(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="indicator", blank=True, null=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='indicator_user')
    cases = models.ManyToManyField(Case, related_name='indicator_cases')

    security_category = EnumField(enum=IndicatorSecurityCategory)
    security_tags = ArrayField(models.CharField(max_length=32, blank=False),
                               blank=True, null=True,
                               help_text="comma-separated string. (Phishing, Scam, Malware, Hacks, Exploits)")

    pattern = models.CharField(max_length=256)
    pattern_type = EnumField(enum=IndicatorPatternType, blank=False, null=False)
    pattern_subtype = EnumField(enum=IndicatorPatternSubtype, blank=True, null=True)
    pattern_tree = LtreeField(blank=False, null=False)
    detail = models.TextField(default='', blank=True, null=True, max_length=api_settings.INDICATOR_DETAIL_MAX_LEN)
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            GistIndex(fields=['pattern_tree', ]),
            models.Index(fields=['pattern_tree', ]),
            models.Index(fields=['case', ]),
            models.Index(fields=['user']),
        ]

    @property
    def short_pattern(self):
        return truncatechars(self.pattern, 50)

    def save(self, *args, **kwargs):
        # TODO: pattern ltrim rtrim
        self.pattern_tree = Pattern.getMaterializedPathForInsert(self.pattern)
        return super(Indicator, self).save(*args, **kwargs)

    def clean(self):
        validates.validate_max_length(self.pattern, model=True, limit=api_settings.INDICATOR_PATTERN_MAX_LEN, field_name="pattern")
        validates.validate_max_length(self.detail, model=True, limit=api_settings.CASE_DETAIL_MAX_LEN, field_name="detail")
        validates.validate_pattern_type_subtype(self.pattern_type, self.pattern_subtype, model=True)
        validates.validate_security_type_tag(self.security_category, self.security_tags, model=True)
        return super(Indicator, self).clean()


class ICO(models.Model):
    name = models.CharField(max_length=128, default='')
    symbol = models.CharField(max_length=128, default='')
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    verifier = models.ForeignKey(User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='%(class)s_verifier')
    image = models.ImageField(null=True, blank=True, storage=ImageStorage, upload_to=image_upload_path)
    type = models.TextField(null=True, blank=True)
    subtitle = models.TextField(null=True, blank=True)
    website = models.TextField(null=True, blank=True)
    detail = models.TextField(null=True, blank=True)
    platform = models.TextField(null=True, blank=True)
    category = models.TextField(null=True, blank=True)
    country = models.TextField(null=True, blank=True)
    opened = models.DateTimeField(null=True, blank=True)
    closed = models.DateTimeField(null=True, blank=True)

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='ico_user')
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
    uploader = models.ForeignKey(User, null=True, blank=True, on_delete=models.DO_NOTHING, related_name='uploader')
    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.CASCADE, related_name='case')

    class Meta:
        db_table = "api_file"
        indexes = [
            models.Index(fields=['case', ]),
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
    api_key = models.CharField(default=generate_api_key, max_length=40, blank=True, null=True, unique=True)
    request_assign = models.IntegerField(default=10000000, blank=True, null=True)
    request_current = models.IntegerField(default=0, blank=True, null=True)
    type_id = EnumField(enum=APIKeyType, default=APIKeyType.LIMITED)
    name = models.CharField(default = "", max_length=128, blank=True, null=True)
    domain = ArrayField(models.CharField(max_length=256, blank=True), blank=True, null=True)
    domain_restricted = models.NullBooleanField(default=False, blank=True, null=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
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
    type = EnumField(enum=EmailSentType, max_length = 20)


class Comment(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    body = models.TextField(max_length=api_settings.COMMENT_BODY_MAX_LEN, default="")
    writer = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.CASCADE)
    indicator = models.ForeignKey(Indicator, null=True, blank=True, on_delete=models.CASCADE)
    ico = models.ForeignKey(ICO, null=True, blank=True, on_delete=models.CASCADE)
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
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='user')
    initiator = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='initiator')
    target = JSONField(default={})
    read = models.BooleanField(default=False)
    created = models.DateTimeField(default=now)
    type = EnumField(enum=NotificationType, max_length=64)

    class Meta:
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['created'])
        ]
