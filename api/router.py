from django.conf import settings
from django.conf.urls import url, include

from rest_framework import routers
# from rest_framework_swagger.views import get_swagger_view

from . import views
from .internal import views as views_internal

router = routers.SimpleRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^healthcheck/?$', views.HealthCheckView.as_view(), name='healthcheck'),
]

# Internal APIs
if settings.EXPOSE_INTERNAL_API:
    urlpatterns += [
        url(r'^internal/catv/?$', views_internal.CATVInternalView.as_view(),
            name='internal-catv')
    ]

if settings.EXPOSE_GENERAL_API:
    urlpatterns += [
        url(r'^catv/?$', views.CATVView.as_view(), name='catv-view'),
        url(r'^catv_btc_tracking/?$',
            views.CATVBTCView.as_view(), name='catv-btc-view'),
        url(r'^catv_btc_txlist/?$', views.CATVBTCTxlistView.as_view(),
            name='catv-btc-txlist-view'),
        url(r'^catv_history/?$', views.CATVHistoryView.as_view(), name='catv-history'),
        url(r'^catv_requests/?$', views.CATVRequestsView.as_view(), name='catv-requests'),
        url(r'^catv_report/(?P<pk>[0-9a-z\-]+)/?$', views.CATVReportView.as_view(), name='catv-report'),
        url(r'^catv_multi_report/?$', views.CATVMultiReportView.as_view(), name='catv-multi-report'),
        url(r'^catv_requests/(?P<pk>[0-9a-z\-]+)/?$', views.CATVRequestDetailView.as_view(),
            name='catv-request-detail'),
        url(r'^request_search/?$', views.RequestSearchView.as_view(), name='request-search'),
    ]