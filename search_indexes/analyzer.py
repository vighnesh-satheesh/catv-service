from elasticsearch_dsl import analyzer

from .tokenizer import PATTERN_TREE_TOKENIZER

__all__ = ('HTML_STRIP', 'PATTERN_TREE_SPLIT',)

HTML_STRIP = analyzer(
    'html_strip',
    tokenizer="standard",
    filter=["lowercase", "stop", "snowball"],
    char_filter=["html_strip"]
)

PATTERN_TREE_SPLIT = analyzer(
    "pattern_tree_split",
    tokenizer=PATTERN_TREE_TOKENIZER
)
