# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey has `on_delete` set to the desired behavior.
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class ApiAction(models.Model):
    resourceid = models.IntegerField(blank=True, null=True)
    resource = models.CharField(max_length=128, blank=True, null=True)
    action = models.CharField(max_length=500)
    codename = models.CharField(max_length=128)

    class Meta:
        managed = False
        db_table = 'api_action'


class ApiAnnotation(models.Model):
    annotation = models.CharField(max_length=256, blank=True, null=True)
    created = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'api_annotation'


class ApiBloxyDistribution(models.Model):
    address = models.CharField(max_length=50)
    depth_limit = models.IntegerField(blank=True, null=True)
    transaction_limit = models.IntegerField(blank=True, null=True)
    from_time = models.DateTimeField(blank=True, null=True)
    till_time = models.DateTimeField(blank=True, null=True)
    result = models.TextField()  # This field type is a guess.
    token_address = models.CharField(max_length=50, blank=True, null=True)
    updated = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_bloxy_distribution'


class ApiBloxySource(models.Model):
    address = models.CharField(max_length=50)
    depth_limit = models.IntegerField(blank=True, null=True)
    transaction_limit = models.IntegerField(blank=True, null=True)
    from_time = models.DateTimeField(blank=True, null=True)
    till_time = models.DateTimeField(blank=True, null=True)
    result = models.TextField()  # This field type is a guess.
    token_address = models.CharField(max_length=50, blank=True, null=True)
    updated = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_bloxy_source'


class ApiCase(models.Model):
    title = models.CharField(max_length=128)
    detail = models.TextField()
    uid = models.UUIDField(unique=True)
    created = models.DateTimeField()
    status = models.CharField(max_length=10)
    reporter_info = models.CharField(max_length=128, blank=True, null=True)
    block_num = models.IntegerField(blank=True, null=True)
    transaction_id = models.CharField(max_length=64, blank=True, null=True)
    ico = models.ForeignKey('ApiIco', models.DO_NOTHING, blank=True, null=True)
    owner = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)
    reporter = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)
    verifier = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)
    updated = models.DateTimeField()
    rich_text_detail = models.CharField(max_length=5000, blank=True, null=True)
    related_case_id = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_case'


class ApiCasehistory(models.Model):
    log = models.TextField()
    created = models.DateTimeField()
    case = models.ForeignKey(ApiCase, models.DO_NOTHING)
    initiator = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_casehistory'


class ApiCatvHistory(models.Model):
    wallet_address = models.CharField(max_length=50)
    token_address = models.CharField(max_length=50, blank=True, null=True)
    source_depth = models.IntegerField()
    distribution_depth = models.IntegerField()
    transaction_limit = models.IntegerField()
    from_date = models.CharField(max_length=10)
    to_date = models.CharField(max_length=10)
    logged_time = models.DateTimeField()
    user = models.ForeignKey('ApiUser', models.DO_NOTHING)
    token_type = models.CharField(max_length=10)

    class Meta:
        managed = False
        db_table = 'api_catv_history'


class ApiCatvJobQueue(models.Model):
    message = models.TextField()  # This field type is a guess.
    retries_remaining = models.IntegerField()
    created = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'api_catv_job_queue'


