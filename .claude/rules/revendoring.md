# Re-vendoring `cedit/mdcore/`

The procedure behind invariant 1 in [AGENTS.md](../../AGENTS.md): how to
take a new revision of the parser and diff engine from the
markdown-localization research repo, and how to tell whether doing so moved
the hashes in every consumer's `.cedit/` state.

**This file is a reference, not an instruction set.** Like
[release-pipeline.md](release-pipeline.md) and
[manual-release.md](manual-release.md) it is deliberately not `@`-imported by
`AGENTS.md` — read it when you are about to change anything under
`cedit/mdcore/`, or bump one of the parsing pins.

This is the highest-consequence operation in the repo. Nothing in the program
can catch a mistake here: a change to canonicalisation, hashing or
segmentation moves hashes that were recorded on machines you will never see,
and the failure surfaces as *their* next `sync` reporting a wall of conflicts
against blocks nobody touched.

Where the other documents stop:

| Document | Answers |
| --- | --- |
| [AGENTS.md](../../AGENTS.md) | invariant 1 (`mdcore/` is frozen) and invariant 2 (the pins are exact) — the rules |
| [SPEC.md](../../SPEC.md) | *Reuse rules* — what must not fork, and why the vendored machinery is reusable at all |
| [ARCHITECTURE.md](../../ARCHITECTURE.md) | which vendored symbols cedit actually calls, and which are carried unused |
| **this file** | how to perform a re-vendoring, how to classify what it changes, and what consumers do when hashes moved |

## What is vendored, and from where

Upstream is the markdown-localization research repo,
`git@github.com:kantorv/markdown-localization.git`. Two files come from it:

| Vendored file | Upstream source | Relationship |
| --- | --- | --- |
| `cedit/mdcore/tree_diff.py` | `app/tree_diff.py` | the whole module body, copied |
| `cedit/mdcore/utils.py` | `app/utils.py` | trimmed to the four functions cedit uses |
| `cedit/mdcore/__init__.py` | — | cedit's own; no upstream counterpart |

Nothing else in `cedit/` is vendored. `blocks.py`, `align.py`, `merge3.py`,
`state.py`, `store.py` and `cli.py` are cedit's, and the splice/verify and
atomic-write invariants they carry are cedit's too (SPEC.md, *Reuse rules*).

### What may differ from upstream, and nothing else

`tree_diff.py` is byte-identical to upstream from the `# Node classification`
banner through `_focus`. Exactly three hunks differ, and re-applying them is
the whole of a re-vendoring:

1. the module docstring — rewritten to say it is vendored and that a change
   here moves every recorded hash;
2. the imports — upstream's `os`/`sys` imports and its
   `sys.path.insert(...)` hack are dropped, and `from utils import
   ast_to_markdown, markdown_to_ast` becomes `from .utils import
   markdown_to_ast`;
3. the trailing demo — `HERE`, `SAMPLE`, the commented-out `_mutate`, and
   `main()` with its `if __name__ == "__main__"` block are dropped. The
   `WIDTH` / `_clip` / `_focus` display helpers above them are **kept**:
   `cli._pair` and `cli._print_conflict` call them.

`utils.py` keeps `make_parser`, `markdown_to_ast`, `parse_inline` and
`ast_to_markdown`, with `make_parser`'s body identical option for option, and
drops upstream's `normalize_markdown`, `generate_ast_tree`, `node_to_xml` and
`markdown_to_xml` (a file-I/O and XML-demo surface cedit has no use for).
Comments are condensed; the *reasoning* for `tasklists=False` and
`alerts=False` is kept, because it is the worked example of a hash-neutral
argument (below).

### Do not trim the unused surface

`tree_diff.py` carries a large surface cedit never calls: `plan` and
`WorkItem`, `diff_trees` with `_diff_node` / `_diff_children` /
`_align_window` / `_detect_moves` and `Op` / `KINDS`, `similarity`,
`tm_keys`, `_placeholders`, `_units_under`, `_opaque_under`, `_fuzzy_pair`
and `NON_TRANSLATABLE_INLINE`. ARCHITECTURE.md lists it symbol by symbol.

It is kept so that a re-vendoring stays a **copy** rather than a merge. Delete
it and every future re-vendoring becomes a hand-merge of upstream's changes
into a locally-pruned file — which is precisely the operation that moves a
hash by accident. The dead weight is the cheap half of the trade.

