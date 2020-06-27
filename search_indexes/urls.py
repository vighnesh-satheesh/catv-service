from django.conf.urls import url, include
from rest_framework.routers import DefaultRouter

from .viewsets import IndicatorDocumentView, CaseDocumentView

router = DefaultRouter()

indicators = router.register(r'indicators', IndicatorDocumentView, base_name='indicatordocument')
cases = router.register(r'cases', CaseDocumentView, base_name='casedocument')

urlpatterns = [
    url(r'^', include(router.urls))
]
