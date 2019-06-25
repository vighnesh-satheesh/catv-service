import datetime

from celery.task import Task
from celery.registry import tasks
from django.db import connections
from django.utils.timezone import now

from .cache import DefaultCache
from .constants import Constants


def cache_metrics_task():
    month_ago = (datetime.datetime.now() - datetime.timedelta(days=31)).strftime('%Y-%m-%d')
    c = DefaultCache()
    with connections['default'].cursor() as cursor:
        cursor.execute(Constants.QUERIES["SELECT_INDICATORS_WITHIN_DATE"], (month_ago,))
        rows = cursor.fetchall()
        c.set('metrics_indicators', rows, 60 * 6)
        cursor.execute(Constants.QUERIES['SELECT_CASE_BY_CREATED'], (month_ago,))
        rows = cursor.fetchall()
        c.set('metrics_cases', rows, 60 * 6)
    return True


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


class CacheMetricsTask(Task):
    def run(self, *args, **kwargs):
        cache_metrics_task()
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
tasks.register(CacheMetricsTask)
tasks.register(CatvHistoryTask)
tasks.register(CheckUpdateUsageQuotaTask)
