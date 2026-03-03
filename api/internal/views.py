import uuid
import traceback

from django.db import transaction as db_transaction
from rest_framework.views import APIView

from .serializers import CATVInternalSerializer
from .. import permissions
from ..models import CatvRequestStatus, CatvResult, CatvNeoJobQueue
from ..response import APIResponse
from ..rpc.RPCClient import RPCClientUpdateUsageCatvCall


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


class CATVKYTInternalView(APIView):
    """
    POST /internal/catv-kyt
    Internal endpoint to create a CATV job from KYT tracer data.
    Deducts credits before creating the job.
    """
    authentication_classes = ()
    permission_classes = ()

    def post(self, request):
        try:
            user_id = request.data.get("user_id")
            token_type = request.data.get("token_type", "ETH")
            tracer_data = request.data.get("tracer_data", {})
            wallet_address = request.data.get("wallet_address", "")
            source_depth = request.data.get("source_depth", 6)
            distribution_depth = request.data.get("distribution_depth", 0)
            kyt_report_id = request.data.get("kyt_report_id")

            if not user_id:
                return APIResponse({"error": "user_id is required"}, status=400)

            # Deduct credits
            try:
                rpc = RPCClientUpdateUsageCatvCall()
                user_rpc = {
                    "id": user_id,
                    "source": "kyt_catv",
                    "uid": str(user_id),
                    "credits_required": 20
                }
                res = rpc.call(user_rpc).decode('UTF-8')
                print(f"KYT-CATV credit deduction result: {res}")
                if "error" in res.lower() or res == "False":
                    return APIResponse({"error": "Insufficient credits"}, status=403)
            except Exception as e:
                print(f"Credit deduction failed: {e}")
                traceback.print_exc()
                return APIResponse({"error": "Credit deduction failed"}, status=500)

            # Extract date range from tracer_data transactions
            transactions = tracer_data.get("transactions", [])
            from_date = ""
            to_date = ""
            if transactions:
                tx_times = [tx.get("tx_time", "") for tx in transactions if tx.get("tx_time")]
                if tx_times:
                    from_date = min(tx_times)[:10]  # truncate date
                    to_date = max(tx_times)[:10]  # truncate date

            message_id = uuid.uuid4()
            search_params = {
                "wallet_address": wallet_address,
                "source_depth": source_depth,
                "distribution_depth": distribution_depth,
                "transaction_limit": 10000,
                "from_date": from_date,
                "to_date": to_date,
                "force_lookup": True
            }

            with db_transaction.atomic():
                task_record = CatvRequestStatus.objects.create(
                    uid=message_id,
                    params=search_params,
                    user_id=user_id,
                    token_type=token_type,
                )
                CatvResult.objects.create(request=task_record)

            message_body = {
                "message_id": message_id.hex,
                "user_id": user_id,
                "token_type": token_type,
                "search_type": "flow",
                "source": "kyt",
                "kyt_report_id": kyt_report_id,
                "tracer_data": tracer_data,
                "search_params": search_params
            }
            CatvNeoJobQueue.objects.create(message=message_body, retries_remaining=1)

            return APIResponse({
                "catv_request_uid": str(message_id),
                "status": "progress"
            })

        except Exception as e:
            print(f"Error in CATVKYTInternalView: {e}")
            traceback.print_exc()
            return APIResponse({"error": str(e)}, status=500)


class CATVKYTStatusInternalView(APIView):
    """
    GET /internal/catv-kyt-status?request_uid=<uuid>&user_id=<int>
    Internal endpoint to check status of a KYT-CATV request.
    """
    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        try:
            request_uid = request.query_params.get('request_uid')
            user_id = request.query_params.get('user_id')

            if not request_uid or not user_id:
                return APIResponse({"error": "request_uid and user_id are required"}, status=400)

            try:
                task_record = CatvRequestStatus.objects.get(uid=request_uid, user_id=user_id)
            except CatvRequestStatus.DoesNotExist:
                return APIResponse({"error": "Request not found"}, status=404)

            result_file_id = None
            try:
                catv_result = CatvResult.objects.get(request=task_record)
                result_file_id = catv_result.result_file_id
            except CatvResult.DoesNotExist:
                pass

            response_data = {
                "request_uid": str(task_record.uid),
                "status": str(task_record.status.value) if hasattr(task_record.status, 'value') else str(task_record.status),
                "token_type": str(task_record.token_type.value) if hasattr(task_record.token_type, 'value') else str(task_record.token_type),
                "created": str(task_record.created) if task_record.created else None,
                "updated": str(task_record.updated) if task_record.updated else None,
            }

            if result_file_id:
                response_data["result_file_id"] = result_file_id

            return APIResponse(response_data)

        except Exception as e:
            print(f"Error in CATVKYTStatusInternalView: {e}")
            traceback.print_exc()
            return APIResponse({"error": str(e)}, status=500)