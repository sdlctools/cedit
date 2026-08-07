"""Guard against LaTeX math that canonicalisation would silently rewrite.

GitHub renders `$...$` and `$$...$$` as math. The pinned parser does not
know that syntax at all, so to it the delimiters are ordinary text and
whatever sits between them is ordinary inline content — harmless right up
to the point where that content holds a **backslash**. `$\\rightarrow$`
canonicalises to `$\\\\rightarrow$`: a correct CommonMark escape of a
literal backslash, and a *line break* inside GitHub's math. The rendered
page changes.

Nothing downstream can catch it. The block structure is identical, so
`blocks.render_verified` passes; every hash is taken over the already
rewritten text, so the merge sees no edit; the working copy and
`.cedit/base/` are written and cedit exits 0. That is exactly the failure
shape AGENTS.md invariant 3 exists to forbid — a silent clobber — which is
why it is worth a guard even though the syntax is unsupported.

A guard rather than a fix, because a fix is blocked upstream: every
published `mdformat-dollarmath` requires `mdformat<0.8` against this
repo's pinned `mdformat==1.0.0`, and `mdformat-myst` drags in a second
frontmatter plugin, which is a parser-identity problem of its own. The
supported spelling for display math is a ```` ```math ```` fence, which
already round-trips byte for byte; inline, use the Unicode character or a
code span. USERGUIDE.md §13 is the user-facing version of this paragraph.

Detection is deliberately narrow — a false positive on prose costs more
than a missed span. Only a `$`- or `$$`-delimited run whose content holds
a backslash is reported, and only where the parser put inline content:
fenced blocks, indented code, HTML blocks and front matter are not inline
tokens at all, and code spans are masked out below. Everything measured
byte-stable stays quiet, `$100 and $200` and `$x + y = z$` included.

The report goes to **stderr and leaves the exit code alone** (AGENTS.md
invariant 4): an ordinary `sync` of a document containing math must keep
returning what it returns today. A CI job that wants a gate already has
one — `cedit md canonicalize --check` exits 1 on any file whose canonical
form differs, which is precisely this case.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from .mdcore import tree_diff
from .mdcore.utils import markdown_to_ast

# Written over code spans before the dollar scan: a character that can neither
# open nor close anything, and one byte wide, so source offsets stay valid.
_MASK = "\x00"


@dataclass(frozen=True)
class MathSpan:
    """One `$`/`$$` run whose content holds a backslash."""

    line: int    # 1-based, in the source as handed to `find_fragile_math`
    delim: str   # "$" or "$$"
    text: str    # the run as written, delimiters included


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


def find_fragile_math(md: str) -> list[MathSpan]:
    """Every `$`/`$$` run in `md` whose content canonicalisation would rewrite.

    `md` is the **source** as written, not a canonical form: the point is to
    report before the round-trip, not after it.
    """
    found: list[MathSpan] = []
    for token in markdown_to_ast(md):
        # Only `inline` tokens carry prose, and only they carry the raw source
        # of their own region (`.content`) plus the line it starts on
        # (`.map`). Fences, indented code, HTML blocks and front matter are
        # other token types, so they are excluded for free.
        if token.type != "inline" or not token.content:
            continue
        src = token.content
        first_line = token.map[0] if token.map else 0
        masked = _mask_code_spans(src)
        for delim, start, end in _spans(masked):
            body = src[start + len(delim):end - len(delim)]
            if "\\" not in body:
                continue
            found.append(MathSpan(
                line=first_line + src.count("\n", 0, start) + 1,
                delim=delim,
                text=src[start:end],
            ))
    return found


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def warn_fragile_math(md: str, label: str, *, stream=None) -> list[MathSpan]:
    """Report `md`'s fragile math on stderr. **Never touches the exit code.**

    Returns the spans, so a caller that wants to say more about them can,
    and so the tests can assert on the detection rather than on the wording.
    """
    spans = find_fragile_math(md)
    if not spans:
        return spans
    out = sys.stderr if stream is None else stream
    print(f"{label}: warning: {len(spans)} dollar-delimited math span(s) "
          f"contain a backslash", file=out)
    for span in spans:
        print(f"    line {span.line}: {tree_diff._clip(span.text)}", file=out)
    print("    canonicalisation escapes it ($\\x -> $\\\\x) and GitHub reads "
          "\\\\ inside math as a line break, so the rendered maths changes.\n"
          "    Use a ```math fence for display math, and the Unicode character "
          "or a code span inline (USERGUIDE.md §13).", file=out)
    return spans
