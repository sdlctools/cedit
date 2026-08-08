"""The canonicalisation contract — what transformations it applies.

Pins the actual behaviour of `canonicalise` on key constructs, so a transitive
mdformat plugin that changes escaping or thematic breaks gets caught by name
rather than as a mystery hash move.

The shape is `test_mathguard.py`: a column of inputs asserted byte-stable, and
a column of inputs whose transformation is pinned explicitly.
"""

import pytest

from cedit.blocks import canonicalise


# Byte-stable constructs — canonicalisation leaves them alone
STABLE = [
    # Tables with compact separators
    ("| a | b |\n| -- | -- |\n| c | d |\n", "Compact table separators are stable"),

    # Horizontal rules (70 underscores is mdformat's fixed form)
    ("______________________________________________________________________\n",
     "Thematic breaks are 70 underscores"),

    # Code blocks with language tags
    ("```python\nx = 1\n```\n", "Code fences with language tags are stable"),

    # Lists with consistent indentation
    ("- item 1\n- item 2\n", "List items are stable"),

    # Paragraphs without rewrapping
    ("A long line that is not rewrapped because wrap is 'keep'\n",
     "Long lines are not rewrapped"),
]


# Transformed constructs — the output is pinned explicitly
TRANSFORMED = [
    # Link reference definitions (used ones are inlined)
    ("[ref]: https://example.com\n\n[ref] text.\n",
     "[ref](https://example.com) text.\n",
     "Used link references are inlined"),

    # Link reference definitions (unused ones are dropped)
    ("[unused]: https://example.com\n\nText.\n",
     "Text.\n",
     "Unused link references are dropped"),

    # Multiple spaces collapsed
    ("a  b\n", "a b\n", "Multiple spaces are collapsed"),

    # Trailing whitespace removed
    ("text   \n", "text\n", "Trailing whitespace is removed"),
]


@pytest.mark.parametrize("md,reason", STABLE)
def test_stable_constructs_are_byte_stable(md, reason):
    """Constructs that should not change stay byte-for-byte identical."""
    assert canonicalise(md) == md, reason


@pytest.mark.parametrize("input,expected,reason", TRANSFORMED)
def test_transformed_constructs_have_pinned_output(input, expected, reason):
    """Constructs that do change have their output pinned explicitly."""
    assert canonicalise(input) == expected, reason


def test_canonicalisation_is_idempotent():
    """Running canonicalise twice produces the same output."""
    for md, _ in STABLE:
        once = canonicalise(md)
        assert canonicalise(once) == once

    for input, expected, _ in TRANSFORMED:
        once = canonicalise(input)
        assert canonicalise(once) == once
        assert once == expected


def test_link_reference_detection_matches_what_will_be_lost():
    """The linkguard correctly identifies what canonicalisation will drop."""
    from cedit.linkguard import find_link_refs

    # Used reference: should be detected as used
    md = "[ref]: https://example.com\n\n[ref] text.\n"
    defs, used = find_link_refs(md)
    assert "ref" in defs
    assert "ref" in used  # used, so won't be lost

    # Unused reference: should be detected as unused
    md = "[unused]: https://example.com\n\nText.\n"
    defs, used = find_link_refs(md)
    assert "unused" in defs
    assert "unused" not in used  # unused, will be lost

    # Multiple references
    md = "[a]: https://a.com\n[b]: https://b.com\n\n[a] and text.\n"
    defs, used = find_link_refs(md)
    assert set(defs.keys()) == {"a", "b"}
    assert used == {"a"}  # only 'a' is used
    assert "b" not in used  # 'b' is unused
