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


class CatvSearchType(Enum):
    PATH = 'path'
    FLOW = 'flow'


class CatvTaskStatusType(Enum):
    PROGRESS = 'progress'
    RELEASED = 'released'
    FAILED = 'failed'

class ProductType(Enum):
    CATV = 'catv'

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