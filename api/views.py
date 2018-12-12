from collections import defaultdict

from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import JSONRenderer

from django_filters import rest_framework as filters
from django.db.models import Q, Prefetch, Count
from indicatorlib import Pattern
from django.db import transaction, IntegrityError

from .models import (
    User, Case, Indicator, ICO, CaseStatus, Key, Comment,
    Notification, NotificationType,
    AttachedFile, UserPermission, UppwardRewardInfo,
    UserStatus
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
        return APIResponse({"data": {}})


class DashboardView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request, format=None):
        if request.user is None or request.auth is None:
            raise exceptions.AuthenticationCheckError()
        user = request.user
        count_dict = defaultdict(int)
        total_count = 0
        my_count = 0
        try:
            for item in CaseStatus:
                count = Case.objects.filter(status=item).count()
                count_dict["case_all_{0}".format(item.value)] = count
                total_count += count
        except Case.DoesNotExist:
            pass

        try:
            for item in CaseStatus:
                if item == CaseStatus.NEW:
                    continue
                count = Case.objects.filter(Q(owner=user.pk) & Q(status=item)).count()
                count_dict["case_my_{0}".format(item.value)] = count
                my_count += count
        except Case.DoesNotExist:
            pass

        cases = [
            {
                "id": "case_my",
                "count": my_count,
                "children": [
                    utils.get_dashboard_item("case_my", "progress", count_dict),
                    utils.get_dashboard_item("case_my", "confirmed", count_dict),
                    utils.get_dashboard_item("case_my", "rejected", count_dict),
                    utils.get_dashboard_item("case_my", "released", count_dict),
                ]
            },
            {
                "id": "case_all",
                "count": total_count,
                "children": [
                    utils.get_dashboard_item("case_all", "new", count_dict),
                    utils.get_dashboard_item("case_all", "progress", count_dict),
                    utils.get_dashboard_item("case_all", "confirmed", count_dict),
                    utils.get_dashboard_item("case_all", "rejected", count_dict),
                    utils.get_dashboard_item("case_all", "released", count_dict),
                ]
            }
        ]
        if user.permission is UserPermission.EXCHANGE:
            for status, cnt in count_dict.items():
                if status in ['case_all_new', 'case_all_progress', 'all_confirmed']:
                    total_count -= cnt
            cases[1]["children"] = cases[1]["children"][3:]
            cases[1]["count"] = total_count

            indicator_attached_filter = Q(num_cases__gt=0) & \
                                        (Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | Q(user=user.pk))
            indicators = [
                {
                    "id": "indicator_attached",
                    "count": Indicator.objects.annotate(num_cases=Count('cases')).filter(indicator_attached_filter).count(),
                    "children": []
                },
                {
                    "id": "indicator_unattached",
                    "count":  Indicator.objects.annotate(num_cases=Count('cases')).filter(num_cases=0).count(),
                    "children": []
                }
            ]
        else:
            indicators = [
                {
                    "id": "indicator_attached",
                    "count": Indicator.objects.annotate(num_cases=Count('cases')).filter(num_cases__gt=0).count(),
                    "children": []
                },
                {
                    "id": "indicator_unattached",
                    "count":  Indicator.objects.annotate(num_cases=Count('cases')).filter(num_cases=0).count(),
                    "children": []
                }
            ]

        notifications = []
        notification_objs = Notification.objects.filter(user=user.pk).order_by('-created')
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
            return queryset.filter(reporter = user.pk)
        elif action == 'released':
            return queryset.filter(verifier = user.pk)

        return queryset

    def filter_case_board(self, queryset, name, value):  # TODO: very dirty code, gets even dirtier
        case_cate = value.split("_")
        if len(case_cate) not in [1, 2]:
            raise exceptions.CaseFilterError()

        cate = case_cate[0]
        subcate = None
        if len(case_cate) == 2:
            subcate = case_cate[1]

        if cate not in ["all", "my"]:
            raise exceptions.CaseFilterError()

        if cate == "all":
            if subcate is None:
                if self.request.user.permission == UserPermission.EXCHANGE:
                    return queryset.filter(Q(status="released") | Q(status="rejected"))
                else:
                    return queryset

            if subcate not in ["new", "progress", "confirmed", "rejected", "released"]:
                raise exceptions.CaseFilterError()

            try:
                return queryset.filter(status=subcate)
            except Exception:
                raise exceptions.CaseFilterError()
        elif cate == "my":
            if subcate is None:
                return queryset.filter(owner=self.request.user.pk)

            if subcate not in ["progress", "confirmed", "rejected", "released"]:
                raise exceptions.CaseFilterError()
            try:
                return queryset.filter(status=subcate, owner=self.request.user.pk)
            except Exception:
                raise exceptions.CaseFilterError()
        else:
            return queryset


