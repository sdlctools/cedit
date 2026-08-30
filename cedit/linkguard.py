"""Warn about link reference definitions that canonicalisation would drop.

Markdown lets a link be defined away from its use:

    [ref]: https://example.com

    Link to [ref].

The pinned parser (mdformat) inlines a definition wherever it is used and
**discards it everywhere it is not** — an unused `[ref]: …` line is content
loss with no trace downstream, the same shape of failure `mathguard` and
`rowguard` answer.

Unlike those two this guard only reports: an unused definition is genuinely
gone after the round-trip and there is nothing byte-exact to lift out and
put back. So `warn_link_refs` scans the source for definitions, subtracts
the ones actually referenced, and reports the rest on **stderr, leaving the
exit code alone** (AGENTS.md invariant 4). A document whose definitions are
all used says nothing. docs/userguide/help/limits.md is the user-facing
version of this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import guardreport
from .mathguard import mask_code_spans
from .mdcore.utils import markdown_to_ast


@dataclass(frozen=True)
class LinkRef:
    """One link reference definition."""

    line: int
    label: str
    url: str
    title: str | None


# Token types whose text is not prose: a definition inside one is preserved
# byte for byte by canonicalisation (code blocks) or passes straight through
# (HTML, front matter), so it is not at risk and must not be flagged.
_NON_PROSE_TYPES = frozenset({
    "fence", "code_block", "html_block", "front_matter",
})

# A link reference definition: `[label]: url` with an optional `"title"` or
# `'title'`, url optionally wrapped in `<>`.
_REF_DEF = re.compile(
    r"^\s*\[([^\]]+)\]\s*:\s*(?:<([^>]+)>|(\S+))"
    r"(?:\s+(?:\"([^\"]*)\"|'([^']*)'))?\s*$"
)


def _non_prose_line_ranges(md: str) -> list[tuple[int, int]]:
    """1-based inclusive line ranges of the non-prose regions in `md`."""
    ranges = []
    for token in markdown_to_ast(md):
        if token.type in _NON_PROSE_TYPES and token.map:
            start = token.map[0] + 1        # token.map is [start, end), 0-based
            end = token.map[1]              # → 1-based inclusive
            if start <= end:
                ranges.append((start, end))
    return ranges


def _in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line <= end for start, end in ranges)


def _find_link_ref_defs(md: str) -> dict[str, LinkRef]:
    """Every link reference definition in `md`, outside the non-prose regions."""
    non_prose = _non_prose_line_ranges(md)
    definitions: dict[str, LinkRef] = {}
    for i, line in enumerate(md.split("\n"), 1):
        if _in_ranges(i, non_prose):
            continue
        match = _REF_DEF.match(line)
        if match:
            label = match.group(1)
            url = match.group(2) or match.group(3)
            title = match.group(4) or match.group(5)
            definitions[label] = LinkRef(line=i, label=label, url=url, title=title)
    return definitions


def _find_used_refs(md: str, definitions: dict[str, LinkRef]) -> set[str]:
    """The subset of `definitions` actually referenced in `md`'s prose.

    Scans inline-token content only, with code spans masked out first — a
    `[label]` inside a backtick span is text, not a reference, exactly as
    `mathguard` masks them before its own scan.
    """
    if not definitions:
        return set()

    used: set[str] = set()
    for token in markdown_to_ast(md):
        if token.type != "inline" or not token.content:
            continue
        src = mask_code_spans(token.content)

        # Full reference links: `[text][label]`, but not `![text][label]`.
        for m in re.finditer(r"(?<!!)\[([^\]]+)\]\s*\[([^\]]+)\]", src):
            if m.group(2) in definitions:
                used.add(m.group(2))

        # Shortcut reference links: a bare `[label]` that is neither an image,
        # an inline link `[text](url)`, nor a definition `[label]:`.
        for m in re.finditer(r"(?<!!)\[([^\]]+)\]", src):
            label = m.group(1)
            if not label.strip():
                continue
            after = src[m.end():m.end() + 1]
            if after in (":", "("):
                continue
            if label in definitions:
                used.add(label)

    return used


def find_link_refs(md: str) -> tuple[dict[str, LinkRef], set[str]]:
    """`(definitions, used_labels)` for `md`.

    `definitions` maps label → `LinkRef`; `used_labels` is the subset
    referenced in prose. Both consult the parser's AST so definitions and
    references inside code blocks, HTML blocks and front matter are ignored —
    canonicalisation does not touch those.
    """
    definitions = _find_link_ref_defs(md)
    return definitions, _find_used_refs(md, definitions)


def warn_link_refs(md: str, label: str, *, stream=None) -> list[LinkRef]:
    """Report the unused link reference definitions in `md` on stderr.

    Returns the reported `LinkRef`s, so the tests can assert on the detection
    rather than on the wording. **Never touches the exit code.**
    """
    definitions, used = find_link_refs(md)
    unused = [ref for lbl, ref in definitions.items() if lbl not in used]

    def detail(ref: LinkRef) -> str:
        text = f"[{ref.label}]: {ref.url}"
        return f'{text} "{ref.title}"' if ref.title else text

    return list(guardreport.emit(
        label, unused, stream=stream,
        summary=f"{len(unused)} link reference definition(s) would be lost "
                f"during canonicalisation",
        detail=detail,
        footer="    Link reference definitions (`[label]: https://…`) are "
               "inlined where they are\n"
               "    used and silently dropped where they are not. Use the "
               "reference, or make it a\n"
               "    direct link — the user guide, *Limits, stated plainly*:",
    ))
