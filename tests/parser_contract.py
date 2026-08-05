"""The parser contract — a drift detector for everything hashes depend on.

`cedit/mdcore/utils.make_parser` is a contract, not a convenience: every hash
in every consumer's `.cedit/` state is taken over its output. It is assembled
from six pinned packages *plus whatever mdformat plugins happen to be
installed*, so it can move without a single line of this repository changing.

That failure mode is cheap to detect and expensive to discover. The suite
cannot detect it on its own: every other test computes both sides of every
comparison with the parser it is running under, so a change that moves every
hash consistently passes green. This module is the check that does not.

    venv/bin/python3 -m pytest tests/test_parser_contract.py   # verify
    venv/bin/python3 tests/parser_contract.py --update         # re-record

Re-recording is a deliberate act. Read the diff first, and read
`.claude/rules/hash-stability.md` before deciding the move is acceptable —
a moved hash is a wall of false conflicts on machines you will never see.

## The four drift classes, cheapest signal first

1. **Pins** — the installed versions of the six packages `make_parser` is
   built from. Catches an environment that does not match
   `requirements.txt`, before anything subtler is even worth reading.

2. **Plugin set** — `mdformat.plugins.PARSER_EXTENSIONS`, which
   `make_parser` enumerates at runtime and appends *all* of. Installing any
   further mdformat plugin, even as a transitive dependency of something
   unrelated, changes what the parser is. Nothing in `requirements.txt`
   records that it happened; this does.

3. **Option surface** — the effective options of the configured parser. A
   preset gaining an option shows up here *before* anyone writes a document
   that triggers it, which is the earliest warning available and the reason
   `tasklists` and `alerts` are set explicitly in `make_parser`.

4. **Canonical form and hashes** — the fixture's canonical bytes, its
   document hash and every block key. This is the expensive drift: nothing
   raises, the corpus just silently re-keys. Pinned exactly.

The fixture rather than the repository's own Markdown is the subject,
deliberately: the docs change whenever someone edits them, which would make
the baseline churn and train everyone to re-record it without reading.
`tests/fixtures/kitchen-sink.md` changes only when someone means to.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import pathlib
import sys

if __name__ == "__main__":  # direct run: make `import cedit` work
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import mdformat.plugins

from cedit.blocks import parse_doc
from cedit.mdcore.utils import make_parser

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "kitchen-sink.md"
BASELINE = HERE / "parser-baseline.json"

# The packages `make_parser` is assembled from. Kept as a literal rather than
# read out of requirements.txt: this list is about what the parser *is*, and
# test_packaging.py already guards requirements.txt against pyproject.toml.
PINNED = (
    "markdown-it-py",
    "mdit-py-plugins",
    "mdformat",
    "mdformat-gfm",
    "mdformat-frontmatter",
    "linkify-it-py",
)

# Option values that are objects rather than data — module lists, callables.
# Their reprs carry memory addresses and import paths, so recording them would
# be noise. `parser_extension` is covered by the plugin set above it.
_SCALARS = (str, int, float, bool, type(None))


def option_surface() -> dict:
    """Every option name, with the value where the value is data."""
    options = make_parser().options
    return {
        name: (value if isinstance(value, _SCALARS) else f"<{type(value).__name__}>")
        for name, value in sorted(options.items())
    }


def record() -> dict:
    """The complete surface every recorded hash depends on."""
    raw = FIXTURE.read_text("utf-8")
    doc = parse_doc(raw)

    return {
        "pins": {name: importlib.metadata.version(name) for name in PINNED},
        "plugins": sorted(mdformat.plugins.PARSER_EXTENSIONS),
        "options": option_surface(),
        "fixture": {
            "source_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "canonical_sha256": hashlib.sha256(doc.canonical.encode()).hexdigest(),
            "doc_hash": doc.doc_hash,
            "blocks": [
                {
                    "key": b.key,
                    "kind": b.kind,
                    "node_type": b.node_type,
                    "info": b.info,
                    "context": b.context,
                }
                for b in doc.blocks
            ],
        },
    }


def load_baseline() -> dict:
    return json.loads(BASELINE.read_text("utf-8"))


def drift() -> list[str]:
    """Human-readable descriptions of every difference, empty when clean."""
    current, baseline = record(), load_baseline()
    found: list[str] = []

    for name, version in current["pins"].items():
        was = baseline["pins"].get(name)
        if was != version:
            found.append(f"pin {name}: baseline {was} -> installed {version}")

    added = set(current["plugins"]) - set(baseline["plugins"])
    removed = set(baseline["plugins"]) - set(current["plugins"])
    if added:
        found.append(
            f"mdformat plugins added: {sorted(added)} — every installed plugin "
            f"is appended by make_parser, so this changes the parser"
        )
    if removed:
        found.append(f"mdformat plugins removed: {sorted(removed)}")

    for name in sorted(set(current["options"]) | set(baseline["options"])):
        now = current["options"].get(name, "<absent>")
        was = baseline["options"].get(name, "<absent>")
        if now != was:
            found.append(f"parser option {name!r}: baseline {was!r} -> now {now!r}")

    fix_now, fix_was = current["fixture"], baseline["fixture"]
    if fix_now["source_sha256"] != fix_was["source_sha256"]:
        found.append(
            "the fixture itself was edited — re-record deliberately, and know "
            "that the hashes below moved because of the edit, not the parser"
        )
    for field in ("canonical_sha256", "doc_hash"):
        if fix_now[field] != fix_was[field]:
            found.append(
                f"fixture {field}: baseline {fix_was[field]} -> now {fix_now[field]}"
            )

    keys_now = [b["key"] for b in fix_now["blocks"]]
    keys_was = [b["key"] for b in fix_was["blocks"]]
    if keys_now != keys_was:
        moved = [k for k in keys_was if k not in keys_now]
        fresh = [k for k in keys_now if k not in keys_was]
        found.append(
            f"{len(moved)} of {len(keys_was)} block hashes moved "
            f"(gone: {moved[:3]}{'...' if len(moved) > 3 else ''}; "
            f"new: {fresh[:3]}{'...' if len(fresh) > 3 else ''})"
        )
    elif fix_now["blocks"] != fix_was["blocks"]:
        found.append("block classification changed with the hashes unmoved")

    return found


def main() -> int:
    if "--update" in sys.argv:
        BASELINE.write_text(
            json.dumps(record(), indent=2, ensure_ascii=False) + "\n", "utf-8"
        )
        print(f"re-recorded {BASELINE.relative_to(BASELINE.parent.parent)}")
        return 0

    found = drift()
    if not found:
        print("no drift — the parser contract holds")
        return 0
    print("PARSER DRIFT:", file=sys.stderr)
    for line in found:
        print(f"  - {line}", file=sys.stderr)
    print(
        "\nRead .claude/rules/hash-stability.md before accepting this. "
        "Re-record with --update only once you have read the diff.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
