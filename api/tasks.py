from celery.task.schedules import crontab
from celery.task import task
from celery.decorators import periodic_task

from .models import Case, Indicator, CaseIndicator, IndicatorSecurityCategory
from .cache.indicator import IndicatorCache

@periodic_task(run_every=(crontab(hour="23", minute="59", day_of_week="*")))
def get_dashboard_metrics():
    pass

@task()
@periodic_task(run_every=(crontab(hour="*", minute="0", day_of_week="*")))
def released_indicators():
    indicators = Indicator.objects.filter(cases__status = 'released').order_by('pattern', '-created').distinct('pattern')

    for indicator in indicators:
        IndicatorCache().set_indicator(indicator.pattern, indicator, indicator.security_category.value)

    return True
