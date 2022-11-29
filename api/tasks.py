import uuid
from celery import shared_task
from django.db import connections, transaction, IntegrityError
from django.utils.timezone import now
from .constants import Constants
from .exceptions import DataIntegrityError
from .models import (
    CatvJobQueue, CatvRequestStatus, CatvResult,
)
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


@shared_task
def catv_history_task(*args, **kwargs):
    logger.info("Running catv_history_task()")
    entry = kwargs['history']
    from_history = kwargs['from_history']
    query_list = [Constants.QUERIES['INSERT_USER_CATV_HISTORY']]
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


@shared_task
def catv_path_history_task(*args, **kwargs):
    logger.info("Running catv_path_history_task()")
    entry = kwargs['history']
    from_history = kwargs['from_history']
    query_list = [Constants.QUERIES['INSERT_USER_CATV_PATH_SEARCH']]
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
            "user_id": self.user["user_id"],
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
                    user_id=self.user["user_id"],
                    token_type=self.token_type
                )
                CatvResult.objects.create(request=task_record)
            return task_record
        except IntegrityError:
            raise DataIntegrityError("data integrity error")
