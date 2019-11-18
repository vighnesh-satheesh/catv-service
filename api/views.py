import gzip
import datetime
import pytz
import json
import math
from json import dumps

from django.conf import settings
from django_filters import rest_framework as filters
from django.db.models import Q, When, Value, Case as CaseFunc, IntegerField
from django.db import transaction, IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db import connection
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from social_django.utils import psa
from web3.auto.infura import w3
from kafka import KafkaProducer
from requests.exceptions import HTTPError

from .models import (
    User, Case, Indicator, CaseIndicator, ICO, CaseStatus, Key, Comment, CaseHistory,
    Notification, NotificationType,
    AttachedFile, UserPermission, UppwardRewardInfo,
    UserStatus,
    IndicatorPatternType, IndicatorPatternSubtype, IndicatorEnvironment, IndicatorVector, IndicatorSecurityCategory,
    RewardSetting, ProductType, Organization, OrganizationInvites, OrganizationInviteStatus, OrganizationUser)
from .serializers import (
    LoginSerializer, ChangePasswordSerializer,
    CaseListSerializer, CaseDetailSerializer, CasePatchSerializer, CasePostSerializer,
    AutoCompleteSerializer, AttachedFilePostSerializer,
    ICODetailSerializer, ICOListSerializer,
    IndicatorPostSerializer, IndicatorDetailSerializer, IndicatorListSerializer, IndicatorSimpleListSerializer,
    IndicatorLatestRecordSerializer,
    UppwardRewardInfoPostSerializer,
    UserDetailSerializer, UserPostSerializer,
    ICFDetailSerializer, ICFPostSerializer,
    CommentSerializer, CommentPostSerializer,
    NotificationSerializer, CATVSerializer,
    RewardSettingSerializer, OrganizationPostSerializer,
    OrganizationSimpleSerializer, OrganizationUserPostSerializer,
    InvitationSerializer, SocialSerializer
)
from .throttling import (
    SignUpThrottle, UserLoginThrottle, ChangePasswordThrottle,
    FileUploadThrottle, CasePostThrottle,
    EmailVerificationThrottle,
    IndicatorPostThrottle, CatvPostThrottle, CatvUsageExceededThrottle,
    CaraUsageExceededThrottle, CaraPostThrottle, GuestSearchThrottle)
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
from .tasks import CacheLeftPanelValuesTask, CatvHistoryTask, CacheNumberOfIndicatorsCases


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
        lpv = c.get(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        all_cases = []
        my_cases = []
        org_cases = []
        user_list = []
        org_admin = Organization.objects.filter(administrator=user).values_list('id', flat=True)
        member_orgs = OrganizationUser.objects.filter(user=user).values_list('organization_id', flat=True)
        if org_admin:
            user_list.extend(OrganizationUser.objects.filter(organization__in=org_admin).values_list('user_id',
                                                                                                     flat=True))
            user_list.extend([user.id, user.id])
        elif member_orgs:
            user_list.extend(Organization.objects.filter(pk__in=member_orgs).values_list('administrator',
                                                                                         flat=True))
            user_list.extend(OrganizationUser.objects.filter(organization__administrator__in=user_list).
                             values_list('user_id', flat=True))

        for item in CaseStatus:
            my_cases.append({
                "id": "case_my_{0}".format(item.value),
                "count": 0
            })
            all_cases.append({
                "id": "case_all_{0}".format(item.value),
                "count": 0
            })
            if user_list:
                org_cases.append({
                    "id": "case_org_{0}".format(item.value),
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
        if org_cases:
            cases.append({
                "id": "case_org",
                "count": 0,
                "children": org_cases
            })

        with connection.cursor() as cursor:
            cursor.execute(Constants.QUERIES['SELECT_LEFT_PANEL_VALUES_CASE_ALL'])
            all_cases = cursor.fetchall()
            cursor.execute(Constants.QUERIES['SELECT_LEFT_PANEL_VALUES_CASE_MY'].format(user.id))
            my_cases = cursor.fetchall()
            cases[0]["children"] = all_cases
            cases[1]["children"] = my_cases
            if org_cases:
                users = tuple(user_list)
                cursor.execute(Constants.QUERIES['SELECT_LEFT_PANEL_VALUES_CASE_ORG'].format(users))
                org_cases = cursor.fetchall()
                cases[2]["children"] = org_cases

        for case in cases:
            case["children"] = [{"id": case["id"] + "_" + c[0], "count": c[1]} for c in case["children"]]
            case["count"] = sum(map(lambda x: x["count"], case["children"]))

        if user.permission is UserPermission.EXCHANGE:
            cases[0]["children"] = [c for c in cases[0]["children"] if "confirmed" in c["id"] or "released" in c["id"]]
        elif user.permission is UserPermission.USER:
            cases = [cases[1]]

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
                    sql = Constants.QUERIES['SELECT_INDICATOR_COUNT']
                else:
                    sql = Constants.QUERIES['SELECT_CASE_INDICATOR_COUNT'] % ("'released'", "'confirmed'",)

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
            user = User.objects.get(uid=user_uid)
        except User.DoesNotExist:
            raise exceptions.CaseFilterError()

        if action not in ['reported', 'released']:
            raise exceptions.CaseFilterError()

        if action == 'reported':
            return queryset.filter(reporter=user.pk).distinct('id')
        elif action == 'released':
            return queryset.filter(verifier=user.pk).distinct('id')

        return queryset.distinct('id')

    def filter_case_board(self, queryset, name, value):
        case_cate = value.split("_")
        if len(case_cate) not in [1, 2]:
            raise exceptions.CaseFilterError()
        case_filter = Q()
        case_keyword_filter = Q()
        indicator_filter = Q()
        indicator_keyword_filter = Q()
        cate = case_cate[0]
        subcate = None
        if len(case_cate) == 2:
            subcate = case_cate[1]

        if cate not in ["all", "my", "org"]:
            raise exceptions.CaseFilterError()

        if subcate and subcate not in ["new", "progress", "confirmed", "rejected", "released"]:
            raise exceptions.CaseFilterError()

        if subcate is not None:
            case_filter &= Q(status=subcate)

        if cate == "all":
            if self.request.user.permission == UserPermission.EXCHANGE:
                case_filter &= (Q(status="released") | Q(status="confirmed"))
        elif cate == "my":
            case_filter &= (Q(owner=self.request.user.pk) | Q(reporter=self.request.user.pk))

        security_category = self.request.GET.getlist("security_category") or []
        pattern_subtype = self.request.GET.getlist("pattern_subtype") or []
        pattern_type = self.request.GET.getlist("pattern_type") or []
        keyword = self.request.GET.getlist("keyword") or []

        if len(security_category) > 0:
            indicator_filter &= Q(indicator__security_category__in=security_category)
        if len(pattern_type) > 0:
            indicator_filter &= Q(indicator__pattern_type__in=pattern_type)
        if len(pattern_subtype) > 0:
            indicator_filter &= Q(indicator__pattern_subtype__in=pattern_subtype)

        if len(keyword) > 0:
            keyword_pattern_type = []
            keyword_pattern_subtype = []
            keyword_vector = []
            keyword_environment = []
            for idx, k in enumerate(keyword):
                case_keyword_filter |= Q(title__ilike=k)
                case_keyword_filter |= Q(detail__ilike=k)
                indicator_keyword_filter |= Q(indicators__pattern__ilike=k)
                indicator_keyword_filter |= Q(indicators__annotation=k)
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
                    case_keyword_filter |= Q(id=k)

            if len(keyword_pattern_type) > 0:
                indicator_keyword_filter |= Q(indicator__pattern_type__in=keyword_pattern_type)
            if len(keyword_pattern_subtype) > 0:
                indicator_keyword_filter |= Q(indicator__pattern_subtype__in=keyword_pattern_subtype)
            if len(keyword_vector) > 0:
                indicator_keyword_filter |= Q(indicator__vector__contains=keyword_vector)
            if len(keyword_environment) > 0:
                indicator_keyword_filter |= Q(indicator__environment__contains=keyword_environment)

        if (indicator_filter or indicator_keyword_filter) and case_keyword_filter:
            return queryset.filter(case_filter & case_keyword_filter).union(queryset.filter(case_filter &
                                                                                            indicator_filter &
                                                                                            indicator_keyword_filter))
        elif indicator_filter or indicator_keyword_filter:
            return queryset.filter(case_filter & indicator_filter & indicator_keyword_filter)
        else:
            return queryset.filter(case_filter & case_keyword_filter)


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
        category = self.request.GET.get('case', 'all')
        order_by = order_by.split('_')
        key = ""
        if order_by[1] == "desc":
            key = "-"
        key = key + order_by[0]
        user_list = []
        current_user = self.request.user
        if 'org' in category:
            org_admin = Organization.objects.filter(administrator=current_user).values_list('id', flat=True)
            member_orgs = OrganizationUser.objects.filter(user=current_user).values_list('organization_id', flat=True)
            if org_admin:
                user_list.extend(OrganizationUser.objects.filter(organization__in=org_admin).values_list('user_id',
                                                                                                         flat=True))
                user_list.append(current_user.id)
            elif member_orgs:
                user_list.extend(Organization.objects.filter(pk__in=member_orgs).values_list('administrator',
                                                                                             flat=True))
                user_list.extend(OrganizationUser.objects.filter(organization__administrator__in=user_list).
                                 values_list('user_id', flat=True))

            if user_list:
                return self.model.objects.filter(Q(owner__in=user_list) | Q(reporter__in=user_list)).\
                    distinct('id').order_by(key)
            else:
                return self.model.objects.none()

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

        CaseHistory.objects.create(
            case=case,
            log=json.dumps(history_log),
            initiator=case.reporter if case.reporter is not None else None
        )

        c = DefaultCache()
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])

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

    def get_permission(self, request, obj, status, pk=None):
        user_permission = getattr(request.user, 'permission', None)
        is_super = True if user_permission == UserPermission.SUPERSENTINEL else False
        is_owner = True if request.user == obj.owner else False

        permission_data = {}

        if user_permission == UserPermission.SUPERSENTINEL and obj.status in [CaseStatus.NEW, CaseStatus.PROGRESS]:
            permission_data['editable'] = True
            permission_data['deletable'] = True

        if obj.owner == request.user and status == CaseStatus.PROGRESS:
            permission_data['editable'] = True
            permission_data['deletable'] = True

        if obj.reporter == request.user and status == CaseStatus.NEW:
            permission_data['editable'] = True
            permission_data['deletable'] = True

        if 'editable' not in permission_data:
            permission_data['editable'] = False

        if 'deletable' not in permission_data:
            permission_data['deletable'] = False

        next_status = utils.CASE_STATUS_FSM.next(status, is_super, is_owner, user_permission)
        permission_data["status"] = [e.value for e in next_status]
        return permission_data

    def get(self, request, pk=None):
        obj = self.get_object(pk, request)
        serializer = CaseDetailSerializer(obj, context={'request': request})
        data = serializer.data

        user_permission = getattr(request.user, 'permission', None)
        is_super = True if user_permission == UserPermission.SUPERSENTINEL else False
        is_owner = True if request.user == obj.owner else False

        permission_data = self.get_permission(request, obj, obj.status)

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
            SendEmail().delay(kv=kv,
                              subject=Constants.EMAIL_TITLE["NOTIFICATION_MODIFY_CASE"].format(request.user.nickname),
                              email_type=e.EMAIL_TYPE["NOTIFICATION"],
                              sender=e.EMAIL_SENDER["NO-REPLY"],
                              recipient=[obj.reporter.email])

        return APIResponse({
            "data": {}})

    def patch(self, request, pk=None):
        obj = self.get_object(pk, request)
        serializer = CasePatchSerializer(obj, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        c = DefaultCache()
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])
        c.delete_view_cache(request)

        permission_data = self.get_permission(request, obj, CaseStatus(request.data['status']))

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
            SendEmail().delay(kv=kv,
                              subject=Constants.EMAIL_TITLE["NOTIFICATION_PATCH_CASE"].format(request.user.nickname,
                                                                                              obj.status.value),
                              email_type=e.EMAIL_TYPE["NOTIFICATION"],
                              sender=e.EMAIL_SENDER["NO-REPLY"],
                              recipient=[obj.reporter.email])

        return APIResponse({"data": {
            'case_permission': permission_data
        }})

    def delete(self, request, pk=None):
        try:
            with transaction.atomic():
                obj = self.get_object(pk, request)

                if obj.status in [CaseStatus.CONFIRMED, CaseStatus.RELEASED]:
                    raise exceptions.ValidationError("case cannot be deleted.")

                if (request.user.permission not in [UserPermission.SENTINEL, UserPermission.SUPERSENTINEL]) and \
                        (obj.status == CaseStatus.NEW and obj.reporter != request.user or \
                         (obj.status in [CaseStatus.PROGRESS, CaseStatus.REJECTED] and obj.owner != request.user)):
                    raise exceptions.OwnerRequiredError()

                CaseIndicator.objects.filter(case=obj).delete()

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
            SendEmail().delay(kv=kv,
                              subject=Constants.EMAIL_TITLE["NOTIFICATION_DELETE_CASE"].format(request.user.nickname),
                              email_type=e.EMAIL_TYPE["NOTIFICATION"],
                              sender=e.EMAIL_SENDER["NO-REPLY"],
                              recipient=[obj.reporter.email])
        obj.delete()

        c = DefaultCache()
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])
        c.delete_view_cache(request)
        return APIResponse({"data": {}})


