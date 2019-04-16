from collections import defaultdict

from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import JSONRenderer

from django_filters import rest_framework as filters
from django.db.models import Q, Count
from django.db import transaction, IntegrityError

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from .models import (
    User, Case, Indicator, CaseIndicator, ICO, CaseStatus, Key, Comment,
    Notification, NotificationType,
    AttachedFile, UserPermission, UppwardRewardInfo,
    UserStatus,
    IndicatorPatternType, IndicatorPatternSubtype, IndicatorEnvironment, IndicatorVector, IndicatorSecurityCategory,
)
from .serializers import (
    LoginSerializer, ChangePasswordSerializer,
    CaseListSerializer, CaseDetailSerializer, CasePatchSerializer, CasePostSerializer,
    AutoCompleteSerializer, AttachedFilePostSerializer,
    ICODetailSerializer, ICOListSerializer,
    IndicatorPostSerializer, IndicatorDetailSerializer, IndicatorListSerializer, IndicatorSimpleListSerializer,
    UppwardRewardInfoPostSerializer,
    UserDetailSerializer, UserPostSerializer,
    ICFDetailSerializer, ICFPostSerializer,
    CommentSerializer, CommentPostSerializer,
    NotificationSerializer
)
from .throttling import (
    SignUpThrottle, UserLoginThrottle, ChangePasswordThrottle,
    FileUploadThrottle, CasePostThrottle,
    EmailVerificationThrottle,
    IndicatorPostThrottle
)
from .response import APIResponse, FileResponse, FileRenderer
from .pagination import CustomPagination
from . import exceptions
from . import permissions
from . import utils
from .multitoken.tokens_auth import CachedTokenAuthentication, MultiToken
from .settings import api_settings
from .cache import DefaultCache
from .email import Email
from .email.tasks import SendEmail
from .constants import Constants


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
        count_dict = defaultdict(int)
        number_of_all_cases = 0
        number_of_all_my_cases = 0
        number_of_all_indicators = 0
        all_cases = []
        my_cases = []

        my_cases = Case.objects.filter(Q(owner=user.pk) | Q(reporter=user.pk)).values("status").annotate(count=Count("status"))

        if user.permission in [UserPermission.SUPERSENTINEL, user.permission is UserPermission.SENTINEL]:
            all_cases = Case.objects.filter().values("status").annotate(count=Count("status"))

        if user.permission is UserPermission.EXCHANGE:
            all_cases = Case.objects.filter(Q(status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED])).values("status").annotate(count=Count("status"))

        for item in CaseStatus:
            all = 0
            my = 0

            for ac in all_cases:
                if ac["status"] == item:
                    all = ac["count"]
                    break
            for mc in my_cases:
                if mc["status"] == item:
                    my = mc["count"]
                    break

            count_dict["case_all_{0}".format(item.value)] = all
            count_dict["case_my_{0}".format(item.value)] = my

            number_of_all_cases += all
            number_of_all_my_cases += my


        if user.permission in [UserPermission.SUPERSENTINEL, UserPermission.SENTINEL]:
            cases = [
                {
                    "id": "case_my",
                    "count": number_of_all_my_cases,
                    "children": [
                        utils.get_dashboard_item("case_my", "new", count_dict),
                        utils.get_dashboard_item("case_my", "progress", count_dict),
                        utils.get_dashboard_item("case_my", "confirmed", count_dict),
                        utils.get_dashboard_item("case_my", "rejected", count_dict),
                        utils.get_dashboard_item("case_my", "released", count_dict),
                    ]
                },
                {
                    "id": "case_all",
                    "count": number_of_all_cases,
                    "children": [
                        utils.get_dashboard_item("case_all", "new", count_dict),
                        utils.get_dashboard_item("case_all", "progress", count_dict),
                        utils.get_dashboard_item("case_all", "confirmed", count_dict),
                        utils.get_dashboard_item("case_all", "rejected", count_dict),
                        utils.get_dashboard_item("case_all", "released", count_dict),
                    ]
                }
            ]
        elif user.permission is UserPermission.EXCHANGE:
            cases = [
                {
                    "id": "case_my",
                    "count": number_of_all_my_cases,
                    "children": [
                        utils.get_dashboard_item("case_my", "new", count_dict),
                        utils.get_dashboard_item("case_my", "progress", count_dict),
                        utils.get_dashboard_item("case_my", "confirmed", count_dict),
                        utils.get_dashboard_item("case_my", "rejected", count_dict),
                        utils.get_dashboard_item("case_my", "released", count_dict),
                    ]
                },
                {
                    "id": "case_all",
                    "count": number_of_all_cases,
                    "children": [
                        utils.get_dashboard_item("case_all", "confirmed", count_dict),
                        utils.get_dashboard_item("case_all", "released", count_dict),
                    ]
                }
            ]
        else:
            cases = [
                {
                    "id": "case_my",
                    "count": number_of_all_my_cases,
                    "children": [
                        utils.get_dashboard_item("case_my", "new", count_dict),
                        utils.get_dashboard_item("case_my", "progress", count_dict),
                        utils.get_dashboard_item("case_my", "confirmed", count_dict),
                        utils.get_dashboard_item("case_my", "rejected", count_dict),
                        utils.get_dashboard_item("case_my", "released", count_dict),
                    ]
                }
            ]

        if user.permission is UserPermission.SUPERSENTINEL or \
                user.permission is UserPermission.SENTINEL:
            number_of_all_indicators = Indicator.objects.count()
        else:
            number_of_all_indicators = Indicator.objects.filter(Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | Q(user=user.pk)).count()

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

    def get_object(self, pk):
        try:
            return self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            raise exceptions.CaseNotFound()

    def get(self, request, pk=None):
        obj = self.get_object(pk)
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
        obj = self.get_object(pk)
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
        obj = self.get_object(pk)
        serializer = CasePatchSerializer(obj, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        c = DefaultCache()
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
                obj = self.get_object(pk)
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
            serializer = IndicatorPostSerializer(data=request.data["indicators"], many=True)
        else:
            serializer = IndicatorPostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if request.auth is not None:
            indicator_obj = serializer.save(user=request.user)
        else:
            indicator_obj = serializer.save()
        result_serializer = IndicatorSimpleListSerializer(indicator_obj, many="indicators" in request.data)
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

    def get_object(self, pk):
        try:
            indicator = self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            raise exceptions.IndicatorNotFound()
        return indicator

    def get(self, request, pk=None):
        c = DefaultCache()
        cached_response = c.get_view_cache(request)
        if cached_response:
            return APIResponse(cached_response)

        obj = self.get_object(pk)
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
        obj = self.get_object(pk)
        case_test_objs = obj.cases.filter(status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED])
        if len(case_test_objs) > 0:
            raise exceptions.NotAllowedError()
        serializer = IndicatorPostSerializer(obj, data=request.data)
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
    permission_classes = (IsAuthenticated,)
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
