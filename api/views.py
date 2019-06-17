from collections import defaultdict
import gzip

from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import JSONRenderer

from django_filters import rest_framework as filters
from django.db.models import Q, Count
from django.db.models.functions import TruncDate
from django.db import transaction, IntegrityError

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db import connection

from .models import (
    User, Case, Indicator, CaseIndicator, ICO, CaseStatus, Key, Comment,
    Notification, NotificationType,
    AttachedFile, UserPermission, UppwardRewardInfo,
    UserStatus,
    IndicatorPatternType, IndicatorPatternSubtype, IndicatorEnvironment, IndicatorVector, IndicatorSecurityCategory,
)
from .serializers import (
    LoginSerializer, ChangePasswordSerializer,
    CaseListSerializer, CaseDetailSerializer, CasePatchSerializer, CasePostSerializer, CaseHistoryPostSerializer,
    AutoCompleteSerializer, AttachedFilePostSerializer,
    ICODetailSerializer, ICOListSerializer,
    IndicatorPostSerializer, IndicatorDetailSerializer, IndicatorListSerializer, IndicatorSimpleListSerializer,
    UppwardRewardInfoPostSerializer,
    UserDetailSerializer, UserPostSerializer,
    ICFDetailSerializer, ICFPostSerializer,
    CommentSerializer, CommentPostSerializer,
    NotificationSerializer, CATVSerializer
)
from .throttling import (
    SignUpThrottle, UserLoginThrottle, ChangePasswordThrottle,
    FileUploadThrottle, CasePostThrottle,
    EmailVerificationThrottle,
    IndicatorPostThrottle, CatvPostThrottle
)
from .response import APIResponse, FileResponse, FileRenderer
from .pagination import CustomPagination
from . import exceptions
from . import permissions
from . import utils
from .multitoken.tokens_auth import CachedTokenAuthentication, MultiToken
from .settings import api_settings
from .cache import DefaultCache
from .cache.catv import TrackingCache
from .email import Email
from .email.tasks import SendEmail
from .constants import Constants
from .tasks import CacheLeftPanelValuesTask, CacheMetricsTask
from django.utils import timezone
from django.utils.timezone import make_aware

import datetime
import pytz
import json

class HealthCheckView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)

    def get(self, request):
        return APIResponse({
            "status": "ok"
        })


class LoginView(ObtainAuthToken):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    throttle_classes = (UserLoginThrottle,)

    def post(self, request, format=None):
        serializer = LoginSerializer(data=request.data,
                                     context={"request": request})
        serializer.is_valid(raise_exception=True)
        return APIResponse({
            "data": serializer.validated_data
        })


class LogoutView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def post(self, request, format=None):
        try:
            MultiToken.expire_token(request.auth)
        except self.model.DoesNotExist:
            pass

        return APIResponse({"data": ""})


class ChangePasswordView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    throttle_classes = (ChangePasswordThrottle,)
    model = User

    def get_object(self, email):
        try:
            return self.model.objects.get(email__iexact=email)
        except self.model.DoesNotExist:
            raise exceptions.UserNotFound("")

    def get(self, request, code=None):
        msg = "password reset code is not valid"
        if not code:
            raise exceptions.PasswordResetCodeNotValid(msg)

        c = DefaultCache()
        email = c.get_email_by_password_reset_key(code)
        if not email:
            raise exceptions.PasswordResetCodeNotValid(msg)

        return APIResponse({
            "data": {
                "email": email
            }
        })

    def put(self, request, format=None):
        data = request.data
        try:
            code = data.get("code", None)
        except KeyError:
            raise exceptions.AuthenticationValidationError("invalid data")
        c = DefaultCache()
        v = c.get(code)
        if not v:
            raise exceptions.AuthenticationValidationError("code not found")
        email = v.split("-")[0]
        obj = self.get_object(email)
        serializer = ChangePasswordSerializer(obj, data=data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        c.delete_key(code)
        return APIResponse({"data": {}})


class DashboardView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None):
        if request.user is None or request.auth is None:
            raise exceptions.AuthenticationCheckError()
        user = request.user

        c = DefaultCache()
        lpv = c.get('left_panel_values')
        number_of_all_indicators = 0
        all_cases = []
        my_cases = []
        cases = []
        for item in CaseStatus:
            my_cases.append({
                "id": "case_my_{0}".format(item.value),
                "count": 0
            })
            all_cases.append({
                "id": "case_all_{0}".format(item.value),
                "count": 0
            })
        cases = [
            {
                "id": "case_all",
                "count": 0,
                "children": all_cases
            },
            {
                "id": "case_my",
                "count": 0,
                "children": my_cases
            }
        ]
        with connection.cursor() as cursor:
            if not lpv:
                cursor.execute('SELECT status, reporter_id, owner_id FROM api_case')
                row = cursor.fetchall()
            else:
                row = lpv['cases']
            for r in row:
                status = r[0]
                reporter_id = r[1]
                owner_id = r[2]
                for case in cases:
                    if "my" in case["id"] and user.pk != reporter_id and user.pk != owner_id:
                        continue
                    for c in case["children"]:
                        if status not in c["id"]:
                            continue
                        c["count"] += 1

        if user.permission is UserPermission.EXCHANGE:
            cases[0]["children"]  = [c for c in cases[0]["children"] if "confirmed" in c["id"] or "released" in c["id"]]
        elif user.permission is UserPermission.USER:
            cases = cases[1:]

        for case in cases:
            count = 0
            for c in case["children"]:
                count += c["count"]
            case["count"] = count

        with connection.cursor() as cursor:
            if lpv:
                if user.permission is UserPermission.SUPERSENTINEL or \
                        user.permission is UserPermission.SENTINEL:
                    number_of_all_indicators = lpv['indicators']['all']
                else:
                    number_of_all_indicators = lpv['indicators']['cr']
            else:
                sql = ''
                if user.permission is UserPermission.SUPERSENTINEL or \
                        user.permission is UserPermission.SENTINEL:
                    sql = 'SELECT count(*) from api_indicator'
                else:
                    sql = 'SELECT COUNT(*) FROM api_indicator AS i \
                        JOIN api_m2m_case_indicator AS ci ON ci.indicator_id = i.id \
                        JOIN api_case as c ON ci.case_id = c.id \
                        WHERE c.status = \'released\' OR c.status = \'confirmed\''
                cursor.execute(sql)
                row = cursor.fetchone()
                number_of_all_indicators = row[0]

        indicators = [
            {
                "id": "indicator_all",
                "count": number_of_all_indicators,
                "children": []
            }
        ]

        notifications = []
        notification_objs = Notification.objects.filter(user=user.pk).order_by('-created')[:100]
        if notification_objs:
            notifications = NotificationSerializer(notification_objs, many=True).data

        if not lpv:
            CacheLeftPanelValuesTask().delay()

        return APIResponse({
            "data": {
                "cases": cases,
                "indicators": indicators,
                "notifications": notifications
            }
        })


