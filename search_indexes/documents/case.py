from django.conf import settings
from django_elasticsearch_dsl import Document, Index, fields
from django_elasticsearch_dsl_drf.compat import KeywordField, StringField

from api.models import Case
from ..analyzer import HTML_STRIP

__all__ = ('CaseDocument',)

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
class CaseDocument(Document):
    """
    Case Elasticsearch document.
    """
    id = fields.IntegerField(attr='id')

    title = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP)
        }
    )

    detail = StringField(
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    # Doing this because indexing UUIDs is not recommended in Elasticsearch
    # and disabling indexing only works for object fields and top-level doc definition.
    # Re-construct the UUID from the hex value later on in the serializer.
    uid = fields.ObjectField(
        enabled=False,
        properties={
            'hex': StringField()
        }
    )

    created = fields.DateField()

    updated = fields.DateField()

    status = StringField(
        attr='status_indexing',
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    reporter_info = StringField(
        analyzer=HTML_STRIP,
        fields={
            'raw': KeywordField(),
            'lower': StringField(analyzer=HTML_STRIP),
        }
    )

    reporter = fields.ObjectField(
        properties={
            'nickname': StringField(
                analyzer=HTML_STRIP,
                fields={
                    'raw': KeywordField(),
                    'lower': StringField(analyzer=HTML_STRIP),
                }
            ),
            'uid': fields.ObjectField(
                enabled=False,
                properties={
                    'hex': StringField()
                }
            )
        }
    )

    owner = fields.ObjectField(
        properties={
            'nickname': StringField(
                analyzer=HTML_STRIP,
                fields={
                    'raw': KeywordField(),
                    'lower': StringField(analyzer=HTML_STRIP),
                }
            ),
            'uid': fields.ObjectField(
                enabled=False,
                properties={
                    'hex': StringField()
                }
            )
        }
    )

    verifier = fields.ObjectField(
        properties={
            'nickname': StringField(
                analyzer=HTML_STRIP,
                fields={
                    'raw': KeywordField(),
                    'lower': StringField(analyzer=HTML_STRIP),
                }
            ),
            'uid': fields.ObjectField(
                enabled=False,
                properties={
                    'hex': StringField()
                }
            )
        }
    )

    # Uncomment the lines below tp include indicator objects in the Case document
    # WARNING: Indexing can take painfully long if there are a large number
    # of indicators, i.e., more than a million.
    #
    # indicators = fields.ListField(
    #     fields.ObjectField(
    #         properties={
    #             'id': fields.IntegerField(attr='id'),
    #             'uid': fields.StringField(),
    #             'security_category': StringField(
    #                 attr='security_category_indexing',
    #                 fields={
    #                     'raw': KeywordField(),
    #                     'suggest': fields.CompletionField(),
    #                     'edge_ngram_completion': StringField(
    #                         analyzer=edge_ngram_completion
    #                     )
    #                 }
    #             ),
    #             'pattern_type': StringField(
    #                 attr='pattern_type_indexing',
    #                 fields={
    #                     'raw': KeywordField(),
    #                     'suggest': fields.CompletionField(),
    #                     'edge_ngram_completion': StringField(
    #                         analyzer=edge_ngram_completion
    #                     )
    #                 }
    #             ),
    #             'pattern_subtype': StringField(
    #                 attr='pattern_subtype_indexing',
    #                 fields={
    #                     'raw': KeywordField(),
    #                     'suggest': fields.CompletionField(),
    #                     'edge_ngram_completion': StringField(
    #                         analyzer=edge_ngram_completion
    #                     )
    #                 }
    #             ),
    #             'annotation': StringField(
    #                 fields={
    #                     'raw': KeywordField(),
    #                     'suggest': fields.CompletionField(),
    #                     'edge_ngram_completion': StringField(
    #                         analyzer=edge_ngram_completion
    #                     )
    #                 }
    #             ),
    #             'pattern': StringField(
    #                 fields={
    #                     'raw': KeywordField(),
    #                     'suggest': fields.CompletionField(),
    #                     'edge_ngram_completion': StringField(
    #                         analyzer=edge_ngram_completion
    #                     )
    #                 }
    #             )
    #         }
    #     )
    # )

    class Django(object):
        """
        Inner nested class to link Elasticsearch with Django ORM
        """
        model = Case  # The model associated with this document.

    class Meta(object):
        parallel_indexing = True
        # Use queryset_pagination to control how many documents are indexed at a time
        # queryset_pagination = 100
