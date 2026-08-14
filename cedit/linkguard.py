"""Preserve link reference definitions that canonicalisation would otherwise drop.

Markdown allows link references to be defined separately from their use:

    [ref]: https://example.com

    Link to [ref].

The pinned parser (mdformat) inlines these definitions on render, converting
them to direct links. This is semantically correct for used references, but
destroys unused references entirely — content loss with no warning.

This module preserves them by:
1. Detecting link reference definitions in the source
2. Warning about unused definitions that would be lost
3. Optionally preserving them in the output (future work)

The immediate fix is detection + warning, wired exactly like the fragile-math
alarm: stderr only, exit code untouched, so a clean document says nothing.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from .mdcore.utils import markdown_to_ast
from .mdcore import tree_diff


@dataclass(frozen=True)
class LinkRef:
    """One link reference definition."""
    line: int
    label: str
    url: str
    title: str | None


# Token types that contain non-prose content where definitions should NOT be detected
_NON_PROSE_TYPES = frozenset({
    "fence",         # fenced code blocks
    "code_block",    # indented code blocks
    "html_block",    # HTML blocks
    "front_matter",  # YAML front matter
})


def _non_prose_line_ranges(md: str) -> list[tuple[int, int]]:
    """Return line ranges (1-based, inclusive) of non-prose regions.

    Definitions inside these regions are not lost during canonicalisation
    (code blocks are preserved byte-for-byte, HTML blocks pass through),
    so we exclude them from detection.
    """
    ranges = []
    for token in markdown_to_ast(md):
        if token.type in _NON_PROSE_TYPES and token.map:
            # map is [start_line, end_line] 0-based, end is exclusive
            # Convert to 1-based inclusive range
            start = token.map[0] + 1
            end = token.map[1]  # already 1-based after +1 to inclusive
            if start <= end:
                ranges.append((start, end))
    return ranges


def _line_in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
    """Check if a line number falls within any of the ranges."""
    for start, end in ranges:
        if start <= line <= end:
            return True
    return False


def _find_link_ref_defs(md: str) -> dict[str, LinkRef]:
    """Find all link reference definitions in the markdown source.

    Scans the raw source but excludes definitions inside non-prose regions
    (code blocks, HTML blocks, front matter) by consulting the AST.
    """
    non_prose = _non_prose_line_ranges(md)

    # Pattern for link reference definitions: [label]: url "title" or 'title'
    # Title is optional, and url can be in <>
    # Allows both single and double quoted titles
    ref_pattern = re.compile(
        r'^\s*\[([^\]]+)\]\s*:\s*(?:<([^>]+)>|([^\s]+))'
        r'(?:\s+(?:"([^"]*)"|\'([^\']*)\'))?\s*$'
    )

    definitions = {}
    for i, line in enumerate(md.split('\n'), 1):
        # Skip lines inside non-prose regions
        if _line_in_ranges(i, non_prose):
            continue
        match = ref_pattern.match(line)
        if match:
            label = match.group(1)
            url = match.group(2) or match.group(3)
            title = match.group(4) or match.group(5)
            definitions[label] = LinkRef(line=i, label=label, url=url, title=title)
    return definitions


def _find_used_refs(md: str, definitions: dict[str, LinkRef]) -> set[str]:
    """Find all used reference labels in the markdown source.

    Scans only inline tokens (excludes code blocks, HTML blocks, front matter).
    Returns the set of labels that are actually referenced.
    """
    if not definitions:
        return set()

    used = set()
    for token in markdown_to_ast(md):
        # Only inline tokens carry prose where references can be used
        if token.type != "inline" or not token.content:
            continue

        src = token.content

        # Look for full reference links: [text][label]
        # Skip if preceded by ! (image syntax)
        for m in re.finditer(r'(?<!\!)\[([^\]]+)\]\s*\[([^\]]+)\]', src):
            label = m.group(2)
            if label in definitions:
                used.add(label)

        # Look for shortcut reference links: [label]
        # Must not be preceded by ! (image) or followed by ( (inline link)
        # Must not be a definition line (followed by :)
        for m in re.finditer(r'(?<!\!)\[([^\]]+)\]', src):
            label = m.group(1)
            if not label or label in ('', ' '):
                continue
            start, end = m.span()

            # Skip if this is a definition: [label]:
            if end < len(src) and src[end] == ':':
                continue

            # Skip if followed by ( — inline link [text](url)
            if end < len(src) and src[end] == '(':
                continue

            # If the label matches a definition, count it as used
            if label in definitions:
                used.add(label)

    return used


def find_link_refs(md: str) -> tuple[dict[str, LinkRef], set[str]]:
    """Find all link reference definitions and identify which are used.

    Returns (all_definitions, used_labels) where:
    - all_definitions maps label -> LinkRef
    - used_labels is the set of labels actually referenced in the text

    Uses the parser's AST to exclude non-prose regions (code blocks, HTML
    blocks, front matter) from definition scanning, so definitions inside
    those regions are correctly ignored — they are NOT lost during
    canonicalisation. Usage tracking also uses the AST's inline tokens,
    so references inside code blocks are not counted as "used".
    """
    definitions = _find_link_ref_defs(md)
    used = _find_used_refs(md, definitions)
    return definitions, used


def warn_link_refs(md: str, label: str, *, stream=None) -> list[LinkRef]:
    """Warn about link reference definitions that would be lost.

    Reports unused definitions on stderr, leaving the exit code alone.
    Returns the list of unused definitions that were reported.
    """
    definitions, used = find_link_refs(md)

    if not definitions:
        return []

    # Identify unused definitions
    unused = [ref for label, ref in definitions.items() if label not in used]

    if not unused:
        return []

    out = sys.stderr if stream is None else stream

    print(f"{label}: warning: {len(unused)} link reference definition(s) "
          f"would be lost during canonicalisation", file=out)

    for ref in unused:
        line = f"    line {ref.line}: [{ref.label}]: {ref.url}"
        if ref.title:
            line += f" \"{ref.title}\""
        print(line, file=out)

    print("    Link reference definitions (e.g., '[label]: https://...') are "
          "inlined when used,", file=out)
    print("    but unused definitions are silently dropped. Either use the "
          "reference or convert it", file=out)
    print("    to a direct link. See the user guide for details:", file=out)
    print("    https://sdlctools.github.io/cedit/docs/userguide/limits",
          file=out)

    return unused
