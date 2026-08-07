"""End-to-end CLI flows in a throwaway consumer repo — SPEC.md's worked
scenario: vendor a skill, adapt bash→zsh locally, keep syncing upstream.
"""

import json
import os

import pytest

from cedit import cli
from cedit.blocks import canonicalise

DOC = os.path.join("skills", "demo", "SKILL.md")

UPSTREAM_V1 = """\
# Demo skill

Intro paragraph explaining the skill.

## Setup

Run the healthcheck first:

```bash
bash scripts/statuscheck.sh --role assigner
```

Prose about the setup step.

## Create

```bash
bash scripts/jira.sh issue create --project "$KEY"
```
"""

# v2: ordinary upstream evolution — new intro wording, a better create command.
UPSTREAM_V2 = UPSTREAM_V1.replace(
    "Intro paragraph explaining the skill.",
    "Intro paragraph explaining the skill, now clearer.",
).replace('--project "$KEY"', '--project "$KEY" --type Task')

# v3: upstream now touches the fence the user rewrote for zsh.
UPSTREAM_V3 = UPSTREAM_V2.replace(
    "statuscheck.sh --role assigner",
    "statuscheck.sh --role assigner --strict",
)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    upstream = tmp_path / "upstream" / DOC
    upstream.parent.mkdir(parents=True)
    upstream.write_text(UPSTREAM_V1, encoding="utf-8")
    return tmp_path


def read_doc(repo):
    return (repo / DOC).read_text(encoding="utf-8")


def write_upstream(repo, text):
    (repo / "upstream" / DOC).write_text(text, encoding="utf-8")


def zshify_working_copy(repo):
    doc = repo / DOC
    doc.write_text(
        read_doc(repo).replace(
            "```bash\nbash scripts/statuscheck.sh --role assigner",
            "```zsh\nzsh scripts/statuscheck.sh --role assigner",
        ),
        encoding="utf-8",
    )


def manifest(repo):
    return json.loads((repo / ".cedit" / "manifest.json").read_text())


def overlay(repo):
    return json.loads((repo / ".cedit" / "overlay.json").read_text())