class ApiCatvPathHistory(models.Model):
    address_from = models.CharField(max_length=100)
    address_to = models.CharField(max_length=100)
    token_address = models.CharField(max_length=100, blank=True, null=True)
    depth = models.IntegerField()
    min_tx_amount = models.FloatField()
    from_date = models.CharField(max_length=10)
    to_date = models.CharField(max_length=10)
    limit_address_tx_count = models.IntegerField()
    token_type = models.CharField(max_length=10)
    logged_time = models.DateTimeField()
    user = models.ForeignKey('ApiUser', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'api_catv_path_history'


class ApiCatvRequestStatus(models.Model):
    uid = models.UUIDField(unique=True)
    params = models.TextField()  # This field type is a guess.
    status = models.CharField(max_length=10)
    created = models.DateTimeField()
    updated = models.DateTimeField()
    user = models.ForeignKey('ApiUser', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'api_catv_request_status'


class ApiCatvResult(models.Model):
    request = models.ForeignKey(ApiCatvRequestStatus, models.DO_NOTHING)
    # result_file = models.ForeignKey('ApiFile', models.DO_NOTHING, blank=True, null=True)
    result_file_id = models.IntegerField(null=True)

    class Meta:
        managed = False
        db_table = 'api_catv_result'


class ApiComment(models.Model):
    uid = models.UUIDField(unique=True)
    body = models.TextField()
    deleted = models.BooleanField()
    created = models.DateTimeField()
    case = models.ForeignKey(ApiCase, models.DO_NOTHING, blank=True, null=True)
    ico = models.ForeignKey('ApiIco', models.DO_NOTHING, blank=True, null=True)
    indicator = models.ForeignKey('ApiIndicator', models.DO_NOTHING, blank=True, null=True)
    writer = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_comment'


class ApiConsumerErrorLogs(models.Model):
    topic = models.CharField(max_length=100)
    message = models.TextField()  # This field type is a guess.
    error_trace = models.TextField()
    logged_time = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'api_consumer_error_logs'


class ApiEmailsent(models.Model):
    email = models.CharField(max_length=254)
    created = models.DateTimeField()
    type = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = 'api_emailsent'


class ApiExchangeToken(models.Model):
    sp_amount = models.IntegerField(blank=True, null=True)
    status = models.CharField(max_length=100, blank=True, null=True)
    req_time = models.DateTimeField(blank=True, null=True)
    app_time = models.DateTimeField(blank=True, null=True)
    upp = models.IntegerField(blank=True, null=True)
    user_id = models.CharField(max_length=200, blank=True, null=True)
    id = models.AutoField()

    class Meta:
        managed = False
        db_table = 'api_exchange_token'


class ApiFile(models.Model):
    file = models.CharField(max_length=100)
    name = models.TextField(blank=True, null=True)
    hash = models.TextField(blank=True, null=True)
    type = models.TextField(blank=True, null=True)
    size = models.IntegerField(blank=True, null=True)
    status = models.CharField(max_length=10)
    created = models.DateTimeField()
    uid = models.UUIDField(unique=True)
    case = models.ForeignKey(ApiCase, models.DO_NOTHING, blank=True, null=True)
    uploader = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)
    indicator = models.ForeignKey('ApiIndicator', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_file'


class ApiIcfHistory(models.Model):
    api_key = models.CharField(max_length=40)
    request_endpoint = models.CharField(max_length=100)
    request_type = models.CharField(max_length=10)
    request_data = models.TextField(blank=True, null=True)
    logged_time = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'api_icf_history'


class ApiIco(models.Model):
    name = models.CharField(max_length=128)
    symbol = models.CharField(max_length=128)
    uid = models.UUIDField(unique=True)
    image = models.CharField(max_length=100, blank=True, null=True)
    type = models.TextField(blank=True, null=True)
    subtitle = models.TextField(blank=True, null=True)
    detail = models.TextField(blank=True, null=True)
    platform = models.TextField(blank=True, null=True)
    category = models.TextField(blank=True, null=True)
    country = models.TextField(blank=True, null=True)
    opened = models.DateTimeField(blank=True, null=True)
    closed = models.DateTimeField(blank=True, null=True)
    verifier = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)
    website = models.TextField(blank=True, null=True)
    created = models.DateTimeField()
    updated = models.DateTimeField()
    user = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_ico'


class ApiIndicator(models.Model):
    uid = models.UUIDField(unique=True)
    security_category = models.CharField(max_length=10)
    security_tags = models.TextField(blank=True, null=True)  # This field type is a guess.
    pattern = models.CharField(max_length=256)
    detail = models.TextField(blank=True, null=True)
    pattern_subtype = models.CharField(max_length=10, blank=True, null=True)
    pattern_tree = models.TextField()  # This field type is a guess.
    pattern_type = models.CharField(max_length=32)
    created = models.DateTimeField()
    updated = models.DateTimeField()
    user = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)
    environment = models.TextField(blank=True, null=True)  # This field type is a guess.
    vector = models.TextField(blank=True, null=True)  # This field type is a guess.
    annotation = models.CharField(max_length=256, blank=True, null=True)
    reporter_info = models.CharField(max_length=128, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_indicator'


class ApiIndicatorExtraAnnotation(models.Model):
    pattern = models.CharField(max_length=256)
    annotation = models.TextField(blank=True, null=True)
    created = models.DateTimeField()
    updated = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'api_indicator_extra_annotation'


class ApiIndicatorNullUserIdBackup(models.Model):
    id = models.IntegerField(blank=True, null=True)
    uid = models.UUIDField(blank=True, null=True)
    security_category = models.CharField(max_length=10, blank=True, null=True)
    security_tags = models.TextField(blank=True, null=True)  # This field type is a guess.
    pattern = models.CharField(max_length=256, blank=True, null=True)
    detail = models.TextField(blank=True, null=True)
    pattern_subtype = models.CharField(max_length=10, blank=True, null=True)
    pattern_tree = models.TextField(blank=True, null=True)  # This field type is a guess.
    pattern_type = models.CharField(max_length=32, blank=True, null=True)
    created = models.DateTimeField(blank=True, null=True)
    updated = models.DateTimeField(blank=True, null=True)
    user_id = models.IntegerField(blank=True, null=True)
    environment = models.TextField(blank=True, null=True)  # This field type is a guess.
    vector = models.TextField(blank=True, null=True)  # This field type is a guess.
    annotation = models.CharField(max_length=256, blank=True, null=True)
    reporter_info = models.CharField(max_length=128, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_indicator_null_user_id_backup'


class ApiIndicatorPoint(models.Model):
    user_id = models.IntegerField()
    indicator_id = models.IntegerField()
    points = models.NullBooleanField()

    class Meta:
        managed = False
        db_table = 'api_indicator_point'


class ApiKey(models.Model):
    uid = models.UUIDField(unique=True)
    api_key = models.CharField(unique=True, max_length=40, blank=True, null=True)
    request_assign = models.IntegerField(blank=True, null=True)
    request_current = models.IntegerField(blank=True, null=True)
    type_id = models.CharField(max_length=10)
    name = models.CharField(max_length=128, blank=True, null=True)
    domain = models.TextField(blank=True, null=True)  # This field type is a guess.
    domain_restricted = models.NullBooleanField()
    created = models.DateTimeField()
    expire_datetime = models.DateTimeField(blank=True, null=True)
    user = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_key'


class ApiM2MCaseIndicator(models.Model):
    case = models.ForeignKey(ApiCase, models.DO_NOTHING)
    indicator = models.ForeignKey(ApiIndicator, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'api_m2m_case_indicator'


class ApiM2MIndicatorAnnotation(models.Model):
    annotation = models.ForeignKey(ApiAnnotation, models.DO_NOTHING)
    indicator = models.ForeignKey(ApiIndicator, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'api_m2m_indicator_annotation'


class ApiNotification(models.Model):
    uid = models.UUIDField(unique=True)
    target = models.TextField()  # This field type is a guess.
    read = models.BooleanField()
    created = models.DateTimeField()
    type = models.CharField(max_length=64)
    initiator = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey('ApiUser', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_notification'


class ApiOrganization(models.Model):
    uid = models.UUIDField(unique=True)
    name = models.CharField(max_length=100)
    image = models.CharField(max_length=100, blank=True, null=True)
    administrator = models.ForeignKey('ApiUser', models.DO_NOTHING)
    domains = models.TextField()  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'api_organization'


class ApiOrganizationinvites(models.Model):
    email = models.CharField(max_length=254)
    invite_hash = models.CharField(max_length=40)
    inviter_key = models.CharField(max_length=100)
    sent = models.DateTimeField()
    updated = models.DateTimeField()
    status = models.CharField(max_length=50)
    organization = models.ForeignKey(ApiOrganization, models.DO_NOTHING)
    user = models.ForeignKey('ApiUser', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'api_organizationinvites'


class ApiOrganizationuser(models.Model):
    status = models.CharField(max_length=50)
    organization = models.ForeignKey(ApiOrganization, models.DO_NOTHING)
    user = models.ForeignKey('ApiUser', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'api_organizationuser'


class ApiPatternChecksum(models.Model):
    id = models.IntegerField(primary_key=True)
    pattern = models.CharField(max_length=256)

    class Meta:
        managed = False
        db_table = 'api_pattern_checksum'


class ApiRelatedCase(models.Model):
    related = models.ForeignKey(ApiCase, models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_related_case'


class ApiRewardsetting(models.Model):
    id = models.IntegerField()
    min_token = models.IntegerField(blank=True, null=True)
    token_address = models.CharField(max_length=100, blank=True, null=True)
    token_abi = models.CharField(max_length=-1, blank=True, null=True)
    sentinel_point_reward = models.IntegerField(blank=True, null=True)
    upp_reward = models.IntegerField(blank=True, null=True)
    sp_required = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_rewardsetting'


class ApiRole(models.Model):
    role_name = models.CharField(unique=True, max_length=128)
    display_name = models.CharField(max_length=128, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_role'


class ApiRoleInfo(models.Model):
    icf_rate_limit = models.CharField(max_length=32)
    cara_rate_limit = models.CharField(max_length=32)
    cara_submit_rate_limit = models.CharField(max_length=32)
    catv_rate_limit = models.CharField(max_length=32)
    org_access = models.BooleanField()
    role = models.ForeignKey(ApiRole, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'api_role_info'


class ApiRolePermission(models.Model):
    allowed = models.BooleanField()
    action = models.ForeignKey(ApiAction, models.DO_NOTHING)
    role = models.ForeignKey(ApiRole, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'api_role_permission'


class ApiRoleUsageLimit(models.Model):
    api_limit = models.IntegerField(blank=True, null=True)
    catv_limit = models.IntegerField(blank=True, null=True)
    cara_limit = models.IntegerField(blank=True, null=True)
    role = models.ForeignKey(ApiRole, models.DO_NOTHING)
    org_invite_limit = models.IntegerField(blank=True, null=True)
    max_api_keys = models.IntegerField(blank=True, null=True)
    api_limit_y = models.IntegerField()
    cara_limit_y = models.IntegerField()
    catv_limit_y = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'api_role_usage_limit'


class ApiUsage(models.Model):
    api_calls_left = models.IntegerField()
    catv_calls_left = models.IntegerField()
    cara_calls_left = models.IntegerField()
    last_renewal_at = models.DateTimeField(blank=True, null=True)
    user = models.ForeignKey('ApiUser', models.DO_NOTHING)
    api_calls = models.IntegerField()
    api_calls_left_y = models.IntegerField()
    cara_calls = models.IntegerField()
    cara_calls_left_y = models.IntegerField()
    catv_calls = models.IntegerField()
    catv_calls_left_y = models.IntegerField()
    last_renewal_at_y = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_usage'


class ApiUser(models.Model):
    email = models.CharField(unique=True, max_length=254)
    nickname = models.CharField(unique=True, max_length=128)
    password = models.CharField(max_length=128)
    uid = models.UUIDField(unique=True)
    created = models.DateTimeField()
    permission = models.CharField(max_length=16)
    image = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=16)
    email_notification = models.BooleanField()
    timestamp = models.DateTimeField()
    role = models.ForeignKey(ApiRole, models.DO_NOTHING)
    address = models.CharField(unique=True, max_length=100, blank=True, null=True)
    points = models.BigIntegerField(blank=True, null=True)
    last_logged_out = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_user'


class ApiUserUpgrade(models.Model):
    asked_tokens = models.FloatField(blank=True, null=True)
    status = models.CharField(max_length=10, blank=True, null=True)
    created = models.DateTimeField()
    updated = models.DateTimeField()
    user = models.ForeignKey(ApiUser, models.DO_NOTHING)
    tx_hash = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_user_upgrade'


class AuthGroup(models.Model):
    name = models.CharField(unique=True, max_length=80)

    class Meta:
        managed = False
        db_table = 'auth_group'


class AuthGroupPermissions(models.Model):
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)
    permission = models.ForeignKey('AuthPermission', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_group_permissions'
        unique_together = (('group', 'permission'),)


class AuthPermission(models.Model):
    name = models.CharField(max_length=255)
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING)
    codename = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'auth_permission'
        unique_together = (('content_type', 'codename'),)


class AuthUser(models.Model):
    password = models.CharField(max_length=128)
    last_login = models.DateTimeField(blank=True, null=True)
    is_superuser = models.BooleanField()
    username = models.CharField(unique=True, max_length=150)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=150)
    email = models.CharField(max_length=254)
    is_staff = models.BooleanField()
    is_active = models.BooleanField()
    date_joined = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'auth_user'


class AuthUserGroups(models.Model):
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_groups'
        unique_together = (('user', 'group'),)


class AuthUserUserPermissions(models.Model):
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    permission = models.ForeignKey(AuthPermission, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_user_permissions'
        unique_together = (('user', 'permission'),)


class CaraReport(models.Model):
    address = models.CharField(max_length=200, blank=True, null=True)
    risk_score = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    analysis_start_time = models.DateTimeField(blank=True, null=True)
    analysis_end_time = models.DateTimeField(blank=True, null=True)
    total_amt = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    estimated_mal_amt = models.DecimalField(max_digits=65535, decimal_places=65535, blank=True, null=True)
    total_tx = models.BigIntegerField(blank=True, null=True)
    estimated_mal_tx = models.BigIntegerField(blank=True, null=True)
    num_blacklisted_addr_contacted = models.BigIntegerField(blank=True, null=True)
    distinct_transaction_patterns = models.CharField(max_length=500, blank=True, null=True)
    direct_links_to_malicious_activities = models.CharField(max_length=500, blank=True, null=True)
    illegit_activity_links = models.CharField(max_length=500, blank=True, null=True)
    report_generated_time = models.DateTimeField(blank=True, null=True)
    error = models.CharField(max_length=256, blank=True, null=True)
    ground_truth_label = models.CharField(max_length=256, blank=True, null=True)
    tx_interfere_with_funds = models.CharField(max_length=1000, blank=True, null=True)
    blacklisted_addr_list = models.CharField(max_length=1000, blank=True, null=True)
    distinct_tx_patterns_details = models.CharField(max_length=5000, blank=True, null=True)
    mal_activities_details = models.CharField(max_length=5000, blank=True, null=True)
    illegit_activity_links_details = models.CharField(max_length=5000, blank=True, null=True)
    tx_interfere_with_funds_details = models.CharField(max_length=5000, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cara_report'


class CaraSearchHistory(models.Model):
    id = models.UUIDField()
    address = models.CharField(max_length=200)
    query_time = models.DateTimeField()
    error_generated = models.IntegerField(blank=True, null=True)
    blockchain = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cara_search_history'


class CaseInvalidateCandidates(models.Model):
    old_status = models.CharField(max_length=10)
    new_status = models.CharField(max_length=10)
    created = models.DateTimeField()
    status = models.IntegerField()
    case = models.ForeignKey(ApiCase, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'case_invalidate_candidates'


class CeleryTaskmeta(models.Model):
    task_id = models.CharField(unique=True, max_length=255)
    status = models.CharField(max_length=50)
    result = models.TextField(blank=True, null=True)
    date_done = models.DateTimeField()
    traceback = models.TextField(blank=True, null=True)
    hidden = models.BooleanField()
    meta = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'celery_taskmeta'


class CeleryTasksetmeta(models.Model):
    taskset_id = models.CharField(unique=True, max_length=255)
    result = models.TextField()
    date_done = models.DateTimeField()
    hidden = models.BooleanField()

    class Meta:
        managed = False
        db_table = 'celery_tasksetmeta'


class DjangoAdminLog(models.Model):
    action_time = models.DateTimeField()
    object_id = models.TextField(blank=True, null=True)
    object_repr = models.CharField(max_length=200)
    action_flag = models.SmallIntegerField()
    change_message = models.TextField()
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'django_admin_log'


class DjangoContentType(models.Model):
    app_label = models.CharField(max_length=100)
    model = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'django_content_type'
        unique_together = (('app_label', 'model'),)


class DjangoMigrations(models.Model):
    app = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    applied = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_migrations'


class DjangoSession(models.Model):
    session_key = models.CharField(primary_key=True, max_length=40)
    session_data = models.TextField()
    expire_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_session'


class DjceleryCrontabschedule(models.Model):
    minute = models.CharField(max_length=64)
    hour = models.CharField(max_length=64)
    day_of_week = models.CharField(max_length=64)
    day_of_month = models.CharField(max_length=64)
    month_of_year = models.CharField(max_length=64)

    class Meta:
        managed = False
        db_table = 'djcelery_crontabschedule'


class DjceleryIntervalschedule(models.Model):
    every = models.IntegerField()
    period = models.CharField(max_length=24)

    class Meta:
        managed = False
        db_table = 'djcelery_intervalschedule'


class DjceleryPeriodictask(models.Model):
    name = models.CharField(unique=True, max_length=200)
    task = models.CharField(max_length=200)
    args = models.TextField()
    kwargs = models.TextField()
    queue = models.CharField(max_length=200, blank=True, null=True)
    exchange = models.CharField(max_length=200, blank=True, null=True)
    routing_key = models.CharField(max_length=200, blank=True, null=True)
    expires = models.DateTimeField(blank=True, null=True)
    enabled = models.BooleanField()
    last_run_at = models.DateTimeField(blank=True, null=True)
    total_run_count = models.IntegerField()
    date_changed = models.DateTimeField()
    description = models.TextField()
    crontab = models.ForeignKey(DjceleryCrontabschedule, models.DO_NOTHING, blank=True, null=True)
    interval = models.ForeignKey(DjceleryIntervalschedule, models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'djcelery_periodictask'


class DjceleryPeriodictasks(models.Model):
    ident = models.SmallIntegerField(primary_key=True)
    last_update = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'djcelery_periodictasks'


class DjceleryTaskstate(models.Model):
    state = models.CharField(max_length=64)
    task_id = models.CharField(unique=True, max_length=36)
    name = models.CharField(max_length=200, blank=True, null=True)
    tstamp = models.DateTimeField()
    args = models.TextField(blank=True, null=True)
    kwargs = models.TextField(blank=True, null=True)
    eta = models.DateTimeField(blank=True, null=True)
    expires = models.DateTimeField(blank=True, null=True)
    result = models.TextField(blank=True, null=True)
    traceback = models.TextField(blank=True, null=True)
    runtime = models.FloatField(blank=True, null=True)
    retries = models.IntegerField()
    hidden = models.BooleanField()
    worker = models.ForeignKey('DjceleryWorkerstate', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'djcelery_taskstate'


class DjceleryWorkerstate(models.Model):
    hostname = models.CharField(unique=True, max_length=255)
    last_heartbeat = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'djcelery_workerstate'


class KafkaListenerParameters(models.Model):
    id = models.IntegerField(blank=True, null=True)
    kafka_offset = models.IntegerField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'kafka_listener_parameters'


class SocialAuthAssociation(models.Model):
    server_url = models.CharField(max_length=255)
    handle = models.CharField(max_length=255)
    secret = models.CharField(max_length=255)
    issued = models.IntegerField()
    lifetime = models.IntegerField()
    assoc_type = models.CharField(max_length=64)

    class Meta:
        managed = False
        db_table = 'social_auth_association'
        unique_together = (('server_url', 'handle'),)


class SocialAuthCode(models.Model):
    email = models.CharField(max_length=254)
    code = models.CharField(max_length=32)
    verified = models.BooleanField()
    timestamp = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'social_auth_code'
        unique_together = (('email', 'code'),)


class SocialAuthNonce(models.Model):
    server_url = models.CharField(max_length=255)
    timestamp = models.IntegerField()
    salt = models.CharField(max_length=65)

    class Meta:
        managed = False
        db_table = 'social_auth_nonce'
        unique_together = (('server_url', 'timestamp', 'salt'),)


class SocialAuthPartial(models.Model):
    token = models.CharField(max_length=32)
    next_step = models.SmallIntegerField()
    backend = models.CharField(max_length=32)
    data = models.TextField()  # This field type is a guess.
    timestamp = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'social_auth_partial'


class SocialAuthUsersocialauth(models.Model):
    provider = models.CharField(max_length=32)
    uid = models.CharField(max_length=255)
    extra_data = models.TextField()  # This field type is a guess.
    user = models.ForeignKey(ApiUser, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'social_auth_usersocialauth'
        unique_together = (('provider', 'uid'),)


class TrdbCaseTransaction(models.Model):
    action = models.TextField()
    payload = models.TextField()
    created = models.DateTimeField()
    status = models.IntegerField()
    head_block_num = models.IntegerField(blank=True, null=True)
    transaction_id = models.CharField(max_length=64, blank=True, null=True)
    block_num = models.IntegerField(blank=True, null=True)
    case_uid = models.UUIDField()

    class Meta:
        managed = False
        db_table = 'trdb_case_transaction'


class UppwardRewardInfo(models.Model):
    aid = models.CharField(max_length=100)
    uid = models.CharField(max_length=100)
    cid = models.CharField(max_length=100)
    referral_code = models.CharField(max_length=100)
    token_addr = models.CharField(max_length=100)
    created = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'uppward_reward_info'