One trap: the vendored module's own docstring says cedit uses it for
"segmentation (`_units_under`, `_unit_source`, `_opaque_under`)". Only
`_unit_source` is true — `blocks.parse_doc` walks the tree itself using
`is_unit` and `OPAQUE`. The docstring stays as it is because the file is
frozen; ARCHITECTURE.md's table is the accurate list.

## The procedure

Preconditions: a clean worktree, and an upstream checkout at the revision you
intend to vendor. Note its commit SHA now — the vendored files carry no
version marker, so the commit message is the only provenance there will ever
be.

1. **Diff before deciding.** With `$UP` pointing at the upstream checkout:

   ```bash
   diff -u "$UP/app/tree_diff.py" cedit/mdcore/tree_diff.py
   diff -u "$UP/app/utils.py"     cedit/mdcore/utils.py
   ```

   Everything except the known hunks above is upstream's change — that is
   what you are vendoring, and every hunk of it gets classified in step 2. If
   the diff is scattered across the file instead, the vendored copy has been
   edited in place at some point; reconcile that first, as a separate commit,
   or you will vendor a hand-merge.

2. **Classify every incoming hunk** as hash-moving or hash-neutral — see the
   next section. Assume hash-moving until you have measured otherwise.

3. **Copy, then re-apply the three hunks.** Copy the upstream file over the
   vendored one and restore the docstring, the imports and the demo trim (and
   for `utils.py`, the trim to four functions). Do not take the opportunity to
   reformat anything.

4. **Move the pins if upstream moved them** — see *Which pins move with it*.

5. **Verify** — see *Verifying afterwards*. Both halves: the suite, and the
   drift check.

6. **Commit** with the upstream SHA in the message, and say in the message
   whether the change is hash-moving. If it is, that fact belongs in the
   release notes too: it is a breaking change to on-disk state, and the only
   warning a consumer gets.

## Which pins move with it

Six runtime pins, and they exist in two places that must stay byte-identical:
`requirements.txt` and `pyproject.toml`'s `[project] dependencies`.
`tests/test_packaging.py::test_pyproject_pins_match_requirements_txt` fails if
they drift, because the first is what a source checkout gets and the second is
what `pip install cedit` gets.

```
markdown-it-py==4.2.0
mdit-py-plugins==0.6.1
mdformat==1.0.0
mdformat-gfm==1.0.0
mdformat-frontmatter==2.1.2
linkify-it-py==2.1.0
```

Upstream's `requirements.txt` carries the same six plus dependencies of the
localization pipeline (`groq`, `pytest-asyncio`, `jsonschema`, `pyyaml`).
Those do **not** come along — only the six.

### The installed plugin set is part of the parser identity

`make_parser` (`cedit/mdcore/utils.py:35-38`) does not name its extensions.
It appends **every** entry of `mdformat.plugins.PARSER_EXTENSIONS` and calls
`update_mdit` on each — a runtime enumeration of whatever is installed in the
environment. So installing any further mdformat plugin (`mdformat-tables`,
`mdformat-footnote`, one arriving as a transitive dependency of something
unrelated) changes what the parser *is*, exactly like bumping a pin, and
nothing in `requirements.txt` records that it happened.

Corollary for consumers: `pipx install cedit` is safe because pipx gives it
its own environment. `pip install cedit` into a shared environment is not —
whatever else lives there is part of their parser.

## Hash-moving versus hash-neutral

A change is **hash-moving** if it alters any of:

- the canonical bytes `blocks.canonicalise` produces (the mdformat
  round-trip), which is what `.cedit/base/<path>` stores;
- the hash a block gets for the same canonical bytes — `hash_tree`'s inputs
  are `type`, `tag`, `info`, `own_text` and the child hashes;
- which nodes become blocks at all (`is_unit` / `UNIT_PARENTS` / `OPAQUE`),
  which also changes `blocks.block_signature` and therefore the render-verify
  check.

