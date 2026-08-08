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


@dataclass(frozen=True)
class LinkRef:
    """One link reference definition."""
    line: int
    label: str
    url: str
    title: str | None


def find_link_refs(md: str) -> tuple[dict[str, LinkRef], set[str]]:
    """Find all link reference definitions and identify which are used.

    Returns (all_definitions, used_labels) where:
    - all_definitions maps label -> LinkRef
    - used_labels is the set of labels actually referenced in the text

    This is a heuristic detection - we look for patterns that suggest a
    reference is being used, but we may have false positives or negatives.
    The key goal is to warn about definitions that are definitely unused.
    """
    # Pattern for link reference definitions: [label]: url "title"
    # Title is optional, and url can be in <>
    ref_pattern = re.compile(
        r'^\s*\[([^\]]+)\]\s*:\s*(?:<([^>]+)>|([^\s]+))\s*(?:"([^"]*)")?\s*$'
    )

    definitions = {}
    used = set()

    lines = md.split('\n')
    in_code_block = False

    # First pass: find all definitions
    for i, line in enumerate(lines, 1):
        match = ref_pattern.match(line)
        if match:
            label = match.group(1)
            url = match.group(2) or match.group(3)
            title = match.group(4)
            definitions[label] = LinkRef(line=i, label=label, url=url, title=title)

    if not definitions:
        return {}, set()

    # Second pass: find all used references
    # We use a simple heuristic: look for [label] patterns that are likely references
    for i, line in enumerate(lines, 1):
        # Track code block state
        if line.startswith('```') or line.startswith('~~~'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # Skip if this line is a definition
        if ref_pattern.match(line):
            continue

        # Look for reference-style links [text][label]
        # This is the clearest signal that a reference is being used
        # But skip if preceded by ! (image syntax)
        pos = 0
        while pos < len(line):
            # Find patterns like [text][label]
            match = re.search(r'\[([^\]]+)\]\s*\[([^\]]+)\]', line[pos:])
            if not match:
                break

            full_match_start = pos + match.start()
            label = match.group(2)

            # Check if preceded by ! (image syntax)
            if full_match_start > 0 and line[full_match_start-1] == '!':
                pos = full_match_start + len(match.group(0))
                continue

            if label in definitions:
                used.add(label)

            pos = full_match_start + len(match.group(0))

        # Look for shortcut reference-style links [label]
        # These are harder to detect reliably, so we use a simple heuristic:
        # [label] followed by punctuation, whitespace, or end of line
        # and not preceded by ! (which would make it an image)
        pos = 0
        while pos < len(line):
            # Find the next [
            open_bracket = line.find('[', pos)
            if open_bracket == -1:
                break

            # Check if preceded by ! (image syntax)
            if open_bracket > 0 and line[open_bracket-1] == '!':
                pos = open_bracket + 1
                continue

            # Find the matching ]
            close_bracket = line.find(']', open_bracket)
            if close_bracket == -1:
                pos = open_bracket + 1
                continue

            # Extract the label
            label = line[open_bracket+1:close_bracket]
            if not label or label in ('', ' '):
                pos = close_bracket + 1
                continue

            # Check if this is a reference definition [label]:
            if close_bracket + 1 < len(line) and line[close_bracket+1] == ':':
                pos = close_bracket + 1
                continue

            # Check if followed by ( which would make it an inline link [text](url)
            if close_bracket + 1 < len(line) and line[close_bracket+1] == '(':
                pos = close_bracket + 1
                continue

            # If the label matches a definition, count it as used
            if label in definitions:
                # Additional check: make sure this isn't part of a longer pattern
                # by checking what comes after the ]
                after = close_bracket + 1
                if after >= len(line) or not line[after].isalnum():
                    # Followed by whitespace, punctuation, or end of line
                    used.add(label)

            pos = close_bracket + 1

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
        print(f"    line {ref.line}: [{ref.label}]: {ref.url}", file=out)

    print("    Link reference definitions (e.g., '[label]: https://...') are "
          "inlined when used,", file=out)
    print("    but unused definitions are silently dropped. Either use the "
          "reference or convert it", file=out)
    print("    to a direct link. See USERGUIDE.md for details.", file=out)

    return unused
