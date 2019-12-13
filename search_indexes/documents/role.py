from django.conf import settings
from django_elasticsearch_dsl import Document, Index, fields
from django_elasticsearch_dsl_drf.compat import KeywordField, StringField

from api.models import Role
from ..analyzer import HTML_STRIP

__all__ = ('RoleDocument',)

INDEX = Index(settings.ELASTICSEARCH_INDEX_NAMES[__name__])

INDEX.settings(
    number_of_shards=1,
    # TIP: Set `number_of_replicas` to 0 to make initial indexing for large datasets faster.
    number_of_replicas=1,
    # TIP: Set `refresh_interval` to -1 to make initial indexing for large datasets faster.
    # Default is 1s.
    # refresh_interval=1
)


@INDEX.doc_type
class RoleDocument(Document):
    """
    Role Elasticsearch document
    """

    id = fields.IntegerField(attr='id')

    role_name = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP)
        }
    )

    display_name = StringField(analyzer=HTML_STRIP)

    class Django(object):
        """
        Inner nested class to link Elasticsearch with Django ORM
        """
        model = Role  # The model associated with this document.

    class Meta(object):
        parallel_indexing = True
        # Use queryset_pagination to control how many documents are indexed at a time
        # queryset_pagination = 100

