"""The LaTeX-math guard — detection precision, and the fact that nothing
else in the pipeline can see the corruption it reports.

The two columns below are measured, not assumed: `test_the_stable_column_is_byte_stable`
and `test_the_corrupting_column_really_is_corrupted` re-derive them through
`canonicalise` on every run, so a parser change that moved a case from one
column to the other fails here instead of silently invalidating the guard.
"""

import pytest

from cedit.blocks import block_signature, canonicalise, parse_doc, render_verified
from cedit.mathguard import find_fragile_math, warn_fragile_math

# `$`-delimited spans canonicalisation rewrites — a backslash inside the span,
# outside code spans and code blocks. Exactly what the guard must catch.
CORRUPTED = [
    "Inline $\\rightarrow$ here.\n",
    "$$\n\\frac{a}{b}\n$$\n",
    "$$ \\frac{a}{b} $$\n",
    "# Heading with $\\alpha$\n",
    "| col | $\\gamma$ |\n| --- | --- |\n| a | b |\n",
]

# Everything else with a `$` in it. All byte-stable today, and a warning on any
# of them would be a false positive on ordinary prose — the expensive kind.
STABLE = [
    "$x + y = z$\n",
    "$a_i b_j$\n",
    "$x_1^2$\n",
    "$[a,b]$\n",
    "$a * b$\n",
    "$$ x + y = z $$\n",
    "$100 and $200\n",
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


@pytest.mark.parametrize("md", CORRUPTED)
def test_the_corrupting_column_really_is_corrupted(md):
    assert canonicalise(md) != md


@pytest.mark.parametrize("md", STABLE)
def test_the_stable_column_is_byte_stable(md):
    assert canonicalise(md) == md


@pytest.mark.parametrize("md", CORRUPTED)
def test_corrupting_math_is_detected(md):
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


def test_render_and_verify_cannot_catch_this():
    """Why the guard exists at all, pinned as a test.

    The rewrite is inside one paragraph's inline content, so the block
    structure is identical on both sides of the round-trip: `render_verified`
    passes and hands back the corrupted text. Nothing downstream of
    canonicalisation is able to notice.
    """
    md = "Inline $\\rightarrow$ here.\n"
    assert block_signature(md) == block_signature(canonicalise(md))
    rendered = render_verified(parse_doc(md))      # does not raise
    assert "$\\\\rightarrow$" in rendered
    assert find_fragile_math(md)                   # but the guard does see it


def test_the_warning_names_the_label_the_lines_and_the_remedy(capsys):
    md = "Inline $\\rightarrow$ here.\n"
    assert len(warn_fragile_math(md, "skills/demo/SKILL.md")) == 1
    captured = capsys.readouterr()
    assert captured.out == ""                      # stderr only, never stdout
    assert "skills/demo/SKILL.md: warning:" in captured.err
    assert "line 1: $\\rightarrow$" in captured.err
    assert "```math" in captured.err


def test_a_clean_document_says_nothing(capsys):
    assert warn_fragile_math("Plain prose costing $100.\n", "doc.md") == []
    assert capsys.readouterr().err == ""