def test_full_lifecycle(repo, capsys):
    upstream_file = os.path.join("upstream", DOC)

    # -- snapshot vendors the file and records the base --------------------
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    assert read_doc(repo) == canonicalise(UPSTREAM_V1)
    assert (repo / ".cedit" / "base" / DOC).exists()
    assert manifest(repo)["docs"][DOC]["conflicts"] == {}

    # -- the local adaptation shows up in diff and the overlay -------------
    zshify_working_copy(repo)
    assert cli.main(["diff"]) == 0
    out = capsys.readouterr().out
    assert "1 local edit(s)" in out and "zsh" in out

    assert cli.main(["sync", "--from", "upstream"]) == 0  # v1 == base
    assert "up to date" in capsys.readouterr().out

    # -- ordinary upstream evolution merges cleanly ------------------------
    write_upstream(repo, UPSTREAM_V2)
    assert cli.main(["sync", "--from", "upstream"]) == 0
    merged = read_doc(repo)
    assert "now clearer" in merged                       # upstream prose in
    assert "--type Task" in merged                       # unedited fence updated
    assert "zsh scripts/statuscheck.sh" in merged        # adaptation survived
    edits = overlay(repo)["docs"][DOC]["edits"]
    assert len(edits) == 1 and edits[0]["local_info"] == "zsh"

    # -- upstream touching the adapted fence is a conflict -----------------
    write_upstream(repo, UPSTREAM_V3)
    assert cli.main(["sync", "--from", "upstream"]) == 1
    out = capsys.readouterr().out
    assert "CONFLICT" in out
    assert "zsh scripts/statuscheck.sh" in read_doc(repo)  # local kept
    conflicts = manifest(repo)["docs"][DOC]["conflicts"]
    assert len(conflicts) == 1
    (key,) = conflicts
    assert conflicts[key]["upstream_text"].strip().endswith("--strict")

    # -- a doc with open conflicts refuses to sync -------------------------
    assert cli.main(["sync", "--from", "upstream"]) == 2

    # -- status reports the conflict ---------------------------------------
    assert cli.main(["status"]) == 1
    assert "1 unresolved conflict(s)" in capsys.readouterr().out

    # -- resolve --show prints all three versions --------------------------
    assert cli.main(["resolve", DOC, key.split(":")[0], "--show"]) == 0
    out = capsys.readouterr().out
    assert "--strict" in out and "zsh scripts" in out

    # -- take upstream: the file gets upstream's fence ---------------------
    assert cli.main(["resolve", DOC, key, "--take", "upstream"]) == 0
    merged = read_doc(repo)
    assert "--strict" in merged
    assert "zsh scripts/statuscheck.sh" not in merged
    assert manifest(repo)["docs"][DOC]["conflicts"] == {}
    assert overlay(repo)["docs"][DOC]["edits"] == []
    assert cli.main(["sync", "--from", "upstream"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_resolve_take_local_rekeys_the_edit(repo, capsys):
    upstream_file = os.path.join("upstream", DOC)
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    zshify_working_copy(repo)

    write_upstream(repo, UPSTREAM_V3)
    assert cli.main(["sync", "--from", "upstream"]) == 1
    (key,) = manifest(repo)["docs"][DOC]["conflicts"]

    assert cli.main(["resolve", DOC, key, "--take", "local"]) == 0
    assert manifest(repo)["docs"][DOC]["conflicts"] == {}
    # the adaptation is now an ordinary overlay edit against the new base
    edits = overlay(repo)["docs"][DOC]["edits"]
    assert len(edits) == 1 and edits[0]["local_info"] == "zsh"
    assert "--strict" in edits[0]["base_text"]  # re-keyed to the new upstream
    # and the next sync is clean
    assert cli.main(["sync", "--from", "upstream"]) == 0
    assert "up to date" in capsys.readouterr().out
    assert "zsh scripts/statuscheck.sh" in read_doc(repo)


def test_orphan_resolution(repo, capsys):
    upstream_file = os.path.join("upstream", DOC)
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    doc = repo / DOC
    doc.write_text(read_doc(repo).replace("Prose about the setup step.",
                                          "Prose about the setup step (ours)."),
                   encoding="utf-8")

    write_upstream(repo, UPSTREAM_V1.replace("Prose about the setup step.\n\n", ""))
    assert cli.main(["sync", "--from", "upstream"]) == 1
    out = capsys.readouterr().out
    assert "ORPHAN" in out
    (key,) = manifest(repo)["docs"][DOC]["conflicts"]

    # keeping an orphan would be structural — refused with the text preserved
    assert cli.main(["resolve", DOC, key, "--take", "local"]) == 2
    # accepting the deletion clears it
    assert cli.main(["resolve", DOC, key, "--take", "upstream"]) == 0
    assert manifest(repo)["docs"][DOC]["conflicts"] == {}
    assert "Prose about the setup step" not in read_doc(repo)


def test_snapshot_of_already_adapted_copy_records_the_overlay(repo):
    upstream_file = os.path.join("upstream", DOC)
    # the consumer edited their vendored copy before ever using cedit
    doc = repo / DOC
    doc.parent.mkdir(parents=True)
    doc.write_text(
        UPSTREAM_V1.replace(
            "```bash\nbash scripts/statuscheck.sh --role assigner",
            "```zsh\nzsh scripts/statuscheck.sh --role assigner",
        ),
        encoding="utf-8",
    )
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    edits = overlay(repo)["docs"][DOC]["edits"]
    assert len(edits) == 1 and edits[0]["local_info"] == "zsh"


def test_structural_local_edit_blocks_sync_with_a_clear_message(repo, capsys):
    upstream_file = os.path.join("upstream", DOC)
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    doc = repo / DOC
    doc.write_text(read_doc(repo) + "\nA locally appended paragraph.\n",
                   encoding="utf-8")
    write_upstream(repo, UPSTREAM_V2)
    assert cli.main(["sync", "--from", "upstream"]) == 2
    err = capsys.readouterr().err
    assert "structural" in err and "inserted paragraph" in err


def test_dry_run_writes_nothing(repo):
    upstream_file = os.path.join("upstream", DOC)
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    zshify_working_copy(repo)
    before = read_doc(repo)
    base_before = (repo / ".cedit" / "base" / DOC).read_text(encoding="utf-8")
    hash_before = manifest(repo)["docs"][DOC]["base_doc_hash"]
    write_upstream(repo, UPSTREAM_V2)
    assert cli.main(["sync", "--from", "upstream", "--dry-run"]) == 0
    assert read_doc(repo) == before
    assert (repo / ".cedit" / "base" / DOC).read_text(encoding="utf-8") == base_before
    assert manifest(repo)["docs"][DOC]["base_doc_hash"] == hash_before


def test_untracked_doc_is_a_clean_error(repo, capsys):
    assert cli.main(["diff", DOC]) == 2
    assert "not tracked" in capsys.readouterr().err


# `$\rightarrow$` canonicalises to `$\\rightarrow$`, which GitHub renders as a
# line break inside math. Nothing downstream can see it (tests/test_mathguard.py),
# so the CLI has to warn where the bytes are written — and the exit code stays
# exactly what it was, per invariant 4.
MATHY = UPSTREAM_V1.replace("Intro paragraph explaining the skill.",
                            "Intro paragraph, where $\\rightarrow$ means \"then\".")


def test_math_warning_does_not_change_snapshot_or_sync_exit_codes(repo, capsys):
    upstream_file = os.path.join("upstream", DOC)
    write_upstream(repo, MATHY)

    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    captured = capsys.readouterr()
    assert "dollar-delimited math span(s)" in captured.err
    assert upstream_file in captured.err
    assert "```math" in captured.err
    assert "tracking" in captured.out                     # the run still succeeded

    zshify_working_copy(repo)
    write_upstream(repo, MATHY.replace('--project "$KEY"',
                                       '--project "$KEY" --type Task'))
    assert cli.main(["sync", "--from", "upstream"]) == 0   # still clean, still 0
    err = capsys.readouterr().err
    assert err.count("dollar-delimited math span(s)") == 2  # upstream and local


def test_a_document_without_math_warns_about_nothing(repo, capsys):
    upstream_file = os.path.join("upstream", DOC)
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    # UPSTREAM_V1 carries `"$KEY"` inside a fence — neither math nor flagged.
    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------
# CED-25 — GFM footnotes across a whole lifecycle
# --------------------------------------------------------------------------

NOTES = os.path.join("skills", "demo", "NOTES.md")

# Already canonical: the renderer puts definitions at the end in reference
# order, orphans last, which is how this is written.
NOTES_V1 = """\
# Notes

The release pipeline is three workflows.[^ci]

The local suite run is the gate.[^gate]

[^ci]: They are **this repo's own CI**, not a consumer's.

[^gate]: CI covers the version matrix you cannot run locally.

[^unused]: A definition nothing references.
"""

# Ordinary upstream evolution, nowhere near the footnote the consumer adapted.
NOTES_V2 = NOTES_V1.replace(
    "The release pipeline is three workflows.",
    "The release pipeline is three workflows, documented separately.",
)


def test_footnotes_survive_a_snapshot_sync_cycle(repo, capsys):
    """A footnote reference and its definition, end to end.

    Before CED-25 this vendored file came out of `snapshot` with every
    definition escaped to `\\[^label\\]:` — a dangling reference and a visible
    literal on GitHub — and cedit exited 0 while doing it. The cycle below is
    the whole contract: the base is byte-identical to what upstream shipped, a
    footnote body is an adaptable block like any other, and an upstream update
    elsewhere re-applies that adaptation rather than conflicting with it.
    """
    upstream = repo / "upstream" / NOTES
    upstream.write_text(NOTES_V1, encoding="utf-8")
    upstream_file = os.path.join("upstream", NOTES)

    # -- snapshot vendors it unchanged, escapes and all absent -------------
    assert cli.main(["snapshot", NOTES, "--from", upstream_file]) == 0
    vendored = (repo / NOTES).read_text(encoding="utf-8")
    assert vendored == NOTES_V1                      # byte-for-byte, not merely close
    assert "\\[^" not in vendored
    assert "[^unused]: A definition nothing references." in vendored
    base = (repo / ".cedit" / "base" / NOTES).read_text(encoding="utf-8")
    assert base == NOTES_V1                          # and the same went into state

    # -- a footnote body is an ordinary editable block ---------------------
    (repo / NOTES).write_text(
        vendored.replace(
            "CI covers the version matrix you cannot run locally.",
            "CI covers the version matrix; `venv/bin/python3 -m pytest` is ours.",
        ),
        encoding="utf-8",
    )
    assert cli.main(["diff", NOTES]) == 0
    assert "1 local edit(s)" in capsys.readouterr().out

    # -- upstream moves elsewhere; the adapted footnote is re-applied ------
    (repo / "upstream" / NOTES).write_text(NOTES_V2, encoding="utf-8")
    assert cli.main(["sync", "--from", "upstream"]) == 0
    merged = (repo / NOTES).read_text(encoding="utf-8")
    assert "documented separately" in merged                        # upstream in
    assert "`venv/bin/python3 -m pytest` is ours." in merged        # adaptation kept
    assert "\\[^" not in merged                                     # still unescaped
    assert "[^unused]: A definition nothing references." in merged  # orphan still there
    assert manifest(repo)["docs"][NOTES]["conflicts"] == {}
