"""Block extraction and splicing — cedit's view of a document.

A document is a sequence of **edit blocks** in document order:

- *inline units* — the nodes owning an `inline` child (`heading`,
  `paragraph`, `th`, `td`), exactly `tree_diff.is_unit`;
- *opaque blocks* — `fence`, `code_block`, `html_block`, `front_matter`,
  `hr`. `tree_diff` hashes these but never makes them units; here they are
  first-class, because the motivating local edit is a rewritten code fence.

Identity is the Merkle hash `tree_diff.hash_tree` assigns, disambiguated by
per-hash occurrence index: a user may have adapted only the third copy of a
repeated command, so two byte-identical blocks have to stay distinct.

The splice follows strict invariants: block structure comes from the tree
being spliced *into* and is never re-derived from replacement text; a unit
splice replaces only the `inline` token's children/content (re-parsed with
`parse_inline`, so text starting with `- ` stays a paragraph); an opaque
splice replaces only the token's `content` (plus `info` for fences — that is
where ```` ```bash ```` → ```` ```zsh ```` lives).
Every render re-parses its own output and refuses to pass if the block
structure moved (`StructureMismatch`).

Fragile `$...$` math is carried through all of this as a sentinel
(`mathguard`): the token stream holds the sentinel, so mdformat never sees
the backslash it would escape, and every text that leaves this module —
`ParsedDoc.canonical`, `Block.text`, the render — is restored first. A
`ParsedDoc` therefore owns the sentinel map for its own tree, and a splice
registers the math in the text it splices in.

Text a table's body row carries past the header's last column is carried
through the same way, and for the same reason — the parser drops it — but
lifted out and re-appended by row ordinal rather than swapped for a sentinel
(`rowguard`). It belongs to no block, so a `ParsedDoc` owns it alongside the
sentinel map and a splice never sees it. `rowguard.protect` runs **first**,
on the source as written: it shortens row lines, and `mathguard`'s offsets
are taken over whatever it is handed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it.tree import SyntaxTreeNode

from . import rowguard
from .mathguard import protect, restore
from .mdcore import tree_diff
from .mdcore.utils import ast_to_markdown, markdown_to_ast, parse_inline

UNIT = "unit"
OPAQUE = "opaque"

# A newline spliced into a table cell ends the GFM row — collapse whitespace
# for cells only (mdformat already collapses newlines inside a heading).
SINGLE_LINE_TYPES = {"th", "td"}
_WS = re.compile(r"\s+")

# A task-list item's checkbox is block structure parked in an inline child;
# it must be carried across a splice, never replaced. See reassembly spec.
_TASKLIST_CHECKBOX = 'class="task-list-item-checkbox"'


class StructureMismatch(RuntimeError):
    """The rendered document's block structure differs from the tree it was
    spliced into — the one corruption a splice-only design could ship
    invisibly, so it is checked on every render."""


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


@dataclass
class Block:
    kind: str            # UNIT | OPAQUE
    node_type: str       # paragraph / heading / td / fence / front_matter / ...
    hash: str            # tree_diff.hash_tree's 16-hex-char Merkle hash
    occurrence: int      # per-hash index in document order (0-based)
    text: str            # unit: inline source; opaque: token content
    info: str            # fence info string ("bash", "zsh") — "" otherwise
    context: str         # heading trail
    node: SyntaxTreeNode = field(repr=False)

    @property
    def key(self) -> str:
        return f"{self.hash}:{self.occurrence}"

    @property
    def compare_text(self) -> str:
        """What similarity is measured over — the info string is part of the
        editable surface (```bash → ```zsh is an edit, not a replacement)."""
        return f"{self.info}\n{self.text}" if self.info else self.text


@dataclass
class ParsedDoc:
    """One canonicalised document: the token stream (mutable, renderable),
    its tree, and the flat block sequence.

    `canonical` and every `Block.text` read as the document does. `tokens`
    and the hashes taken over them read with the math replaced by sentinels
    — that is what keeps the render from escaping it — and with each body
    row's over-the-header text lifted out, which is what keeps the parser
    from discarding it. `math` and `rows` are the two maps back, both
    consulted by `render_verified`; `math` alone is extended by
    `splice_block`, since no block holds a row's surplus.
    """

    canonical: str
    tokens: list
    root: SyntaxTreeNode
    blocks: list[Block]
    math: dict[str, str] = field(default_factory=dict, repr=False)
    rows: tuple[rowguard.RowOverflow, ...] = field(default=(), repr=False)

    @property
    def doc_hash(self) -> str:
        return self.root.h


def canonicalise(md: str) -> str:
    """The mdformat round-trip every hash in `.cedit/` state is taken over.

    Fragile math goes through it untouched: the round-trip runs over the
    sentinels, and the original bytes go back into the result (`mathguard`).
    A body row's over-the-header text does too, lifted out before the parse
    and appended back onto its row after the render (`rowguard`).
    """
    rows = rowguard.protect(md)
    guarded = protect(rows.text)
    rendered = ast_to_markdown(markdown_to_ast(guarded.text))
    return rows.restore(restore(rendered, guarded.spans))


def parse_doc(md: str, *, canonical: bool = False) -> ParsedDoc:
    # `canonical=True` says the caller already holds canonical bytes (a base
    # snapshot), so only the protection pass runs. Either way the tree is
    # built over the *protected* text, and `protect` is its own inverse over
    # `restore`, so both routes reach the same sentinels — and therefore the
    # same hashes — for the same document.
    rows = rowguard.protect(md)
    guarded = protect(rows.text)
    text = guarded.text if canonical else \
        ast_to_markdown(markdown_to_ast(guarded.text))
    math = dict(guarded.spans)
    tokens = markdown_to_ast(text)
    root = SyntaxTreeNode(tokens)
    tree_diff.hash_tree(root)

    blocks: list[Block] = []

    def walk(node: SyntaxTreeNode) -> None:
        if tree_diff.is_unit(node):
            blocks.append(Block(UNIT, node.type, node.h, 0,
                                restore(tree_diff._unit_source(node), math), "",
                                restore(tree_diff._heading_trail(node), math),
                                node))
            return
        if node.type in tree_diff.OPAQUE:
            blocks.append(Block(OPAQUE, node.type, node.h, 0,
                                tree_diff.own_text(node),
                                tree_diff.attr(node, "info"),
                                restore(tree_diff._heading_trail(node), math),
                                node))
            return
        for child in node.children:
            walk(child)

    for child in root.children:
        walk(child)

    seen: dict[str, int] = {}
    for block in blocks:
        block.occurrence = seen.get(block.hash, 0)
        seen[block.hash] = block.occurrence + 1

    return ParsedDoc(rows.restore(restore(text, math)), tokens, root, blocks,
                     math, rows.overflows)


# --------------------------------------------------------------------------
# Structural signature
# --------------------------------------------------------------------------


def block_signature(md: str) -> tuple:
    """Nested `(type, ...)` tuple of the document's *block* structure.

    Stops at `inline`: what is inside an edit block may differ, what
    contains it may not.
    """

    def walk(node) -> tuple:
        if node.type == "inline":
            return ("inline",)
        head = node.type if node.type == "root" else f"{node.type}:{tree_diff.attr(node, 'tag')}"
        return (head,) + tuple(walk(c) for c in node.children)

    return walk(SyntaxTreeNode(markdown_to_ast(md)))


def _first_difference(a: tuple, b: tuple, path: str = "") -> str:
    if a == b:
        return ""
    if not isinstance(a, tuple) or not isinstance(b, tuple) or a[:1] != b[:1]:
        return f"{path or '<root>'}: expected {a!r} vs rendered {b!r}"
    here = f"{path}/{a[0]}"
    for i in range(max(len(a), len(b))):
        if i >= len(a):
            return f"{here}: rendered has an extra child {b[i]!r}"
        if i >= len(b):
            return f"{here}: rendered is missing child {a[i]!r}"
    diff = next((d for d in (_first_difference(a[i], b[i], here)
                             for i in range(len(a))) if d), "")
    return diff or f"{here}: differs"


# --------------------------------------------------------------------------
# Splicing
# --------------------------------------------------------------------------


def splice_block(doc: ParsedDoc, block: Block, text: str, info: str = "") -> bool:
    """Replace `block`'s editable content in `doc`'s tree, in place.

    `text` reads as the document does — it came from a `Block.text` or a
    conflict record — so any fragile math in it is protected on the way in
    and registered with `doc`, which is what lets the render put it back.
    An opaque block needs none of that: mdformat writes a fence, an HTML
    block or front matter out verbatim, backslashes included.

    Returns False when there is nothing to splice into (a unit with no
    `inline` child — an empty table cell); the caller decides what that
    means.
    """
    node = block.node
    if block.kind == OPAQUE:
        token = node.token
        token.content = text
        if node.type == "fence":
            token.info = info
        return True

    inline = next((c for c in node.children if c.type == "inline"), None)
    if inline is None:
        return False
    # Against the whole document, not the fragment: a sentinel chosen here has
    # to avoid text `doc` already contains and sentinels it already uses.
    guarded = protect(text, context=doc.canonical, taken=doc.math)
    doc.math.update(guarded.spans)
    text = guarded.text
    if node.type in SINGLE_LINE_TYPES:
        text = _WS.sub(" ", text).strip()
    children = parse_inline(text)
    first = (inline.token.children or [None])[0]
    if first is not None and first.type == "html_inline" and _TASKLIST_CHECKBOX in first.content:
        children.insert(0, first)
    inline.token.children = children
    inline.token.content = text
    return True


def render_verified(doc: ParsedDoc, *, label: str = "<doc>") -> str:
    """Render `doc.tokens` (post-splice) and verify the block structure still
    matches what the tree had before rendering. Raises StructureMismatch —
    and the caller must not write the file — otherwise returns the Markdown.
    """
    rendered = rowguard.restore(restore(ast_to_markdown(doc.tokens), doc.math),
                                doc.rows)
    want = block_signature(doc.canonical)
    got = block_signature(rendered)
    if want != got:
        raise StructureMismatch(
            f"{label}: rendered block structure differs — {_first_difference(want, got)}"
        )
    return rendered