class CaseFilter(filters.FilterSet):
    user_case = filters.CharFilter(method='filter_user_case')
    case = filters.CharFilter(method='filter_case_board')

    class Meta:
        model = Case
        fields = ("case",)

    def filter_user_case(self, queryset, name, value):
        usercase_cate = value.split('_')
        if not len(usercase_cate) == 2:
            raise exceptions.CaseFilterError()
        user_uid = usercase_cate[0]
        action = usercase_cate[1]
        try:
            user = User.objects.get(uid = user_uid)
        except User.DoesNotExist:
            raise exceptions.CaseFilterError()

        if action not in ['reported', 'released']:
            raise exceptions.CaseFilterError()

        if action == 'reported':
            return queryset.filter(reporter = user.pk).distinct('id')
        elif action == 'released':
            return queryset.filter(verifier = user.pk).distinct('id')

        return queryset.distinct('id')

    def filter_case_board(self, queryset, name, value):
        case_cate = value.split("_")
        if len(case_cate) not in [1, 2]:
            raise exceptions.CaseFilterError()
        filter = Q()
        keyword_filter = Q()
        cate = case_cate[0]
        subcate = None
        if len(case_cate) == 2:
            subcate = case_cate[1]

        if cate not in ["all", "my"]:
            raise exceptions.CaseFilterError()

        if subcate and subcate not in ["new", "progress", "confirmed", "rejected", "released"]:
            raise exceptions.CaseFilterError()

        if subcate is not None:
            filter &= Q(status=subcate)

        if cate == "all":
            if self.request.user.permission == UserPermission.EXCHANGE:
                filter &= (Q(status="released") | Q(status="confirmed"))
        elif cate == "my":
            filter &= (Q(owner=self.request.user.pk) | Q(reporter=self.request.user.pk))

        security_category = self.request.GET.getlist("security_category") or []
        pattern_subtype = self.request.GET.getlist("pattern_subtype") or []
        pattern_type = self.request.GET.getlist("pattern_type") or []
        keyword = self.request.GET.getlist("keyword") or []

        if len(security_category) > 0:
            filter &= Q(indicator__security_category__in=security_category)
        if len(pattern_type) > 0:
            filter &= Q(indicator__pattern_type__in=pattern_type)
        if len(pattern_subtype) > 0:
            filter &= Q(indicator__pattern_subtype__in=pattern_subtype)

        if len(keyword) > 0:
            keyword_pattern_type = []
            keyword_pattern_subtype = []
            keyword_vector = []
            keyword_environment = []
            for idx, k in enumerate(keyword):
                keyword_filter |= Q(title__icontains=k)
                keyword_filter |= Q(detail__icontains=k)
                keyword_filter |= Q(indicators__pattern__icontains=k)
                keyword_filter |= Q(indicators__annotation=k)
                try:
                    IndicatorPatternType(k)
                    keyword_pattern_type.append(k)
                except ValueError:
                    pass
                try:
                    IndicatorPatternSubtype(k)
                    keyword_pattern_subtype.append(k)
                except ValueError:
                    pass
                try:
                    IndicatorVector(k)
                    keyword_vector.append(k)
                except ValueError:
                    pass
                try:
                    IndicatorEnvironment(k)
                    keyword_environment.append(k)
                except ValueError:
                    pass
                if k.isdigit():
                    keyword_filter |= Q(id=k)

            if len(keyword_pattern_type) > 0:
                keyword_filter |= Q(indicator__pattern_type__in=keyword_pattern_type)
            if len(keyword_pattern_subtype) > 0:
                keyword_filter |= Q(indicator__pattern_subtype__in=keyword_pattern_subtype)
            if len(keyword_vector) > 0:
                keyword_filter |= Q(indicator__vector__contains=keyword_vector)
            if len(keyword_environment) > 0:
                keyword_filter |= Q(indicator__environment__contains=keyword_environment)

        return queryset.filter(filter & keyword_filter).prefetch_related('indicators')


