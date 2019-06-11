from celery.task.schedules import crontab
from celery.decorators import periodic_task
from celery.task import Task
from celery.registry import tasks
from django.db.models import Q
from django.db import connection, connections
from .cache import DefaultCache
from .models import (
    User, Case, Indicator, CaseStatus,
)

"""
@periodic_task(run_every=(crontab(hour="23", minute="59", day_of_week="*")))
def get_dashboard_metrics():
    pass

@periodic_task(run_every=(datetime.timedelta(minutes=10)))
def save_released_indicator_to_cache():
    indicator_cache = IndicatorCache()
    last_id = indicator_cache.get_last_indicator_id()

    q = Q()
    q &= Q(cases__status = 'released')

    if last_id:
        q &= Q(id__gt = last_id)

    indicators = Indicator.objects.filter(q).order_by('pattern', '-created').distinct('pattern')

    max_id = 0
    for indicator in indicators:
        IndicatorCache().set_indicator(indicator.pattern.lower(), indicator, indicator.security_category.value)
        if max_id < indicator.id:
            max_id = max_id

    if max_id > 0:
        IndicatorCache().set_last_indicator_id(max_id)
    return True
"""

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
            c.set('left_panel_values', dashboard_obj, 0)
        return True

tasks.register(CacheLeftPanelValuesTask)
