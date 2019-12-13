from django.conf.urls import url, include
from rest_framework.routers import DefaultRouter

from .viewsets import IndicatorDocumentView

router = DefaultRouter()

indicators = router.register(r'indicators', IndicatorDocumentView, base_name='indicatordocument')

urlpatterns = [
    url(r'^', include(router.urls))
]
