from celery.task import Task
from celery.registry import tasks
from django.db import connections
from django.utils.timezone import now

from .cache import DefaultCache
from .constants import Constants


class CacheLeftPanelValuesTask(Task):
    def run(self, *args, **kwargs):
        dashboard_obj = {
            'cases': [],
            'indicators': {
                'all': 0,
                'cr': 0
            }
        }
        with connections['default'].cursor() as cursor:
            cursor.execute(Constants.QUERIES['SELECT_CASE_DETAILS'])
            row = cursor.fetchall()
            dashboard_obj['cases'] = row
            cursor.execute(Constants.QUERIES['SELECT_INDICATOR_COUNT'])
            row = cursor.fetchone()
            dashboard_obj['indicators']['all'] = row[0]
            cursor.execute(Constants.QUERIES['SELECT_CASE_INDICATOR_COUNT'], ('released', 'confirmed',))
            row = cursor.fetchone()
            dashboard_obj['indicators']['cr'] = row[0]
            c = DefaultCache()
            c.set('left_panel_values', dashboard_obj, 60 * 60)
        return True


class CacheNumberOfIndicators(Task):
    def run(self, *args, **kwargs):
        with connections['default'].cursor() as cursor:
            cursor.execute(Constants.QUERIES['SELECT_INDICATOR_COUNT'])
            all = cursor.fetchone()[0]
            cursor.execute(Constants.QUERIES['SELECT_CASE_INDICATOR_COUNT'], ('released', 'confirmed',))
            released_confirmed = cursor.fetchone()[0]
            obj = {
                "all": all,
                "released_confirmed": released_confirmed
            }
            c = DefaultCache()
            c.set("number_of_indicators", obj, 60 * 60)
        return True


class CatvHistoryTask(Task):
    def run(self, *args, **kwargs):
        entry = kwargs['history']
        query_list = [Constants.QUERIES['INSERT_USER_CATV_HISTORY'], Constants.QUERIES['UPDATE_USER_CATV_USAGE']]
        query_data = [(entry['user_id'], entry['wallet_address'], entry.get('token_address', ''),
                       entry.get('source_depth', 0), entry.get('distribution_depth', 0), entry['transaction_limit'],
                       entry['from_date'], entry['to_date'], now(),),
                      (entry['user_id'],)]

        with connections['default'].cursor() as cursor:
            for query, data in zip(query_list, query_data):
                cursor.execute(query, data)
        return True


class CheckUpdateUsageQuotaTask(Task):
    def run(self, *args, **kwargs):
        query = Constants.QUERIES['REFILL_USER_USAGE_QUOTA']
        with connections['default'].cursor() as cursor:
            cursor.execute(query)
        return True


tasks.register(CacheLeftPanelValuesTask)
tasks.register(CatvHistoryTask)
tasks.register(CheckUpdateUsageQuotaTask)
tasks.register(CacheNumberOfIndicators)
