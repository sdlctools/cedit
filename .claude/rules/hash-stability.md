# Hash stability — changing anything under `cedit/mdcore/`

The procedure behind invariants 1 and 2 in [AGENTS.md](../../AGENTS.md): how
to change the parser, the diff engine or the pinned stack without silently
moving the hashes in every consumer's `.cedit/` state — and how to tell
whether you did.

**This file is a reference, not an instruction set.** Like
[release-pipeline.md](release-pipeline.md) and
[manual-release.md](manual-release.md) it is deliberately not `@`-imported by
`AGENTS.md` — read it when you are about to touch `cedit/mdcore/`, bump one
of the parsing pins, or explain why the drift check is red.

This is the highest-consequence change surface in the repo, and the danger is
that it is quiet. A change to canonicalisation, hashing or segmentation moves
hashes that were recorded on machines you will never see, and it surfaces as
*their* next `sync` reporting a wall of conflicts against blocks nobody
touched. Nothing else in the suite can see it happen — see *The drift check*.

Where the other documents stop:

| Document | Answers |
| --- | --- |
| [AGENTS.md](../../AGENTS.md) | invariant 1 (`mdcore/` is frozen) and invariant 2 (the pins are exact) — the rules |
| [SPEC.md](../../docs/SPEC.md) | *Reuse rules* — which parts must not fork, and why the merge rests on them |
| [ARCHITECTURE.md](../../docs/ARCHITECTURE.md) | what every symbol in `mdcore/` does, and which ones cedit calls |
| **this file** | how to change any of it safely, how to prove you did, and what consumers do when hashes moved |

## What `cedit/mdcore/` is

Two modules, and every hash cedit has ever written is a function of them:

| File | Holds |
| --- | --- |
| `mdcore/utils.py` | `make_parser` — the one parser configuration — plus `markdown_to_ast`, `parse_inline`, `ast_to_markdown` |
| `mdcore/tree_diff.py` | Merkle hashing (`hash_tree`), block classification (`is_unit`, `OPAQUE`), unit source, heading trails, similarity (`ratio`) and the thresholds |

They are **frozen**, and the reason is not stylistic: `.cedit/base/<path>`
snapshots, overlay keys and conflict keys in every consumer's repository are
keyed to exactly this code and exactly these pins. Change it and their
recorded state stops describing their documents.

Every top-level symbol in `tree_diff.py` is now reached from cedit. Roughly
half the module used not to be — a translation-planning surface it was
vendored with, kept for continuity while re-vendoring was still on the
table. CED-19 deleted it once CED-10 had removed that reason, as its own
change with the drift check green on both sides rather than as a tidy-up
folded into another. That is the shape any further deletion here takes: the
"deleting an uncalled symbol" row below is inert, but only a run of the
check makes it evidence.

## What moves a hash

A change is **hash-moving** if it alters any of:

- the canonical bytes `blocks.canonicalise` produces (the mdformat
  round-trip), which is what `.cedit/base/<path>` stores;
- the hash a block gets for the same canonical bytes — `hash_tree`'s inputs
  are `type`, `tag`, `info`, `own_text` and the child hashes;
- which nodes become blocks at all (`is_unit` / `UNIT_PARENTS` / `OPAQUE`),
  which also changes `blocks.block_signature` and therefore the
  render-and-verify check.

| Change | Class |
| --- | --- |
| a `make_parser` option that alters the token stream, or an `ast_to_markdown` option that alters the rendered form | hash-moving |
| a `make_parser` option that only switches *which implementation* produces the same token stream | hash-neutral — but prove it |
| anything touching `hash_tree`, `own_text`, `attr` or `norm` | hash-moving |
| `is_unit`, `UNIT_PARENTS`, `OPAQUE` | hash-moving **and** structural |
| `_unit_source` | hash-moving — a unit's identity is its inline source |
| `_heading_trail` | display-only, but it is stored in conflict records |
| `ratio`, `SIM_THRESHOLD`, `FUZZY_THRESHOLD` | not hash-moving, but merge-moving: pairing changes, so a REAPPLY can become a CONFLICT |
| a docstring or comment | inert — it cannot reach `make_parser` |
| deleting an uncalled symbol | inert, and provable in one run of the drift check |
| any pin bump | assume hash-moving until the drift check says otherwise |
| `mathguard`'s detection (`find_fragile_math` and the scanners under it) or its sentinel (`_PREFIX`, `_DIGEST`, `_sentinel`) | hash-moving — **for documents containing `$…$` math, and only those**. See below |
| `rowguard`'s detection (`find_row_overflow`, `_body_rows`, `_cut`) | **not** hash-moving — canonical-form-moving only, for documents holding an over-the-header table row. The counter-example worth reading before assuming otherwise. See below |

