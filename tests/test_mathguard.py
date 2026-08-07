"""The LaTeX-math guard — preservation, and the detection precision it rests on.

Both columns below are measured, not assumed: every case is re-derived through
`canonicalise` on every run, so a parser change that moved a case from one to
the other fails here instead of silently invalidating the guard. CED-26 recorded
one column as *corrupted*; CED-27 protects it, so the same inputs are now
asserted byte-stable and the tests that pinned the corruption are inverted.
"""

import pytest

from cedit.blocks import (block_signature, canonicalise, parse_doc,
                          render_verified, splice_block)
from cedit.mathguard import find_fragile_math, protect, restore, warn_fragile_math

# `$`-delimited spans canonicalisation would rewrite — a backslash inside the
# span, outside code spans and code blocks. Exactly what the guard must catch,
# and now exactly what it must carry through untouched. Written canonical apart
# from the math, so byte-stability is the whole assertion.
FRAGILE = [
    "Inline $\\rightarrow$ here.\n",
    "$$\n\\frac{a}{b}\n$$\n",
    "$$ \\frac{a}{b} $$\n",
    "# Heading with $\\alpha$\n",
    "| col | $\\gamma$ |\n| -- | -- |\n| a | b |\n",
    "A $\\alpha$ and a $\\beta$ here.\n",
    "Navigate to **Actions** $\\rightarrow$ **General**.\n",
    "> Quoted $\\alpha$ in a blockquote.\n",
    "- List item with $\\beta$\n",
]

# Everything else with a `$` in it. All byte-stable before CED-27 and after it,
# and a warning on any of them would be a false positive on ordinary prose —
# the expensive kind.
STABLE = [
    "$x + y = z$\n",
    "$a_i b_j$\n",
    "$x_1^2$\n",
    "$[a,b]$\n",
    "$a * b$\n",
    "$$ x + y = z $$\n",
    "$100 and $200\n",
    "It costs $100 and $200 total.\n",
    "$a_i$ and $b_j$\n",
    "`$\\rightarrow$`\n",
    "```\n$\\rightarrow$\n```\n",
    "```math\n\\frac{a}{b}\n```\n",          # the supported spelling
    "<div>\n$\\rightarrow$\n</div>\n",
    "---\ntitle: $\\x$\n---\n\nbody\n",       # front matter
]

# Not byte-stable — canonicalisation normalises the escape — but not corrupt
# either: `\$` and `$` render the same, and `\\` outside math is the literal
# backslash it was. The guard is about what the *page* says, so these stay
# quiet too, and the escaped dollars must not be read as delimiters.
ESCAPED = [
    "Costs \\$5 and \\$6.\n",
    "A stray \\ backslash in prose.\n",
]


# --------------------------------------------------------------------------
# Preservation — the point of CED-27
# --------------------------------------------------------------------------


@pytest.mark.parametrize("md", FRAGILE)
def test_fragile_math_round_trips_byte_exact(md):
    assert canonicalise(md) == md


@pytest.mark.parametrize("md", STABLE)
def test_the_stable_column_is_byte_stable(md):
    assert canonicalise(md) == md


@pytest.mark.parametrize("md", FRAGILE + STABLE + ESCAPED)
def test_canonicalisation_is_idempotent(md):
    once = canonicalise(md)
    assert canonicalise(once) == once


@pytest.mark.parametrize("md", FRAGILE)
def test_the_render_path_preserves_it_too(md):
    """`canonicalise` is one of two ways bytes reach a file; this is the other.

    `sync` and `resolve` write what `render_verified` returns — the token
    stream, rendered — and that stream is what mdformat would escape. Before
    CED-27 this test asserted the corruption instead (`$\\\\rightarrow$` in the
    output) as the proof that nothing downstream could catch it.
    """
    assert block_signature(md) == block_signature(canonicalise(md))
    assert render_verified(parse_doc(md)) == canonicalise(md)


def test_a_splice_carries_math_in_the_text_it_splices_in():
    """The merge reapplies a local edit by splicing its text into upstream's
    tree, so text arriving that way needs protecting just as much as text that
    was parsed."""
    doc = parse_doc("Placeholder paragraph.\n")
    assert splice_block(doc, doc.blocks[0], "Now with $\\rightarrow$ in it.")
    assert render_verified(doc) == "Now with $\\rightarrow$ in it.\n"


def test_blocks_read_as_the_document_does_not_as_sentinels():
    """Sentinels are an implementation detail of the token stream. They must
    not reach an overlay entry, a conflict record or `cedit md blocks`."""
    doc = parse_doc("# Heading $\\alpha$\n\nBody with $\\beta$ in it.\n")
    assert [b.text for b in doc.blocks] == ["Heading $\\alpha$",
                                            "Body with $\\beta$ in it."]
    assert doc.blocks[1].context == "Heading $\\alpha$"
    assert doc.canonical == "# Heading $\\alpha$\n\nBody with $\\beta$ in it.\n"


# --------------------------------------------------------------------------
# Detection — CED-26's precision, unchanged and now load-bearing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("md", FRAGILE)
def test_fragile_math_is_detected(md):
    assert find_fragile_math(md)


@pytest.mark.parametrize("md", STABLE + ESCAPED)
def test_harmless_dollars_are_not_flagged(md):
    assert find_fragile_math(md) == []


