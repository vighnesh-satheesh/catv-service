# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey has `on_delete` set to the desired behavior.
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


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


class ApiConsumerErrorLogs(models.Model):
    topic = models.CharField(max_length=100)
    message = models.TextField()  # This field type is a guess.
    error_trace = models.TextField()
    logged_time = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'api_consumer_error_logs'


class ApiIndicatorExtraAnnotation(models.Model):
    pattern = models.CharField(max_length=256)
    annotation = models.TextField(blank=True, null=True)
    created = models.DateTimeField()
    updated = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'api_indicator_extra_annotation'


class ApiRole(models.Model):
    role_name = models.CharField(unique=True, max_length=128)
    display_name = models.CharField(max_length=128, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'api_role'


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