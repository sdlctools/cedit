"""Block extraction and splicing — cedit's view of a document.

A document is a sequence of **edit blocks** in document order:

- *inline units* — the nodes owning an `inline` child (`heading`,
  `paragraph`, `th`, `td`), exactly `tree_diff`'s translation units;
- *opaque blocks* — `fence`, `code_block`, `html_block`, `front_matter`,
  `hr`. `tree_diff` only ever copies these (COPY); here they are
  first-class, because the motivating local edit is a rewritten code fence.

Identity is the Merkle hash `tree_diff.hash_tree` assigns, disambiguated by
per-hash occurrence index (a user may edit only the third copy of a repeated
command — translation never had to care, editing does).

The splice follows strict invariants: block structure comes from the tree
being spliced *into* and is never re-derived from replacement text; a unit
splice replaces only the `inline` token's children/content (re-parsed with
`parse_inline`, so text starting with `- ` stays a paragraph); an opaque
splice replaces only the token's `content` (plus `info` for fences — that is
where ```` ```bash ```` → ```` ```zsh ```` lives).
Every render re-parses its own output and refuses to pass if the block
structure moved (`StructureMismatch`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it.tree import SyntaxTreeNode

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
    its tree, and the flat block sequence."""

    canonical: str
    tokens: list
    root: SyntaxTreeNode
    blocks: list[Block]

    @property
    def doc_hash(self) -> str:
        return self.root.h


def canonicalise(md: str) -> str:
    """The mdformat round-trip every hash in `.cedit/` state is taken over."""
    return ast_to_markdown(markdown_to_ast(md))


def parse_doc(md: str, *, canonical: bool = False) -> ParsedDoc:
    text = md if canonical else canonicalise(md)
    tokens = markdown_to_ast(text)
    root = SyntaxTreeNode(tokens)
    tree_diff.hash_tree(root)

    blocks: list[Block] = []

    def walk(node: SyntaxTreeNode) -> None:
        if tree_diff.is_unit(node):
            blocks.append(Block(UNIT, node.type, node.h, 0,
                                tree_diff._unit_source(node), "",
                                tree_diff._heading_trail(node), node))
            return
        if node.type in tree_diff.OPAQUE:
            blocks.append(Block(OPAQUE, node.type, node.h, 0,
                                tree_diff.own_text(node),
                                tree_diff.attr(node, "info"),
                                tree_diff._heading_trail(node), node))
            return
        for child in node.children:
            walk(child)

    for child in root.children:
        walk(child)

    seen: dict[str, int] = {}
    for block in blocks:
        block.occurrence = seen.get(block.hash, 0)
        seen[block.hash] = block.occurrence + 1

    return ParsedDoc(text, tokens, root, blocks)


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


def splice_block(block: Block, text: str, info: str = "") -> bool:
    """Replace `block`'s editable content in its tree, in place.

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
    rendered = ast_to_markdown(doc.tokens)
    want = block_signature(doc.canonical)
    got = block_signature(rendered)
    if want != got:
        raise StructureMismatch(
            f"{label}: rendered block structure differs — {_first_difference(want, got)}"
        )
    return rendered
