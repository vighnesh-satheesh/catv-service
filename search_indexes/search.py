"""
Custom search backend.
"""

from django_elasticsearch_dsl_drf.filter_backends import SearchFilterBackend

__all__ = ('CustomSearchBackend',)


class CustomSearchBackend(SearchFilterBackend):
    """
    Override `construct_search` method to use `query_string` match technique instead of `match`.
    """
    def construct_search(self, request, view):
        """Construct search.

        :param request: Django REST framework request.
        :param queryset: Base queryset.
        :param view: View.
        :type request: rest_framework.request.Request
        :type queryset: elasticsearch_dsl.search.Search
        :type view: rest_framework.viewsets.ReadOnlyModelViewSet
        :return: Updated queryset.
        :rtype: elasticsearch_dsl.search.Search
        """
        query_params = self.get_search_query_params(request)
        queries = []
        query_proto = {
            "query_string": {
                "fields": [],
                "query": ""
            }
        }

        if not query_params:
            return queries

        for field in view.search_fields:
            query_proto["query_string"]["fields"].append(field)

        for search_term in query_params:
            old_query = query_proto["query_string"]["query"]
            query_proto["query_string"]["query"] = "{0} OR *{1}*".format(old_query, search_term) \
                if old_query else "*{}*".format(search_term)

        queries.append(query_proto)

        return queries
