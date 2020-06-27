from django.conf import settings
from django_elasticsearch_dsl import Document, Index, fields
from django_elasticsearch_dsl_drf.compat import KeywordField, StringField

from api.models import Case, CaseMView
from ..analyzer import HTML_STRIP

__all__ = ('CaseDocument',)

INDEX = Index(settings.ELASTICSEARCH_INDEX_NAMES[__name__])

INDEX.settings(
    number_of_shards=1,
    # TIP: Set `number_of_replicas` to 0 to make initial indexing for large datasets faster.
    number_of_replicas=1,
    # TIP: Set `refresh_interval` to -1 to make initial indexing for large datasets faster.
    # Default is 1s.
    refresh_interval='1s'
)


@INDEX.doc_type
class CaseDocument(Document):
    """
    Case Elasticsearch document.
    """
    id = fields.IntegerField(attr='id')

    # Doing this because indexing UUIDs is not recommended in Elasticsearch
    # and disabling indexing only works for object fields and top-level doc definition.
    # Re-construct the UUID from the hex value later on in the serializer.
    uid = fields.ObjectField(
        enabled=False,
        properties={
            'hex': StringField()
        }
    )

    title = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
        }
    )

    detail = StringField(
        fields={
            'raw': KeywordField(),
        }
    )
    
    rich_text_detail = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
        }
    )

    created = fields.DateField()

    updated = fields.DateField()

    status = StringField(
        fields={
            'raw': KeywordField(),
        }
    )

    reporter_info = StringField(
        fields={
            'raw': KeywordField(),
        }
    )

    reporter = fields.IntegerField(attr='reporter_id')

    owner = fields.IntegerField(attr='owner_id')

    verifier = fields.IntegerField(attr='verifier_id')

    security_category = fields.ListField(
        StringField(
            fields={
                'raw': KeywordField(),
            }
        )
    )

    pattern_type = fields.ListField(
        StringField(
            fields={
                'raw': KeywordField(),
            }
        )
    )

    pattern_subtype = fields.ListField(
        StringField(
            fields={
                'raw': KeywordField(),
            }
        )
    )

    class Django(object):
        """
        Inner nested class to link Elasticsearch with Django ORM
        """
        model = CaseMView  # The model associated with this document.

    class Meta(object):
        parallel_indexing = True
        # Use queryset_pagination to control how many documents are indexed at a time
        queryset_pagination = 100
