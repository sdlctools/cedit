"""Link reference definition preservation and detection.

Tests for the link reference guard — detection of definitions that would be
lost during canonicalisation, and the warning emitted for them.
"""

import pytest

from cedit.linkguard import LinkRef, find_link_refs, warn_link_refs


# --------------------------------------------------------------------------
# Detection — finding definitions and tracking usage
# --------------------------------------------------------------------------


def test_no_definitions_means_empty_results():
    """A document with no link references returns empty dicts."""
    md = "Plain text with [brackets] but no definitions.\n"
    defs, used = find_link_refs(md)
    assert defs == {}
    assert used == set()


def test_simple_definition_is_found():
    """A single link reference definition is detected."""
    md = "[ref]: https://example.com\n"
    defs, used = find_link_refs(md)
    assert len(defs) == 1
    assert "ref" in defs
    assert defs["ref"].label == "ref"
    assert defs["ref"].url == "https://example.com"
    assert defs["ref"].title is None


def test_definition_with_title():
    """Definition with title is parsed correctly."""
    md = '[ref]: https://example.com "A title"\n'
    defs, used = find_link_refs(md)
    assert defs["ref"].title == "A title"


def test_definition_with_angle_brackets():
    """Definition with <url> is parsed correctly."""
    md = "[ref]: <https://example.com>\n"
    defs, used = find_link_refs(md)
    assert defs["ref"].url == "https://example.com"


def test_used_reference_is_detected():
    """A reference that's actually used is marked as such."""
    md = "[ref]: https://example.com\n\nLink to [ref].\n"
    defs, used = find_link_refs(md)
    assert "ref" in defs
    assert "ref" in used


def test_unused_reference_is_not_in_used_set():
    """A reference that's defined but never used is not in the used set."""
    md = "[unused]: https://example.com\n\nPlain text.\n"
    defs, used = find_link_refs(md)
    assert "unused" in defs
    assert "unused" not in used


def test_multiple_uses_are_detected():
    """Multiple uses of the same reference are all detected."""
    md = "[ref]: https://example.com\n\n[ref] and [ref] again.\n"
    defs, used = find_link_refs(md)
    assert "ref" in used
    assert len(used) == 1  # still just one label


def test_image_reference_is_marked_as_used():
    """Image references ([ref]:) ARE counted as uses because they inline the URL."""
    md = "[img]: /path/to/image.png\n\n![alt][img]\n"
    defs, used = find_link_refs(md)
    assert "img" in defs
    assert "img" in used  # images DO use the definition and it gets inlined


def test_reference_in_code_block_is_not_marked_as_used():
    """References inside code blocks are not counted as uses."""
    md = "[ref]: https://example.com\n\n```\n[ref]\n```\n"
    defs, used = find_link_refs(md)
    assert "ref" in defs
    assert "ref" not in used


def test_line_numbers_are_tracked():
    """Line numbers in LinkRef are correct."""
    md = "Line 1\n[ref]: https://example.com\nLine 3"
    defs, used = find_link_refs(md)
    assert defs["ref"].line == 2


# --------------------------------------------------------------------------
# Warning — the stderr report
# --------------------------------------------------------------------------


def test_no_warning_when_no_definitions(capsys):
    """A document with no link references produces no warning."""
    md = "Plain text.\n"
    assert warn_link_refs(md, "doc.md") == []
    assert capsys.readouterr().err == ""


def test_no_warning_when_all_used(capsys):
    """A document where all definitions are used produces no warning."""
    md = "[ref]: https://example.com\n\nLink to [ref].\n"
    assert warn_link_refs(md, "doc.md") == []
    assert capsys.readouterr().err == ""


def test_warning_when_unused_definition(capsys):
    """A document with an unused definition produces a warning."""
    md = "[unused]: https://example.com\n\nText.\n"
    unused = warn_link_refs(md, "doc.md")
    assert len(unused) == 1
    assert unused[0].label == "unused"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "doc.md: warning:" in captured.err
    assert "[unused]:" in captured.err
    assert "would be lost" in captured.err


def test_warning_reports_correct_line_number(capsys):
    """The warning includes the correct line number."""
    md = "Line 1\n[unused]: https://example.com\nLine 3"
    warn_link_refs(md, "doc.md")
    captured = capsys.readouterr()
    assert "line 2:" in captured.err


def test_multiple_unused_definitions_are_all_reported(capsys):
    """Multiple unused definitions are all included in the warning."""
    md = "[a]: https://a.com\n[b]: https://b.com\n\nText.\n"
    unused = warn_link_refs(md, "doc.md")
    assert len(unused) == 2
    captured = capsys.readouterr()
    assert "[a]:" in captured.err
    assert "[b]:" in captured.err


def test_warning_does_not_affect_exit_code():
    """The warning never touches the exit code."""
    # This is tested implicitly by the fact that warn_link_refs returns a list
    # and doesn't raise or return an error code, but we assert it explicitly.
    md = "[unused]: https://example.com\n"
    result = warn_link_refs(md, "doc.md")
    assert isinstance(result, list)  # not an exit code


# --------------------------------------------------------------------------
# Integration — canonicalisation behaviour
# --------------------------------------------------------------------------


def test_canonicalisation_inlines_used_references():
    """Used references are inlined (this is the mdformat behaviour)."""
    from cedit.blocks import canonicalise

    md = "[ref]: https://example.com\n\nLink to [ref].\n"
    canonical = canonicalise(md)
    # The definition is gone, the reference is inlined
    assert "[ref]:" not in canonical
    assert "[ref](https://example.com)" in canonical


def test_canonicalisation_drops_unused_references():
    """Unused references are dropped (this is the mdformat behaviour)."""
    from cedit.blocks import canonicalise

    md = "[unused]: https://example.com\n\nText.\n"
    canonical = canonicalise(md)
    # The definition is gone entirely
    assert "[unused]:" not in canonical
    assert "https://example.com" not in canonical


def test_warning_detects_what_will_be_lost():
    """The warning correctly identifies what canonicalisation will drop."""
    from cedit.blocks import canonicalise

    md = "[unused]: https://example.com\n[used]: https://example.com\n\n[used] link.\n"

    # Check what the warning says will be lost
    defs, used = find_link_refs(md)
    unused_labels = [label for label in defs if label not in used]
    assert unused_labels == ["unused"]

    # Check what actually gets dropped
    canonical = canonicalise(md)
    assert "[unused]:" not in canonical
    assert "[used](https://example.com)" in canonical
