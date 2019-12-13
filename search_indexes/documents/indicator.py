from django.conf import settings
from django_elasticsearch_dsl import Document, Index, fields
from django_elasticsearch_dsl_drf.compat import KeywordField, StringField

from api.models import Indicator
from ..analyzer import HTML_STRIP

__all__ = ('IndicatorDocument',)

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

    security_category = StringField(
        attr='security_category_indexing',
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP)
        }
    )

    security_tags = fields.ListField(
        StringField(
            attr='security_tags_indexing',
            analyzer=HTML_STRIP,
            fields={
                'raw': KeywordField(),
                'lower': StringField(analyzer=HTML_STRIP)
            }
        )
    )

    vector = fields.ListField(
        StringField(
            attr='vector_indexing',
            analyzer=HTML_STRIP,
            fields={
                'raw': KeywordField(),
                'lower': StringField(analyzer=HTML_STRIP)
            }
        )
    )

    environment = fields.ListField(
        StringField(
            attr='environment_indexing',
            analyzer=HTML_STRIP,
            fields={
                'raw': KeywordField(),
                'lower': StringField(analyzer=HTML_STRIP)
            }
        )
    )

    pattern_type = StringField(
        attr='pattern_type_indexing',
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP)
        }
    )

    pattern_subtype = StringField(
        attr='pattern_subtype_indexing',
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP)
        }
    )

    pattern = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP)
        }
    )

    detail = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP)
        }
    )

    created = fields.DateField()

    cases = fields.ListField(
        StringField(
            attr='cases_status_indexing',
            analyzer=HTML_STRIP,
            fields={
                'raw': KeywordField(),
                'lower': StringField(analyzer=HTML_STRIP)
            }
        )
    )

    annotations = fields.ListField(
        StringField(
            attr='annotations_indexing',
            analyzer=HTML_STRIP,
            fields={
                'raw': KeywordField(),
                'lower': StringField(analyzer=HTML_STRIP)
            }
        )
    )

    class Django(object):
        """
        Inner nested class to link Elasticsearch with Django ORM
        """
        model = Indicator  # The model associated with this document.

    class Meta(object):
        parallel_indexing = True
        queryset_pagination = 100
