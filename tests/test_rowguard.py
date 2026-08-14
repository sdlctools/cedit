"""The table-row guard — preservation, detection precision, and hash neutrality.

A GFM table's header row fixes the column count, and the parser truncates every
body row to it, so anything a row carries past its last kept cell is discarded
before cedit's tree exists. CED-30 lifts that text out before the parse and puts
it back after the render.

Every case below is re-derived through `canonicalise` on every run, in the shape
`test_mathguard.py` established: a column asserted byte-stable, a column whose
transformation is pinned, and — unique to this guard — a column asserting that
the hashes did **not** move, which is the claim the whole design rests on.
"""

import pytest

from cedit.blocks import (block_signature, canonicalise, parse_doc,
                          render_verified, splice_block)
from cedit import rowguard
from cedit.rowguard import (RowGuardError, find_row_overflow, protect,
                            warn_row_overflow)

# The exact pattern CED-30 was reported against — an inline pointer parked after
# a two-column row's closing pipe, in a document where the fact it carries
# survives nowhere else on that line.
JIRA_REST = (
    "| Jira type | API value |\n"
    "| --- | --- |\n"
    "| Sub-task | `Subtask`       |   <- **no hyphen** for this project (see §11)\n"
    "| Task | `Task` |\n"
)

# Rows carrying content past the header's last column. Canonicalisation dropped
# every one of these silently; each must now survive byte for byte. Written
# canonical apart from the surplus, so byte-stability is the whole assertion.
OVERFLOWING = [
    "| A | B |\n| -- | -- |\n| a | b |   <- note\n",
    "| A | B |\n| -- | -- |\n| a | b | c |\n",
    "| A | B |\n| -- | -- |\n| a | b | c | d |\n",
    "| A | B |\n| -- | -- |\n| a | b | c\n",
    "| A | B |\n| -- | -- |\n| a | b || x\n",
    "| A | B |\n| -- | -- |\n| a | b \\| c |   <- note\n",
    "| A | B |\n| -- | -- |\n| a | $\\rightarrow$ |   <- note\n",
    "> | A | B |\n> | -- | -- |\n> | a | b |   <- note\n",
    "- item\n\n  | A | B |\n  | -- | -- |\n  | a | b |   <- note\n",
    "| A | B |\n| -- | -- |\n| a | b | x1\n| c | d | x2\n",
]

# Everything else with a table in it. Byte-stable before CED-30 and after it —
# a guard that moved any of these would be moving canonical bytes for tables
# that were never losing anything.
STABLE = [
    "| A | B |\n| -- | -- |\n| a | b |\n",
    "| A | B | C |\n| -- | -- | -- |\n| a | b | c |\n",
    "| A | B |\n| -- | -- |\n| a |  |\n",
    "| A | B |\n| -- | -- |\n| a | b \\| c |\n",
    "```\n| A | B |\n| -- | -- |\n| a | b | x\n```\n",       # a fence, not a table
    "> | A | B |\n> | -- | -- |\n> | a | b |\n",
    "Prose with a | pipe in it.\n",
]

# Not byte-stable, and deliberately so: what trails the last kept cell is only
# whitespace and delimiters. Normalising those is canonicalisation's business —
# this guard is here for lost *content*, and widening it to pure punctuation
# would move canonical bytes for tables that never lost a thing.
NORMALISED = [
    ("| A | B |\n| -- | -- |\n| a | b ||\n", "| A | B |\n| -- | -- |\n| a | b |\n"),
    ("| A | B |\n| -- | -- |\n| a | b |  |\n", "| A | B |\n| -- | -- |\n| a | b |\n"),
    ("| A | B |\n| -- | -- |\n| a | b |   \n", "| A | B |\n| -- | -- |\n| a | b |\n"),
]


# --------------------------------------------------------------------------
# Preservation — the point of CED-30
# --------------------------------------------------------------------------


def test_the_reported_pattern_survives_byte_for_byte():
    """Acceptance criterion 1, against the document the bug was found in."""
    once = canonicalise(JIRA_REST)
    assert "<- **no hyphen** for this project (see §11)" in once
    assert canonicalise(once) == once


@pytest.mark.parametrize("md", OVERFLOWING)
def test_over_the_header_content_round_trips_byte_exact(md):
    assert canonicalise(md) == md


@pytest.mark.parametrize("md", STABLE)
def test_the_stable_column_is_byte_stable(md):
    assert canonicalise(md) == md