class IndicatorView(generics.ListCreateAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    model = Indicator

    def get_throttles(self):
        ret = []
        if self.request.method.lower() == 'get':
            return ret
        elif self.request.method.lower() == 'post':
            return [IndicatorPostThrottle(), ]
        else:
            return super(IndicatorView, self).get_throttles()

    def get_filter(self):
        ftr = Q()
        keyword_filter = Q()

        if self.request.user.permission is not UserPermission.SUPERSENTINEL and \
                self.request.user.permission is not UserPermission.SENTINEL:
            ftr &= Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED])

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
                keyword_filter |= Q(pattern__ilike=k)
                keyword_filter |= Q(detail__icontains=k)
                keyword_filter |= Q(annotation=k)
                if k.isdigit():
                    keyword_filter |= Q(id=k)
            ftr &= keyword_filter

        if len(status) > 0:
            ftr &= Q(cases__status__in=status)

        return ftr

    def list(self, request, *args, **kwargs):
        order_by = self.request.GET.get('order_by', 'id_desc')
        page = self.request.GET.get('page', 1)
        total_items = int(self.request.GET.get('total_items', 0))
        permission = self.request.user.permission
        order_by = order_by.split('_')
        key = ''
        if order_by[1] == 'desc':
            key = '-'
        key = key + order_by[0]
        page = int(page)
        page_size = 25
        ftr = self.get_filter()

        indicators = self.model.objects.filter(ftr).distinct('id').order_by(key)[
                     page_size * (page - 1):page_size * page]
        serializer = IndicatorListSerializer(indicators, many=True)

        if len(ftr) == 0 and total_items == 0:
            c = DefaultCache()
            d = c.get(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])
            if d:
                if permission in [UserPermission.SENTINEL, UserPermission.SUPERSENTINEL]:
                    total_items = d['all']
                else:
                    total_items = d['cr']

        if total_items == 0:
            total_items = self.model.objects.filter(ftr).distinct('id').count()
            CacheNumberOfIndicatorsCases().delay()

        return APIResponse({
            "data": {
                "indicators": serializer.data,
                "totalItems": total_items,
                "totalPages": math.ceil(total_items / page_size),
                "pageIndex": page
            }
        })

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
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])

        return APIResponse({
            "data": result_serializer.data
        })


class IndicatorDetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    model = Indicator

    def get_object(self, pk=None, pattern=None):
        if not pk and not pattern:
            raise exceptions.IndicatorNotFound()
        if pk:
            try:
                indicator = self.model.objects.get(uid=pk)
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
        serializer = IndicatorDetailSerializer(obj,
                                               is_authenticated=True if request.user and request.user.is_authenticated else False)
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

                if (request.user.permission not in [UserPermission.SENTINEL, UserPermission.SUPERSENTINEL]) and \
                        indicator.user != request.user:
                    raise exceptions.NotAllowedError()

                CaseIndicator.objects.filter(indicator=indicator).delete()
                indicator.delete()
        except Indicator.DoesNotExist:
            raise exceptions.ValidationError("indicator does not exist")
        except IntegrityError:
            raise exceptions.DataIntegrityError("")
        c = DefaultCache()
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])
        c.delete_view_cache(request)
        return APIResponse({"data": {}})


class GuestSearchView(generics.ListAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    throttle_classes = (GuestSearchThrottle,)

    @method_decorator(cache_page(60 * 5))
    def dispatch(self, *args, **kwargs):
        return super(GuestSearchView, self).dispatch(*args, **kwargs)

    def list(self, request, *args, **kwargs):
        query = self.request.query_params.get("q", None)
        if query is None:
            raise exceptions.ValidationError("Search query is required.")

        if len(query) > 1024:
            raise exceptions.ValidationError("Search query cannot exceed 1024 characters.")

        if len(query) < 3:
            raise exceptions.ValidationError("Search query should contain at least 3 characters.")

        serializer_cls = IndicatorListSerializer
        queryset = self.get_queryset()
        serializer = serializer_cls(queryset, many=True)

        return APIResponse({
            "data": {
                "items": serializer.data
            }
        })

    def get_indicator_queryset(self, query):
        filter_queries = Q(pattern__ilike=query)
        filter_queries &= Q(security_category__in=[IndicatorSecurityCategory.BLACKLIST,
                                                   IndicatorSecurityCategory.WHITELIST])
        filter_queries &= Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED])

        objs = Indicator.objects.filter(filter_queries).distinct('id').order_by('-pk')[:20]

        return objs

    def get_queryset(self):
        query = self.request.query_params.get("q", None)
        return self.get_indicator_queryset(query)


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
        filter_queries = Q(pattern__ilike=query)
        filter_queries |= Q(security_tags__arrayilike=query)

        try:
            IndicatorPatternSubtype(query.lower())
            filter_queries |= Q(pattern_subtype=query.lower())
        except ValueError:
            pass

        if not self.request.auth:
            filter_queries &= Q(case__status=CaseStatus.RELEASED)
        elif self.request.auth and self.request.user.permission is UserPermission.EXCHANGE:
            filter_queries &= Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | Q(
                user=self.request.user.pk)

        objs = Indicator.objects \
            .filter(filter_queries) \
            .distinct('id') \
            .order_by('-pk')

        return objs

    def get_case_queryset(self, query):
        if not self.request.auth:
            raise exceptions.AuthenticationCheckError()

        case_filter_queries = Q(id=0)
        indicator_filter_queries = Q(id=0)
        if query.isdigit():
            case_filter_queries = Q(id=int(query))
            indicator_filter_queries = Q(id=int(query))
        if len(query) > 1 and case_filter_queries is None:
            case_filter_queries |= Q(title__ilike=query)
        elif len(query) > 1 and case_filter_queries is not None:
            case_filter_queries |= Q(title__ilike=query)

        if len(query) > 1:
            indicator_filter_queries = Q(indicator__pattern__ilike=query)
            indicator_filter_queries |= Q(indicator__pattern_subtype__ilike=query)

        if self.request.user.permission is UserPermission.EXCHANGE:
            case_filter_queries &= Q(status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | \
                                   Q(reporter=self.request.user.pk)
            indicator_filter_queries &= Q(status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | \
                                        Q(reporter=self.request.user.pk)

        case_indicator_results = Case.objects.filter(indicator_filter_queries).annotate(
            match=CaseFunc(
                When(pk=query, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            ) if query.isdigit() else Value(0, IntegerField())
        ).distinct('id')
        case_results = Case.objects.filter(case_filter_queries).annotate(
            match=CaseFunc(
                When(pk=query, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            ) if query.isdigit() else Value(0, IntegerField())
        ).distinct('id')

        objs = case_indicator_results.union(case_results).order_by('-match', '-pk')

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
        try:
            email = request.data["email"]
        except KeyError:
            raise exceptions.DataIntegrityError("")
        user = self.get_object(email)
        e = Email()
        c = DefaultCache()
        link = c.set_signup_verification_key(user.email)
        kv = {
            "nickname": user.nickname,
            "link": api_settings.WEB_URL + "/verify/" + link
        }
        SendEmail().delay(kv=kv,
                          subject=Constants.EMAIL_TITLE["VERIFICATION"],
                          email_type=e.EMAIL_TYPE["REGISTER"],
                          sender=e.EMAIL_SENDER["NO-REPLY"],
                          recipient=[user.email])

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
        email = "-".join(v.split("-")[:-1])
        user = self.get_object(email)
        user.update(status=UserStatus.EMAIL_CONFIRMED)
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
            SendEmail().delay(kv=kv,
                              subject=Constants.EMAIL_TITLE["PASSWORD_RESET"],
                              email_type=e.EMAIL_TYPE["PASSWORD_RESET"],
                              sender=e.EMAIL_SENDER["NO-REPLY"],
                              recipient=[user.email])

        if type == "email_verification":
            if user.status is not UserStatus.SIGNED_UP:
                raise exceptions.AuthenticationValidationError("")
            link = c.set_signup_verification_key(user.email)
            kv = {
                "nickname": user.nickname,
                "link": api_settings.WEB_URL + "/verify/" + link
            }
            SendEmail().delay(kv=kv,
                              subject=Constants.EMAIL_TITLE["VERIFICATION"],
                              email_type=e.EMAIL_TYPE["REGISTER"],
                              sender=e.EMAIL_SENDER["NO-REPLY"],
                              recipient=[user.email])

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
        SendEmail().delay(kv=kv,
                          subject=Constants.EMAIL_TITLE["VERIFICATION"],
                          email_type=e.EMAIL_TYPE["REGISTER"],
                          sender=e.EMAIL_SENDER["NO-REPLY"],
                          recipient=[user.email])

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
        reward_setting = RewardSetting.objects.filter(id=1).values()
        address_c = w3.toChecksumAddress(reward_setting[0].get('token_address'))
        token_abi = json.loads(reward_setting[0].get('token_abi'))
        token = w3.eth.contract(address_c, abi=token_abi)
        user_waddress = user['address']
        bal = token.call().balanceOf(user_waddress) if user_waddress else 0
        user["balance"] = bal
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
        obj = self.model.objects.filter(user=user.pk).order_by("-pk")
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
            comment_objs = Comment.objects.filter(case=pk)
        elif type == 'indicator':
            comment_objs = Comment.objects.filter(indicator=pk)
        elif type == 'ico':
            comment_objs = Comment.objects.filter(ico=pk)
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
            "image": api_settings.S3_USER_IMAGE_DEFAULT if bool(
                request.user.image) is False else request.user.image.url,
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
            SendEmail().delay(kv=kv,
                              subject=Constants.EMAIL_TITLE["NOTIFICATION_COMMENT"].format(request.user.nickname),
                              email_type=e.EMAIL_TYPE["NOTIFICATION"],
                              sender=e.EMAIL_SENDER["NO-REPLY"],
                              recipient=[u.email])

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
                SendEmail().delay(kv=kv,
                                  subject=Constants.EMAIL_TITLE["NOTIFICATION_COMMENT_MENTION"].format(
                                      request.user.nickname),
                                  email_type=e.EMAIL_TYPE["NOTIFICATION"],
                                  sender=e.EMAIL_SENDER["NO-REPLY"],
                                  recipient=[user.email])

        return APIResponse({
            "data": data
        })

    def delete(self, request, type=None, pk=None, uid=None):
        if type is None or pk is None or uid is None:
            raise exceptions.ValidationError("type, pk or uid is not provided.")
        try:
            comment = self.model.objects.get(uid=uid)
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
            return [CatvUsageExceededThrottle(), CatvPostThrottle(), ]

    def post(self, request):
        serializer = CATVSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        tracking_cache = TrackingCache()
        cache_key = utils.create_tracking_cache_pattern(serializer.data)
        cached_entry = tracking_cache.get_cache_entry(cache_key)
        history = serializer.data
        history.update({'user_id': request.user.id})
        if not serializer.data.get('force_lookup', False) and cached_entry:
            results = json.loads(gzip.decompress(cached_entry).decode())
            CatvHistoryTask().delay(history=history, from_history=True)
        else:
            results, api_calls = serializer.get_tracking_results()
            from_db = (api_calls == 0)
            tracking_cache.set_cache_entry(cache_key, gzip.compress(json.dumps(results).encode()), 86400)
            CatvHistoryTask().delay(history=history, from_history=from_db)
        return APIResponse({
            "data": results
        })


class Metrics(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None):
        tz = request.query_params.get('timezone', None)
        rng = request.query_params.get('range', None)
        user_permission = getattr(request.user, 'permission', None)

        if not timezone or not rng:
            raise exceptions.ValidationError("timezone or type is not provided.")

        rng = int(rng)

        now_date = datetime.datetime.now(pytz.timezone(tz))
        start_date = now_date - datetime.timedelta(days=rng - 1)
        unaware_std = datetime.datetime.strptime(start_date.strftime('%Y-%m-%d') + ' 00:00:00', "%Y-%m-%d %H:%M:%S")
        aware_startdate = pytz.timezone(tz).localize(unaware_std)
        offset = str(now_date.utcoffset())
        date_dict = {}
        for d in range(rng):
            key = (now_date - datetime.timedelta(days=d)).strftime('%Y-%m-%d')
            date_dict[key] = {
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

        indicator_cache_key = Constants.CACHE_KEY['METRICS_INDICATOR'].format(str(rng), offset)
        case_cache_key = Constants.CACHE_KEY['METRICS_CASE'].format(str(rng), offset)

        if user_permission in [UserPermission.SUPERSENTINEL, UserPermission.SENTINEL]:
            latest_indicator_cache_key = Constants.CACHE_KEY['METRICS_LATEST_INDICATORS'].format('sentinel')
        else:
            latest_indicator_cache_key = Constants.CACHE_KEY['METRICS_LATEST_INDICATORS'].format('non-sentinel')

        c = DefaultCache()
        indicators = c.get(indicator_cache_key)
        cases = c.get(case_cache_key)
        latest_indicators = c.get(latest_indicator_cache_key)
        cached = True if (indicators != None and cases != None) else False

        if not cached:
            case_row_query = Constants.QUERIES['SELECT_METRICS_CASE'].format(tz, aware_startdate.strftime('%Y-%m-%d'))
            indicator_row_query = Constants.QUERIES['SELECT_METRICS_INDICATOR'].format(tz, aware_startdate.strftime(
                '%Y-%m-%d'))

            with connection.cursor() as cursor:
                cursor.execute(case_row_query)
                cases = cursor.fetchall()
                cursor.execute(indicator_row_query)
                indicators = cursor.fetchall()
                c.set(case_cache_key, cases, 60 * 10)
                c.set(indicator_cache_key, indicators, 60 * 10)

        for case in cases:
            key = case[1].strftime('%Y-%m-%d')
            date_dict[key]['case']['count'] += case[0]

        for indicator in indicators:
            count = indicator[0]
            date = indicator[1].strftime('%Y-%m-%d')
            pattern_type = indicator[2]
            pattern_subtype = indicator[3]
            security_tags = indicator[4]

            date_dict[date]['indicator']['count'] += count

            if pattern_type in date_dict[date]['indicator']['pattern_type']:
                date_dict[date]['indicator']['pattern_type'][pattern_type] += count
            else:
                date_dict[date]['indicator']['pattern_type'][pattern_type] = count

            if pattern_subtype in date_dict[date]['indicator']['pattern_subtype']:
                date_dict[date]['indicator']['pattern_subtype'][pattern_subtype] += count
            else:
                date_dict[date]['indicator']['pattern_subtype'][pattern_subtype] = count

            if security_tags is not None:
                for tag in security_tags:
                    if tag in date_dict[date]['indicator']['security_tags']:
                        date_dict[date]['indicator']['security_tags'][tag] += count
                    else:
                        date_dict[date]['indicator']['security_tags'][tag] = count

        if not latest_indicators:
            filters = Q()
            if user_permission not in [UserPermission.SUPERSENTINEL, UserPermission.SENTINEL]:
                filters &= Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED])
            indicators = Indicator.objects.filter(filters).order_by('-id')[:100]
            indicators_serializer = IndicatorLatestRecordSerializer(indicators, many=True)
            latest_indicators = indicators_serializer.data
            c.set(latest_indicator_cache_key, latest_indicators, 60 * 10)

        return APIResponse({
            "data": {
                "dates": date_dict,
                "indicators": latest_indicators
            }
        })


class ValidateAddress(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)
    model = RewardSetting

    def get(self, request, pk=None, pattern=None):

        settings_obj = self.model.objects.filter(id=1)
        serializer = RewardSettingSerializer(settings_obj, context={"request": request}, many=True)
        data = serializer.data
        token_address = data[0].get('token_address')
        abi = data[0].get('token_abi')
        token_abi = json.loads(abi)
        token = w3.eth.contract(token_address, abi=token_abi)
        bal = token.call().balanceOf(self.request.GET.get('address'))
        if (bal > (data[0].get('min_token') * 1000000000000000000)):
            return APIResponse({
                "data": "success"
            })
        else:
            return APIResponse({
                "data": "fail"
            })


class CARA(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_throttles(self):
        return [CaraUsageExceededThrottle(), CaraPostThrottle(), ]

    def get(self, request):
        kafka_broker_1 = settings.KAFKA_BROKER_1
        kafka_broker_2 = settings.KAFKA_BROKER_2
        kafka_broker_3 = settings.KAFKA_BROKER_3
        producer = KafkaProducer(bootstrap_servers=[kafka_broker_1, kafka_broker_2, kafka_broker_3],
                                 value_serializer=lambda x:
                                 dumps(x).encode('utf-8'))
        address = self.request.GET.get('address')
        user = self.request.GET.get('user')
        force = self.request.GET.get('force')
        if force :
            cara_history_delete_query = Constants.QUERIES['DELETE_ADDRESS_FROM_HISTORY'].format(address, user)
            with connection.cursor() as cursor:
                cursor.execute(cara_history_delete_query)
        cara_history_insert_query = Constants.QUERIES['INSERT_CARA_HISTORY']
        time = datetime.datetime.now(datetime.timezone.utc)
        data = (user, address, time)
        with connection.cursor() as cursor:
            cursor.execute(cara_history_insert_query, data)
        data = {'address': address,
                'time': time.strftime("%Y-%m-%d %H:%M:%S")}
        print(producer.send(settings.KAFKA_USER_TOPIC, data))
        producer.flush()
        producer.close()
        query_list = Constants.QUERIES['UPDATE_USER_CARA_USAGE'].format(request.user.id)
        with connection.cursor() as cursor:
            cursor.execute(query_list)
        return APIResponse(data)


class CARAHistory(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        user = self.request.GET.get('user')
        history_query = Constants.QUERIES['CARA_HISTORY_USER'].format(user)
        error_count_query = Constants.QUERIES['CARA_ERROR_COUNT'].format(user)
        with connection.cursor() as cursor:
            cursor.execute(history_query)
            history = cursor.fetchall()
            cursor.execute(error_count_query)
            address = cursor.fetchall()
            update_error_query = Constants.QUERIES['UPDATE_CARA_ERROR_USAGE'].format(request.user.id)

            for x in address:
                cursor.execute(update_error_query)
                update_error_report_query = Constants.QUERIES['UPDATE_ERROR_REPORT'].format(0, user, x[0])
                cursor.execute(update_error_report_query)
        search = [x[0] for x in history]
        time = [x[1] for x in history]
        reports = []
        errors = []
        for add, t in zip(search, time):
            report_query = Constants.QUERIES['CARA_REPORT_ADDRESS_GENERATED'].format(add, t)
            with connection.cursor() as new_cursor:
                new_cursor.execute(report_query)
                add_report = new_cursor.fetchmany(1)
                if add_report is not None:
                    report = [x[0] for x in add_report]
                    error = [x[1] for x in add_report]
                    reports.extend(list(report))
                    errors.extend(list(error))
        data = {'history': search,
                'time': time,
                'reports': reports,
                'errors': errors}
        return APIResponse(data)


#class for generating report
class CARAReport(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        address = self.request.GET.get('address')
        report_query = Constants.QUERIES['CARA_REPORT_QUERY'].format(address)
        with connection.cursor() as cursor:
            cursor.execute(report_query)
            report = cursor.fetchone()
            if report is not None:
                data = {'report': report}
            else:
                data = {'report': ""}
        return APIResponse(data)


class UsageStatsView(APIView):
    authentication_classes = (CachedTokenAuthentication, )
    permission_classes = (IsAuthenticated, )
    model = User

    def get_user(self, pk):
        try:
            return self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            raise exceptions.UserNotFound()

    def get(self, request, pk=None):
        tz = request.query_params.get('timezone', None)
        date_range = request.query_params.get('range', None)
        product = request.query_params.get('product', None)

        if not all([tz, date_range, product]):
            raise exceptions.ValidationError("Atleast one parameter is missing out of timezone, range or product")

        user = self.get_user(pk)
        date_range = int(date_range) - 1

        with connection.cursor() as cursor:
            cursor.execute(Constants.QUERIES['SELECT_CREDIT_DETAILS'].format(tz, user.id))
            col_desc = [desc[0] for desc in cursor.description]
            credit_details = cursor.fetchall()
            if product == ProductType.CATV.value:
                cursor.execute(Constants.QUERIES['SELECT_CATV_USAGE_OVERXDAYS'].format(tz, date_range, user.id))
            elif product == ProductType.CARA.value:
                cursor.execute(Constants.QUERIES['SELECT_CARA_USAGE_OVERXDAYS'].format(tz, date_range, user.id))
            elif product == ProductType.ICF.value:
                cursor.execute(Constants.QUERIES['SELECT_ICF_USAGE_OVERXDAYS'].format(tz, date_range, user.id))
            results = cursor.fetchall()

        credit_details = dict(zip(col_desc, credit_details[0]))

        return APIResponse({
            "data": {
                "usage_details": results,
                "credit_details": credit_details
            }
        })


class OrganizationDetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_object(self, uid):
        try:
            return Organization.objects.get(uid=uid)
        except Organization.DoesNotExist:
            raise exceptions.OrganizationNotFound()

    def get(self, request, uid):
        organization = self.get_object(uid)
        serializer = OrganizationSimpleSerializer(organization)
        return APIResponse({
            "data": serializer.data
        })

    def post(self, request, format=None):
        serializer = OrganizationPostSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            org = serializer.save()
            return APIResponse({
                "data": {
                    "uid": org.uid
                }
            })
        raise exceptions.ValidationError()

    def put(self, request, uid):
        try:
            organization = self.get_object(uid)
            modified_data = request.data.copy()
            users = modified_data.get("users", "[]")
            users = json.loads(users)
            modified_data.setlist("users", users)
            domains = modified_data.get('domains', "[]")
            domains = json.loads(domains)
            modified_data.setlist("domains", domains)
            orguser_serializer = OrganizationUserPostSerializer(data=users, many=True, context={"request": request})
            orguser_serializer.is_valid(raise_exception=True)
            orguser_serializer.save()
            serializer = OrganizationPostSerializer(organization, data=modified_data, context={"request": request})
            if serializer.is_valid():
                serializer.save()
                return APIResponse({
                    "data": serializer.data
                })
            raise exceptions.ValidationError()
        except json.decoder.JSONDecodeError:
            raise exceptions.ValidationError("Error parsing JSON user list or domains")

    def delete(self, request, uid=None):
        organization = self.get_object(uid)
        current_user = request.user
        try:
            org_user = OrganizationUser.objects.get(organization=organization, user=current_user)
            org_user.delete()
            Notification.objects.filter(user=current_user, initiator=organization.administrator).delete()
            return APIResponse({
                "data": "Succesfully deleted"
            })
        except OrganizationUser.DoesNotExist:
            raise exceptions.ValidationError("You are not a member of this organization")


class InvitationView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (permissions.IsGetOrIsAuthenticated,)

    def get_object(self, uid):
        try:
            org = Organization.objects.get(uid=uid)
            return org
        except Organization.DoesNotExist:
            raise exceptions.ValidationError("Organization does not exist")

    def get(self, request):
        referrer = request.GET.get("user", None)
        referral_code = request.GET.get("code", None)
        msg = "Invitation code is invalid"
        try:
            if not referral_code or not referrer:
                raise exceptions.PasswordResetCodeNotValid(msg)
            org_invite = OrganizationInvites.objects.get(invite_hash=referral_code)
            referrer_email, referred_email = org_invite.inviter_key.split('-invite-')
            user = User.objects.get(uid=referrer)
            if user.email != referrer_email:
                raise exceptions.PasswordResetCodeNotValid(msg)
            organization = org_invite.organization
            return APIResponse({
                "data": {
                    "referrer_org": organization.uid,
                    "invited_email": referred_email
                }
            })
        except (User.DoesNotExist, Organization.DoesNotExist, OrganizationInvites.DoesNotExist):
            raise exceptions.PasswordResetCodeNotValid(msg)

    def post(self, request, format=None):
        org = self.get_object(request.data.get("organization", None))
        serializer = InvitationSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        invited_email = serializer.data['email']
        invitee_email = request.user.email
        invite_hash = utils.generate_random_key(40)
        inviter_key = invitee_email + '-invite-' + invited_email
        e = Email()
        kv = {
            "nickname": request.user.nickname,
            "email": request.user.email,
            "link": api_settings.WEB_URL + '/signup?' + "user=" + str(request.user.uid) + "&code=" + invite_hash,
            "org_name": org.name
        }
        SendEmail().delay(kv=kv,
                          subject=Constants.EMAIL_TITLE["INVITATION_SENTINEL_PORTAL"],
                          email_type=e.EMAIL_TYPE["INVITATION"],
                          sender=e.EMAIL_SENDER["NO-REPLY"],
                          recipient=[serializer.data['email']])
        OrganizationInvites.objects.create(organization=org, user=org.administrator, email=invited_email,
                                           invite_hash=invite_hash, inviter_key=inviter_key,
                                           status=OrganizationInviteStatus.EMAIL_SENT
                                           )
        org.save()
        return APIResponse({
            "data": "Successfully invited"
        })


@api_view(http_method_names=['POST'])
@authentication_classes([CachedTokenAuthentication])
@permission_classes([AllowAny])
@psa()
def exchange_oauth_api_token(request, backend):
    serializer = SocialSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        user = request.backend.do_auth(serializer.validated_data['access_token'])
    except HTTPError:
        raise exceptions.AuthenticationValidationError("Invalid access token provided.")
    if user:
        login_serializer = LoginSerializer(data={'email': user.email, 'password': ''}, context={"request": request})
        login_data = login_serializer.generate_oauth_login_response(user)
        return APIResponse({
            "data": login_data
        })
    else:
        raise exceptions.AuthenticationValidationError()
