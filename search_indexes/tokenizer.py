from elasticsearch_dsl import tokenizer


__all__ = ("PATTERN_TREE_TOKENIZER",)

PATTERN_TREE_TOKENIZER = tokenizer(
    "pattern_tree_tokenizer",
    type="simple_pattern_split",
    pattern=r"\."
)