| Change | Class |
| --- | --- |
| a `make_parser` option that alters the token stream or the rendered form of any construct | hash-moving |
| a `make_parser` option that only switches *which implementation* produces the same token stream | hash-neutral — but prove it |
| anything touching `hash_tree`, `own_text`, `attr` or `norm` | hash-moving |
| `is_unit`, `UNIT_PARENTS`, `OPAQUE` | hash-moving **and** structural |
| `_unit_source`, `_heading_trail` | hash-moving (`_unit_source`) / display-only (`_heading_trail`, but it is stored in conflict records) |
| `ratio`, `SIM_THRESHOLD`, `FUZZY_THRESHOLD` | not hash-moving, but merge-moving: pairing changes, so a REAPPLY can become a CONFLICT |
| `plan`, `diff_trees`, `tm_keys`, `WorkItem`, `_placeholders`, the rest of the unused surface | inert for cedit — copy it and move on |
| any pin bump | assume hash-moving until the drift check says otherwise |

`cedit/mdcore/utils.py:20-30` carries two worked examples of hash-neutral
changes with the argument written out inline:

- **`tasklists = False`** — markdown-it-py ≥ 4.2's `gfm-like2` parses task
  lists natively but emits no checkbox token, while `mdformat_gfm`'s renderer
  was written against `mdit_py_plugins.tasklists`, which emits one. Switching
  the native implementation off hands task lists to the plugin the renderer
  can actually read. The token stream every *other* construct produces is
  unchanged, and so is the canonical form.
- **`alerts = False`** — `> [!NOTE]` would parse into `alert` nodes mdformat
  cannot render at all. Off, they are ordinary blockquotes that round-trip
  byte for byte and render identically on GitHub.

Both arguments have the same shape: *the output is unchanged*, not *the change
looks small*. That is the only shape that works, and it is a claim about
output — so measure it rather than arguing it.

## Verifying afterwards

Two checks, and the first does not subsume the second.

**1. The suite.** `venv/bin/python3 -m pytest` — 29 tests, no network. It
proves the merge matrix, the CLI lifecycle and the packaging guards still
behave. It does **not** prove hashes did not move: every test computes both
sides of every comparison with the parser it is running under, so a change
that moves every hash consistently passes green.

**2. The drift check.** Record the full hash surface over a corpus before the
change, re-record after, and diff. This is what the suite cannot see:

```bash
cat > /tmp/hashprint.py <<'PY'
"""Print the complete hash surface of a Markdown corpus."""
import hashlib, pathlib
from cedit.blocks import parse_doc

for path in sorted(pathlib.Path(".").rglob("*.md")):
    if "venv" in path.parts or ".cedit" in path.parts:
        continue
    doc = parse_doc(path.read_text("utf-8"))
    canon = hashlib.sha256(doc.canonical.encode()).hexdigest()[:16]
    print(f"{path} canonical={canon} doc={doc.doc_hash}")
    for b in doc.blocks:
        print(f"    {b.key} {b.kind}/{b.node_type} info={b.info!r}")
PY

git stash                                          # or check out the pre-change revision
PYTHONPATH=. venv/bin/python3 /tmp/hashprint.py > /tmp/before.txt
git stash pop
venv/bin/pip install -r requirements.txt           # only if the pins moved
PYTHONPATH=. venv/bin/python3 /tmp/hashprint.py > /tmp/after.txt

diff -u /tmp/before.txt /tmp/after.txt && echo "hash-neutral over this corpus"
```

`PYTHONPATH=.` because the script lives outside the repo; the canonical-bytes
checksum is there alongside the hashes because a canonical change that only
moves *inter*-block bytes (list markers, table padding) moves no block hash
and still invalidates every stored base snapshot.

**The corpus is the weak point.** The repo's own Markdown exercises headings,
paragraphs, table cells, fences and thematic breaks — and nothing else. The
constructs that have actually broken this parser before are the ones it does
not contain: task lists, GitHub alerts, front matter, HTML blocks, indented
code blocks. Upstream keeps a fixture for exactly this,
`cl10n/tests/fixtures/kitchen-sink.md`; copy it (and anything else you care
about) into the tree before recording, and delete it afterwards.

**3. If a pin moved, run upstream's detector too.** markdown-localization
ships `cl10n/compat_check.py`, which pins the parser's option surface, the set
of node types it can emit against the set mdformat can render, and the
canonical form plus unit hashes of that fixture. Run it *in the upstream
checkout*, against the new pin:

```bash
venv/bin/python3 cl10n/compat_check.py        # exit 0 = no drift, 1 = drift, 2 = check failed
```

