"""The pinned parser configuration — VENDORED from markdown-localization
`app/utils.py`, trimmed to the four functions cedit uses.

One `make_parser` because every consumer must agree: snapshots are hashed
over what this parses, and the merge re-parses spliced inline content with
the *same* rules (`parse_inline`). Two copies of this setup drifting apart
would change token streams under recorded hashes — which is also why
`requirements.txt` pins the whole parsing stack exactly.
"""

from markdown_it import MarkdownIt
from mdformat.renderer import MDRenderer
import mdformat.plugins


def make_parser() -> MarkdownIt:
    """A parser configured exactly as the whole pipeline expects it."""
    md = MarkdownIt("gfm-like2")
    md.options["linkify"] = False
    # markdown-it-py >= 4.2's `gfm-like2` parses task lists *natively*: it sets
    # `class="task-list-item"` and eats the `[ ] ` marker, but emits no token
    # for the checkbox. `mdformat_gfm`'s list-item renderer was written against
    # `mdit_py_plugins.tasklists`, which *does* emit one — so the native
    # implementation is switched off and the plugin (installed by
    # `mdformat_gfm.update_mdit` below) owns task lists. Hash-neutral.
    md.options["tasklists"] = False
    # Same story: `gfm-like2` parses GitHub alerts (`> [!NOTE]`) into `alert`
    # nodes mdformat cannot render at all. Off, they are ordinary blockquotes,
    # which round-trip byte-for-byte and render identically on GitHub.
    md.options["alerts"] = False
    md.options["parser_extension"] = []

    # Dynamically load EVERY installed mdformat plugin (GFM, tables,
    # frontmatter, ...).
    for plugin in mdformat.plugins.PARSER_EXTENSIONS.values():
        if plugin not in md.options["parser_extension"]:
            md.options["parser_extension"].append(plugin)
            plugin.update_mdit(md)

    return md


def markdown_to_ast(raw_markdown) -> list:
    """Parse Markdown into markdown-it tokens."""
    return make_parser().parse(raw_markdown)


def parse_inline(text: str) -> list:
    """Tokenize `text` as *inline* markdown — no block parsing at all.

    The splice needs this: a replacement segment is inline content by
    definition, so text that happens to start with `- ` or `1. ` must stay
    one paragraph rather than becoming a list.
    """
    return make_parser().parseInline(text, {})[0].children or []


def ast_to_markdown(tokens) -> str:
    """Render tokens back to canonical Markdown (the mdformat round-trip)."""
    md = make_parser()
    options = dict(md.options)
    options["mdformat"] = {
        "number": True,        # consecutive numbering for ordered lists
        "wrap": "keep",        # retain semantic line breaks
        "compact_tables": True,
    }
    # NOTE: do NOT overwrite options["parser_extension"] here.
    return MDRenderer().render(tokens, options, {})