class CaseView(generics.ListCreateAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (permissions.IsPostOrIsAuthenticated,)
    pagination_class = CustomPagination
    filter_backends = (filters.DjangoFilterBackend,)
    filter_class = CaseFilter
    serializer_class = CaseListSerializer
    model = Case

    def get_queryset(self):
        return self.model.objects.select_related('owner').select_related('ico') \
            .prefetch_related(Prefetch('indicator',
                                       queryset=Indicator.objects.all(),
                                       to_attr='indicators')) \
            .order_by('-pk')

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
    permission_classes = (IsAuthenticated,)
    model = Case

    def get_object(self, pk):
        try:
            return self.model.objects.get(uid__iexact=pk)
        except self.model.DoesNotExist:
            raise exceptions.CaseNotFound()

    def get(self, request, pk=None):
        obj = self.get_object(pk)
        serializer = CaseDetailSerializer(obj, context={"request": request})
        data = serializer.data

        permission_data = {}
        if request.user == obj.owner and obj.status == CaseStatus.PROGRESS:
            permission_data["editable"] = True
        else:
            permission_data["editable"] = False

        user_permission = getattr(request.user, "permission", None)
        is_super = True if user_permission == UserPermission.SUPERSENTINEL else False
        is_owner = True if request.user == obj.owner else False

        next_status = utils.CASE_STATUS_FSM.next(obj.status, is_super, is_owner)
        permission_data["status"] = [e.value for e in next_status]

        return APIResponse({
            "data": {
                "case": data,
                "case_permission": permission_data
            }
        })

    def put(self, request, pk=None):
        obj = self.get_object(pk)
        if obj.owner != request.user or obj.status != CaseStatus.PROGRESS:
            raise exceptions.NotAllowedError()

        serializer = CasePostSerializer(obj, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if obj.reporter:
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
        if obj.reporter:
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
                for indicator in obj.indicators.all():
                    indicator.cases.remove(obj)
                    obj.indicators.remove(indicator)
        except Case.DoesNotExist:
            raise exceptions.ValidationError("case does not exist")
        except IntegrityError:
            raise exceptions.DataIntegrityError("")
        if obj.reporter:
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

        return APIResponse({"data": {}})


class IndicatorFilter(filters.FilterSet):
    type = filters.CharFilter(method='filter_type')

    class Meta:
        model = Indicator
        fields = ("type",)

    def filter_type(self, queryset, name, value):
        if self.request.user.permission is UserPermission.EXCHANGE:
            indicator_attached_filter = Q(num_cases__gt=0) & \
                                        (Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | Q(user=self.request.user.pk))
        else:
            indicator_attached_filter = Q(num_cases__gt=0)

        if value == 'attached':
            return queryset.annotate(num_cases=Count('cases')).filter(indicator_attached_filter)
        elif value == 'unattached':
            return queryset.annotate(num_cases=Count('cases')).filter(num_cases=0)
        else:
            raise exceptions.IndicatorNotFound()


class IndicatorView(generics.ListCreateAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    pagination_class = CustomPagination
    filter_backends = (filters.DjangoFilterBackend,)
    filter_class = IndicatorFilter
    serializer_class = IndicatorListSerializer
    model = Indicator

    def get_queryset(self):
        return self.model.objects.all().order_by('-created')

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
            indicator_obj = serializer.save
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
        obj = self.get_object(pk)
        serializer = IndicatorDetailSerializer(obj, is_authenticated=True if request.user and request.user.is_authenticated else False)
        data = serializer.data
        return APIResponse({
            "data": {
                "indicator": data
            }
        })

    def put(self, request, pk=None):
        obj = self.get_object(pk)
        case_test_objs = obj.cases.filter(status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED])
        if len(case_test_objs) > 0:
            raise exceptions.NotAllowedError()
        serializer = IndicatorPostSerializer(obj, data=request.data)
        serializer.is_valid(raise_exception=True)
        indicator_obj = serializer.save()
        result_serializer = IndicatorSimpleListSerializer(indicator_obj)
        return APIResponse({
            "data": result_serializer.data
        })

    def delete(self, request, pk=None):
        try:
            with transaction.atomic():
                indicator = self.get_object(pk)
                for case in indicator.cases.all():
                    if case.status in [CaseStatus.CONFIRMED, CaseStatus.RELEASED]:
                        raise exceptions.ValidationError("has confirmed or released attached cases.")
                    case.indicators.remove(indicator)
                    indicator.cases.remove(case)
                indicator.delete()
        except Indicator.DoesNotExist:
            raise exceptions.ValidationError("indicator does not exist")
        except IntegrityError:
            raise exceptions.DataIntegrityError("")
        return APIResponse({"data": {}})


# /search?q=aa&type=ico&page=1
class SearchView(generics.ListAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    pagination_class = CustomPagination

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
        if page is not None:
            if request.auth and search_type == "indicator":
                serializer = serializer_cls(page, many=True, is_authenticated=True)
            else:
                serializer = serializer_cls(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = serializer_cls(queryset, many=True)
        serializer.is_valid(raise_exception=True)
        return APIResponse(serializer.validated_data)

    def get_ico_queryset(self, query):
        filter_queries = Q(symbol__istartswith=query)
        if len(query) > 1:
            filter_queries |= Q(name__icontains=query)
        objs = ICO.objects.filter(filter_queries).order_by('pk')
        return objs

    def get_indicator_queryset(self, query):
        objs = []
        #filter_queries = Q(pattern_tree__aore=ltree_pattern) | Q(pattern_tree__dore=ltree_pattern)
        filter_queries = Q(pattern__icontains=query)

        if not self.request.auth:
            filter_queries &= Q(case__status=CaseStatus.RELEASED)
        elif self.request.auth and self.request.user.permission is UserPermission.EXCHANGE:
            filter_queries &= Q(cases__status__in=[CaseStatus.CONFIRMED, CaseStatus.RELEASED]) | Q(user=self.request.user.pk)

        objs = Indicator.objects.filter(filter_queries).order_by('pk')

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
            .prefetch_related('indicators') \
            .select_related('ico') \
            .filter(filter_queries) \
            .order_by('-created')

        return objs.all()


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


# /search/autocomplete?type=ico&q=aa
class AutoCompleteView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

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
            print(err)
            raise exceptions.FileNotFound()
        return FileResponse(buf, obj.uid, content_type=obj.type)


class ICODetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    model = ICO

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
        if u:
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
                  recipient = [obj.reporter.email])

        if notification:
            users = User.objects.filter(id__in=notification)
            for user in users:
                notification = Notification.objects.create(
                    user=user,
                    initiator=request.user,
                    type=NotificationType.COMMENT_MENTIONED,
                    target=target
                )
                kv = {
                    "nickname": u.nickname,
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