### The two guards outside `mdcore/`, and why only one moves hashes

`cedit/mathguard.py` is not frozen, but since CED-27 it sits on the hashing
path: `blocks.canonicalise` and `blocks.parse_doc` swap every fragile `$…$`
span for a sentinel *before* the parser sees the document, and put the
original bytes back afterwards. So the tree — and every hash taken over it —
is a function of what `find_fragile_math` detects and of how `_sentinel`
spells its replacement, as well as of `mdcore/`.

Two things make this a narrower surface than a parser change, and it is worth
keeping them straight:

- **The move is scoped to documents that contain fragile math.** Protection is
  a no-op everywhere else, byte for byte. A change here is measured by running
  the new canonicalisation over a corpus and showing which files move — CED-27
  measured 10 tracked `.md` in this repo (0 moved) and 60 in
  demo-jst-customization (1 moved, the one holding `$\rightarrow$`).
- **Detection and sentinel move different things.** Changing *detection* moves
  the canonical bytes, which is the damaging class for consumers
  (`.cedit/base/` goes stale). Changing only the *sentinel* leaves the
  canonical bytes identical — `restore` puts the same math back — and moves
  only the hash values, which is the recoverable class. Say which in the notes.

The drift check cannot see either unless the fixture contains fragile math,
and it deliberately does not: adding math to `tests/fixtures/kitchen-sink.md`
would re-key the baseline (invariant 4). `tests/test_mathguard.py` is the
instrument for this surface instead, and it re-measures its whole corpus
through `canonicalise` and `render_verified` on every run.

`cedit/rowguard.py` (CED-30) sits on the same path and is the instructive
counter-example: it moves **no** hash, and the difference is worth
internalising before assuming any guard is hash-moving because of where it
sits. It lifts what a table body row carries past the header's last column
out of the source before the parse — text markdown-it was discarding anyway,
because its body-row loop is `for i in range(columnCount)`. Handing the
parser the row without those bytes therefore yields the *identical* token
stream, which `rowguard.protect` asserts on every document by parsing both
sides and comparing full token fingerprints, abandoning the lift if they
differ. Widening or narrowing its detection changes what `.cedit/base/`
stores for the affected documents and nothing else; no `base_doc_hash`, no
overlay key and no conflict key moves. CED-30 measured that across 131
tracked `.md` in three repositories — 3 files' canonical bytes moved (2 in
this repo, 1 in demo-jst-customization), 0 hashes — and
`tests/parser-baseline.json` was unchanged by `--update`.

Note also which damage class that canonical-form move *is not*: the recovered
bytes sit outside every block and are stripped again before hashing, so a
base snapshot written before the guard still aligns block for block against a
working copy that has them. It is the only canonical-form move on record here
that does not call for re-baselining.

`tests/test_rowguard.py` is that guard's instrument, and it carries a column
`test_mathguard.py` has no equivalent of: `test_lifting_the_surplus_moves_no_hash`
and `test_a_base_snapshot_written_before_the_guard_still_matches` re-derive
the neutrality claim on every run, so a later change that quietly turns it
into a hash move fails there rather than in a consumer's next `sync`.

`cedit/mdcore/utils.py` carries three worked examples of narrow-blast-radius
changes with the argument written out inline:

- **`tasklists = False`** — markdown-it-py ≥ 4.2's `gfm-like2` parses task
  lists natively but emits no checkbox token, while `mdformat_gfm`'s renderer
  was written against `mdit_py_plugins.tasklists`, which does. Switching the
  native implementation off hands task lists to the plugin the renderer can
  actually read. Every other construct's token stream is untouched, and so is
  the canonical form.
- **`alerts = False`** — `> [!NOTE]` would parse into `alert` nodes mdformat
  cannot render at all. Off, they are ordinary blockquotes that round-trip
  byte for byte and render identically on GitHub.
