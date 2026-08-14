"""End-to-end CLI flows in a throwaway consumer repo — docs/SPEC.md's worked
scenario: vendor a skill, adapt bash→zsh locally, keep syncing upstream.
"""

import importlib.metadata
import json
import os

import mdformat.plugins
import pytest

import cedit
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


# CED-26/CED-27 — `$\rightarrow$` used to canonicalise to `$\\rightarrow$`,
# which GitHub renders as a line break inside math. CED-26 warned about it;
# CED-27 preserves it. These are the two stateful write paths (the third,
# `md canonicalize -i`, is in tests/test_mdcli.py).
MATH_LINE = "Intro paragraph, where $\\rightarrow$ means \"then\"."
MATHY = UPSTREAM_V1.replace("Intro paragraph explaining the skill.", MATH_LINE)


def test_snapshot_writes_a_base_with_the_math_intact(repo, capsys):
    upstream_file = os.path.join("upstream", DOC)
    write_upstream(repo, MATHY)

    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    captured = capsys.readouterr()
    assert "tracking" in captured.out
    assert captured.err == ""                             # nothing left to warn about

    # `.cedit/base/` is what every later merge reads as the truth about
    # upstream; before CED-27 it held `$\\rightarrow$` from the first snapshot
    # on, while the working copy still held the correct form.
    base = (repo / ".cedit" / "base" / DOC).read_text(encoding="utf-8")
    assert MATH_LINE in base
    assert read_doc(repo) == base


def test_sync_does_not_rewrite_a_math_line_neither_side_touched(repo, capsys):
    """QA's reproduction, end to end, as a regression test.

    The math line is byte-identical upstream and locally, and upstream's new
    revision does not go near it. cedit used to report "no conflicts", exit 0,
    and rewrite that line in the user's document anyway — inventing a change
    neither side made, which AGENTS.md invariant 3 forbids outright.
    """
    upstream_file = os.path.join("upstream", DOC)
    write_upstream(repo, MATHY)
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    zshify_working_copy(repo)
    before = read_doc(repo)
    assert MATH_LINE in before

    # An unrelated upstream edit: a new flag on the create command.
    write_upstream(repo, MATHY.replace('--project "$KEY"',
                                       '--project "$KEY" --type Task'))
    capsys.readouterr()
    assert cli.main(["sync", "--from", "upstream"]) == 0
    captured = capsys.readouterr()
    assert "no conflicts" in captured.out
    assert captured.err == ""

    after = read_doc(repo)
    assert MATH_LINE in after
    assert "$\\\\rightarrow$" not in after
    # The only difference is the one upstream actually made.
    assert after == before.replace('--project "$KEY"',
                                   '--project "$KEY" --type Task')
    assert MATH_LINE in (repo / ".cedit" / "base" / DOC).read_text(encoding="utf-8")

    # And the overlay still sees exactly the one local edit, so the math line
    # did not quietly become an adaptation of a base that was never written.
    assert cli.main(["status", DOC]) == 0
    assert "1 local edit(s)" in capsys.readouterr().out


def test_resolve_take_upstream_writes_the_math_it_recorded(repo, capsys):
    """The fourth write path, and the one that goes through a splice.

    It also pins the boundary: what the manifest records, and what `resolve
    --show` prints back, is the math as the author wrote it — the sentinel
    lives in the token stream and nowhere a user or a state file can see it.
    """
    upstream_file = os.path.join("upstream", DOC)
    assert cli.main(["snapshot", DOC, "--from", upstream_file]) == 0
    doc = repo / DOC
    doc.write_text(read_doc(repo).replace("Prose about the setup step.",
                                          "Prose about the setup step (ours)."),
                   encoding="utf-8")

    write_upstream(repo, UPSTREAM_V1.replace(
        "Prose about the setup step.",
        "Prose about the setup step, now $\\rightarrow$ annotated."))
    assert cli.main(["sync", "--from", "upstream"]) == 1
    (key,) = manifest(repo)["docs"][DOC]["conflicts"]
    recorded = manifest(repo)["docs"][DOC]["conflicts"][key]
    assert recorded["upstream_text"] == \
        "Prose about the setup step, now $\\rightarrow$ annotated."

    capsys.readouterr()
    assert cli.main(["resolve", DOC, key, "--take", "upstream"]) == 0
    assert capsys.readouterr().err == ""
    assert "now $\\rightarrow$ annotated." in read_doc(repo)
    assert "$\\\\rightarrow$" not in read_doc(repo)


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


