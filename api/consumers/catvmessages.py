import json

from api.models import CatvTokens, CatvSearchType, ConsumerErrorLogs
from api.serializers import (
    CATVSerializer, CATVBTCCoinpathSerializer,
    CatvBtcPathSerializer, CATVEthPathSerializer
)

__all__ = ('process_catv_messages',)


def process_catv_messages(message):
    request_body = json.loads(message.value.decode("utf-8"))
    print("Processing message:\n")
    print(request_body)

    serializer_map = {
        CatvTokens.ETH.value: {
            CatvSearchType.FLOW.value: CATVSerializer,
            CatvSearchType.PATH.value: CATVEthPathSerializer
        },
        CatvTokens.BTC.value: {
            CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
            CatvSearchType.PATH.value: CatvBtcPathSerializer
        }
    }

    try:
        message_id = request_body["message_id"]
        user_id = request_body["user_id"]
        token_type = request_body.get("token_type", CatvTokens.ETH.value)
        search_type = request_body.get("search_type", CatvSearchType.FLOW.value)
        search_params = request_body.get("search_params", {})
        serializer_obj = serializer_map[token_type][search_type](data=search_params)
        results = serializer_obj.get_tracking_results(save_to_db=False)
        return results
    except Exception as e:
        print(str(e))
        ConsumerErrorLogs.objects.create(
            topic=message.topic,
            message=request_body,
            error_trace=str(e)
        )