- **`options["mdformat"] = {"keep_orphans": True}`, seeded before the plugin
  loop** (CED-25) — the one of the three that *is* hash-moving, and the worked
  example of scoping the move instead of waving at it. Adding
  `mdformat-footnote` stops `[^label]:` being escaped to `\[^label\]:`, so the
  canonical form of any document holding a footnote **definition** changes;
  the seed is separately required because that plugin's `update_mdit` reads
  `mdit.options["mdformat"]` unguarded and dies with `KeyError: 'mdformat'`
  against an unseeded parser. The claim shipped with it was measured on both
  sides: the unedited fixture re-canonicalised to its recorded
  `canonical_sha256` with all 40 block records identical, the repo's ten other
  Markdown files were byte-identical old parser vs new, and a sweep of
  footnote-*adjacent* constructs — regex character classes like `[^a-z]` in
  prose, in code spans and in fences, references with no definition,
  reference-style links, pre-escaped brackets, footnote-like text in table
  cells — all came out unchanged. Only a real definition moves.

All three arguments have the same shape: a claim about *output*, over a
named corpus, not *the change looks small*. That is the only shape that
works — so measure it rather than arguing it, and when it does move, measure
how far.

## The pins

Seven runtime pins, and they exist in two places that must stay byte-identical:
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
mdformat-footnote==0.1.3
linkify-it-py==2.1.0
```

Bump them one at a time, running the drift check between each.

### The installed plugin set is part of the parser identity

`make_parser` (`cedit/mdcore/utils.py:51-56`) does not name its extensions.
It appends **every** entry of `mdformat.plugins.PARSER_EXTENSIONS` and calls
`update_mdit` on each — a runtime enumeration of whatever is installed in the
environment. So installing any further mdformat plugin (`mdformat-tables`,
`mdformat-simple-breaks`, one arriving as a transitive dependency of
something unrelated) changes what the parser *is*, exactly like bumping a
pin, and nothing in `requirements.txt` records that it happened.

`mdformat-footnote` is the pin that arrived that way and got adopted (CED-25)
rather than pinned out: the parser was wrong without it, silently escaping
`[^label]:` into visible literal text. Adopting a plugin is the *other*
response to this section, and it is the more invasive one — a plugin can also
add parse-time behaviour nobody asked for, which is why that entry seeds
`keep_orphans` rather than taking the plugin's defaults.

The drift check records the plugin set for precisely this reason; it is the
one class of drift no lockfile would catch.

Corollary for consumers: `pipx install cedit` is safe because pipx gives it
its own environment. `pip install cedit` into a shared environment is not —
whatever else lives there is part of their parser.

## The drift check

**`venv/bin/python3 -m pytest` cannot see a moved hash on its own.** Every
other test computes both sides of every comparison with the parser it is
running under, so a change that moves hashes consistently passes green. That
was measured, not assumed: with a one-line renderer change in
`ast_to_markdown`, 30 of the 31 tests still passed. The one that failed was
this check.

`tests/parser_contract.py` records four things, cheapest signal first:

1. **Pins** — installed versions of the six packages.
2. **Plugin set** — `mdformat.plugins.PARSER_EXTENSIONS`.
3. **Option surface** — the configured parser's effective options, so a
   preset *gaining* an option shows up before any document triggers it.
4. **Canonical form and hashes** — `tests/fixtures/kitchen-sink.md`'s source
   and canonical checksums, its document hash, and every block key with its
   kind, node type, info string and heading trail.

The canonical checksum is not redundant with the hashes. A renderer change
can move the stored canonical bytes while every block hash stays put —
`compact_tables` does exactly that — and stale canonical bytes are the
damaging half for consumers, because that is what `.cedit/base/` holds.

```bash
venv/bin/python3 -m pytest tests/test_parser_contract.py   # verify (also runs in the full suite)
venv/bin/python3 tests/parser_contract.py                  # the same check, readable output
venv/bin/python3 tests/parser_contract.py --update         # re-record
```

`--update` is a deliberate act, not a way to get to green. Read the diff of
`tests/parser-baseline.json` in the commit; each moved line is a hash
somebody has recorded.

The fixture rather than the repository's own Markdown is the subject on
purpose: the docs change whenever someone edits them, which would make the
baseline churn and train everyone to re-record it without reading. The
fixture changes only when someone means it, and `test_parser_contract.py`
asserts it still covers front matter, HTML blocks, fences with and without
info strings, thematic breaks, headings, paragraphs and table cells — so a
fixture that quietly stopped testing something cannot keep passing.

## Making a deliberate change

1. **Start green.** `venv/bin/python3 tests/parser_contract.py`. A red
   baseline before you start means your environment already disagrees with
   the repository, and nothing you measure afterwards means anything.
2. **Make the change**, one pin or one option at a time.
3. **Run the full suite.** It proves behaviour: the merge matrix, the CLI
   lifecycle, the packaging guards.
4. **Read the drift check's output.** Green ⇒ hash-neutral, and you are
   done. Red ⇒ classify what moved against the table above.
5. **If it is hash-moving and you still want it**, re-record with `--update`,
   commit the baseline diff *in the same commit as the change* so review sees
   both together, and say so in the commit message.
6. **Then tell consumers.** A hash-moving release is a breaking change to
   on-disk state, and the release notes are the only warning anyone gets.

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

If that revision is genuinely gone, re-canonicalise the stored base in place
instead — `cedit md canonicalize` is that operation on the supported surface,
and `-i` writes through `store.atomic_write_text`, so an interrupted run cannot
leave a half-written base:

```bash
cedit md canonicalize -i .cedit/base/<doc>
```

`--check` on the same path is the probe that tells you whether it is needed at
all: the base was written canonical, so a non-zero exit means this parser
disagrees with what is stored, which is the first damage class above.

Second best: the recorded `base_doc_hash` stays stale until the next `sync`
rewrites it. It is still preferable to inventing a base revision that never
existed.

## Invariants — do not violate these

1. **Assume hash-moving until measured.** "The change looks small" is not the
   argument — "the drift check is green, here is the run" is.

2. **`--update` and the change it justifies go in one commit.** A baseline
   re-recorded on its own is indistinguishable from one re-recorded to get to
   green.

3. **Pins move in two files at once**, byte-identical: `requirements.txt` and
   `pyproject.toml`. The packaging test enforces it.

4. **The fixture is not a scratch file.** Editing
   `tests/fixtures/kitchen-sink.md` re-keys the baseline, so an edit made for
   convenience hides a real move. The check reports a changed fixture
   separately for that reason.

5. **A hash-moving release says so in its notes.** Consumers cannot detect it
   themselves until their next `sync` fails.

## Failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `test_parser_contract_has_not_drifted` fails right after a `pip install` | the environment does not match `requirements.txt`, or something pulled in an extra mdformat plugin | read which class it names; reinstall from `requirements.txt` before concluding anything about the code |
| The check names a *plugin* nobody added on purpose | a transitive dependency shipped an mdformat entry point | pin it out, or accept it and re-record knowing every hash moved |
| The check is green but a consumer still hits a wall of conflicts | their environment, not yours — see the plugin corollary above | have them compare their installed plugin set against the baseline's, and run `cedit md canonicalize --check .cedit/base/<doc>` on their machine: a non-zero exit says the canonical form moved under them, which is the first damage class above |
| Full suite green, drift check red | working as designed: the suite cannot see a consistent hash move | classify the change, then decide; do not "fix" it by re-recording |
| Drift check green, full suite red | an ordinary bug — the hashes are fine | fix the code |
| `KeyError` on a node type, or an assertion inside mdformat's renderer | a parser upgrade grew a construct mdformat cannot render — the failure that produced `tasklists=False` and `alerts=False` | switch the construct off in `make_parser` **only** if the resulting token stream is unchanged, and record the argument inline like the existing ones |
| `KeyError: 'mdformat'` from inside a plugin's `update_mdit`, while `make_parser` is still building the parser | that plugin reads its own configuration out of `mdit.options["mdformat"]` at parse-configuration time; `ast_to_markdown` sets that key, and it runs much later | already fixed generally — `make_parser` seeds the key before the plugin loop. If a plugin needs a *value* in there, add it to the seed and to `ast_to_markdown`'s dict together, or the two contexts disagree |
| A construct silently disappears from a document that canonicalises without error | a plugin's own default is to drop it — `mdformat_footnote` deletes unreferenced definitions unless `keep_orphans` is set | never inherit a plugin's content-dropping default. Canonicalisation feeds `.cedit/base/`, and render-and-verify cannot see it: both sides re-parse the same already-lossy text |
