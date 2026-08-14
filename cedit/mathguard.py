"""Preserve LaTeX math that canonicalisation would otherwise rewrite.

GitHub renders `$...$` and `$$...$$` as math. The pinned parser does not
know that syntax at all, so to it the delimiters are ordinary text and
whatever sits between them is ordinary inline content — harmless right up
to the point where that content holds a **backslash**. Left alone,
`$\\rightarrow$` canonicalises to `$\\\\rightarrow$`: a correct CommonMark
escape of a literal backslash, and a *line break* inside GitHub's math. The
rendered page changes.

Nothing downstream could catch that. The block structure is identical, so
`blocks.render_verified` passes; every hash is taken over the already
rewritten text, so the merge sees no edit; the working copy and
`.cedit/base/` are written and cedit exits 0 — the silent clobber AGENTS.md
invariant 3 forbids outright, on a line nobody touched.

So this module does not merely report it: it **prevents** it. `protect`
replaces every fragile span with an alphanumeric sentinel *before* the
document is parsed, and `restore` puts the original bytes back into the
rendered output afterwards:

    source -> protect(sentinel) -> parse -> render -> restore -> canonical

A sentinel is inert to the parser and to mdformat's renderer — one run of
`[a-z0-9]`, nothing to escape, nothing to reflow — so the round-trip cannot
touch what it stands for, and the span comes back byte for byte. The
sentinel is content-derived (a prefix plus a digest of the span), which is
what keeps it deterministic across machines and across the two ways cedit
reaches the same canonical text; it is collision-checked against the
document all the same. `blocks.canonicalise`, `blocks.parse_doc`,
`blocks.splice_block` and `blocks.render_verified` are the four users, and
between them they cover every path that writes.

The fix lives here rather than in the parser because `cedit/mdcore/` is
frozen and no plugin can help: every published `mdformat-dollarmath`
requires `mdformat<0.8` against this repo's pinned `mdformat==1.0.0`, and
`mdformat-myst` drags in a second frontmatter plugin, which is a
parser-identity problem of its own.

Detection is deliberately narrow — a false positive on prose costs more
than a missed span. Only a `$`- or `$$`-delimited run whose content holds
a backslash is reported, and only where the parser put inline content:
fenced blocks, indented code, HTML blocks and front matter are not inline
tokens at all, and code spans are masked out below. Everything measured
byte-stable stays quiet, `$100 and $200` and `$x + y = z$` included. That
narrowness now decides what gets *preserved*, not just what gets mentioned,
so an unflagged span is one canonicalisation was already leaving alone.

`warn_fragile_math` survives as the fallback alarm, and only that. A span
is protected by rewriting the **source**, which needs its absolute offsets;
`find_fragile_math` derives them by locating each inline token's own lines
back in the source, and a handful of constructs defeat that (a table cell
holding `\\|`, whose inline content is already unescaped, is the reachable
one). Those spans — and no others — are reported on **stderr, leaving the
exit code alone** (AGENTS.md invariant 4), because they are the only ones
still exposed to the old rewrite. A clean document says nothing at all now.
docs/userguide/help/limits.md is the user-facing version of this paragraph.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass

from .mdcore import tree_diff
from .mdcore.utils import markdown_to_ast

# Written over code spans before the dollar scan: a character that can neither
# open nor close anything, and one byte wide, so source offsets stay valid.
_MASK = "\x00"

# Sentinel shape: `[a-z0-9]+`, so neither the parser nor mdformat's renderer
# has anything to do with it — no escaping, no emphasis, no list marker, no
# autolink (linkify is off anyway). The digest makes it a function of the span
# it stands for, so protecting the same span twice — in a source and in the
# canonical form derived from it — yields the same sentinel and therefore the
# same hashes.
_PREFIX = "ceditmath"
_DIGEST = 16


@dataclass(frozen=True)
class MathSpan:
    """One `$`/`$$` run whose content holds a backslash.

    `start`/`end` are absolute offsets into the source the span was found in,
    and they are what `protect` rewrites. They are `None` when the span could
    not be located there — see the module docstring — and such a span is what
    `warn_fragile_math` reports.
    """

    line: int    # 1-based, in the source as handed to `find_fragile_math`
    delim: str   # "$" or "$$"
    text: str    # the run as written, delimiters included
    start: int | None = None
    end: int | None = None


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------


def _mask_code_spans(src: str) -> str:
    """Blank out inline code spans, preserving length and every other offset.

    CommonMark's rule: a run of N backticks opens a code span that the next
    run of *exactly* N backticks closes; an unmatched run is literal text.
    A backslash escapes the character after it, so `` \\` `` opens nothing.
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        if src[i] == "\\":
            i += 2
            continue
        if src[i] != "`":
            i += 1
            continue
        j = i
        while j < n and src[j] == "`":
            j += 1
        close = _matching_backticks(src, j, j - i)
        if close is None:
            i = j                      # unmatched run — ordinary text
            continue
        for p in range(i, close):
            out[p] = _MASK
        i = close
    return "".join(out)


