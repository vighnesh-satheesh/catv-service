import json
from urllib.parse import urlparse
import uuid

from celery.task import Task
from celery.registry import tasks
from django.db import connections, transaction, IntegrityError
from django.utils.timezone import now
from elasticsearch import Elasticsearch
from elasticsearch.helpers import streaming_bulk
from kafka import KafkaProducer

from .cache import DefaultCache
from .constants import Constants
from .exceptions import DataIntegrityError
from .models import (
    Case, CatvJobQueue,
    CatvRequestStatus, CatvResult,
    Role, RoleUsageLimit,
    User, Usage
)
from .settings import api_settings


class CacheLeftPanelValuesTask(Task):
    def run(self, *args, **kwargs):
        dashboard_obj = {
            'cases': [],
            'indicators': {
                'all': 0,
                'cr': 0
            }
        }
        with connections['readonly'].cursor() as cursor:
            cursor.execute(Constants.QUERIES['SELECT_CASE_DETAILS'])
            row = cursor.fetchall()
            dashboard_obj['cases'] = row
            cursor.execute(Constants.QUERIES['FAKE_SELECT_INDICATOR_COUNT'])
            row = cursor.fetchone()
            dashboard_obj['indicators']['all'] = row[0]
            cursor.execute(Constants.QUERIES['FAKE_SELECT_INDICATOR_COUNT'])
            row = cursor.fetchone()
            dashboard_obj['indicators']['cr'] = row[0]
            c = DefaultCache()
            c.set(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'], dashboard_obj['indicators'], 60 * 60)
            c.set(Constants.CACHE_KEY['LEFT_PANEL_VALUES'], dashboard_obj, 60 * 60)
        return True


class CacheNumberOfIndicatorsCases(Task):
    def run(self, *args, **kwargs):
        data = {
            'all': 0,
            'cr': 0
        }
        with connections['readonly'].cursor() as cursor:
            cursor.execute(Constants.QUERIES['FAKE_SELECT_INDICATOR_COUNT'])
            row = cursor.fetchone()
            data['all'] = row[0]
            cursor.execute(Constants.QUERIES['FAKE_SELECT_INDICATOR_COUNT'])
            row = cursor.fetchone()
            data['cr'] = row[0]
            c = DefaultCache()
            c.set(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'], data, 60 * 60)
        return True


class CatvHistoryTask(Task):
    def run(self, *args, **kwargs):
        entry = kwargs['history']
        from_history = kwargs['from_history']
        query_list = [Constants.QUERIES['INSERT_USER_CATV_HISTORY'], Constants.QUERIES['UPDATE_USER_CATV_USAGE']]
        query_data = [(entry['user_id'], entry['wallet_address'], entry.get('token_address', ''),
                       entry.get('source_depth', 0), entry.get('distribution_depth', 0), entry['transaction_limit'],
                       entry['from_date'], entry['to_date'], now(), entry['token_type']),
                      (entry['user_id'],)]

        with connections['default'].cursor() as cursor:
            if not from_history:
                for query, data in zip(query_list, query_data):
                    cursor.execute(query.format(*data))
            else:
                cursor.execute(query_list[0].format(*query_data[0]))
        return True


class CaraHistoryTask(Task):
    def run(self, *args, **kwargs):
        entry = kwargs['usage']
        query_list = Constants.QUERIES['UPDATE_USER_CARA_USAGE']
        query_data = [entry['user_id'], ]
        with connections['default'].cursor() as cursor:
            cursor.execute(query_list, query_data)
        return True


class CheckUpdateUsageQuotaTask(Task):
    def run(self, *args, **kwargs):
        query = Constants.QUERIES['REFILL_USER_USAGE_QUOTA']
        with connections['default'].cursor() as cursor:
            cursor.execute(query)
        return True


class CheckDeleteInvitesTask(Task):
    def run(self, *args, **kwargs):
        query = Constants.QUERIES['DELETE_ORG_INVITES']
        with connections['default'].cursor() as cursor:
            cursor.execute(query)
        return True


class IndicatorESDocumentTask:
    def __init__(self, action=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.action = action if Constants.INDEX_ACTIONS.get(action, None) else Constants.INDEX_ACTIONS["INDEX"]
        self.related_indicators = []
        self.security_category = set()
        self.pattern_type = set()
        self.pattern_subtype = set()
        self.case_uid = ""
        self.case_status = ""
        self.case_updated = None
        if api_settings.ELASTICSEARCH_CREDENTIALS:
            host_netloc = urlparse(api_settings.ELASTICSEARCH_HOST).netloc
            es_host = f'http://{api_settings.ELASTICSEARCH_CREDENTIALS}@{host_netloc}'
        else:
            es_host = api_settings.ELASTICSEARCH_HOST
        self.es_client = Elasticsearch([es_host])

    def generate_indicator_data(self):
        for indicator in self.related_indicators:
            self.security_category.add(indicator.security_category_indexing)
            self.pattern_type.add(indicator.pattern_type_indexing)
            self.pattern_subtype.add(indicator.pattern_subtype_indexing)
            yield {
                "_op_type": self.action,
                "_type": "_doc",
                "_id": indicator.id,
                "_source": {
                    'id': indicator.id,
                    'uid': {
                        'hex': indicator.uid.hex
                    },
                    'security_category': indicator.security_category_indexing,
                    'security_tags': indicator.security_tags,
                    'vector': indicator.vector_indexing,
                    'environment': indicator.environment_indexing,
                    'pattern_type': indicator.pattern_type_indexing,
                    'pattern_subtype': indicator.pattern_subtype_indexing,
                    'pattern': indicator.pattern,
                    'detail': indicator.detail,
                    'created': indicator.created.isoformat(sep='T', timespec='milliseconds'),
                    'cases': self.case_status,
                    'annotations': indicator.annotations_indexing,
                    'latest_case': {
                        'hex': getattr(self.case_uid, 'hex', '')
                    },
                    'user_id': indicator.user_id_indexing,
                    'pattern_tree': indicator.pattern_tree.split(".") if indicator.pattern_tree else [],
                    'pattern_tree_count': len(indicator.pattern_tree.split(".")) if indicator.pattern_tree else 0,
                    'updated': self.case_updated.isoformat(sep='T', timespec='milliseconds') if self.case_updated else None
                }
            }
    
    def generate_case_data(self, case_instance: Case):
        return {
            "id": case_instance.id,
            "uid": {
                "hex": case_instance.uid.hex
            },
            "title": case_instance.title,
            "detail": case_instance.detail,
            "rich_text_detail": case_instance.rich_text_detail,
            "created": case_instance.created.isoformat(sep='T', timespec='milliseconds'),
            "updated": case_instance.updated.isoformat(sep='T', timespec='milliseconds'),
            "status": case_instance.status.value,
            "reporter_info": case_instance.reporter_info,
            "reporter": case_instance.reporter_id,
            "owner": case_instance.owner_id,
            "verifier": case_instance.verifier_id,
            "security_category": list(self.security_category),
            "pattern_type": list(self.pattern_type),
            "pattern_subtype": list(self.pattern_subtype)
        }

    def run(self, *args, **kwargs):
        case_instance = kwargs.get('case', None)
        indicators = kwargs.get('indicators', None)
        if isinstance(case_instance, Case):
            try:
                self.related_indicators = Case.objects.using('default').get(id=case_instance.id).indicators.all()
                self.case_uid = case_instance.uid
                self.case_status = case_instance.status.value
                self.case_updated = case_instance.updated
            except Case.DoesNotExist:
                self.related_indicators = []
        elif indicators:
            self.related_indicators = indicators

        successes = 0
        for ok, action in streaming_bulk(
                client=self.es_client,
                index=api_settings.ELASTICSEARCH_INDICATOR_IDX,
                actions=self.generate_indicator_data(),
                chunk_size=50,
                max_retries=3
        ):
            successes += ok
        print(f"Indexed {successes} documents")
        
        if isinstance(case_instance, Case):
            self.es_client.index(
                index=api_settings.ELASTICSEARCH_CASE_IDX, id=case_instance.id,
                body=self.generate_case_data(case_instance))
        elif isinstance(case_instance, (str, int)):
            self.es_client.delete(
                index=api_settings.ELASTICSEARCH_CASE_IDX, id=int(case_instance)
            )

        return True


class CatvPathHistoryTask(Task):
    def run(self, *args, **kwargs):
        entry = kwargs['history']
        from_history = kwargs['from_history']
        query_list = [Constants.QUERIES['INSERT_USER_CATV_PATH_SEARCH'], Constants.QUERIES['UPDATE_USER_CATV_USAGE']]
        query_data = [(entry['user_id'], entry['address_from'], entry['address_to'], entry['depth'],
                       entry['from_date'], entry['to_date'], now(), entry['token_type'], entry['min_tx_amount'],
                       entry['limit_address_tx'], entry['token_address']),
                      (entry['user_id'],)]

        with connections['default'].cursor() as cursor:
            if not from_history:
                for query, data in zip(query_list, query_data):
                    cursor.execute(query.format(*data))
            else:
                cursor.execute(query_list[0].format(*query_data[0]))
        return True


class CaseMessageTask:
    def __init__(self, topic, action=None):
        self.topic = topic
        self.related_ids = None
        self.case_id = None
        print(f"Param action is: {action}")
        self.action = action if action else Constants.CASE_ACTIONS["CREATE"]
        print(self.action)

    def run(self):
        message_body = {
            "action_type": self.action,
            "related_ids": self.related_ids,
            "case_id": self.case_id
        }
        producer = KafkaProducer(
            bootstrap_servers=[
                api_settings.KAFKA_BROKER_1,
                api_settings.KAFKA_BROKER_2,
                api_settings.KAFKA_BROKER_3
            ],
            value_serializer=lambda m: json.dumps(m).encode('utf-8'),
            retries=3
        )
        producer.send(self.topic, message_body)
        producer.flush()
        producer.close()


class CatvRequestTask:
    def __init__(self, topic, **kwargs):
        self.topic = topic
        self.message_id = uuid.uuid4()
        self.token_type = kwargs["token_type"]
        self.search_type = kwargs["search_type"]
        self.search_params = kwargs["search_params"]
        self.user = kwargs["user"]
        
    def run(self):
        message_body = {
            "message_id": self.message_id.hex,
            "user_id": self.user.id,
            "token_type": self.token_type,
            "search_type": self.search_type,
            "search_params": self.search_params
        }
        CatvJobQueue.objects.create(message=message_body, retries_remaining=1)
    
    def save(self):
        try:
            with transaction.atomic():
                task_record = CatvRequestStatus.objects.create(
                    uid=self.message_id,
                    params=self.search_params,
                    user=self.user
                )
                CatvResult.objects.create(request=task_record)
            return task_record
        except IntegrityError:
            raise DataIntegrityError("data integrity error")


class UserRoleUpdateTask(Task):
    def run(self, *args, **kwargs):
        user_id = kwargs['user_id']
        new_role = Role.objects.get(role_name=kwargs['new_role'])
        new_role_usage = RoleUsageLimit.objects.get(role=new_role)
        with transaction.atomic():
            User.objects.filter(id=user_id).update(role=new_role)
            Usage.objects.filter(user_id=user_id).update(
                api_calls_left=new_role_usage.api_limit,
                catv_calls_left=new_role_usage.catv_limit,
                cara_calls_left=new_role_usage.cara_limit,
                api_calls=0, catv_calls=0, cara_calls=0,
                api_calls_left_y=new_role_usage.api_limit_y - new_role_usage.api_limit,
                catv_calls_left_y=new_role_usage.catv_limit_y - new_role_usage.catv_limit,
                cara_calls_left_y=new_role_usage.cara_limit_y - new_role_usage.cara_limit,
                last_renewal_at_y=now()
            )
        return True


class CheckUserUpgradeTask(Task):
    def run(self, *args, **kwargs):
        query = Constants.QUERIES['EXPIRE_UPGRADE_CHALLENGE']
        with connections['default'].cursor() as cursor:
            cursor.execute(query)
        return True


class RefillCreditsYearlyTask(Task):
    def run(self, *args, **kwargs):
        query = Constants.QUERIES['REFILL_USER_USAGE_QUOTA_Y']
        with connections['default'].cursor() as cursor:
            cursor.execute(query)
        return True


tasks.register(CacheLeftPanelValuesTask)
tasks.register(CatvHistoryTask)
tasks.register(CheckUpdateUsageQuotaTask)
tasks.register(CacheNumberOfIndicatorsCases)
tasks.register(CaraHistoryTask)
tasks.register(CheckDeleteInvitesTask)
tasks.register(CatvPathHistoryTask)
tasks.register(UserRoleUpdateTask)
tasks.register(CheckUserUpgradeTask)
tasks.register(RefillCreditsYearlyTask)
