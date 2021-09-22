import json

from rest_framework import exceptions
from ..exceptions import AuthenticationValidationError
from rest_framework.views import APIView
from ..models import (
    Case,
    CaseStatus,
    CaseHistory,
    Indicator,
    IndicatorPatternType,
    IndicatorPatternSubtype,
    Key,
    Notification,
    NotificationType,
    User
)

from django.db.models import Q
from django.db.models.functions import Lower
from kafka import KafkaProducer

from .serializers import (
    IndicatorPostSerializer,
    IndicatorSimpleListSerializer,
    IndicatorDetailSerializer,
    CaseHistoryPostSerializer,
    CATVInternalSerializer
)

from ..constants import Constants
from .. import utils
from .. import permissions
from ..cache import DefaultCache
from ..response import APIResponse
from ..settings import api_settings
from ..email import Email
from ..email.tasks import SendEmail

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

class CATVInternalView(APIView):
    authentication_classes = ()
    permission_classes = (permissions.InternalOnly,)

    def post(self, request):
        serializer = CATVInternalSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        addr_limit = serializer.data.get("transaction_limit", 100000)
        results = serializer.get_tracking_results(tx_limit=addr_limit, limit=addr_limit, save_to_db=False, build_lossy_graph=False)
        return APIResponse({
            "data": {**results["graph"]}
        })