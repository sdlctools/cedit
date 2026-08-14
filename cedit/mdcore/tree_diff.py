"""
Merkle-hashed AST over Markdown — what a block *is*.

The hashing and segmentation engine. cedit uses it for segmentation
(`is_unit`, `OPAQUE`, `_unit_source`), hashing (`hash_tree` — every hash in
`.cedit/` state is one of these), similarity (`ratio` and the two
thresholds) and the `diff` view's clipping. FROZEN: a change here moves
every recorded hash. The design rationale is `docs/SPEC.md`; the procedure for
changing it anyway is `.claude/rules/hash-stability.md`.

Why Merkle hashing: hash(node) = H(type, tag, own_text, hash(c1)…hash(cn)).
Two subtrees are identical iff their hashes match, so a single O(n) pass
gives every block a content identity that survives being moved and survives
reflow. That is what lets an alignment pair blocks by equality before it
compares any text, and what lets `.cedit/` state name a block at all. The
pairing itself is `cedit/align.py`'s job, not this module's.
"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from markdown_it.tree import SyntaxTreeNode

# ---------------------------------------------------------------------------
# Node classification
# ---------------------------------------------------------------------------

# Blocks that carry prose. In markdown-it's tree these are exactly the nodes
# owning an `inline` child: that child's `.content` is the raw markdown source
# of the segment (`` Reference for `x`. Read **this** ``) — the text a local
# adaptation rewrites. docs/SPEC.md, *Edit blocks*, maps this module's
# vendored names.
UNIT_PARENTS = {"heading", "paragraph", "th", "td"}

# Opaque blocks: hashed, so a change or a move is noticed, but never units.
OPAQUE = {"fence", "code_block", "html_block", "front_matter", "hr"}

_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    """Whitespace-insensitive normalisation.

    Reflowing a paragraph (80 cols -> 72 cols) must NOT re-key it and strand
    the local edit overlaid on it, so whitespace collapses before hashing.
    """
    return _WS.sub(" ", text or "").strip()


def is_unit(node: SyntaxTreeNode) -> bool:
    return node.type in UNIT_PARENTS


def attr(node: SyntaxTreeNode, name: str, default=""):
    """Safe accessor — the root node raises on tag/content/map/level/info."""
    if node.type == "root":
        return default
    try:
        return getattr(node, name, default) or default
    except AttributeError:
        return default


def own_text(node: SyntaxTreeNode) -> str:
    """The text this node contributes on its own (excluding children)."""
    return attr(node, "content")


# ---------------------------------------------------------------------------
# 1. Merkle hashing
# ---------------------------------------------------------------------------


def hash_tree(node: SyntaxTreeNode) -> str:
    """Annotate every node with `.h`, its Merkle hash.

    Deliberately excluded from the hash:
      * `map` (line numbers)  — shift on every insert above
      * `level`               — shifts when nesting changes elsewhere
    Included: type, tag, `info` (fence language), and normalised own text.
    """
    if is_unit(node):
        # A unit's identity is its inline source; its children are just the
        # parsed view of that same string.
        payload = f"{node.type}|{attr(node, 'tag')}|{norm(_unit_source(node))}"
        h = hashlib.sha256(payload.encode()).hexdigest()[:16]
        node.h = h
        for c in node.children:
            hash_tree(c)
        return h

    parts = [node.type, attr(node, "tag"), attr(node, "info")]
    if not node.children:
        parts.append(norm(own_text(node)))
    for child in node.children:
        parts.append(hash_tree(child))
    node.h = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return node.h


def _unit_source(node: SyntaxTreeNode) -> str:
    for c in node.children:
        if c.type == "inline":
            return c.content or ""
    return own_text(node)


# ---------------------------------------------------------------------------
# 2. Similarity — is this the same block, edited?
# ---------------------------------------------------------------------------

# Below this, two nodes are considered unrelated rather than "one edited into
# the other". GumTree (Falleri et al., ASE'14) uses 0.5 for structural
# similarity; 0.4 is a little more eager, which is what we want for prose.
SIM_THRESHOLD = 0.4


def ratio(a: str, b: str) -> float:
    """Normalised text similarity in [0, 1].

    `autojunk=False` is not optional here. difflib's default heuristic marks any
    element occurring in >1% of a sequence as junk once the sequence reaches 200
    items — on *character* sequences that is every common letter, which both
    skews the score on long paragraphs and makes it asymmetric.
    """
    return SequenceMatcher(None, norm(a), norm(b), autojunk=False).ratio()


# ---------------------------------------------------------------------------
# 3. Heading trail, and the fuzzy-match cut-off
# ---------------------------------------------------------------------------


def _heading_trail(node: SyntaxTreeNode) -> str:
    """Ancestor headings above `node` — the trail that names a block to a
    human: display only, but recorded in `.cedit/`'s conflict entries."""
    trail: list[str] = []
    cur = node
    while cur is not None and cur.type != "root":
        parent = cur.parent
        if parent is None:
            break
        sibs = parent.children
        for sib in sibs[: sibs.index(cur)][::-1]:
            if sib.type == "heading":
                trail.append(norm(_unit_source(sib)))
                break
        cur = parent
    return " › ".join(reversed(trail))


# Floor for the moved-and-edited pairing: a weaker match costs more to repair
# than to redo — why SDL/Trados and memoQ cut translation-memory reuse at 70%.
FUZZY_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Display helpers (used by cedit's `diff` view)
# ---------------------------------------------------------------------------

WIDTH = 110


def _clip(text: str, start: int = 0) -> str:
    body = norm(text)
    frag = body[start:start + WIDTH]
    return ("…" if start else "") + frag + ("…" if start + WIDTH < len(body) else "")


def _focus(old: str, new: str) -> tuple[str, str]:
    """Clip both sides around their *first difference*.

    Plain head-truncation hides the edit whenever it falls past the cut-off,
    which makes an edit line look like it reports two identical strings.
    """
    o, n = norm(old), norm(new)
    lead = 30
    for tag, i1, _i2, j1, _j2 in SequenceMatcher(None, o, n, autojunk=False).get_opcodes():
        if tag != "equal":
            return _clip(o, max(0, i1 - lead)), _clip(n, max(0, j1 - lead))
    return _clip(o), _clip(n)


