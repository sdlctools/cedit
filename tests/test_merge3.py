"""The merge matrix, exercised edit by edit — docs/SPEC.md's phase-1 acceptance.

Every test builds three revisions of a small but realistic skill document
(front matter, headings, prose, fences, a list, a table) and checks both the
classification counts and the merged text itself.
"""

import pytest

from cedit.blocks import canonicalise, parse_doc
from cedit.merge3 import ORPHAN, StructuralDrift, local_edits, merge

BASE = """\
---
name: demo-skill
---

# Demo skill

Intro paragraph explaining the skill.

## Setup

Run the healthcheck first:

```bash
bash scripts/statuscheck.sh --role assigner
```

Prose about the setup step.

## Create

Create the issue:

```bash
bash scripts/jira.sh issue create --project "$KEY"
```

- item one
- item two

| col1 | col2 |
| ---- | ---- |
| a    | b    |
"""


def zshify(md: str) -> str:
    """The motivating local edit: the healthcheck fence, rewritten for zsh."""
    return md.replace(
        '```bash\nbash scripts/statuscheck.sh --role assigner\n```',
        '```zsh\nzsh scripts/statuscheck.sh --role assigner\n```',
    )


LOCAL = zshify(BASE)


def units_and_fences(md: str):
    return [(b.kind, b.node_type, b.info, b.text) for b in parse_doc(md).blocks]


# --------------------------------------------------------------------------
# Overlay derivation
# --------------------------------------------------------------------------


def test_no_edits_no_overlay():
    edits = local_edits(parse_doc(BASE), parse_doc(BASE))
    assert edits == []


def test_fence_edit_is_one_overlay_entry_with_info_change():
    edits = local_edits(parse_doc(BASE), parse_doc(LOCAL))
    assert len(edits) == 1
    (edit,) = edits
    assert edit.kind == "opaque"
    assert edit.node_type == "fence"
    assert (edit.base_info, edit.local_info) == ("bash", "zsh")
    assert "zsh scripts/statuscheck.sh" in edit.local_text
    assert "Setup" in edit.context


def test_prose_edit_is_a_unit_entry():
    local = BASE.replace("Prose about the setup step.",
                         "Prose about the setup step, adapted locally.")
    (edit,) = local_edits(parse_doc(BASE), parse_doc(local))
    assert edit.kind == "unit"
    assert edit.node_type == "paragraph"


def test_local_insertion_is_structural_drift():
    local = BASE.replace("## Create", "A locally added warning.\n\n## Create")
    with pytest.raises(StructuralDrift, match="inserted paragraph"):
        local_edits(parse_doc(BASE), parse_doc(local))


def test_local_deletion_is_structural_drift():
    local = BASE.replace("Prose about the setup step.\n", "")
    with pytest.raises(StructuralDrift, match="deleted paragraph"):
        local_edits(parse_doc(BASE), parse_doc(local))


# --------------------------------------------------------------------------
# The merge matrix
# --------------------------------------------------------------------------


def test_reapply_on_unchanged_upstream():
    result = merge(BASE, LOCAL, BASE)
    assert len(result.reapplied) == 1
    assert not result.conflicts
    assert "zsh scripts/statuscheck.sh" in result.merged
    assert result.merged == canonicalise(LOCAL)


def test_upstream_prose_change_flows_in_while_edit_survives():
    upstream = BASE.replace("Intro paragraph explaining the skill.",
                            "Intro paragraph explaining the skill in detail.")
    result = merge(BASE, LOCAL, upstream)
    assert len(result.reapplied) == 1
    assert result.updated == 1
    assert not result.conflicts
    assert "in detail" in result.merged
    assert "zsh scripts/statuscheck.sh" in result.merged


def test_upstream_change_to_unedited_fence_is_taken():
    upstream = BASE.replace('--project "$KEY"', '--project "$KEY" --type Task')
    result = merge(BASE, LOCAL, upstream)
    assert result.updated == 1
    assert '--type Task' in result.merged
    assert "zsh scripts/statuscheck.sh" in result.merged  # edit still reapplied


