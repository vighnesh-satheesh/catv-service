import random
import string
import uuid
import warnings
from enum import Enum

from django.contrib.postgres.fields import ArrayField
from django.db.models import JSONField
from django.db import models
from django.db.models.lookups import IContains
from django.utils.timezone import now
from enumfields import EnumField

warnings.filterwarnings("once", "This field is deprecated", DeprecationWarning)


def generate_api_key():
    return "".join(random.choice(string.ascii_letters) for x in range(40))

class CatvTokens(Enum):
    ETH = 'ETH'
    BTC = 'BTC'
    TRON = 'TRX'
    LTC = 'LTC'
    BCH = 'BCH'
    XRP = 'XRP'
    EOS = 'EOS'
    XLM = 'XLM'
    BNB = 'BNB'
    ADA = 'ADA'
    BSC = 'BSC'
    KLAY = 'KLAY'
    LUNC = 'LUNC'
    FTM = 'FTM'
    AVAX = 'AVAX'
    DOGE = 'DOGE'
    ZEC = 'ZEC'
    DASH = 'DASH'
    POL = 'POL'

class CatvSearchType(Enum):
    PATH = 'path'
    FLOW = 'flow'


class CatvTaskStatusType(Enum):
    PROGRESS = 'progress'
    RELEASED = 'released'
    FAILED = 'failed'

class PostgresILike(IContains):
    lookup_name = 'ilike'

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = lhs_params + rhs_params
        return '%s ILIKE %s' % (lhs, rhs), params

class ProductType(Enum):
    CATV = 'catv'

class PostgresArrayILike(IContains):
    lookup_name = 'arrayilike'

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = lhs_params + rhs_params
        return 'array_to_text(%s) ILIKE %s' % (lhs, rhs), params

models.CharField.register_lookup(PostgresILike)
models.TextField.register_lookup(PostgresILike)
ArrayField.register_lookup(PostgresArrayILike)

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
    user_id = models.IntegerField(null=False)
    wallet_address = models.CharField(null=False, max_length=256)
    token_address = models.CharField(null=True, max_length=256)
    source_depth = models.IntegerField(default=0)
    distribution_depth = models.IntegerField(default=0)
    transaction_limit = models.IntegerField(null=False)
    from_date = models.CharField(null=False, max_length=10)
    to_date = models.CharField(null=False, max_length=10)
    # token_type = EnumField(CatvTokens, default=CatvTokens.ETH)
    token_type = models.CharField(null=False, max_length=10)
    logged_time = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_catv_history'
        indexes = [
            models.Index(fields=['user_id', ]),
        ]

class CatvPathHistory(models.Model):
    user_id = models.IntegerField(null=False)
    address_from = models.CharField(null=False, max_length=256)
    address_to = models.CharField(null=False, max_length=256)
    token_address = models.CharField(null=True, max_length=256)
    depth = models.IntegerField(default=0)
    min_tx_amount = models.FloatField(default=0.0)
    from_date = models.CharField(null=False, max_length=10)
    to_date = models.CharField(null=False, max_length=10)
    limit_address_tx_count = models.IntegerField(default=0)
    # token_type = EnumField(CatvTokens, default=CatvTokens.ETH)
    token_type = models.CharField(null=False, max_length=10)
    logged_time = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_catv_path_history'
        indexes = [
            models.Index(fields=['user_id', 'token_type', ]),
        ]

class CatvRequestStatus(models.Model):
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    params = JSONField(default=dict)
    status = EnumField(enum=CatvTaskStatusType,
                       default=CatvTaskStatusType.PROGRESS)
    user_id = models.IntegerField(null=False)
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)
    labels = ArrayField(models.CharField(max_length=100, blank=False), default=list)
    token_type = EnumField(CatvTokens, default=CatvTokens.ETH)
    is_legacy = models.BooleanField(default=False)
    is_bounty_track = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_catv_request_status'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['user_id']),
            models.Index(fields=['uid']),
        ]

class CatvResult(models.Model):
    request = models.ForeignKey(CatvRequestStatus, null=False,
                                blank=False, on_delete=models.CASCADE, related_name='request')
    # result_file = models.ForeignKey(
    #     AttachedFile, null=True, blank=True, on_delete=models.CASCADE, related_name='result_file')
    result_file_id = models.IntegerField(null=True)

    class Meta:
        db_table = 'api_catv_result'
        indexes = [
            models.Index(fields=['request'])
        ]


class CatvJobQueue(models.Model):
    message = JSONField(default=dict)
    retries_remaining = models.IntegerField(default=3)
    created = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_catv_job_queue'
        indexes = [
            models.Index(fields=['retries_remaining']),
            models.Index(fields=['created'])
        ]

# New job queue for CATV revamp
class CatvNeoJobQueue(models.Model):
    message = JSONField(default=dict)
    retries_remaining = models.IntegerField(default=3)
    created = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_neo_catv_job_queue'
        indexes = [
            models.Index(fields=['retries_remaining']),
            models.Index(fields=['created'])
        ]