def _matching_backticks(src: str, start: int, run: int) -> int | None:
    """End offset (exclusive) of the next backtick run of exactly `run`."""
    i, n = start, len(src)
    while i < n:
        if src[i] != "`":
            i += 1
            continue
        j = i
        while j < n and src[j] == "`":
            j += 1
        if j - i == run:
            return j
        i = j
    return None


def _inline_close(masked: str, open_at: int) -> int | None:
    """Offset of the `$` closing an inline span opened at `open_at`, or None.

    GitHub's delimiter rules, which are also what keeps prose quiet: the
    opening `$` may not be followed by whitespace, the closing one may not be
    preceded by it, and an inline span does not cross a line. `$100 and $200`
    fails the closing rule and is therefore not a span at all.
    """
    i, n = open_at + 1, len(masked)
    if i >= n or masked[i].isspace():
        return None
    while i < n:
        c = masked[i]
        if c == "\n":
            return None
        if c == "\\":
            i += 2
            continue
        if c == "$" and not masked[i - 1].isspace():
            return i
        i += 1
    return None


def _spans(masked: str):
    """Yield `(delim, start, end)` for every `$`/`$$` run in `masked`."""
    i, n = 0, len(masked)
    while i < n:
        c = masked[i]
        if c == "\\":
            i += 2
            continue
        if c != "$":
            i += 1
            continue
        if masked.startswith("$$", i):
            close = masked.find("$$", i + 2)
            if close == -1:
                i += 2
                continue
            yield "$$", i, close + 2
            i = close + 2
            continue
        close = _inline_close(masked, i)
        if close is None:
            i += 1
            continue
        yield "$", i, close + 1
        i = close + 1


def _line_offsets(md: str) -> list[int]:
    """Absolute offset of the start of each line of `md`."""
    starts = [0]
    for index, char in enumerate(md):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _content_line_offsets(content: str, first_line: int, src_lines: list[str],
                          line_offset: list[int],
                          cursor: dict[int, int]) -> list[int | None]:
    """Where each line of an inline token's `content` sits in the source.

    An inline token's `.content` is the raw source of its region with the
    block-level prefix removed — a list marker, a `>`, the indentation of a
    continuation line — so content line *k* is a substring of source line
    `first_line + k`, and finding it there recovers the column the block
    parser dropped. `cursor` carries the search forward within a line so the
    cells of one table row, which all share it, resolve left to right instead
    of all matching the first one.

    `None` for a line whose content is not there verbatim: markdown-it hands
    back an *unescaped* table cell (`\\|` arrives as `|`), and a span on such a
    line cannot be rewritten in the source. The caller reports those.
    """
    out: list[int | None] = []
    for k, content_line in enumerate(content.split("\n")):
        line = first_line + k
        if line >= len(src_lines):
            out.append(None)
            continue
        at = src_lines[line].find(content_line, cursor.get(line, 0))
        if at < 0:
            out.append(None)
            continue
        out.append(line_offset[line] + at)
        cursor[line] = at + len(content_line)
    return out


def _absolute(offsets: list[int | None], content: str, pos: int) -> int | None:
    """Map an offset into an inline token's `content` to a source offset."""
    line = content.count("\n", 0, pos)
    if line >= len(offsets) or offsets[line] is None:
        return None
    return offsets[line] + pos - (content.rfind("\n", 0, pos) + 1)


def find_fragile_math(md: str) -> list[MathSpan]:
    """Every `$`/`$$` run in `md` whose content canonicalisation would rewrite.

    `md` is the **source** as written, not a canonical form: the point is to
    catch these before the round-trip, not after it. Spans come back in
    document order, each with the absolute offsets `protect` needs.
    """
    if "$" not in md:
        # Not an optimisation for its own sake: `protect` runs on every parse,
        # every canonicalisation and every splice, and this is the branch
        # almost all of them take. No dollar, no span, no parse.
        return []
    found: list[MathSpan] = []
    src_lines = md.split("\n")
    line_offset = _line_offsets(md)
    cursor: dict[int, int] = {}
    for token in markdown_to_ast(md):
        # Only `inline` tokens carry prose, and only they carry the raw source
        # of their own region (`.content`) plus the line it starts on
        # (`.map`). Fences, indented code, HTML blocks and front matter are
        # other token types, so they are excluded for free.
        if token.type != "inline" or not token.content:
            continue
        src = token.content
        first_line = token.map[0] if token.map else 0
        # Computed for every inline token, flagged or not: it is what advances
        # `cursor` past the cells of a table row that precede the flagged one.
        offsets = _content_line_offsets(src, first_line, src_lines,
                                        line_offset, cursor)
        masked = _mask_code_spans(src)
        for delim, start, end in _spans(masked):
            body = src[start + len(delim):end - len(delim)]
            if "\\" not in body:
                continue
            text = src[start:end]
            at = _absolute(offsets, src, start)
            to = _absolute(offsets, src, end)
            # The offsets are derived, so verify them against the source rather
            # than trusting the derivation: a span `protect` would rewrite into
            # the wrong bytes is worse than one it leaves alone and reports.
            if at is None or to is None or md[at:to] != text:
                at = to = None
            found.append(MathSpan(
                line=first_line + src.count("\n", 0, start) + 1,
                delim=delim,
                text=text,
                start=at,
                end=to,
            ))
    return found