class CaseView(generics.ListCreateAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (permissions.IsPostOrIsAuthenticated, permissions.CaseListPermission)
    pagination_class = CustomPagination
    filter_backends = (filters.DjangoFilterBackend,)
    filter_class = CaseFilter
    serializer_class = CaseListSerializer
    model = Case

    def get_queryset(self):
        order_by = self.request.GET.get('order_by') or 'id_desc'
        order_by = order_by.split('_')
        key = ""
        if order_by[1] == "desc":
            key = "-"
        key = key + order_by[0]
        return self.model.objects.distinct('id').order_by(key)

    def get_throttles(self):
        ret = []
        if self.request.method.lower() == 'get':
            return ret
        elif self.request.method.lower() == 'post':
            return [CasePostThrottle(), ]
        else:
            return super(CaseView, self).get_throttles()

    def post(self, request, format=None):
        serializer = CasePostSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        if request.auth is not None:
            case = serializer.save(reporter=request.user)
        else:
            case = serializer.save()

        # save history.
        history_log = Constants.HISTORY_LOG
        history_log["msg"] = CaseStatus.NEW.value
        history_log["type"] = "status"

        history_data = {
            "log": json.dumps(history_log),
            "case": case.pk,
            "initiator":  case.reporter.pk if case.reporter else None
        }

        ch_serializer = CaseHistoryPostSerializer(data=history_data)
        ch_serializer.is_valid(raise_exception=True)
        ch_serializer.save()

        c = DefaultCache()
        c.delete_key('left_panel_values')

        return APIResponse({
            "data": {
                "case": {
                    "id": case.pk,
                    "uid": case.uid
                }
            }
        })

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data, data_key="cases")


class CaseDetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated, permissions.CheckCaseDetailPermission)
    model = Case

    def get_object(self, pk, request):
        try:
            return self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            raise exceptions.CaseNotFound()

    def get(self, request, pk=None):
        obj = self.get_object(pk, request)
        serializer = CaseDetailSerializer(obj, context={'request': request})
        data = serializer.data

        user_permission = getattr(request.user, 'permission', None)
        is_super = True if user_permission == UserPermission.SUPERSENTINEL else False
        is_owner = True if request.user == obj.owner else False

        permission_data = {}

        if user_permission == UserPermission.SUPERSENTINEL and obj.status in [CaseStatus.NEW, CaseStatus.PROGRESS]:
            permission_data['editable'] = True
            permission_data['deletable'] = True

        if obj.owner == request.user and obj.status == CaseStatus.PROGRESS:
            permission_data['editable'] = True
            permission_data['deletable'] = True

        if obj.reporter == request.user and obj.status == CaseStatus.NEW:
            permission_data['editable'] = True
            permission_data['deletable'] = True

        if 'editable' not in permission_data:
            permission_data['editable'] = False

        if 'deletable' not in permission_data:
            permission_data['deletable'] = False

        next_status = utils.CASE_STATUS_FSM.next(obj.status, is_super, is_owner, user_permission)
        permission_data["status"] = [e.value for e in next_status]

        return APIResponse({
            "data": {
                "case": data,
                "case_permission": permission_data
            }
        })

    def put(self, request, pk=None):
        obj = self.get_object(pk, request)
        user_permission = getattr(request.user, 'permission', None)

        if user_permission != UserPermission.SUPERSENTINEL:
            if obj.status == CaseStatus.PROGRESS and obj.owner != request.user:
                raise exceptions.NotAllowedError()
            if obj.status == CaseStatus.NEW and obj.reporter != request.user:
                raise exceptions.NotAllowedError()

        serializer = CasePostSerializer(obj, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        c = DefaultCache()
        c.delete_view_cache(request)

        if obj.reporter and obj.reporter.email_notification:
            notification = Notification.objects.create(
                user=obj.reporter,
                initiator=request.user,
                type=NotificationType.CASE_UPDATED,
                target={
                    "uid": str(obj.uid),
                    "title": obj.title,
                    "type": "case"
                }
            )
            e = Email()
            kv = {
                "nickname": obj.reporter.nickname,
                "link": api_settings.WEB_URL + '/case/' + str(obj.uid)
            }
            SendEmail().delay(kv = kv,
                  subject = Constants.EMAIL_TITLE["NOTIFICATION_MODIFY_CASE"].format(request.user.nickname),
                  email_type = e.EMAIL_TYPE["NOTIFICATION"],
                  sender = e.EMAIL_SENDER["NO-REPLY"],
                  recipient = [obj.reporter.email])

        return APIResponse({
            "data": {}})

    def patch(self, request, pk=None):
        obj = self.get_object(pk, request)
        serializer = CasePatchSerializer(obj, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        c = DefaultCache()
        c.delete_key('left_panel_values')
        c.delete_view_cache(request)

        if obj.reporter and obj.reporter.email_notification:
            notification = Notification.objects.create(
                user=obj.reporter,
                initiator=request.user,
                type=NotificationType("case_status_updated_to_{0}".format(serializer.data["status"])),
                target={
                    "uid": str(obj.uid),
                    "title": obj.title,
                    "type": "case"
                }
            )
            e = Email()
            kv = {
                "nickname": obj.reporter.nickname,
                "link": api_settings.WEB_URL + '/case/' + str(obj.uid)
            }
            SendEmail().delay(kv = kv,
                              subject = Constants.EMAIL_TITLE["NOTIFICATION_PATCH_CASE"].format(request.user.nickname, obj.status.value),
                              email_type = e.EMAIL_TYPE["NOTIFICATION"],
                              sender = e.EMAIL_SENDER["NO-REPLY"],
                              recipient = [obj.reporter.email])

        return APIResponse({"data": {}})

    def delete(self, request, pk=None):
        try:
            with transaction.atomic():
                obj = self.get_object(pk, request)
                if obj.status != CaseStatus.PROGRESS:
                    raise exceptions.ValidationError("case cannot be deleted.")
                if obj.owner != request.user:
                    raise exceptions.OwnerRequiredError()
                CaseIndicator.objects.filter(case = obj).delete()

        except Case.DoesNotExist:
            raise exceptions.ValidationError("case does not exist")
        except IntegrityError:
            raise exceptions.DataIntegrityError("")
        if obj.reporter and obj.reporter.email_notification:
            notification = Notification.objects.create(
                user=obj.reporter,
                initiator=request.user,
                type=NotificationType.CASE_DELETED,
                target={
                    "uid": str(obj.uid),
                    "title": obj.title,
                    "type": "case"
                }
            )
            e = Email()
            kv = {
                "nickname": obj.reporter.nickname,
                "link": api_settings.WEB_URL + '/case/' + str(obj.uid)
            }
            SendEmail().delay(kv = kv,
                              subject = Constants.EMAIL_TITLE["NOTIFICATION_DELETE_CASE"].format(request.user.nickname),
                              email_type = e.EMAIL_TYPE["NOTIFICATION"],
                              sender = e.EMAIL_SENDER["NO-REPLY"],
                              recipient = [obj.reporter.email])
        obj.delete()

        c = DefaultCache()
        c.delete_key('left_panel_values')
        c.delete_view_cache(request)
        return APIResponse({"data": {}})


class IndicatorFilter(filters.FilterSet):
    page = filters.CharFilter(method='filter_queryset')

    class Meta:
        model = Indicator
        fields = ()

    def filter_queryset(self, queryset, name, value):
        ftr = Q()
        keyword_filter = Q()

        if self.request.user.permission is not UserPermission.SUPERSENTINEL and \
            self.request.user.permission is not UserPermission.SENTINEL:
            ftr &= (Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | Q(user=self.request.user.pk))

        status = self.request.GET.getlist("status") or []
        security_category = self.request.GET.getlist("security_category") or []
        pattern_subtype = self.request.GET.getlist("pattern_subtype") or []
        pattern_type = self.request.GET.getlist("pattern_type") or []
        keyword = self.request.GET.getlist("keyword") or []

        if len(security_category) > 0:
            ftr &= Q(security_category__in=security_category)
        if len(pattern_type) > 0:
            ftr &= Q(pattern_type__in=pattern_type)
        if len(pattern_subtype) > 0:
            ftr &= Q(pattern_subtype__in=pattern_subtype)
        if len(keyword) > 0:
            for idx, k in enumerate(keyword):
                keyword_filter |= Q(pattern__icontains=k)
                keyword_filter |= Q(detail__icontains=k)
                keyword_filter |= Q(annotation=k)
                if k.isdigit():
                    keyword_filter |= Q(id=k)
            ftr &= keyword_filter

        if len(status) > 0:
            ftr &= Q(cases__status__in=status)
            return queryset.filter(ftr).prefetch_related('cases')

        return queryset.filter(ftr)


class IndicatorView(generics.ListCreateAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    pagination_class = CustomPagination
    filter_backends = (filters.DjangoFilterBackend,)
    filter_class = IndicatorFilter
    serializer_class = IndicatorListSerializer
    model = Indicator

    def get_queryset(self):
        order_by = self.request.GET.get('order_by') or 'id_desc'
        order_by = order_by.split('_')
        key = ""
        if order_by[1] == "desc":
            key = "-"
        key = key + order_by[0]
        return self.model.objects.distinct('id').order_by(key)

    def get_throttles(self):
        ret = []
        if self.request.method.lower() == 'get':
            return ret
        elif self.request.method.lower() == 'post':
            return [IndicatorPostThrottle(), ]
        else:
            return super(IndicatorView, self).get_throttles()

    def post(self, request):
        if "indicators" in request.data:
            serializer = IndicatorPostSerializer(data=request.data["indicators"], many=True,
                                                 context={'request': request})
        else:
            serializer = IndicatorPostSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        if request.auth is not None:
            indicator_obj = serializer.save(user=request.user)
        else:
            indicator_obj = serializer.save()
        result_serializer = IndicatorSimpleListSerializer(indicator_obj, many="indicators" in request.data)

        c = DefaultCache()
        c.delete_key('left_panel_values')

        return APIResponse({
            "data": result_serializer.data
        })

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data, data_key="indicators")


class IndicatorDetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    model = Indicator

    def get_object(self, pk, pattern):
        if not pk and not pattern:
            raise exceptions.IndicatorNotFound()
        if pk:
            try:
                indicator = self.model.objects.get(uid__iexact=pk)
            except self.model.DoesNotExist:
                raise exceptions.IndicatorNotFound()
        elif pattern:
            try:
                indicator = self.model.objects.filter(pattern__iexact=pattern).order_by('-id')[0]
            except IndexError:
                raise exceptions.IndicatorNotFound()
        return indicator

    def get(self, request, pk=None, pattern=None):
        c = DefaultCache()
        cached_response = c.get_view_cache(request)
        if cached_response:
            return APIResponse(cached_response)

        obj = self.get_object(pk, pattern)
        serializer = IndicatorDetailSerializer(obj, is_authenticated=True if request.user and request.user.is_authenticated else False)
        data = serializer.data
        return APIResponse(
            c.set_view_cache(request, {
                "data": {
                    "indicator": data
                }
            })
        )

    def put(self, request, pk=None):
        obj = self.get_object(pk, None)
        case_test_objs = obj.cases.filter(status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED])
        if len(case_test_objs) > 0:
            raise exceptions.NotAllowedError()
        serializer = IndicatorPostSerializer(obj, data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        indicator_obj = serializer.save()
        result_serializer = IndicatorSimpleListSerializer(indicator_obj)
        c = DefaultCache()
        c.delete_view_cache(request)
        return APIResponse({
            "data": result_serializer.data
        })

    def delete(self, request, pk=None):
        try:
            with transaction.atomic():
                indicator = self.get_object(pk)
                cases = indicator.cases.all()
                for case in cases:
                    if case.status in [CaseStatus.CONFIRMED, CaseStatus.RELEASED]:
                        raise exceptions.ValidationError("has confirmed or released attached cases.")
                CaseIndicator.objects.filter(indicator=indicator).delete()
                indicator.delete()
        except Indicator.DoesNotExist:
            raise exceptions.ValidationError("indicator does not exist")
        except IntegrityError:
            raise exceptions.DataIntegrityError("")
        c = DefaultCache()
        c.delete_key('left_panel_values')
        c.delete_view_cache(request)
        return APIResponse({"data": {}})


class SearchView(generics.ListAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    pagination_class = CustomPagination
    filter_backends = (filters.DjangoFilterBackend,)

    @method_decorator(cache_page(60 * 5))
    def dispatch(self, *args, **kwargs):
        return super(SearchView, self).dispatch(*args, **kwargs)

    def list(self, request, *args, **kwargs):
        search_type = self.request.query_params.get("type", "ico")
        query = self.request.query_params.get("q", None)
        if query is None:
            raise exceptions.ValidationError("q is required.")

        if len(query) > 1024:
            raise exceptions.ValidationError("q is too long.")

        if search_type == "case":
            serializer_cls = CaseListSerializer
        elif search_type == "indicator":
            serializer_cls = IndicatorListSerializer
        elif search_type == "ico":
            serializer_cls = ICOListSerializer
        else:
            serializer_cls = ICOListSerializer

        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if request.auth and search_type == "indicator":
            serializer = serializer_cls(page, many=True, is_authenticated=True)
        else:
            serializer = serializer_cls(page, many=True)
        return self.get_paginated_response(serializer.data)

    def get_ico_queryset(self, query):
        filter_queries = Q(symbol__istartswith=query)
        if len(query) > 1:
            filter_queries |= Q(name__icontains=query)
        objs = ICO.objects.filter(filter_queries).distinct('id').order_by('-pk')
        return objs

    def get_indicator_queryset(self, query):
        objs = []
        filter_queries = Q(pattern__icontains=query)
        filter_queries |= Q(security_tags__icontains=query)

        try:
            IndicatorPatternSubtype(query.lower())
            filter_queries |= Q(pattern_subtype=query.lower())
        except ValueError:
            pass

        if not self.request.auth:
            filter_queries &= Q(case__status=CaseStatus.RELEASED)
        elif self.request.auth and self.request.user.permission is UserPermission.EXCHANGE:
            filter_queries &= Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | Q(user=self.request.user.pk)

        objs = Indicator.objects \
            .filter(filter_queries) \
            .distinct('id') \
            .order_by('-pk')

        return objs

    def get_case_queryset(self, query):
        if not self.request.auth:
            raise exceptions.AuthenticationCheckError()

        filter_queries = Q(id=0)
        if query.isdigit():
            filter_queries = Q(id=int(query))
        if len(query) > 1 and filter_queries is None:
            filter_queries = Q(title__icontains=query)
        elif len(query) > 1 and filter_queries is not None:
            filter_queries |= Q(title__icontains=query)

        if len(query) > 1:
            filter_queries |= Q(indicator__pattern__icontains=query)
            filter_queries |= Q(indicator__pattern_subtype__icontains=query)
            filter_queries |= Q(ico__symbol__icontains=query)

        if self.request.user.permission is UserPermission.EXCHANGE:
            filter_queries &= Q(status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | Q(reporter=self.request.user.pk)

        objs = Case.objects \
            .filter(filter_queries) \
            .select_related('ico') \
            .distinct('id') \
            .order_by('-pk')

        return objs

    def get_queryset(self):
        query = self.request.query_params.get("q", None)
        search_type = self.request.query_params.get("type", "ico")

        if search_type not in ["case", "ico", "indicator"]:
            search_type = "ico"

        objs = None
        if search_type == "ico":
            return self.get_ico_queryset(query)
        elif search_type == "indicator":
            return self.get_indicator_queryset(query)
        elif search_type == "case":
            return self.get_case_queryset(query)
        return objs

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data, data_key="items")


class AutoCompleteView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    @method_decorator(cache_page(60 * 5))
    def dispatch(self, *args, **kwargs):
        return super(AutoCompleteView, self).dispatch(*args, **kwargs)

    def get(self, request, **kwargs):
        serializer = AutoCompleteSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return APIResponse({
            "data": data})


class AttachedFilePostView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    throttle_classes = (FileUploadThrottle,)
    model = AttachedFile

    def __create_response(self, files):
        files_data = []
        for file in files:
            file_data = {
                "uid": file.uid,
                "type": file.type,
                "size": file.size,
            }
            files_data.append(file_data)
        return files_data

    def post(self, request, format=None):
        serializer = AttachedFilePostSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as err:
            err.exc_file_rid = request.data.get("rid", None)
            raise err
        files = serializer.save()
        return APIResponse({"data": {
            "files": self.__create_response(files),
            "rid": serializer.validated_data["rid"]
        }})


class AttachedFileDetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)
    renderer_classes = (FileRenderer, JSONRenderer)
    model = AttachedFile

    def get_object(self, pk, raise_exception=False):
        try:
            obj = self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            if raise_exception:
                raise exceptions.FileNotFound()
            else:
                return None

        if obj.case is None:  # TODO: this file should be deleted!
            raise exceptions.CaseNotFound()
        return obj

    def get(self, request, pk=None):  # TODO: error response should be json.
        obj = self.get_object(pk, raise_exception=True)
        try:
            file_obj = obj.file.open(mode='rb')
            buf = file_obj.read()
        except Exception as err:
            raise exceptions.FileNotFound()
        return FileResponse(buf, obj.uid, content_type=obj.type)


class ICODetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    model = ICO

    @method_decorator(cache_page(60 * 5))
    def dispatch(self, *args, **kwargs):
        return super(ICODetailView, self).dispatch(*args, **kwargs)

    def get(self, request, pk=None):
        try:
            queryset = self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            raise exceptions.ICONotFound()

        serializer = ICODetailSerializer(queryset)
        data = serializer.data
        return APIResponse({
            "data": {
                "ico": data
            }
        })


class UppwardRewardInfoView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    serializer_class = UppwardRewardInfoPostSerializer
    model = UppwardRewardInfo

    def post(self, request, format=None):
        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            serializer.save()
        except Exception as err:
            print(">>> uppward_referral failed to validate", err)

        return APIResponse({
            "data": {
            }
        })


class VerifyEmail(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    throttle_classes = (EmailVerificationThrottle,)
    model = User

    def get_object(self, email):
        try:
            return self.model.objects.get(email__iexact=email)
        except self.model.DoesNotExist:
            raise exceptions.AuthenticationValidationError("")

    def get(self, request):
        email = request.data["email"]
        user = self.get_object(email)
        e = Email()
        c = DefaultCache()
        link = c.set_signup_verification_key(user.email)
        kv = {
            "nickname": user.nickname,
            "link": api_settings.WEB_URL + "/verify/" + link
        }
        SendEmail().delay(kv = kv,
                          subject = Constants.EMAIL_TITLE["VERIFICATION"],
                          email_type = e.EMAIL_TYPE["REGISTER"],
                          sender = e.EMAIL_SENDER["NO-REPLY"],
                          recipient = [user.email])

        return APIResponse({
            "data": {}
        })

    def post(self, request, code=None):
        if not code:
            raise exceptions.AuthenticationValidationError("")
        c = DefaultCache()
        v = c.get(code)
        if not v:
            raise exceptions.AuthenticationValidationError("")
        email = v.split("-")[0]
        user = self.get_object(email)
        user.update(status = UserStatus.EMAIL_CONFIRMED)
        token, _ = MultiToken.create_token(user)
        c.delete_key(code)
        return APIResponse({
            "data": {
                "accessToken": token.key,
                "user": {
                    "email": user.email,
                    "id": user.uid,
                    "nickname": user.nickname,
                    "permission": user.permission.value,
                    "image": "",
                    "status": user.status.value
                }
            }
        })


class SendEmailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    throttle_classes = (EmailVerificationThrottle,)
    model = User

    def get_object(self, email):
        try:
            return self.model.objects.get(email__iexact=email)
        except self.model.DoesNotExist:
            raise exceptions.AuthenticationValidationError("")

    def post(self, request, format=None):
        data = request.data
        try:
            email = data.get("email", None)
            type = data.get("type", None)
        except KeyError:
            raise exceptions.DataIntegrityError("")

        user = self.get_object(email)
        e = Email()
        c = DefaultCache()
        if type == "password_reset":
            link = c.set_password_reset_key(user.email)
            kv = {
                "nickname": user.nickname,
                "link": api_settings.WEB_URL + "/password-reset/" + link
            }
            SendEmail().delay(kv = kv,
                              subject = Constants.EMAIL_TITLE["PASSWORD_RESET"],
                              email_type = e.EMAIL_TYPE["PASSWORD_RESET"],
                              sender = e.EMAIL_SENDER["NO-REPLY"],
                              recipient = [user.email])

        if type == "email_verification":
            if user.status is not UserStatus.SIGNED_UP:
                raise exceptions.AuthenticationValidationError("")
            link = c.set_signup_verification_key(user.email)
            kv = {
                "nickname": user.nickname,
                "link": api_settings.WEB_URL + "/verify/" + link
            }
            SendEmail().delay(kv = kv,
                              subject = Constants.EMAIL_TITLE["VERIFICATION"],
                              email_type = e.EMAIL_TYPE["REGISTER"],
                              sender = e.EMAIL_SENDER["NO-REPLY"],
                              recipient = [user.email])

        return APIResponse({
            "data": {}
        })


class UserSignUpView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (permissions.IsPostOrIsAuthenticated,)
    throttle_classes = (SignUpThrottle,)
    model = User

    def get_object(self, email):
        try:
            return self.model.objects.get(email__iexact=email)
        except self.model.DoesNotExist:
            raise exceptions.UserNotFound()


    def post(self, request, pk=None):
        serializer = UserPostSerializer(data=request.data, context={"request": request, "payload": {}})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        user = self.get_object(serializer.validated_data["email"])
        token, _ = MultiToken.create_token(user)
        e = Email()
        c = DefaultCache()
        link = c.set_signup_verification_key(user.email)
        kv = {
            "nickname": user.nickname,
            "link": api_settings.WEB_URL + "/verify/" + link
        }
        SendEmail().delay(kv = kv,
                          subject = Constants.EMAIL_TITLE["VERIFICATION"],
                          email_type = e.EMAIL_TYPE["REGISTER"],
                          sender = e.EMAIL_SENDER["NO-REPLY"],
                          recipient = [user.email])

        return APIResponse({
            "data": {
                "accessToken": token.key,
                "user": {
                    "email": user.email,
                    "id": user.uid,
                    "nickname": user.nickname,
                    "permission": user.permission.value,
                    "image": "",
                    "status": user.status.value
                }
            }
        })


class UserDetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (permissions.IsPostOrIsAuthenticated,)
    model = User

    def get_object(self, pk):
        try:
            return self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            raise exceptions.UserNotFound()

    def get(self, request, pk=None):
        obj = self.get_object(pk)
        serializer = UserDetailSerializer(obj)
        data = serializer.data
        return APIResponse({
            "data": {
                "user": data
            }
        })

    def put(self, request, pk=None):
        obj = self.get_object(pk)
        serializer = UserPostSerializer(obj, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        user = serializer.data
        user["status"] = obj.status.value
        user["image"] = obj.image.url if bool(obj.image) else api_settings.S3_USER_IMAGE_DEFAULT
        return APIResponse({
            "data": {
                "accessToken": serializer.validated_data["token"],
                "user": user
            }
        })


class IcfView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated, permissions.APIKeyPermission,)
    model = Key

    def get_object(self, request):
        if request.user is None or request.auth is None:
            raise exceptions.AuthenticationCheckError()
        user = request.user
        obj = self.model.objects.filter(user = user.pk).order_by("-pk")
        if not obj.exists():
            raise exceptions.ICFNotFound()

        return obj[0]

    def get(self, request, pk=None):
        obj = self.get_object(request)
        serializer = ICFDetailSerializer(obj)
        data = serializer.data
        return APIResponse({
            "data": {
                "api": data
            }
        })

    def put(self, request, pk=None):
        obj = self.get_object(request)
        serializer = ICFPostSerializer(obj, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        data = serializer.data
        return APIResponse({
            "data": {
                "api": data
            }
        })

    def post(self, request, format=None):
        serializer = ICFPostSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        data = serializer.data
        return APIResponse({
            "data": {
                "api": data
            }
        })


class CommentView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)
    model = Comment

    def get(self, request, type=None, pk=None):
        if type is None or pk is None:
            raise exceptions.ValidationError("type or uid is not provided.")
        comment_objs = []

        if type == 'case':
            comment_objs = Comment.objects.filter(case = pk)
        elif type == 'indicator':
            comment_objs = Comment.objects.filter(indicator = pk)
        elif type == 'ico':
            comment_objs = Comment.objects.filter(ico = pk)
        else:
            raise exceptions.ValidationError("invalid type")
        if len(comment_objs) == 0:
            data = []
        else:
            serializer = CommentSerializer(comment_objs, context={"request": request}, many=True)
            data = serializer.data
        return APIResponse({
            "data": data
        })

    def post(self, request, type=None, pk=None, uid=None, format=None):
        if type is None or pk is None:
            raise exceptions.ValidationError("type or uid is not provided.")
        notification = request.data.pop("notification", [])
        serializer = CommentPostSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        data = serializer.data
        data["writer"] = {
            "nickname": request.user.nickname,
            "image": api_settings.S3_USER_IMAGE_DEFAULT if bool(request.user.image) is False else request.user.image.url,
            "uid": request.user.uid
        }
        u = None
        target = {}
        e = Email()
        if "case" in data:
            obj = Case.objects.get(id=data["case"])
            target["uid"] = str(obj.uid)
            target["title"] = obj.title
            target["type"] = "case"
            u = obj.reporter
        if "indicator" in data:
            obj = Indicator.objects.get(id=data["indicator"])
            target["uid"] = str(obj.uid)
            target["title"] = obj.pattern
            target["type"] = "indicator"
            u = obj.user
        if "ico" in data:
            obj = ICO.objects.get(id=data["ico"])
            target["uid"] = str(obj.uid)
            target["title"] = obj.name
            target["type"] = "ico"
            u = obj.user
        if u and u.email_notification:
            Notification.objects.create(
                user=u,
                initiator=request.user,
                type=NotificationType.COMMENT,
                target=target
            )
            kv = {
                "nickname": u.nickname,
                "link": api_settings.WEB_URL + '/' + target["type"] + '/' + str(obj.uid)
            }
            SendEmail().delay(kv = kv,
                  subject = Constants.EMAIL_TITLE["NOTIFICATION_COMMENT"].format(request.user.nickname),
                  email_type = e.EMAIL_TYPE["NOTIFICATION"],
                  sender = e.EMAIL_SENDER["NO-REPLY"],
                  recipient = [u.email])

        if notification:
            users = User.objects.filter(id__in=notification)
            for user in users:
                if not user.email_notification:
                    continue
                notification = Notification.objects.create(
                    user=user,
                    initiator=request.user,
                    type=NotificationType.COMMENT_MENTIONED,
                    target=target
                )
                kv = {
                    "nickname": user.nickname,
                    "link": api_settings.WEB_URL + '/' + target["type"] + '/' + str(obj.uid)
                }
                SendEmail().delay(kv = kv,
                    subject = Constants.EMAIL_TITLE["NOTIFICATION_COMMENT_MENTION"].format(request.user.nickname),
                    email_type = e.EMAIL_TYPE["NOTIFICATION"],
                    sender = e.EMAIL_SENDER["NO-REPLY"],
                    recipient = [user.email])

        return APIResponse({
            "data": data
        })

    def delete(self, request, type=None, pk=None, uid=None):
        if type is None or pk is None or uid is None:
            raise exceptions.ValidationError("type, pk or uid is not provided.")
        try:
            comment = self.model.objects.get(uid = uid)
        except Comment.DoesNotExist:
            raise exceptions.ValidatationError("comment does not exist")
        comment.deleted = True
        comment.save()
        return APIResponse({"data": {
            "id": comment.pk
        }})


class NotificationView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)
    model = Notification

    def delete(self, request, uid=None):
        if uid is None:
            notification = self.model.objects.filter(user=request.user)
        else:
            notification = self.model.objects.filter(user=request.user, uid=uid)

        if notification.exists():
            notification.delete()
        else:
            raise exceptions.ValidationError('nothing to delete')
        return APIResponse({
            "data": ""
        })

    def patch(self, request):
        self.model.objects.filter(user=request.user).exclude(read=True).update(read=True)
        return APIResponse({
            "data": ""
        })


class CATVView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_throttles(self):
        if self.request.method.lower() == 'post':
            return [CatvPostThrottle(), ]

    def post(self, request):
        serializer = CATVSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        tracking_cache = TrackingCache()
        cache_key = utils.create_tracking_cache_pattern(serializer.data)
        cached_entry = tracking_cache.get_cache_entry(cache_key)
        if not serializer.data.get('force_lookup', False) and cached_entry:
            results = json.loads(gzip.decompress(cached_entry).decode())
        else:
            results = serializer.get_tracking_results()
            tracking_cache.set_cache_entry(cache_key, gzip.compress(json.dumps(results).encode()), 86400)
        return APIResponse({
            "data": results
        })


class Metrics(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)

    def get(self, request, format=None):
        tz = request.query_params.get('timezone', None)
        rng = request.query_params.get('range', None)

        if not timezone or not rng:
            raise exceptions.ValidationError("timezone or type is not provided.")

        rng = int(rng)

        now_date = datetime.datetime.now(pytz.timezone(tz))
        start_date = now_date - datetime.timedelta(days=rng - 1)
        unaware_std = datetime.datetime.strptime(start_date.strftime('%Y-%m-%d') + ' 00:00:00', "%Y-%m-%d %H:%M:%S")
        aware_startdate = pytz.timezone(tz).localize(unaware_std)
        data_dict = {}
        for d in range(rng):
            key = (now_date - datetime.timedelta(days=d)).strftime('%Y-%m-%d')
            data_dict[key] = {
                'indicator': {
                    'count': 0,
                    'security_tags': {},
                    'pattern_type': {},
                    'pattern_subtype': {}
                },
                'case': {
                    'count': 0,
                }
            }

        c = DefaultCache()
        indicators = c.get('metrics_indicators')
        cases = c.get('metrics_cases')
        cached = True

        if not indicators or not cases:
            cached = False
            CacheMetricsTask().delay()
            cases = Case\
                .objects \
                .filter(created__gte=aware_startdate) \
                .annotate(created_date=TruncDate('created')) \
                .values('created', 'created_date') \
                .annotate(count=Count('id')) \
                .order_by('-created')

            indicators = Indicator.\
                objects\
                .filter(created__gte=aware_startdate)\
                .annotate(created_date=TruncDate('created'))\
                .values('created', 'created_date', 'security_tags', 'pattern_type', 'pattern_subtype')\
                .annotate(count=Count('id'))\
                .order_by('-created')

        for indicator in indicators:
            if cached:
                if indicator[0] < aware_startdate:
                    break
                created = indicator[0]
                security_tags = indicator[1]
                pattern_type = indicator[2]
                pattern_subtype = indicator[3]
            else:
                created = indicator['created']
                security_tags = indicator['security_tags']
                pattern_type = indicator['pattern_type'].value
                pattern_subtype = indicator['pattern_subtype'].value
            key = created.astimezone(pytz.timezone(tz)).strftime('%Y-%m-%d')
            indi = data_dict[key]['indicator']

            if cached:
                indi['count'] += 1
            else:
                indi['count'] += indicator['count']

            if security_tags:
                for tag in security_tags:
                    if tag in indi['security_tags']:
                        indi['security_tags'][tag] += 1
                    else:
                        indi['security_tags'][tag] = 1

            if pattern_type in indi['pattern_type']:
                indi['pattern_type'][pattern_type] += 1
            else:
                indi['pattern_type'][pattern_type] = 1

            if pattern_subtype in indi['pattern_subtype']:
                indi['pattern_subtype'][pattern_subtype] += 1
            else:
                indi['pattern_subtype'][pattern_subtype] = 1

        for case in cases:
            if cached:
                if case[0] < aware_startdate:
                    break
                created = case[0]
            else:
                created = case['created']
            key = created.astimezone(pytz.timezone(tz)).strftime('%Y-%m-%d')
            if not cached:
                data_dict[key]['case']['count'] += case['count']
            else:
                data_dict[key]['case']['count'] += 1

        return APIResponse({
            "data": data_dict
        })
