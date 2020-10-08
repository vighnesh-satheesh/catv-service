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

if settings.EXPOSE_FREESEARCH_ENDPOINT:
    urlpatterns += [
        url(r'^search/autocomplete/?$',
            views.AutoCompleteView.as_view(), name='search-autocomplete'),
    ]

# Internal APIs
if settings.EXPOSE_INTERNAL_API:
    urlpatterns += [
        url(r'^internal/indicator/?$',
            views_internal.IndicatorInternalView.as_view(), name='internal-indicator'),
        url(r'^internal/indicators/?$', views_internal.IndicatorInternalPostView.as_view(),
            name='internal-indicator-post'),
        url(r'^internal/case/?$', views_internal.CaseIntervalView.as_view(),
            name='internal-case'),
        url(r'^internal/catv/?$', views_internal.CATVInternalView.as_view(),
            name='internal-catv'),
        url(r'^internal/proxy_token/?$',
            views_internal.ProxyAuthentication.as_view(), name='proxy-api-token'),
        url(r'^internal/proxy_auth/?$', 
            views_internal.ProxyPasswordAuthentication.as_view(), name='proxy-pwd-auth')
    ]

if settings.EXPOSE_GENERAL_API:
    urlpatterns += [
        url(r'^login/?$', views.LoginView.as_view(), name='user-login'),
        url(r'^logout/?$', views.LogoutView.as_view(), name='user-logout'),
        url(r'^changepw/(?P<code>[0-9a-zA-Z\-]+)/?$',
            views.ChangePasswordView.as_view(), name='user-changepw'),
        url(r'^changepw/?$', views.ChangePasswordView.as_view(), name='user-changepw'),
        url(r'^case/?$', views.CaseView.as_view(), name='case-list'),
        url(r'^case/(?P<pk>[0-9a-z\-]+)/?$',
            views.CaseDetailView.as_view(), name='case-detail'),
        url(r'^indicator/?$', views.IndicatorView.as_view(), name='indicator'),
        url(r'^indicator/pattern/(?P<pattern>[\w|\W]+)/?$', views.IndicatorDetailView.as_view(
        ), name='indicator-detail-with-pattern'),
        url(r'^indicator/(?P<pk>[0-9a-z\-]+)/?$',
            views.IndicatorDetailView.as_view(), name='indicator-detail'),
        url(r'^icf/?$', views.IcfView.as_view(), name='icf'),
        url(r'^icf/(?P<pk>[0-9a-z\-]+)/?$',
            views.IcfView.as_view(), name='icf-update'),
        url(r'^sendemail/?$', views.SendEmailView.as_view(), name='send-email'),
        url(r'^verify/(?P<code>[0-9a-zA-Z\-]+)/?$',
            views.VerifyEmail.as_view(), name='verify-email'),
        url(r'^verify/?$', views.VerifyEmail.as_view(), name='verify-email'),
        url(r'^validate/?$', views.ValidateAddress.as_view(),
            name='validate-address'),
        url(r'^carasearch/?$', views.CARA.as_view(), name='cara-search'),
        url(r'^carahistory/?$', views.CARAHistory.as_view(), name='cara-history'),
        url(r'^carareport/?$', views.CARAReport.as_view(), name='cara-report'),
        url(r'^swapdata/?$', views.SwapData.as_view(), name='swap-data'),
        url(r'^swaphistory/?$', views.SwapHistory.as_view(), name='swap-history'),
        url(r'^exchange/?$', views.ExchangeTokenView.as_view(), name='exchange-data'),
        url(r'^user/create?$', views.UserSignUpView.as_view(), name='user-signup'),
        url(r'^user/(?P<pk>[0-9a-z\-]+)/?$',
            views.UserDetailView.as_view(), name='user-detail'),
        url(r'^search/?$', views.SearchView.as_view(), name='search-query'),
        url(r'^dashboard/?$', views.DashboardView.as_view(), name='user-dashboard'),
        url(r'^ico/(?P<pk>[0-9a-z\-]+)/?$',
            views.ICODetailView.as_view(), name='ico-detail'),
        url(r'^uppward_reward/?$', views.UppwardRewardInfoView.as_view(),
            name='uppward-reward-post'),
        url(r'^comment/(?P<type>[a-z\-]+)/(?P<pk>[0-9]+)/(?P<uid>[0-9a-z\-]+)/?$',
            views.CommentView.as_view(), name='comment-modify'),
        url(r'^comment/(?P<type>[a-z\-]+)/(?P<pk>[0-9]+)/?$',
            views.CommentView.as_view(), name='comment-view'),
        url(r'^notification/?$', views.NotificationView.as_view(),
            name='notification-view-single'),
        url(r'^notification/(?P<uid>[0-9a-z\-]+)/?$',
            views.NotificationView.as_view(), name='notification-view-uid'),
        url(r'^catv/?$', views.CATVView.as_view(), name='catv-view'),
        url(r'^catv_btc_tracking/?$',
            views.CATVBTCView.as_view(), name='catv-btc-view'),
        url(r'^catv_btc_txlist/?$', views.CATVBTCTxlistView.as_view(),
            name='catv-btc-txlist-view'),
        url(r'^catv_history/?$', views.CATVHistoryView.as_view(), name='catv-history'),
        url(r'^metrics/?$', views.Metrics.as_view(), name='metrics-view'),
        url(r'^guest_search/?$', views.GuestSearchView.as_view(), name='guest-search'),
        url(r'^usage_stats/user/(?P<pk>[0-9a-z\-]+)/?$',
            views.UsageStatsView.as_view(), name='usage-stats'),
        url(r'^organization/?$',
            views.OrganizationDetailView.as_view(), name="org-simple"),
        url(r'^organization/(?P<uid>[0-9a-z\-]+/?$)',
            views.OrganizationDetailView.as_view(), name='org-detail'),
        url(r'^invitation/?$', views.InvitationView.as_view(), name='org-invitation'),
        url(r'^social/login/(?P<backend>[0-9a-z\-]+)/?$',
            views.exchange_oauth_api_token, name='oauth-api-login'),
        url(r'^catv_requests/?$', views.CATVRequestsView.as_view(), name='catv-requests'),
        url(r'^catv_report/(?P<pk>[0-9a-z\-]+)/?$', views.CATVReportView.as_view(), name='catv-report'),
        url(r'^upgrade/?$', views.UserUpgradeView.as_view(), name='upgrade-plans'),
        url(r'^catv_requests/(?P<pk>[0-9a-z\-]+)/?$', views.CATVRequestDetailView.as_view(),
            name='catv-request-detail'),

    ]


if settings.EXPOSE_FILE_API:
    urlpatterns += [
        url(r'^file/?$', views.AttachedFilePostView.as_view(), name='file-upload'),
        url(r'^file/(?P<pk>[0-9a-z\-]+)/?$',
            views.AttachedFileDetailView.as_view(), name='file-handle')
    ]
