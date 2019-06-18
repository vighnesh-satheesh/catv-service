from celery.decorators import periodic_task
from celery.task import Task
from celery.registry import tasks
from django.db.models import Q
from django.db import connection, connections
from .cache import DefaultCache
from celery.schedules import crontab
import datetime

@periodic_task(run_every=crontab(minute='*/5'))
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

tasks.register(CacheLeftPanelValuesTask)
tasks.register(CacheMetricsTask)
