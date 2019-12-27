from django.conf import settings
from django_elasticsearch_dsl import Document, Index, fields
from django_elasticsearch_dsl_drf.compat import KeywordField, StringField

from api.models import User
from ..analyzer import HTML_STRIP

__all__ = ('UserDocument',)

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
class UserDocument(Document):
    """
    User Elasticsearch document.
    """

    id = fields.IntegerField(attr='id')

    email = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    address = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    nickname = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    uid = StringField()

    created = fields.DateField()

    permission = StringField(
        analyzer=HTML_STRIP,
        attr='permission_indexing',
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    status = StringField(
        analyzer=HTML_STRIP,
        attr='status_indexing',
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    role = StringField(
        analyzer=HTML_STRIP,
        attr='role_indexing',
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    points = fields.IntegerField(
        attr='points',
        fields={
            'raw': KeywordField()
        }
    )

    class Django(object):
        """
        Inner nested class to link Elasticsearch with Django ORM
        """
        model = User  # The model associated with this document.

    class Meta(object):
        parallel_indexing = True
        # Use queryset_pagination to control how many documents are indexed at a time
        # queryset_pagination = 100