@pytest.mark.parametrize("md,expected", NORMALISED)
def test_delimiters_and_whitespace_are_still_normalised(md, expected):
    assert canonicalise(md) == expected


@pytest.mark.parametrize("md", OVERFLOWING + STABLE + [JIRA_REST])
def test_canonicalisation_is_idempotent(md):
    once = canonicalise(md)
    assert canonicalise(once) == once


@pytest.mark.parametrize("md", OVERFLOWING)
def test_the_render_path_preserves_it_too(md):
    """`canonicalise` is one of two ways bytes reach a file; this is the other.

    `sync` and `resolve` write what `render_verified` returns — the token
    stream, rendered — and that stream is exactly where the surplus is absent.
    """
    assert block_signature(md) == block_signature(canonicalise(md))
    assert render_verified(parse_doc(md)) == canonicalise(md)


def test_a_splice_leaves_the_surplus_on_its_row():
    """The surplus rides with its row, not with a cell, so re-splicing the cell
    next to it must neither consume it nor displace it."""
    doc = parse_doc("| A | B |\n| -- | -- |\n| a | b |   <- note\n")
    cell = next(b for b in doc.blocks if b.text == "b")
    assert splice_block(doc, cell, "rewritten")
    assert render_verified(doc) == \
        "| A | B |\n| -- | -- |\n| a | rewritten |   <- note\n"


def test_blocks_read_as_cells_do_not_as_rows():
    """No block holds the surplus — it is in no cell — so it must not leak into
    an overlay entry, a conflict record or `cedit md blocks`."""
    doc = parse_doc(JIRA_REST)
    assert [b.text for b in doc.blocks] == [
        "Jira type", "API value", "Sub-task", "`Subtask`", "Task", "`Task`"]


# --------------------------------------------------------------------------
# Hash neutrality — the property this design was chosen for
# --------------------------------------------------------------------------


@pytest.mark.parametrize("md", OVERFLOWING + [JIRA_REST])
def test_lifting_the_surplus_moves_no_hash(md):
    """The parser was already discarding these bytes, so handing it the row
    without them must produce the identical tree.

    This is what makes CED-30 safe to ship as a hotfix: an existing
    `.cedit/base/` snapshot, written before the guard, still hashes to what the
    manifest recorded, so no consumer sees a false conflict. Only the canonical
    *bytes* move, and only by gaining back what was lost.
    """
    guarded = protect(md)
    assert guarded.overflows and not guarded.unprotected
    lifted, whole = parse_doc(guarded.text), parse_doc(md)
    assert lifted.doc_hash == whole.doc_hash
    assert [b.key for b in lifted.blocks] == [b.key for b in whole.blocks]
    assert [b.text for b in lifted.blocks] == [b.text for b in whole.blocks]


def test_a_base_snapshot_written_before_the_guard_still_matches():
    """The concrete consumer case behind the test above: `.cedit/base/` holds
    the truncated form, the working copy holds the full row, and the two must
    still align block for block."""
    old_base = parse_doc("| A | B |\n| -- | -- |\n| a | b |\n", canonical=True)
    working = parse_doc("| A | B |\n| -- | -- |\n| a | b |   <- note\n")
    assert old_base.doc_hash == working.doc_hash


# --------------------------------------------------------------------------
# Detection — where the parser truncates, and nowhere else
# --------------------------------------------------------------------------


@pytest.mark.parametrize("md", OVERFLOWING + [JIRA_REST])
def test_over_the_header_content_is_detected(md):
    assert find_row_overflow(md)


@pytest.mark.parametrize("md", STABLE + [md for md, _ in NORMALISED])
def test_rows_that_lose_nothing_are_not_flagged(md):
    assert find_row_overflow(md) == []


def test_trailing_text_that_fits_the_header_is_a_cell_not_a_surplus():
    """The same line loses nothing under a wider header — the parser reads it
    as a third cell. A purely lexical `text after the last pipe` rule would
    protect it anyway and pin bytes canonicalisation is entitled to rewrite."""
    md = "| A | B | C |\n| -- | -- | -- |\n| a | b |   <- note\n"
    assert find_row_overflow(md) == []
    assert canonicalise(md) == "| A | B | C |\n| -- | -- | -- |\n| a | b | \\<- note |\n"


