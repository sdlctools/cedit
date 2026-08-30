"""The process-cached parser (CED-34, finding F).

`make_parser` is `@lru_cache`d, so every parse and render in a run shares one
`MarkdownIt`. That is only safe while nothing mutates it — these tests pin
both halves: the instance is shared, and the paths that use it leave its
options untouched.
"""

from cedit.blocks import canonicalise
from cedit.mdcore.utils import ast_to_markdown, make_parser, markdown_to_ast

SAMPLE = (
    "# Title\n\n"
    "Some *prose* with a [link](https://example.com).\n\n"
    "| a | b |\n| - | - |\n| 1 | 2 |\n\n"
    "```python\nprint('hi')\n```\n"
)


def test_make_parser_returns_one_shared_instance():
    assert make_parser() is make_parser()


def test_render_does_not_mutate_the_shared_parser():
    before = dict(make_parser().options)
    extensions_before = list(make_parser().options["parser_extension"])
    ast_to_markdown(markdown_to_ast(SAMPLE))
    assert dict(make_parser().options) == before
    assert make_parser().options["parser_extension"] == extensions_before


def test_canonicalise_is_stable_across_repeated_calls():
    once = canonicalise(SAMPLE)
    assert [canonicalise(SAMPLE) for _ in range(3)] == [once, once, once]
