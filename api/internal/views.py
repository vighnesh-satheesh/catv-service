from rest_framework.views import APIView

from .serializers import CATVInternalSerializer
from .. import utils
from .. import permissions
from ..response import APIResponse

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
        