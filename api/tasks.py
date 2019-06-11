from celery.task.schedules import crontab
from celery.decorators import periodic_task
from django.db.models import Q
from .models import Case, Indicator, CaseIndicator, IndicatorSecurityCategory
import datetime

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
