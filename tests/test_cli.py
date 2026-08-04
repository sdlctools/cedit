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
