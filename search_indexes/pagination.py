from math import ceil

from django_elasticsearch_dsl_drf.pagination import PageNumberPagination

__all__ = ('CustomPageNumberPagination',)


class CustomPageNumberPagination(PageNumberPagination):
    page_size = 25

    def get_paginated_response_context(self, data):
        __data = super(CustomPageNumberPagination, self).get_paginated_response_context(data)
        actual_count = self.page.paginator.count
        result_count = actual_count if actual_count <= 10000 else 10000
        page_size = self.get_page_size(self.request)
        page_count = ceil(result_count / page_size)
        __data.append(
            ('pageIndex', int(self.request.query_params.get('page', 1)))
        )
        __data.append(
            ('totalItems', result_count)
        )
        __data.append(
            ('page_size', page_size)
        )
        __data.append(
            ('totalPages', page_count)
        )
        __data.append(
            ('actual_count', actual_count)
        )
        return sorted(__data)
