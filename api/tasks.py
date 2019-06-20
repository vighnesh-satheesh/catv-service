import datetime

from celery.task import Task
from celery.registry import tasks
from django.db import connections
from django.utils.timezone import now

from .cache import DefaultCache


def cache_metrics_task():
    month_ago = (datetime.datetime.now() - datetime.timedelta(days=31)).strftime('%Y-%m-%d')
    c = DefaultCache()
    with connections['default'].cursor() as cursor:
        cursor.execute( \
            'SELECT \
            id, uid, security_category, pattern, created, security_tags, pattern_type, pattern_subtype \
            FROM api_indicator \
            where created > ' + '\'' + month_ago + '\' \
                order by created desc')
        rows = cursor.fetchall()
        c.set('metrics_indicators', rows, 60 * 6)
        cursor.execute('SELECT created from api_case where created > \'' + month_ago + '\' order by created desc')
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
            cursor.execute('SELECT status, reporter_id, owner_id FROM api_case')
            row = cursor.fetchall()
            dashboard_obj['cases'] = row
            cursor.execute('SELECT count(*) from api_indicator')
            row = cursor.fetchone()
            dashboard_obj['indicators']['all'] = row[0]
            cursor.execute(\
                'SELECT COUNT(*) FROM api_indicator AS i \
                            JOIN api_m2m_case_indicator AS ci ON ci.indicator_id = i.id \
                            JOIN api_case as c ON ci.case_id = c.id \
                            WHERE c.status = \'released\' OR c.status = \'confirmed\''\
            )
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
        with connections['default'].cursor() as cursor:
            query = ("INSERT INTO api_catv_history(user_id,wallet_address,token_address,source_depth,"
                     "distribution_depth,transaction_limit,from_date,to_date,logged_time) "
                     "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);")
            data = (entry['user_id'], entry['wallet_address'], entry.get('token_address', ''),
                    entry.get('source_depth', 0), entry.get('distribution_depth', 0), entry['transaction_limit'],
                    entry['from_date'], entry['to_date'], now(),)
            cursor.execute(query, data)
        return True


tasks.register(CacheLeftPanelValuesTask)
tasks.register(CacheMetricsTask)
tasks.register(CatvHistoryTask)
