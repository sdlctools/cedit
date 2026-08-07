"""The `cedit md` group — stateless views of the parsing core (mdcli.py).

These verbs are the only window onto `cedit/mdcore/`, so the tests worth
having are the ones that pin *contracts* rather than formatting: that
`blocks` reports the same keys the merge would use, that the token JSON
really round-trips, and that the exit codes stay inside AGENTS.md invariant 4.
"""

import io
import json
import os

import pytest

from cedit import cli
from cedit.blocks import canonicalise, parse_doc

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "kitchen-sink.md")

# Deliberately not canonical: mdformat renumbers the ordered list, normalises
# the bullet marker and strips the trailing spaces.
MESSY = "# Title\n\n*   one\n*   two\n\n1. a\n1. b\n"


def run(argv, capsys):
    """Run the CLI, returning (exit code, stdout, stderr)."""
    rc = cli.main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def feed_stdin(monkeypatch, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


# --------------------------------------------------------------------------
# canonicalize
# --------------------------------------------------------------------------


def test_canonicalize_writes_the_canonical_form_to_stdout(capsys):
    rc, out, _ = run(["md", "canonicalize", FIXTURE], capsys)
    assert rc == 0
    assert out == canonicalise(open(FIXTURE, encoding="utf-8").read())


def test_canonicalize_is_idempotent(capsys):
    _, once, _ = run(["md", "canonicalize", FIXTURE], capsys)
    assert canonicalise(once) == once


def test_canonicalize_reads_stdin(capsys, monkeypatch):
    feed_stdin(monkeypatch, MESSY)
    rc, out, _ = run(["md", "canonicalize"], capsys)
    assert rc == 0
    assert out == "# Title\n\n- one\n- two\n\n1. a\n2. b\n"


def test_check_exits_1_on_a_non_canonical_file(tmp_path, capsys):
    doc = tmp_path / "messy.md"
    doc.write_text(MESSY, encoding="utf-8")
    rc, _, err = run(["md", "canonicalize", "--check", str(doc)], capsys)
    assert rc == 1
    assert "not canonical" in err
    # --check never writes.
    assert doc.read_text(encoding="utf-8") == MESSY


def test_check_exits_0_on_a_canonical_file(tmp_path, capsys):
    doc = tmp_path / "clean.md"
    doc.write_text(canonicalise(MESSY), encoding="utf-8")
    rc, out, _ = run(["md", "canonicalize", "--check", str(doc)], capsys)
    assert rc == 0
    assert out == ""


def test_in_place_rewrites_and_then_reports_no_change(tmp_path, capsys):
    doc = tmp_path / "messy.md"
    doc.write_text(MESSY, encoding="utf-8")

    rc, out, _ = run(["md", "canonicalize", "-i", str(doc)], capsys)
    assert rc == 0
    assert "canonicalised" in out
    assert doc.read_text(encoding="utf-8") == canonicalise(MESSY)

    rc, out, _ = run(["md", "canonicalize", "-i", str(doc)], capsys)
    assert rc == 0
    assert "already canonical" in out


def test_in_place_on_stdin_is_an_error(capsys, monkeypatch):
    feed_stdin(monkeypatch, MESSY)
    rc, _, err = run(["md", "canonicalize", "-i"], capsys)
    assert rc == 2
    assert "--in-place needs a file" in err


def test_check_and_in_place_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.main(["md", "canonicalize", "--check", "-i", FIXTURE])


def test_canonicalize_warns_about_math_without_moving_the_exit_code(tmp_path, capsys):
    doc = tmp_path / "math.md"
    doc.write_text("Inline $\\rightarrow$ here.\n", encoding="utf-8")

    # stdout stays the data channel: the canonical form, and only that.
    rc, out, err = run(["md", "canonicalize", str(doc)], capsys)
    assert rc == 0
    assert out == "Inline $\\\\rightarrow$ here.\n"
    assert "dollar-delimited math span(s)" in err

    # --check keeps its own meaning of 1 — the warning explains it, and the
    # pair is the gate a CI job wires up (USERGUIDE.md §13).
    rc, _, err = run(["md", "canonicalize", "--check", str(doc)], capsys)
    assert rc == 1
    assert "dollar-delimited math span(s)" in err and "not canonical" in err


# --------------------------------------------------------------------------
# ast
# --------------------------------------------------------------------------


def test_ast_dumps_a_nested_tree_marking_the_edit_blocks(capsys):
    rc, out, _ = run(["md", "ast", FIXTURE], capsys)
    assert rc == 0
    lines = out.splitlines()
    assert lines[0] == 'front_matter [opaque] "title: Kitchen sink tags: - fixture - do-not-edit-casually"'
    # Units are marked, and their inline children are nested under them.
    assert any(line.startswith("heading h1 [unit]") for line in lines)
    assert any(line.startswith("  inline") for line in lines)
    # A fence carries its info string, which is where ```bash -> ```zsh lives.
    assert any("fence code info=bash [opaque]" in line for line in lines)


def test_ast_hashes_match_the_block_hashes(capsys):
    rc, out, _ = run(["md", "ast", "--hashes", FIXTURE], capsys)
    assert rc == 0
    hashed = [line for line in out.splitlines() if "#" in line]
    assert hashed
    doc = parse_doc(open(FIXTURE, encoding="utf-8").read())
    for block in doc.blocks:
        assert any(f"#{block.hash}" in line for line in hashed)


def test_raw_and_canonical_differ_on_a_non_canonical_input(tmp_path, capsys):
    doc = tmp_path / "messy.md"
    doc.write_text(MESSY, encoding="utf-8")
    _, canonical, _ = run(["md", "ast", "--hashes", str(doc)], capsys)
    _, raw, _ = run(["md", "ast", "--hashes", "--raw", str(doc)], capsys)
    # Same structure, different hashes: the ordered list was renumbered.
    assert raw != canonical


# --------------------------------------------------------------------------
# json / from-json
# --------------------------------------------------------------------------


def test_json_defaults_to_the_token_stream(capsys):
    rc, out, _ = run(["md", "json", FIXTURE], capsys)
    assert rc == 0
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert payload[0]["type"] == "front_matter"


def test_json_tree_is_nested_and_carries_hashes_and_kinds(capsys):
    rc, out, _ = run(["md", "json", "--tree", FIXTURE], capsys)
    assert rc == 0
    root = json.loads(out)
    assert root["type"] == "root"
    kinds = {c.get("kind") for c in root["children"]}
    assert {"unit", "opaque"} <= kinds
    assert all("hash" in c for c in root["children"])


def test_token_json_round_trips_back_to_the_canonical_form(tmp_path, capsys):
    """The contract that makes `--tokens` an interchange format and not a dump."""
    _, tokens, _ = run(["md", "json", FIXTURE], capsys)
    blob = tmp_path / "tokens.json"
    blob.write_text(tokens, encoding="utf-8")

    rc, rendered, _ = run(["md", "from-json", str(blob)], capsys)
    assert rc == 0
    assert rendered == canonicalise(open(FIXTURE, encoding="utf-8").read())


def test_from_json_rejects_invalid_json(tmp_path, capsys):
    blob = tmp_path / "bad.json"
    blob.write_text("{not json", encoding="utf-8")
    rc, _, err = run(["md", "from-json", str(blob)], capsys)
    assert rc == 2
    assert "invalid JSON" in err


def test_from_json_rejects_the_tree_shape_with_a_pointed_message(tmp_path, capsys):
    _, tree, _ = run(["md", "json", "--tree", FIXTURE], capsys)
    blob = tmp_path / "tree.json"
    blob.write_text(tree, encoding="utf-8")
    rc, _, err = run(["md", "from-json", str(blob)], capsys)
    assert rc == 2
    assert "expected a token stream" in err


def test_from_json_rejects_a_list_of_non_tokens(tmp_path, capsys):
    blob = tmp_path / "bad.json"
    blob.write_text('[{"nope": 1}]', encoding="utf-8")
    rc, _, err = run(["md", "from-json", str(blob)], capsys)
    assert rc == 2
    assert "not a markdown-it token" in err


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------


def test_blocks_json_reports_exactly_what_the_merge_keys_on(capsys):
    """`md blocks` must agree with `parse_doc`, or it is lying about hashes."""
    rc, out, _ = run(["md", "blocks", "--json", FIXTURE], capsys)
    assert rc == 0
    payload = json.loads(out)

    doc = parse_doc(open(FIXTURE, encoding="utf-8").read())
    assert payload["doc_hash"] == doc.doc_hash
    assert [b["key"] for b in payload["blocks"]] == [b.key for b in doc.blocks]
    assert [b["kind"] for b in payload["blocks"]] == [b.kind for b in doc.blocks]
    assert [b["text"] for b in payload["blocks"]] == [b.text for b in doc.blocks]


def test_blocks_keys_match_the_recorded_parser_baseline():
    """The keys `md blocks` prints are the ones consumers have in `.cedit/`.

    `tests/parser-baseline.json` is the drift check's record of this fixture;
    if the two ever disagree, one of them is computing hashes differently.
    """
    baseline = json.load(open(
        os.path.join(os.path.dirname(__file__), "parser-baseline.json"),
        encoding="utf-8"))["fixture"]
    doc = parse_doc(open(FIXTURE, encoding="utf-8").read())
    assert doc.doc_hash == baseline["doc_hash"]
    assert [b.key for b in doc.blocks] == [b["key"] for b in baseline["blocks"]]


def test_blocks_human_output_names_the_conflict_key_shape(capsys):
    rc, out, _ = run(["md", "blocks", FIXTURE], capsys)
    assert rc == 0
    assert "block(s), doc " in out
    doc = parse_doc(open(FIXTURE, encoding="utf-8").read())
    first = doc.blocks[0]
    # `<hash>:<occurrence>` — the same key `cedit resolve` takes.
    assert f"#{first.hash}:{first.occurrence}" in out


def test_blocks_reads_stdin(capsys, monkeypatch):
    feed_stdin(monkeypatch, MESSY)
    rc, out, _ = run(["md", "blocks", "--json"], capsys)
    assert rc == 0
    assert len(json.loads(out)["blocks"]) == 5  # heading + 2 bullets + 2 items


# --------------------------------------------------------------------------
# Shared contracts
# --------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["canonicalize", "ast", "json", "blocks"])
def test_a_missing_file_is_a_clean_exit_2(verb, capsys):
    rc, _, err = run(["md", verb, "no-such-file.md"], capsys)
    assert rc == 2
    assert "no-such-file.md" in err


def test_md_needs_a_verb():
    with pytest.raises(SystemExit):
        cli.main(["md"])


def test_state_dir_is_accepted_and_ignored(tmp_path, capsys, monkeypatch):
    """The stateless verbs must not touch `.cedit/` even when pointed at one."""
    monkeypatch.chdir(tmp_path)
    rc, _, _ = run(["--state-dir", str(tmp_path / "state"),
                    "md", "canonicalize", FIXTURE], capsys)
    assert rc == 0
    assert not (tmp_path / "state").exists()
