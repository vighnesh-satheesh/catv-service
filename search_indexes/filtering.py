"""
Custom filtering backend.
"""
import operator

import six
from django_elasticsearch_dsl_drf.constants import (
    LOOKUP_FILTER_PREFIX,
    LOOKUP_FILTER_RANGE,
    LOOKUP_FILTER_TERMS,
    LOOKUP_FILTER_EXISTS,
    LOOKUP_FILTER_WILDCARD,
    LOOKUP_QUERY_CONTAINS,
    LOOKUP_QUERY_IN,
    LOOKUP_QUERY_GT,
    LOOKUP_QUERY_GTE,
    LOOKUP_QUERY_LT,
    LOOKUP_QUERY_LTE,
    LOOKUP_QUERY_STARTSWITH,
    LOOKUP_QUERY_ENDSWITH,
    LOOKUP_QUERY_ISNULL,
    LOOKUP_QUERY_EXCLUDE,
)
from django_elasticsearch_dsl_drf.filter_backends import FilteringFilterBackend
from elasticsearch_dsl.query import Q

__all__ = ('CustomFilteringBackend',)


class CustomFilteringBackend(FilteringFilterBackend):
    """
    Filtering filter backend for Elasticsearch.

    Overriding methods from the base django_elasticsearch_dsl_drf.filter_backends
    to convert query strings to lowercase.
    """
    @classmethod
    def apply_query_contains(cls, queryset, options, value):
        """
        Apply `contains` filter after converting in to lowercase.

        Syntax:

            /endpoint/?field_name__contains={value}

        Example:

            http://localhost:8000/ecsearch/indicators/?pattern__contains=LoTtEry


        :param queryset: Original queryset.
        :param options: Filter options.
        :param value: Value to filter on.
        :return: Modified queryset.
        """

        value_lower = value

        if options.get('field', None) != 'pattern_subtype.raw':
            value_lower = value.lower()

        return super(CustomFilteringBackend, cls).apply_query_contains(
            queryset=queryset,
            options=options,
            value=value_lower
        )

    @classmethod
    def apply_query_in(cls, queryset, options, value):
        """
        Apply `in` functional query.

        Syntax:

            /endpoint/?field_name__in={value1}__{value2}
            /endpoint/?field_name__in={value1}
            Note, that number of values is not limited.

        Example:

            http://localhost:8000/ecsearch/indicators/?pattern_subtype__in=ETH__filehash


        :param queryset: Original queryset.
        :param options: Filter options.
        :param value: value to filter on.
        :type options: dict
        :type value: str
        :return: Modified queryset.
        """

        value_lower = value

        if options.get('field', None) != 'pattern_subtype.raw':
            value_lower = value.lower()

        return super(CustomFilteringBackend, cls).apply_query_in(
            queryset=queryset,
            options=options,
            value=value_lower
        )

    @classmethod
    def apply_query_wildcard(cls, queryset, options, value):
        """
        Apply `wildcard` filter.

        Syntax:

            /endpoint/?field_name__wildcard={value}*
            /endpoint/?field_name__wildcard=*{value}
            /endpoint/?field_name__wildcard=*{value}*

        Example:

            http://localhost:8000/ecsearch/indicators/?pattern__wildcard=lotte*


        :param queryset: Original queryset.
        :param options: Filter options.
        :param value: value to filter on.
        :type options: dict
        :type value: str
        :return: Modified queryset.
        """
        value_lower = value

        if options.get('field', None) != 'pattern_subtype.raw':
            value_lower = value.lower()

        return super(CustomFilteringBackend, cls).apply_query_wildcard(
            queryset=queryset,
            options=options,
            value=value_lower
        )
    
    @classmethod
    def apply_query_combine(cls, queryset, query_list):
        """Combine disparate columns into an OR search with term clause.

        Example:

            http://localhost:8000/ecsearch/dev_cases/?owner=84&reporter=84
            We want to find documents with owner id 84 or reporter id 84.
            With the way that the django-elastic-dsl-drf constructs filter columns,
            there is no way to specify an OR clause for multiple columns.
            This can be controlled by the `combine_fields` property in the viewset class.

        :param queryset: Original queryset.
        :param options: Filter options.
        :param value: value to filter on.
        :type queryset: elasticsearch_dsl.search.Search
        :type options: dict
        :type value: str
        :return: Modified queryset.
        :rtype: elasticsearch_dsl.search.Search
        """
        __queries = []
        for query in query_list:
            for value in query['values']:
                __values = cls.split_lookup_complex_value(value)
                for __value in __values:
                    __queries.append(
                        Q('term', **{query['field']: __value})
                    )

        if __queries:
            queryset = cls.apply_query(
                queryset=queryset,
                options=None,
                args=[six.moves.reduce(operator.or_, __queries)]
            )

        return queryset
    
    def filter_queryset(self, request, queryset, view):
        """Filter the queryset.

        :param request: Django REST framework request.
        :param queryset: Base queryset.
        :param view: View.
        :type request: rest_framework.request.Request
        :type queryset: elasticsearch_dsl.search.Search
        :type view: rest_framework.viewsets.ReadOnlyModelViewSet
        :return: Updated queryset.
        :rtype: elasticsearch_dsl.search.Search
        """
        filter_query_params = self.get_filter_query_params(request, view)
        if getattr(view, "combine_fields", None):
            excluded_query_params = {key: val for key, val in filter_query_params.items() if key in view.combine_fields}
            included_query_params = {key: val for key, val in filter_query_params.items() if key not in view.combine_fields}
        else:
            excluded_query_params = None
            included_query_params = filter_query_params
        for options in included_query_params.values():
            # When no specific lookup given, in case of multiple values
            # we apply `terms` filter by default and proceed to the next
            # query param.
            if isinstance(options['values'], (list, tuple)) \
                    and options['lookup'] is None:
                queryset = self.apply_filter_terms(queryset,
                                                   options,
                                                   options['values'])
                continue

            # For all other cases, when we don't have multiple values,
            # we follow the normal flow.
            for value in options['values']:
                # `terms` filter lookup
                if options['lookup'] == LOOKUP_FILTER_TERMS:
                    queryset = self.apply_filter_terms(queryset,
                                                       options,
                                                       value)

                # `prefix` filter lookup
                elif options['lookup'] in (LOOKUP_FILTER_PREFIX,
                                           LOOKUP_QUERY_STARTSWITH):
                    queryset = self.apply_filter_prefix(queryset,
                                                        options,
                                                        value)

                # `range` filter lookup
                elif options['lookup'] == LOOKUP_FILTER_RANGE:
                    queryset = self.apply_filter_range(queryset,
                                                       options,
                                                       value)

                # `exists` filter lookup
                elif options['lookup'] == LOOKUP_FILTER_EXISTS:
                    queryset = self.apply_query_exists(queryset,
                                                       options,
                                                       value)

                # `wildcard` filter lookup
                elif options['lookup'] == LOOKUP_FILTER_WILDCARD:
                    queryset = self.apply_query_wildcard(queryset,
                                                         options,
                                                         value)

                # `contains` filter lookup
                elif options['lookup'] == LOOKUP_QUERY_CONTAINS:
                    queryset = self.apply_query_contains(queryset,
                                                         options,
                                                         value)

                # `in` functional query lookup
                elif options['lookup'] == LOOKUP_QUERY_IN:
                    queryset = self.apply_query_in(queryset,
                                                   options,
                                                   value)

                # `gt` functional query lookup
                elif options['lookup'] == LOOKUP_QUERY_GT:
                    queryset = self.apply_query_gt(queryset,
                                                   options,
                                                   value)

                # `gte` functional query lookup
                elif options['lookup'] == LOOKUP_QUERY_GTE:
                    queryset = self.apply_query_gte(queryset,
                                                    options,
                                                    value)

                # `lt` functional query lookup
                elif options['lookup'] == LOOKUP_QUERY_LT:
                    queryset = self.apply_query_lt(queryset,
                                                   options,
                                                   value)

                # `lte` functional query lookup
                elif options['lookup'] == LOOKUP_QUERY_LTE:
                    queryset = self.apply_query_lte(queryset,
                                                    options,
                                                    value)

                # `endswith` filter lookup
                elif options['lookup'] == LOOKUP_QUERY_ENDSWITH:
                    queryset = self.apply_query_endswith(queryset,
                                                         options,
                                                         value)

                # `isnull` functional query lookup
                elif options['lookup'] == LOOKUP_QUERY_ISNULL:
                    queryset = self.apply_query_isnull(queryset,
                                                       options,
                                                       value)

                # `exclude` functional query lookup
                elif options['lookup'] == LOOKUP_QUERY_EXCLUDE:
                    queryset = self.apply_query_exclude(queryset,
                                                        options,
                                                        value)

                # `term` filter lookup. This is default if no `default_lookup`
                # option has been given or explicit lookup provided.
                else:
                    queryset = self.apply_filter_term(queryset,
                                                      options,
                                                      value)
        if excluded_query_params:
            queryset = self.apply_query_combine(queryset, excluded_query_params.values())
        return queryset