# --------------------------------------------------------------------------
# Protect and restore
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Protected:
    """A source with its fragile math swapped out for sentinels."""

    text: str                       # `protect`'s input, spans replaced
    spans: dict[str, str]           # sentinel -> the original span, verbatim
    unprotected: tuple[MathSpan, ...]   # spans that could not be located

    def restore(self) -> str:
        return restore(self.text, self.spans)


def _sentinel(text: str, doc: str, taken: dict[str, str]) -> str:
    """A sentinel standing for `text`, colliding with nothing in `doc`.

    Content-derived, so the same span always gets the same sentinel — two
    occurrences of one span share it, and a document protected twice comes
    out identical. Collisions are then only against text the document already
    contains, or a digest clash between two different spans; both are
    resolved by counting up, deterministically.
    """
    base = _PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST]
    candidate, n = base, 0
    while candidate in doc or taken.get(candidate, text) != text:
        n += 1
        candidate = f"{base}{n}"
    return candidate


def protect(md: str, *, context: str | None = None,
            taken: dict[str, str] | None = None) -> Protected:
    """Replace every fragile math span in `md` with a sentinel.

    `context` and `taken` are for protecting a *fragment* that is about to
    join a larger document — a splice. Collisions must then be resolved
    against that document and the sentinels already in it, not against the
    fragment, or the fragment could pick a sentinel the document uses as
    literal text and `restore` would rewrite it.
    """
    spans = find_fragile_math(md)
    unprotected = tuple(s for s in spans if s.start is None)
    locatable = sorted((s for s in spans if s.start is not None),
                       key=lambda s: s.start)
    if not locatable:
        return Protected(md, {}, unprotected)

    against = md if context is None else context
    seen = dict(taken or {})
    mapping: dict[str, str] = {}
    out: list[str] = []
    prev = 0
    for span in locatable:
        if span.start < prev:       # overlapping — keep the first, drop this
            continue
        sentinel = _sentinel(span.text, against, seen)
        seen[sentinel] = mapping[sentinel] = span.text
        out.append(md[prev:span.start])
        out.append(sentinel)
        prev = span.end
    out.append(md[prev:])
    return Protected("".join(out), mapping, unprotected)


def restore(text: str, spans: dict[str, str]) -> str:
    """Put the original math back where `protect` left sentinels.

    Longest sentinel first: a collision-resolved sentinel is its base plus a
    counter, so the base would otherwise match inside it.
    """
    for sentinel in sorted(spans, key=len, reverse=True):
        text = text.replace(sentinel, spans[sentinel])
    return text


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def warn_fragile_math(md: str, label: str, *, stream=None) -> list[MathSpan]:
    """Report the math in `md` that `protect` could **not** cover, on stderr.

    The fallback alarm, not a running commentary: preserved spans — which is
    all of them, on every document measured — say nothing. **Never touches
    the exit code** (AGENTS.md invariant 4). Returns the reported spans, so
    the tests can assert on the detection rather than on the wording.
    """
    spans = list(protect(md).unprotected)
    if not spans:
        return spans
    out = sys.stderr if stream is None else stream
    print(f"{label}: warning: {len(spans)} dollar-delimited math span(s) "
          f"could not be located in the source", file=out)
    for span in spans:
        print(f"    line {span.line}: {tree_diff._clip(span.text)}", file=out)
    print("    cedit preserves $...$ byte for byte by rewriting the source "
          "around it, and\n"
          "    cannot for these — canonicalisation will escape the backslash "
          "($\\x -> $\\\\x),\n"
          "    which GitHub reads inside math as a line break, so the rendered "
          "maths changes.\n"
          "    Use a ```math fence for display math, and the Unicode character "
          "or a code span\n"
          "    inline — the user guide, *Limits, stated plainly*:\n"
          "    https://sdlctools.github.io/cedit/docs/userguide/limits",
          file=out)
    return spans