def test_a_header_or_delimiter_row_is_never_touched():
    """Trailing text on either makes the two disagree, so there is no table and
    no truncation — the line survives as an ordinary paragraph."""
    for md in ("| A | B |   <- note\n| --- | --- |\n| a | b |\n",
               "| A | B |\n| --- | --- |  <- note\n| a | b |\n"):
        assert find_row_overflow(md) == []
        assert "<- note" in canonicalise(md)


def test_surpluses_are_reported_with_their_row_ordinal_and_line():
    md = ("| A | B |\n| -- | -- |\n| a | b | x1\n\ntext\n\n"
          "| C | D |\n| -- | -- |\n| c | d |\n| e | f | x2\n")
    assert [(o.row, o.line, o.text) for o in find_row_overflow(md)] == [
        (0, 3, " x1"), (2, 10, " x2")]


def test_an_escaped_pipe_is_not_a_cell_boundary():
    """`escapedSplit` treats `\\|` as literal, so the surplus starts at the
    next *unescaped* pipe — cutting at the escaped one would eat a real cell."""
    md = "| A | B |\n| -- | -- |\n| a | b \\| c | x\n"
    assert [o.text for o in find_row_overflow(md)] == [" x"]
    assert canonicalise(md) == md


# --------------------------------------------------------------------------
# Protect and restore
# --------------------------------------------------------------------------


def test_protect_hands_the_parser_the_row_it_would_have_read_anyway():
    guarded = protect("| A | B |\n| -- | -- |\n| a | b |   <- note\n")
    assert guarded.text == "| A | B |\n| -- | -- |\n| a | b |\n"
    assert guarded.restore(guarded.text) == \
        "| A | B |\n| -- | -- |\n| a | b |   <- note\n"


def test_restore_finds_the_row_by_ordinal_not_by_line_number():
    """The render moves lines around — a dropped link definition, a reflowed
    fence — so the surplus is keyed to its row, not to where it started."""
    md = ("[unused]: https://example.com\n\n"
          "| A | B |\n| -- | -- |\n| a | b | x\n")
    assert canonicalise(md) == "| A | B |\n| -- | -- |\n| a | b | x\n"


def test_restore_refuses_to_drop_a_surplus_whose_row_is_gone():
    """The one failure `restore` can meet is losing the bytes it exists to
    keep, so it raises rather than returning a quietly shortened document."""
    overflows = protect("| A | B |\n| -- | -- |\n| a | b | x\n").overflows
    with pytest.raises(RowGuardError):
        rowguard.restore("Just a paragraph.\n", overflows)


# --------------------------------------------------------------------------
# The fallback alarm
# --------------------------------------------------------------------------


@pytest.fixture
def bad_cut(monkeypatch):
    """Force `protect`'s lift to land in the wrong place.

    No input is known to defeat the cut — the prefix rule follows blockquotes
    and list indentation, and the sweep in the CED-30 PR found none — so the
    rejection branch is reached by breaking the cut rather than by contriving a
    document. What is under test is the contract: a lift the parser can tell
    apart is abandoned whole, loudly, instead of rewriting bytes nobody wrote.
    """
    monkeypatch.setattr(rowguard, "_cut", lambda line, columns: 4)


def test_a_lift_the_parser_can_see_is_abandoned(bad_cut):
    md = "| A | B |\n| -- | -- |\n| a | b | x\n"
    guarded = protect(md)
    assert guarded.text == md                      # nothing rewritten
    assert guarded.overflows == ()
    assert [o.text for o in guarded.unprotected] == [" b | x"]
    assert canonicalise(md) != md                  # the old behaviour, kept


def test_an_unliftable_row_is_reported(capsys, bad_cut):
    overflows = warn_row_overflow("| A | B |\n| -- | -- |\n| a | b | x\n",
                                  "skills/demo/SKILL.md")
    assert [o.line for o in overflows] == [3]
    captured = capsys.readouterr()
    assert captured.out == ""                      # stderr only, never stdout
    assert "skills/demo/SKILL.md: warning:" in captured.err
    assert "past the header's last column" in captured.err
    # The pointer a real user follows out of this warning. It is a published
    # URL rather than a repo path because the reader is running an installed
    # cedit and has no checkout — CED-32 moved the guide onto the docs site.
    assert ("https://sdlctools.github.io/cedit/docs/userguide"
            "#13-limits-stated-plainly") in captured.err


@pytest.mark.parametrize("md", OVERFLOWING + STABLE + [JIRA_REST])
def test_a_preserved_or_harmless_document_says_nothing(md, capsys):
    assert warn_row_overflow(md, "doc.md") == []
    assert capsys.readouterr().err == ""
