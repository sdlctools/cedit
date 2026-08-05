"""Invariant 2, enforced rather than asserted.

`parser_contract.py` carries the reasoning and the re-record path; this file
is the gate. One test, because there is one question: has anything the
recorded hashes depend on moved since the baseline was taken?
"""

import parser_contract


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
