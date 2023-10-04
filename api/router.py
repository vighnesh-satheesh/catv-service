from django.conf import settings
from django.urls import re_path, include

from rest_framework import routers
# from rest_framework_swagger.views import get_swagger_view

from . import views,api_views
from .internal import views as views_internal

router = routers.SimpleRouter()

urlpatterns = [
    re_path(r'^', include(router.urls)),
    re_path(r'^healthcheck/?$', views.HealthCheckView.as_view(), name='healthcheck'),
]

# Internal APIs
if settings.EXPOSE_INTERNAL_API:
    urlpatterns += [
        re_path(r'^internal/catv/?$', views_internal.CATVInternalView.as_view(),
            name='internal-catv')
    ]

if settings.EXPOSE_GENERAL_API:
    urlpatterns += [
        re_path(r'^catv/?$', views.CATVView.as_view(), name='catv-view'),
        re_path(r'^catvbtctracking/?$',
            views.CATVBTCView.as_view(), name='catv-btc-view'),
        re_path(r'^catvbtctxlist/?$', views.CATVBTCTxlistView.as_view(),
            name='catv-btc-txlist-view'),
        re_path(r'^catvhistory/?$', views.CATVHistoryView.as_view(), name='catv-history'),
        re_path(r'^catvrequests/?$', views.CATVRequestsView.as_view(), name='catv-requests'),
        re_path(r'^catvreport/(?P<pk>[0-9a-z\-]+)/?$', views.CATVReportView.as_view(), name='catv-report'),
        re_path(r'^catvmultireport/?$', views.CATVMultiReportView.as_view(), name='catv-multi-report'),
        re_path(r'^catvrequests/(?P<pk>[0-9a-z\-]+)/?$', views.CATVRequestDetailView.as_view(),
            name='catv-request-detail'),
        re_path(r'^request_search/?$', views.RequestSearchView.as_view(), name='request-search'),
        re_path(r'^catvnodelabel/?$', views.CATVNodeLabelView.as_view(), name='catv-node-label'),
        re_path(r'^catvcsvupload/?$', views.CATVCSVUploadView.as_view(), name='catv-csv-upload'),
        re_path(r'^api_key_info', api_views.ApiKeyInfo.as_view(),name='api-key-info'),
        re_path(r'^v1/source', api_views.CatvInbound.as_view(),name='catv-inbound'),
        re_path(r'^v1/destination', api_views.CatvOutbound.as_view(),name='catv-outbound'),
        re_path(r'^v1/supported_networks', api_views.CatvSupportedNetworks.as_view(),name='catv-supported-networks'),
        re_path(r'^time?$', api_views.ServerTime.as_view(), name='server-time')

    ]