class CatvNodeLabelModel(models.Model):
    uid = models.CharField(max_length=100)
    wallet_address = models.CharField(max_length=100)
    user_id = models.IntegerField(null=False)
    label = models.CharField(max_length=100)

    class Meta:
        db_table = "api_catv_node_label_request"

class CatvCSVJobQueue(models.Model):
    message = JSONField(default=dict)
    retries_remaining = models.IntegerField(default=3)
    created = models.DateTimeField(default=now)
    class Meta:
        db_table = 'api_csv_catv_job_queue'
        indexes = [
            models.Index(fields=['retries_remaining']),
            models.Index(fields=['created'])
        ]

class CatvNeoCSVJobQueue(models.Model):
    message = JSONField(default=dict)
    retries_remaining = models.IntegerField(default=3)
    created = models.DateTimeField(default=now)
    class Meta:
        db_table = 'api_neo_csv_catv_job_queue'
        indexes = [
            models.Index(fields=['retries_remaining']),
            models.Index(fields=['created'])
        ]

class UserRoles(Enum):
    COMMUNITY = 'communityuser'
    PAID = 'paiduser'
    ORG = 'organization'
    ORG_TRIAL = 'organization-trial'
    SENTINEL = 'sentinel'
    SUPERSENTINEL = 'supersentinel'
    COMMUNITY_VERIFIED = 'communityuser-verified'
    WEB3COMMUNITY = 'Web3-Community'
    INVESTIGATOR_STARTER_CAMS = 'Investigator-Starter_CAMS'
    INVESTIGATOR_PRO_CAMS ='Investigator-Pro_CAMS'
    INVESTIGATOR_ADVANCED_CAMS ='Investigator-Advanced_CAMS'
    
class ApiCase(models.Model):
    # For api_case table
    # user generated info
    class Meta:
        db_table = 'api_case'
        managed = False
    status = models.CharField(max_length=128)
    indicators = models.ManyToManyField(
        'ApiIndicator', through='CaseIndicator')

class ApiIndicator(models.Model):
    class Meta:
        managed = False
        db_table = 'api_indicator'
    case_id = models.ManyToManyField(ApiCase, through='CaseIndicator')
    pattern = models.CharField(max_length=256)
    pattern_type = models.CharField(max_length=32)
    pattern_subtype = models.CharField(max_length=10)
    detail = models.TextField(default='', blank=True, null=True,
                              max_length=4096)
    security_category = models.CharField(max_length=256)
    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(default=now)
    annotation = models.CharField(
        max_length=256, blank=True, null=False, default="")


class ApiUsage(models.Model):
    class Meta:
        managed = False
        db_table = 'api_usage'
    id = models.IntegerField(null=False, primary_key=True)
    api_calls_left = models.IntegerField(null=False)
    catv_calls_left = models.IntegerField(null=False)
    cara_calls_left = models.IntegerField(null=False)
    last_renewal_at = models.DateTimeField(null=True)
    user_id = models.IntegerField(null=False)
    api_calls_left_y = models.IntegerField(default=0)
    catv_calls_left_y = models.IntegerField(default=0)
    cara_calls_left_y = models.IntegerField(default=0)
    api_calls = models.IntegerField(default=0)
    catv_calls = models.IntegerField(default=0)
    cara_calls = models.IntegerField(default=0)
    last_renewal_at_y = models.DateTimeField(null=True)


class ApiKey(models.Model):
    class Meta:
        managed = False
        db_table = 'api_key'
    # For api_key table
    id = models.IntegerField(null=False, primary_key=True)
    uid = models.UUIDField(default=uuid.uuid4)
    api_key = models.CharField(
        default=generate_api_key, max_length=40, blank=True, null=True, unique=True)
    request_assign = models.IntegerField(
        default=10000000, blank=True, null=True)
    request_current = models.IntegerField(default=0, blank=True, null=True)
    type_id = models.IntegerField(default=1, blank=False, null=False)
    name = models.CharField(default="", max_length=128, blank=True, null=True)
    domain = ArrayField(models.CharField(
        max_length=256, blank=True), blank=True, null=True)
    domain_restricted = models.NullBooleanField(
        default=False, blank=True, null=True)
    # user = models.ForeignKey(
    #     User, null=True, blank=True, on_delete=models.CASCADE)
    created = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(null=True, blank=True)
    user_id = models.IntegerField(default=0, blank=False, null=False)
    # cara_calls = models.ForeignKey(
    #     ApiUsage, on_delete=models.CASCADE)

class ConsumerErrorLogs(models.Model):
    request = models.ForeignKey(CatvRequestStatus, null=True,
                                blank=False, on_delete=models.CASCADE, related_name='error_logs')
    topic = models.CharField(max_length=100)
    message = JSONField(default=dict)
    error_trace = models.TextField()
    user_error_message = models.TextField(default=None)
    logged_time = models.DateTimeField(default=now)

    class Meta:
        db_table = 'api_consumer_error_logs'
        indexes = [models.Index(fields=["request"])]