cedit has no equivalent of its own. Until it does, that detector plus the
script above is the check, and the option-surface half of it is the only thing
that catches a preset growing an option *before* someone writes a document
that triggers it.

## When hashes did move — what consumers have to do

Two damage classes, and they are not equally bad.

**The canonical form moved.** `.cedit/base/<path>` now holds text the new
parser would render differently. cedit reads base snapshots as already
canonical and does not re-canonicalise them (`parse_doc(..., canonical=True)`
— `cli.py:113`, `:233`, `:315`), so every block whose canonical form moved
reads as a local edit against the working copy *and* as an upstream change
against the incoming revision: CONFLICT, on blocks nobody touched. This is the
wall of false conflicts the invariants keep warning about.

**Only the hash values moved** (same canonical bytes, different hash inputs).
Base, local and upstream all re-hash under the new function, so alignment
still pairs correctly and the derived overlay recomputes — the merge itself is
unaffected. What goes stale is the recorded *labels*: `base_doc_hash` in the
manifest, and the keys of any open conflict. Those keys still resolve, because
`cedit resolve` finds the conflicted block by its recorded text rather than by
hash (`cli.py:292-296`) and `_match_conflict` matches against the stored key —
but a key copied out of `cedit diff` (recomputed) will no longer match the one
`cedit status` prints (stored).

### Re-baselining a document

The repair for the first class. It keeps every adaptation, because the
adaptations live in the working copy, not in `.cedit/`:

1. `cedit status` — settle every open conflict first (`cedit resolve`).
   Re-baselining drops the conflict records.
2. Find the upstream revision the base was taken from: the doc's `upstream`
   field in `.cedit/manifest.json`.
3. Drop that doc's state — remove its entry from `.cedit/manifest.json` and
   delete `.cedit/base/<doc>`. `cedit snapshot` refuses a tracked document
   (`cli.py:78-81`), so this step is not optional.
4. `cedit snapshot <doc> --from <that revision>`. The working copy is left
   untouched; the base is re-canonicalised under the new parser,
   `base_doc_hash` is refreshed, and the overlay is re-derived from the new
   base against the existing working copy.
5. `cedit status` should now report the same edit count as before, and zero
   conflicts.

If that upstream revision is genuinely gone, re-canonicalise the stored base
in place instead:

```bash
venv/bin/python3 -c "
import pathlib
from cedit.blocks import canonicalise
p = pathlib.Path('.cedit/base/<doc>')
p.write_text(canonicalise(p.read_text('utf-8')), 'utf-8')"
```

Second best: the recorded `base_doc_hash` stays stale until the next `sync`
rewrites it. It is still preferable to inventing a base revision that never
existed.

## Invariants — do not violate these

1. **The copy is a copy.** Only the three known hunks (docstring, imports,
   demo trim) and `utils.py`'s trim to four functions may differ from
   upstream. If you find yourself hand-merging, stop and reconcile the drift
   first.

2. **Never trim the unused surface.** It is what keeps a re-vendoring a copy.

3. **Pins move in two files at once**, byte-identical: `requirements.txt` and
   `pyproject.toml`. The packaging test enforces it; invariant 2 in AGENTS.md
   explains why.

4. **Assume hash-moving until measured.** "The change looks small" is not the
   argument — "the output is unchanged, here is the diff" is.

5. **Record the upstream SHA in the commit message.** The vendored files carry
   no version marker; provenance exists nowhere else.

## Failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `diff` against upstream shows hunks scattered through the file | the vendored copy was edited in place at some point | reconcile that as its own commit before vendoring anything new |
| suite green, then a consumer reports a wall of conflicts on their first `sync` after upgrading | the canonical form moved and the drift check was not run | they re-baseline, per the recipe above; nothing recovers it on their behalf |
| `cedit resolve <hash>` says *no conflict matches* after an upgrade | the key came from `cedit diff` (recomputed) while the stored key is a pre-change hash | use the key `cedit status` prints — it is the stored one |
| `test_pyproject_pins_match_requirements_txt` fails | a pin moved in one file only | make them byte-identical; the ordering matters too |
| `KeyError` on a node type, or an assertion inside mdformat's renderer | a parser upgrade grew a construct mdformat cannot render — the failure that produced `tasklists=False` and `alerts=False` | switch the construct off in `make_parser` **only** if the resulting token stream is unchanged, and record the argument inline like the two existing ones |
