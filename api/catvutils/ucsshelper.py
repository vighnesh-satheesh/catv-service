import traceback
import json
from enum import Enum
from ..models import (
    CatvTokens, CatvSearchType
)
from ..serializers import (
    CATVSerializer, CATVBTCCoinpathSerializer, CATVRequestListSerializer
)
from ..tasks import (
    CatvRequestTask
)
from ..settings import api_settings


class UcssHelper:

    def __init__(self, catv_query):
        self.address = catv_query.get('address')
        self.token_type = catv_query.get('token_type', CatvTokens.ETH.value)
        self.search_type = catv_query.get('search_type', CatvSearchType.FLOW.value)
        self.from_date = catv_query.get('from_date')
        self.to_date = catv_query.get('to_date')
        self.source_depth = catv_query.get('source_depth')
        self.distribution_depth = catv_query.get('distribution_depth')
        self.user = catv_query.get('user')

    # TODO: validation Error for wrong token_type

    def process_catv_request(self):
        try:
            serializer_map = {
                CatvTokens.ETH.value: {
                    CatvSearchType.FLOW.value: CATVSerializer,
                    # CatvSearchType.PATH.value: CATVEthPathSerializer
                },
                CatvTokens.BTC.value: {
                    CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
                    # CatvSearchType.PATH.value: CatvBtcPathSerializer
                },
                CatvTokens.TRON.value: {
                    CatvSearchType.FLOW.value: CATVSerializer,
                    # CatvSearchType.PATH.value: CATVEthPathSerializer
                },
                CatvTokens.LTC.value: {
                    CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
                    # CatvSearchType.PATH.value: CatvBtcPathSerializer
                },
                CatvTokens.BCH.value: {
                    CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
                    # CatvSearchType.PATH.value: CatvBtcPathSerializer
                },
                CatvTokens.XRP.value: {
                    CatvSearchType.FLOW.value: CATVSerializer,
                    # CatvSearchType.PATH.value: CATVEthPathSerializer
                },
                CatvTokens.EOS.value: {
                    CatvSearchType.FLOW.value: CATVSerializer,
                    # CatvSearchType.PATH.value: CATVEthPathSerializer
                },
                CatvTokens.XLM.value: {
                    CatvSearchType.FLOW.value: CATVSerializer,
                    # CatvSearchType.PATH.value: CATVEthPathSerializer
                },
                CatvTokens.BNB.value: {
                    CatvSearchType.FLOW.value: CATVSerializer,
                    # CatvSearchType.PATH.value: CATVEthPathSerializer
                },
                CatvTokens.ADA.value: {
                    CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
                    # CatvSearchType.PATH.value: CatvBtcPathSerializer
                },
                CatvTokens.BSC.value: {
                    CatvSearchType.FLOW.value: CATVSerializer,
                    # CatvSearchType.PATH.value: CATVEthPathSerializer
                },
                CatvTokens.KLAY.value: {
                    CatvSearchType.FLOW.value: CATVSerializer,
                    # CatvSearchType.PATH.value: CATVEthPathSerializer
                }
            }
            serializer_cls = serializer_map[self.token_type][self.search_type]
            request_data = {
                "wallet_address": self.address,
                "from_date": self.from_date,
                "to_date": self.to_date,
                "force_lookup": False,
                "transaction_limit": 2000,
                "distribution_depth": self.distribution_depth,
                "source_depth": self.source_depth
            }
            serializer = serializer_cls(data=request_data)
            serializer._token_type = self.token_type
            serializer.is_valid(raise_exception=True)
            history = serializer.data
            catv_req_task = CatvRequestTask(api_settings.KAFKA_CATV_TOPIC,
                                            "ucss",
                                            token_type=self.token_type,
                                            search_type=self.search_type,
                                            search_params=history,
                                            user=json.loads(self.user),
                                            )
            catv_req_task.run()
            task = catv_req_task.save()
            task_serializer = CATVRequestListSerializer(task)
            print("Submission Status: ", task_serializer.data)
            return task_serializer.data
        except Exception as e:
            traceback.print_exc()
            return {}
