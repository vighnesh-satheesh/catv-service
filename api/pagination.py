import math

from django.utils.translation import gettext_lazy as _

from rest_framework import pagination

from .response import APIResponse


# "totalPages": 50, # = ceiling(totalItems / ItemsPerPage)

class CustomPagination(pagination.PageNumberPagination):
    page_size = 20
    page_query_param = "page"
    invalid_page_message = _('invalid page number.')

    def get_current_page_number(self):
        return self.page.number

    def get_paginated_response(self, data, data_key=None):
        return APIResponse({
            "data": {
                "totalItems": self.page.paginator.count,
                "itemsPerPage": self.page_size,
                "pageIndex": self.get_current_page_number(),
                "totalPages": math.ceil(self.page.paginator.count / self.page_size),
                data_key: data
            }
        })


class CatvRequestPagination(CustomPagination):
    page_size = 10
