from .models import (
    CatvHistory, CatvTokens, CatvSearchType,
    CatvRequestStatus, CatvTaskStatusType, CatvResult,
    ProductType, CatvNodeLabelModel
)

class UcssHelper:

    def __init__(self, catv_query):
        self.token_type = catv_query.get('token_type', CatvTokens.ETH.value)
        self.search_type = catv_query.get('search_type', CatvSearchType.FLOW.value)
        self.allowed_tokens = [token.value for token in CatvTokens]
        self.allowed_search = [search.value for search in CatvSearchType]

       # TODO: validation Error for wrong token_type


    def process_catv_request(self, catv_query):
