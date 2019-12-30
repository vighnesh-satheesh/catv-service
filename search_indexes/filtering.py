"""
Custom filtering backend.
"""


from django_elasticsearch_dsl_drf.filter_backends import FilteringFilterBackend

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