def test_both_edit_same_fence_is_conflict_keeping_local():
    upstream = BASE.replace("statuscheck.sh --role assigner",
                            "statuscheck.sh --role assigner --verbose")
    result = merge(BASE, LOCAL, upstream)
    assert len(result.conflicts) == 1
    (conflict,) = result.conflicts
    assert conflict.reason == "conflict"
    assert conflict.upstream_text.strip().endswith("--verbose")
    assert conflict.local_info == "zsh"
    # the working file keeps the local adaptation
    assert "zsh scripts/statuscheck.sh" in result.merged
    assert "--verbose" not in result.merged


def test_both_edit_same_paragraph_is_conflict():
    local = BASE.replace("Prose about the setup step.",
                         "Prose about the setup step (ours).")
    upstream = BASE.replace("Prose about the setup step.",
                            "Prose about the setup step (theirs).")
    result = merge(BASE, local, upstream)
    assert [c.reason for c in result.conflicts] == ["conflict"]
    assert "(ours)" in result.merged
    assert "(theirs)" not in result.merged


def test_upstream_deleting_edited_block_is_orphan():
    local = BASE.replace("Prose about the setup step.",
                         "Prose about the setup step (ours).")
    upstream = BASE.replace("Prose about the setup step.\n\n", "")
    result = merge(BASE, local, upstream)
    assert [c.reason for c in result.conflicts] == [ORPHAN]
    (conflict,) = result.conflicts
    assert conflict.upstream_text is None
    assert "(ours)" in conflict.local_text
    # the block is gone from the merged document — structure comes from U
    assert "Prose about the setup step" not in result.merged


def test_upstream_move_carries_the_edit_along():
    # Move the whole Setup section after Create.
    setup = ("## Setup\n\nRun the healthcheck first:\n\n"
             "```bash\nbash scripts/statuscheck.sh --role assigner\n```\n\n"
             "Prose about the setup step.\n\n")
    assert setup in BASE
    upstream = BASE.replace(setup, "")
    upstream = upstream.replace("## Create", "## Create\n\nPlaced first now.")
    upstream += "\n" + setup.rstrip() + "\n"
    result = merge(BASE, LOCAL, upstream)
    assert not result.conflicts
    assert len(result.reapplied) == 1
    assert result.moved >= 1
    assert "zsh scripts/statuscheck.sh" in result.merged


def test_upstream_reflow_is_a_noop_for_the_edit():
    upstream = BASE.replace(
        "Intro paragraph explaining the skill.",
        "Intro paragraph\nexplaining the skill.",  # pure reflow
    )
    result = merge(BASE, LOCAL, upstream)
    assert not result.conflicts
    assert len(result.reapplied) == 1


def test_duplicate_occurrence_edit_applies_to_the_right_copy():
    base = (
        "# Doc\n\nFirst use:\n\n```bash\nrun tool\n```\n\n"
        "Second use:\n\n```bash\nrun tool\n```\n"
    )
    local = base.replace("Second use:\n\n```bash\nrun tool\n```",
                         "Second use:\n\n```zsh\nrun tool --flag\n```")
    (edit,) = local_edits(parse_doc(base), parse_doc(local))
    assert edit.occurrence == 1
    result = merge(base, local, base)
    assert len(result.reapplied) == 1
    first, second = [b for b in parse_doc(result.merged).blocks
                     if b.node_type == "fence"]
    assert (first.info, first.text.strip()) == ("bash", "run tool")
    assert (second.info, second.text.strip()) == ("zsh", "run tool --flag")


def test_table_cell_edit_reapplies_without_breaking_the_table():
    local = BASE.replace("| a    | b    |", "| a-adapted | b    |")
    result = merge(BASE, local, BASE)
    assert len(result.reapplied) == 1
    assert "a-adapted" in result.merged
    # still a table with the same shape
    cells = [b for b in parse_doc(result.merged).blocks if b.node_type == "td"]
    assert len(cells) == 2


def test_front_matter_edit_reapplies():
    local = BASE.replace("name: demo-skill", "name: demo-skill\ndisable: true")
    result = merge(BASE, local, BASE)
    assert len(result.reapplied) == 1
    assert "disable: true" in result.merged


def test_upstream_insertion_is_taken():
    upstream = BASE.replace("## Create",
                            "New upstream paragraph.\n\n## Create")
    result = merge(BASE, LOCAL, upstream)
    assert result.inserted == 1
    assert "New upstream paragraph." in result.merged
    assert not result.conflicts
