import json
from urllib.parse import urlparse
import uuid

from celery.task import Task
from celery.registry import tasks
from django.db import connections
from django.utils.timezone import now
from elasticsearch import Elasticsearch
from elasticsearch.helpers import streaming_bulk
from kafka import KafkaProducer

from .cache import DefaultCache
from .constants import Constants
from .models import Case, CatvRequestStatus
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
                    cursor.execute(query, data)
            else:
                cursor.execute(query_list[0], query_data[0])
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
        if api_settings.ELASTICSEARCH_CREDENTIALS:
            host_netloc = urlparse(api_settings.ELASTICSEARCH_HOST).netloc
            es_host = f'http://{api_settings.ELASTICSEARCH_CREDENTIALS}@{host_netloc}'
        else:
            es_host = api_settings.ELASTICSEARCH_HOST
        self.es_client = Elasticsearch([es_host])

    def generate_indicator_data(self):
        for indicator in self.related_indicators:
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
                    'security_tags': indicator.security_tags_indexing,
                    'vector': indicator.vector_indexing,
                    'environment': indicator.environment_indexing,
                    'pattern_type': indicator.pattern_type_indexing,
                    'pattern_subtype': indicator.pattern_subtype_indexing,
                    'pattern': indicator.pattern,
                    'detail': indicator.detail,
                    'created': indicator.created.isoformat(sep='T', timespec='milliseconds'),
                    'cases': indicator.cases_indexing,
                    'annotations': indicator.annotations_indexing,
                    'latest_case': {
                        'hex': getattr(indicator.latest_case_indexing, 'hex', '')
                    },
                    'user_id': indicator.user_id_indexing
                }
            }

    def run(self, *args, **kwargs):
        case_instance = kwargs.get('case', None)
        indicators = kwargs.get('indicators', None)
        if case_instance:
            try:
                self.related_indicators = Case.objects.using('default').get(id=case_instance.id).indicators.all()
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
                    cursor.execute(query, data)
            else:
                cursor.execute(query_list[0], query_data[0])
        return True


class CaseMessageTask:
    def __init__(self, topic, action=None):
        self.topic = topic
        self.related_ids = None
        print(f"Param action is: {action}")
        self.action = action if action else Constants.CASE_ACTIONS["CREATE"]
        print(self.action)

    def run(self):
        message_body = {
            "action_type": self.action,
            "related_ids": self.related_ids
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
        producer = KafkaProducer(
            bootstrap_servers=[
                api_settings.KAFKA_BROKER_1,
                api_settings.KAFKA_BROKER_2,
                api_settings.KAFKA_BROKER_3
            ],
            value_serializer=lambda m: json.dumps(m).encode("utf-8"),
            retries=3
        )
        producer.send(self.topic, message_body)
        producer.flush()
        producer.close()
    
    def save(self):
        task_record = CatvRequestStatus.objects.create(
            uid=self.message_id,
            params=self.search_params,
            user=self.user
        )
        return task_record.uid


tasks.register(CacheLeftPanelValuesTask)
tasks.register(CatvHistoryTask)
tasks.register(CheckUpdateUsageQuotaTask)
tasks.register(CacheNumberOfIndicatorsCases)
tasks.register(CaraHistoryTask)
tasks.register(CheckDeleteInvitesTask)
tasks.register(CatvPathHistoryTask)
