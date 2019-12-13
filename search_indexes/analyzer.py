from elasticsearch_dsl import analyzer

__all__ = ('HTML_STRIP',)

HTML_STRIP = analyzer(
    'html_strip',
    tokenizer="standard",
    filter=["lowercase", "stop", "snowball"],
    char_filter=["html_strip"]
)
