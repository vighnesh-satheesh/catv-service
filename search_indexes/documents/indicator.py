from django.conf import settings
from django_elasticsearch_dsl import Document, Index, fields
from django_elasticsearch_dsl_drf.compat import KeywordField, StringField

from api.models import IndicatorMView
from ..analyzer import HTML_STRIP, PATTERN_TREE_SPLIT

__all__ = ('IndicatorDocument',)

INDEX = Index(settings.ELASTICSEARCH_INDEX_NAMES[__name__])

INDEX.settings(
    number_of_shards=2,
    # TIP: Set `number_of_replicas` to 0 to make initial indexing for large datasets faster.
    number_of_replicas=1,
    # TIP: Set `refresh_interval` to -1 to make initial indexing for large datasets faster.
    # Default is 1s.
    # refresh_interval=1
)


@INDEX.doc_type
class IndicatorDocument(Document):
    """
    Indicator Elasticsearch document.
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

    security_category = KeywordField()

    security_tags = KeywordField()

    vector = KeywordField()

    environment = KeywordField()

    pattern_type = KeywordField()

    pattern_subtype = KeywordField()

    pattern = KeywordField()

    detail = KeywordField()

    created = fields.DateField()

    cases = KeywordField()

    annotations = KeywordField()

    latest_case = fields.ObjectField(
        enabled=False,
        properties={
            'hex': StringField()
        }
    )

    user_id = fields.IntegerField()
    
    pattern_tree = KeywordField()
    
    pattern_tree_count = fields.IntegerField(
        attr='pattern_tree_count'
    )
    
    updated = fields.DateField()

    class Django(object):
        """
        Inner nested class to link Elasticsearch with Django ORM
        """
        model = IndicatorMView  # The model associated with this document.

    class Meta(object):
        parallel_indexing = True
        queryset_pagination = 100
