"""Preserve table-row content that canonicalisation would otherwise drop.

A GFM table's **header row fixes the column count for the whole table**, and
markdown-it applies that count to every body row by index:

    for i in range(columnCount):
        ...
        token.content = columns[i].strip() if columns[i] else ""

Cells past `columnCount` are never read, so a body row that carries more than
the header declares loses the surplus *before cedit's tree exists*. The
common spelling is an inline annotation parked after the row's closing pipe:

    | Sub-task | `Subtask` |   <- **no hyphen** for this project (see §11)

which splits into three cells against a two-column header, and canonicalises
to `| Sub-task | \\`Subtask\\` |`. The pointer is gone.

Nothing downstream could catch that. The block structure is identical, so
`blocks.render_verified` passes; every hash is taken over a tree the text
never reached; the working copy and `.cedit/base/` are written and cedit
exits 0 — the silent clobber AGENTS.md invariant 3 forbids outright, on a row
nobody touched. It is the same shape of failure as `mathguard`'s, and this
module answers it the same way: prevent, do not merely report.

**The mechanism has to differ, though, and that is the whole design.** A
`mathguard` sentinel works because the fragile bytes sit somewhere the parser
reads: swap them in place and the round-trip carries the sentinel through.
Here the *position* is what gets dropped, not the content — a sentinel
written past the last kept cell is discarded exactly as the text was. So the
surplus is **lifted out of the source before parsing and appended back onto
its own row after rendering**, keyed by the row's ordinal among the
document's body rows:

    source -> protect(surplus lifted) -> parse -> render -> restore -> canonical

Row ordinals are stable across the round-trip because the splice never adds,
removes or reorders a row, and `blocks.render_verified` refuses to write if
block structure moved at all.

That buys a property the sentinel shape could not: **no hash moves, ever.**
The parser was already discarding these bytes, so lifting them out hands it
the identical token stream — which `protect` asserts rather than assumes, by
parsing both sides and comparing. A row it cannot lift cleanly is left alone
and reported by `warn_row_overflow` on **stderr, leaving the exit code
alone** (AGENTS.md invariant 4). Only the canonical *bytes* move, and only
for documents that were losing content: they gain it back.

The surplus rides with its row rather than joining a block, because it is not
in one — no cell contains it. Editing it is therefore invisible to the merge:
a `sync` keeps the row annotation the incoming upstream revision carries.
Preserving the bytes is the fix; making them mergeable is not phase 1's to
give. docs/USERGUIDE.md §13 is the user-facing version of this paragraph.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from .mdcore import tree_diff
from .mdcore.utils import markdown_to_ast

# What markdown-it's blockquote and paragraph handling has already stripped by
# the time its table rule reads a row (`getLine` starts at `bMarks + tShift`,
# then `.strip()`). Reproduced here because the surplus has to be cut out of
# the *source* line, which still carries it.
_ROW_PREFIX = re.compile(r"^(?:[ \t]*>[ \t]?)*[ \t]*")


class RowGuardError(RuntimeError):
    """A lifted row surplus had no row to go back onto.

    Unreachable unless the rendered document's body rows stopped matching the
    source's, which `protect`'s token-stream check and `render_verified`
    between them rule out. Raised rather than dropped: losing the bytes here
    is the very thing this module exists to prevent.
    """


@dataclass(frozen=True)
class RowOverflow:
    """The content of one body row that sits past the header's last column.

    `row` is the row's 0-based ordinal among **every** body row in the
    document, in token order — the key `restore` puts it back by. `text` is
    the surplus exactly as written, from the pipe that closes the last kept
    cell to the end of the line (trailing whitespace excluded, which
    canonicalisation strips everywhere else too).
    """

    row: int
    line: int    # 1-based, in the source as handed to `find_row_overflow`
    text: str


@dataclass(frozen=True)
class Protected:
    """A source with its body-row surplus lifted out."""

    text: str
    overflows: tuple[RowOverflow, ...]
    unprotected: tuple[RowOverflow, ...]

    def restore(self, text: str) -> str:
        return restore(text, self.overflows)


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------


def _unescaped_pipes(line: str) -> list[int]:
    """Offsets of the `|` characters markdown-it splits a row on.

    `escapedSplit` tracks a single-character `isEscaped` flag, so a pipe is a
    separator unless the character immediately before it is a backslash —
    `\\\\|` counts as escaped there too. Matching that exactly matters more
    than being right about `\\\\|`: the point is to cut the row where the
    parser cuts it.
    """
    return [i for i, ch in enumerate(line)
            if ch == "|" and (i == 0 or line[i - 1] != "\\")]


def _body_rows(tokens) -> list[tuple[int, int]]:
    """`(source line, column count)` for every table body row, in order.

    The column count is the header's, which is the number the body row is
    truncated to. Header rows are not listed: trailing text on one makes the
    header and the delimiter row disagree, the table is not recognised at
    all, and the line survives as an ordinary paragraph.
    """
    rows: list[tuple[int, int]] = []
    columns = 0
    in_head = in_body = False
    for token in tokens:
        if token.type == "thead_open":
            in_head, columns = True, 0
        elif token.type == "th_open" and in_head:
            columns += 1
        elif token.type == "thead_close":
            in_head = False
        elif token.type == "tbody_open":
            in_body = True
        elif token.type == "tbody_close":
            in_body = False
        elif token.type == "tr_open" and in_body and token.map:
            rows.append((token.map[0], columns))
    return rows


def _cut(line: str, columns: int) -> int | None:
    """Offset of the pipe that closes the last cell `line` keeps, or None.

    `None` when the row has no surplus to lift: it fits the header, or what
    trails the last kept cell is only whitespace and pipes. Delimiters alone
    are normalisation's business, not this module's — the guard is here for
    lost *content*.
    """
    pipes = _unescaped_pipes(line)
    # `escapedSplit` yields `len(pipes) + 1` segments; markdown-it then drops
    # the empty one an enclosing pipe leaves, first at the front and then —
    # on what is left — at the back.
    first = 1 if pipes and pipes[0] == 0 else 0
    last = len(pipes) if pipes and pipes[-1] == len(line) - 1 else len(pipes) + 1
    if not columns or last - first <= columns:
        return None
    at = pipes[first + columns - 1]
    return at if line[at + 1:].strip(" \t|") else None


def find_row_overflow(md: str) -> list[RowOverflow]:
    """Every body-row surplus in `md` that canonicalisation would drop.

    `md` is the **source** as written: the point is to catch these before the
    round-trip, since after it there is nothing left to catch.
    """
    if "|" not in md:
        # `protect` runs on every parse, every canonicalisation and every
        # splice; a document with no pipe cannot hold a table. No pipe, no
        # row, no parse.
        return []
    src_lines = md.split("\n")
    found: list[RowOverflow] = []
    for ordinal, (line_no, columns) in enumerate(_body_rows(markdown_to_ast(md))):
        if line_no >= len(src_lines):
            continue
        raw = src_lines[line_no]
        start = _ROW_PREFIX.match(raw).end()
        end = len(raw.rstrip())
        at = _cut(raw[start:end], columns)
        if at is None:
            continue
        found.append(RowOverflow(row=ordinal, line=line_no + 1,
                                 text=raw[start + at + 1:end]))
    return found


# --------------------------------------------------------------------------
# Protect and restore
# --------------------------------------------------------------------------


def _fingerprint(tokens) -> tuple:
    """Everything about a token stream that a hash or a render can read."""
    return tuple(
        (t.type, t.tag, t.content, t.info, t.markup, t.nesting, t.level,
         t.block, t.hidden, tuple(t.map or ()),
         tuple(sorted((t.attrs or {}).items())),
         _fingerprint(t.children or ()))
        for t in tokens
    )


def protect(md: str) -> Protected:
    """Lift every droppable body-row surplus out of `md`.

    The lift is only accepted if the parser cannot tell: both sides are
    parsed and their token streams compared, so a row this module cut in the
    wrong place — a table nested somewhere the prefix rule does not follow —
    is put back rather than trusted. Nothing is protected in that case and
    every overflow is reported instead, which keeps the hash-neutrality claim
    a checked one rather than an argued one.
    """
    overflows = find_row_overflow(md)
    if not overflows:
        return Protected(md, (), ())

    lines = md.split("\n")
    for overflow in overflows:
        # The surplus runs to the end of the row's content, so cutting its own
        # length off there lands exactly on the pipe `_cut` chose — trailing
        # whitespace, which is not part of it, goes with it.
        line = lines[overflow.line - 1]
        lines[overflow.line - 1] = line[:len(line.rstrip()) - len(overflow.text)]
    text = "\n".join(lines)

    if _fingerprint(markdown_to_ast(text)) != _fingerprint(markdown_to_ast(md)):
        return Protected(md, (), tuple(overflows))
    return Protected(text, tuple(overflows), ())


def restore(text: str, overflows: tuple[RowOverflow, ...]) -> str:
    """Append each lifted surplus back onto its own body row in `text`."""
    if not overflows:
        return text
    lines = text.split("\n")
    rows = [line for line, _ in _body_rows(markdown_to_ast(text))]
    for overflow in overflows:
        if overflow.row >= len(rows):
            raise RowGuardError(
                f"table row {overflow.row} is gone from the rendered document, "
                f"so its trailing text cannot be restored: {overflow.text!r}"
            )
        lines[rows[overflow.row]] += overflow.text
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def warn_row_overflow(md: str, label: str, *, stream=None) -> list[RowOverflow]:
    """Report the row surplus in `md` that `protect` could **not** lift.

    The fallback alarm, not a running commentary: preserved rows say nothing.
    **Never touches the exit code** (AGENTS.md invariant 4). Returns the
    reported overflows, so the tests can assert on the detection rather than
    on the wording.
    """
    overflows = list(protect(md).unprotected)
    if not overflows:
        return overflows
    out = sys.stderr if stream is None else stream
    print(f"{label}: warning: {len(overflows)} table row(s) carry text past "
          f"the header's last column that could not be preserved", file=out)
    for overflow in overflows:
        print(f"    line {overflow.line}: {tree_diff._clip(overflow.text)}",
              file=out)
    print("    A GFM table's header row fixes the column count, and cedit's "
          "parser discards\n"
          "    whatever a body row carries past it — an annotation after the "
          "closing pipe, or an\n"
          "    extra cell. cedit normally lifts that text out and puts it "
          "back verbatim, and\n"
          "    cannot for these. Give the table another column, or move the "
          "note into a cell\n"
          "    — user guide §13:\n"
          "    https://sdlctools.github.io/cedit/docs/userguide"
          "#13-limits-stated-plainly", file=out)
    return overflows