def test_spans_are_reported_with_their_line_and_delimiter():
    md = ("# Title\n\nLine three has $\\rightarrow$ in it.\n\nProse.\n\n"
          "$$\n\\frac{a}{b}\n$$\n\n| col | $\\gamma$ |\n| --- | --- |\n| a | b |\n")
    spans = find_fragile_math(md)
    assert [(s.line, s.delim) for s in spans] == [(3, "$"), (7, "$$"), (11, "$")]
    assert spans[0].text == "$\\rightarrow$"


def test_a_code_span_shields_the_math_after_it():
    # The backtick scan must consume the code span and resume, not swallow the
    # rest of the line — otherwise the real span behind it goes unreported.
    md = "See `$\\a$` and then $\\rightarrow$ next.\n"
    assert [s.text for s in find_fragile_math(md)] == ["$\\rightarrow$"]


def test_an_unmatched_backtick_run_is_ordinary_text():
    md = "A ` stray backtick and $\\rightarrow$ after it.\n"
    assert len(find_fragile_math(md)) == 1


# --------------------------------------------------------------------------
# Protect and restore — the three gaps the CED-27 prototype papered over
# --------------------------------------------------------------------------


def test_spans_are_located_by_offset_not_by_matching_their_text():
    """A prototype using `str.replace` on the span text rewrites the copy in
    the fence too, and the copy in the code span. Offsets do not."""
    md = ("```\n$\\a$\n```\n\nProse `$\\a$` then a real $\\a$ span.\n")
    guarded = protect(md)
    assert guarded.text.count("$\\a$") == 2        # the fence and the code span
    assert "```\n$\\a$\n```" in guarded.text
    assert "`$\\a$`" in guarded.text
    assert len(guarded.spans) == 1
    assert canonicalise(md) == md


def test_the_same_span_twice_is_protected_at_both_positions():
    md = "First $\\a$, then $\\a$ again.\n"
    guarded = protect(md)
    assert "$" not in guarded.text
    assert len(guarded.spans) == 1                 # content-derived: one sentinel
    assert guarded.restore() == md
    assert canonicalise(md) == md


def test_the_sentinel_is_inert_and_checked_against_the_document():
    md = "Inline $\\rightarrow$ here.\n"
    sentinel, original = next(iter(protect(md).spans.items()))
    assert sentinel.isalnum() and sentinel.islower()
    assert original == "$\\rightarrow$"

    # A document that already contains the sentinel gets a different one, so
    # `restore` can never put math where the author wrote that literal text.
    collides = f"Literal {sentinel} in prose, and $\\rightarrow$ math.\n"
    guarded = protect(collides)
    assert sentinel not in guarded.spans
    assert guarded.restore() == collides
    assert canonicalise(collides) == collides


def test_restore_is_the_inverse_of_protect():
    for md in FRAGILE + STABLE:
        guarded = protect(md)
        assert guarded.restore() == md
        # ... and protecting the restored text reproduces the same sentinels,
        # which is what makes a base snapshot and a working copy hash alike.
        assert protect(guarded.restore()).text == guarded.text


def test_a_splice_resolves_its_sentinel_against_the_document_it_joins():
    """A fragment protected on its own could pick a sentinel the destination
    already uses as literal text, and `restore` would then rewrite that text
    into math. The splice passes the document in so it cannot."""
    span = "$\\rightarrow$"
    sentinel = next(iter(protect(f"x {span} y").spans))
    doc = parse_doc(f"Literal {sentinel} in prose.\n\nPlaceholder.\n")
    assert splice_block(doc, doc.blocks[1], f"Now with {span} in it.")
    assert render_verified(doc) == \
        f"Literal {sentinel} in prose.\n\nNow with {span} in it.\n"


def test_restore_prefers_the_longer_sentinel():
    # A collision-resolved sentinel is its base plus a counter, so replacing
    # the base first would eat the prefix of the longer one.
    spans = {"ceditmathabc": "$\\a$", "ceditmathabc1": "$\\b$"}
    assert restore("x ceditmathabc1 y", spans) == "x $\\b$ y"


# --------------------------------------------------------------------------
# The fallback alarm
# --------------------------------------------------------------------------

# markdown-it hands back an *unescaped* table cell, so this span's inline
# content (`$x | y \alpha$`) is not in the source verbatim and its offsets
# cannot be derived. It is the one reachable construct that defeats the
# protection, and it is what `warn_fragile_math` exists for now.
UNLOCATABLE = "| a | $x \\| y \\alpha$ |\n| -- | -- |\n| c | d |\n"


def test_a_span_that_cannot_be_located_is_reported(capsys):
    spans = warn_fragile_math(UNLOCATABLE, "skills/demo/SKILL.md")
    assert [s.text for s in spans] == ["$x | y \\alpha$"]
    captured = capsys.readouterr()
    assert captured.out == ""                      # stderr only, never stdout
    assert "skills/demo/SKILL.md: warning:" in captured.err
    assert "could not be located" in captured.err
    assert "```math" in captured.err


def test_an_unlocatable_span_is_left_alone_rather_than_rewritten_wrongly():
    """Protection is all-or-nothing per span: a span whose offsets are not
    trustworthy keeps the old behaviour, loudly, instead of being rewritten
    into bytes nobody wrote."""
    assert protect(UNLOCATABLE).spans == {}
    assert canonicalise(UNLOCATABLE) != UNLOCATABLE


@pytest.mark.parametrize("md", FRAGILE + STABLE + ESCAPED)
def test_a_protected_or_harmless_document_says_nothing(md, capsys):
    assert warn_fragile_math(md, "doc.md") == []
    assert capsys.readouterr().err == ""
