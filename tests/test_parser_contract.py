"""Invariant 2, enforced rather than asserted.

`parser_contract.py` carries the reasoning and the re-record path; this file
is the gate. One test, because there is one question: has anything the
recorded hashes depend on moved since the baseline was taken?
"""

import re

import parser_contract

from cedit.blocks import parse_doc

# A reference is `[^label]`; a definition is the same at the start of a line,
# followed by a colon. Both spellings are asserted unescaped — `\[^label\]` is
# precisely the corruption CED-25 was.
_FOOTNOTE_REF = re.compile(r"(?<!\\)\[\^([^\]\s]+)\](?!:)")
_FOOTNOTE_DEF = re.compile(r"^\[\^([^\]\s]+)\]:", re.MULTILINE)


def test_parser_contract_has_not_drifted():
    """Every hash in every consumer's `.cedit/` state is taken over this.

    A failure here is not a broken test — it is the parser having changed
    under hashes that were recorded on other people's machines. Read
    `.claude/rules/hash-stability.md`, decide whether the move is acceptable,
    and only then re-record with

        venv/bin/python3 tests/parser_contract.py --update
    """
    found = parser_contract.drift()
    assert not found, "the parser contract moved:\n  - " + "\n  - ".join(found)


def test_fixture_covers_the_constructs_that_move_hashes():
    """The baseline is only worth as much as the fixture underneath it.

    Front matter, raw HTML and fences are the opaque blocks; headings,
    paragraphs and table cells are the inline units. A fixture that quietly
    stopped covering one of them would keep passing the drift check while
    testing less, which is the failure mode a baseline cannot see.
    """
    baseline = parser_contract.load_baseline()
    covered = {b["node_type"] for b in baseline["fixture"]["blocks"]}

    assert {"front_matter", "html_block", "fence", "hr"} <= covered
    assert {"heading", "paragraph", "th", "td"} <= covered

    infos = {b["info"] for b in baseline["fixture"]["blocks"] if b["kind"] == "opaque"}
    assert {"bash", "python", ""} <= infos, (
        "the fence info string is part of the editable surface — the fixture "
        "needs fences that differ by info alone"
    )


def test_fixture_covers_gfm_footnotes():
    """Footnotes leave no distinctive node type, so cover them by their form.

    A footnote definition's body parses as an ordinary `paragraph` unit, which
    means the assertion above cannot see whether the fixture still exercises
    footnotes at all — it would keep passing over a fixture that dropped them.
    This looks at the canonical form instead, which is the thing the baseline
    hashes, and pins the two ways CED-25 could come back:

    * no plugin loaded — `[^label]:` is plain text, mdformat escapes it, and
      the document gets a dangling reference plus a visible `\\[^label\\]:`;
    * `keep_orphans` unseeded — the plugin's own default *deletes* every
      definition nothing references, on the way into `.cedit/base/`.
    """
    canonical = parse_doc(parser_contract.FIXTURE.read_text("utf-8")).canonical

    refs = set(_FOOTNOTE_REF.findall(canonical))
    defs = set(_FOOTNOTE_DEF.findall(canonical))

    assert refs, "the fixture no longer contains a footnote reference"
    assert defs, (
        "the fixture no longer contains a footnote definition — or one came "
        "back escaped, which is CED-25 itself"
    )
    assert refs <= defs, f"referenced but undefined in the fixture: {refs - defs}"
    assert defs - refs, (
        "the fixture needs an unreferenced definition: it is the only thing "
        "that would notice make_parser's keep_orphans seed going away, and "
        "losing it is silent"
    )
    assert "\\[^" not in canonical, (
        "a footnote came back escaped — mdformat-footnote is not installed, "
        "or make_parser stopped loading it"
    )