# --------------------------------------------------------------------------
# `--version` / `--help` — CED-33
#
# The flag reports what the parser *is*, which is the first question any
# conflict report needs answered: every hash in a consumer's `.cedit/` state
# is a function of the parsing stack and of the mdformat plugins installed
# alongside it (AGENTS.md invariant 2). These tests pin the parts of that
# block a reader is told to compare against a baseline.
#
# `main()` returns an int; the version and help actions instead exit during
# parsing, so they are asserted with `pytest.raises(SystemExit)` rather than
# by relaxing main()'s contract to accommodate them.
# --------------------------------------------------------------------------


def test_version_exits_zero_with_no_subcommand(capsys):
    """`add_subparsers(required=True)` must not defeat `--version`.

    argparse runs an option's action during parsing, before it checks that a
    required subparser was supplied — but that ordering is the whole reason
    the flag is usable, so it is asserted rather than assumed.
    """
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0

    first = capsys.readouterr().out.splitlines()[0]
    assert first == f"cedit {cedit.__version__}"


def test_version_reports_the_stack_resolved_at_runtime(capsys):
    """Every pinned distribution, at the version actually installed.

    Hard-coding the list from requirements.txt would report the pin while the
    user runs something else entirely — the precise failure this flag exists
    to diagnose — so the assertion is against the live metadata.
    """
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    out = capsys.readouterr().out

    assert "Python " in out
    # The stack line wraps, so match against it flattened rather than pinning
    # a layout the criteria explicitly leave to the implementer.
    flat = " ".join(out.split())
    for name in cli._STACK:
        assert f"{name} {importlib.metadata.version(name)}" in flat


def test_version_reports_the_installed_mdformat_plugin_set(capsys):
    """The highest-value line: `make_parser` never names its extensions.

    It appends every entry it finds in the environment, so an unrelated
    `pip install` changes what the parser is without touching any pin. This
    line is what .claude/rules/hash-stability.md asks an affected user to
    compare against the baseline's, without needing a Python REPL.
    """
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    out = capsys.readouterr().out

    plugins = sorted(mdformat.plugins.PARSER_EXTENSIONS)
    assert plugins, "no mdformat plugins installed — the environment is wrong"
    assert f"mdformat plugins: {', '.join(plugins)}" in out


def test_help_shows_both_the_flag_and_the_resolved_version(capsys):
    """`cedit --help` alone has to identify the build.

    Only the first line, though: the stack block belongs to `--version`, not
    to every help screen.
    """
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert "--version" in out                  # the standard options row
    assert cedit.__version__ in out            # and the build itself
    assert "mdformat plugins:" not in out      # but not the whole block


def test_version_degrades_rather_than_raising_when_nothing_is_installed(
        capsys, monkeypatch):
    """A diagnostic must survive the broken environment it describes.

    `importlib.metadata.version` raises `PackageNotFoundError` for anything
    not installed, and the test suite itself runs from an uninstalled source
    checkout (conftest.py puts the repo root on sys.path), so a naive lookup
    would traceback here rather than in some consumer's terminal.
    """
    def _raise(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _raise)

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert out.startswith(f"cedit {cedit.__version__}")
    flat = " ".join(out.split())
    for name in cli._STACK:
        assert f"{name} (not installed)" in flat
