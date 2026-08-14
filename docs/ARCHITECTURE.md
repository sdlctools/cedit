---
id: architecture
slug: /architecture
sidebar_label: Architecture
sidebar_position: 3
---

# cedit architecture

Code-level reference for the `cedit` implementation: what every module,
function and dataclass actually does, how a call flows from `cli.main` down
to the splice, where each of AGENTS.md's five invariants is enforced, and —
in [Changing cedit](#changing-cedit) at the end — what to touch when you
extend it.

**This file is a reference, not an instruction set.** It is deliberately not
`@`-imported by `AGENTS.md` — read it when you are about to change code,
not on every session.

Where the other documents stop:

| Document | Answers |
| --- | --- |
| [README.md](https://github.com/sdlctools/cedit/blob/main/README.md) | setup, quickstart, exit codes, repo layout |
| [User guide](userguide/index.md) | command reference, task flows, conflict lifecycle, troubleshooting |
| [SPEC.md](SPEC.md) | normative design — merge matrix, sync algorithm, state format, reuse rules, phases |
| [AGENTS.md](https://github.com/sdlctools/cedit/blob/main/AGENTS.md) | orientation and the five invariants |
| [.claude/rules/release-pipeline.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/release-pipeline.md) | the three versioning workflows and how they break |
| [.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md) | changing `mdcore/` or the pins without moving consumers' hashes |
| **this file** | the implementation that realises them, and how to change it |

Nothing here restates behaviour those five define. Where a design decision
is at issue, SPEC.md wins; this file tells you which lines carry it out.

## The call graph

`python3 -m cedit` enters at `cedit/__main__.py`, which is three lines:
`from .cli import main` then `raise SystemExit(main())`. `cli.main` builds
the parser (`cli.build_arg_parser`), dispatches to `args.func`, and converts
four exception types into exit code 2.

A `sync` is the deep path. Everything else is a subset of it:

```
cli.cmd_sync
├── state.State(...)                        load .cedit/manifest.json + overlay.json
├── entry["conflicts"] guard                refuse to sync a doc with open conflicts
├── state.read_base(doc)                    B — the canonical base snapshot
├── blocks.canonicalise(upstream file)      U — mdformat round-trip, then compared to B
│   ├── rowguard.protect / restore           a body row's over-the-header text lifted out and back
│   └── mathguard.protect / restore          `$…$` math swapped for a sentinel and back
├── mathguard.warn_fragile_math(U src, L)   stderr only, and only for spans `protect`
│                                           could not locate — silent on every document
│                                           measured
├── rowguard.warn_row_overflow(U src, L)    the same, for rows `protect` could not lift
└── merge3.merge(B, L, U)
    ├── blocks.parse_doc  ×3                → ParsedDoc(canonical, tokens, root, blocks, math, rows)
    │   ├── rowguard.protect                 runs first: it shortens row lines, and
    │   │                                    mathguard's offsets are over what it is handed
    │   ├── mathguard.protect                the tree is built over the *protected* text
    │   ├── mdcore.utils.markdown_to_ast     the one pinned parser
    │   └── mdcore.tree_diff.hash_tree       Merkle hash per node → Block.hash
    ├── merge3.local_edits(B, L)            the overlay
    │   ├── align.align(B.blocks, L.blocks)  → [Fate], [inserted Block]
    │   ├── merge3._describe_structural      any local insert/delete/move …
    │   └── raise merge3.StructuralDrift      … aborts here, before anything is written
    ├── align.align(B.blocks, U.blocks)     what upstream did
    ├── one pass over B.blocks              the merge matrix (below)
    │   └── blocks.splice_block(U, U-node, local_text, local_info)
    └── blocks.render_verified(U)           re-parse own output, compare block_signature
                                            → raise blocks.StructureMismatch, or the Markdown
                                            (restored through U.math on the way out)
```

then, back in `cmd_sync` and **in this order** (`cli.py:195-212`):

```
store.atomic_write_text(working file, result.merged)   ← the working copy FIRST
state.write_base(doc, result.upstream_canonical)       ← U becomes the new B
state.set_entry(...) / state.save_manifest()           ← conflicts recorded here
merge3.local_edits(new B, merged) → state.set_overlay / save_overlay
```

The ordering is load-bearing and commented at the call site: a crash between
the working-file write and the state write leaves a merged working copy
against the *old* base, which the next `sync` simply re-derives as local
edits and converges. The reverse order would record a sync that never
happened.

Two properties fall out of this shape and are worth holding onto:

- **The merged document is U's token stream, mutated in place.** `merge3.merge`
  ends at `render_verified(upstream, ...)` (`merge3.py:248`) — the document is
  never reassembled from fragments, so upstream structure survives by
  construction.
- **The overlay is always re-derived, never edited.** `set_overlay` is only
  ever handed a fresh `local_edits(...)` result — in `cmd_snapshot`,
  `cmd_sync`, and `cli._refresh_overlay`. There is no code path that mutates
  a stored overlay entry.

## `cedit/cli.py` — subcommands and exit-code policy

Imports its whole working set at the top (`cli.py:20-25`): `blocks`
(`StructureMismatch`, `canonicalise`, `parse_doc`, `splice_block`,
`render_verified`), `mathguard` (`warn_fragile_math`), `mdcore.tree_diff`,
`merge3` (`ORPHAN`, `Conflict`, `StructuralDrift`, `local_edits`, `merge`),
`state` (`State`, `StateError`, `norm_doc`), `store` (`atomic_write_text`,
`read_text`).

### Display helpers

| Symbol | Behaviour |
| --- | --- |
| `_pair(a, b)` (`cli.py:32`) | delegates to `tree_diff._focus` — clips both sides around their *first difference*, so an edit past the cut-off is still visible |
| `_print_edit(edit)` (`cli.py:36`) | one overlay entry: `[edit <kind> <node_type>] #<key>`, `sim=` only when truthy, `ctx`, an `info :` line only when the fence info changed, then focused base/local fragments |
| `_print_conflict(doc, conflict, *, full=False)` (`cli.py:49`) | the three versions plus a copy-pasteable `resolve` line. `full=False` clips through `tree_diff._clip`; `full=True` (the `resolve --show` path) prints untruncated. An `ORPHAN` prints `upstream: (deleted)` and omits the "kept in the working file" note |

### Subcommands

**`cmd_snapshot`** (`cli.py:75`) — start tracking. Refuses a doc that is
already tracked (exit 2; the remedy printed is `cedit sync`). Two entry
shapes:

- working file **absent** → the canonical base is written *as* the working
  copy and the overlay starts empty (initial vendoring);
- working file **present** → it is parsed and `local_edits(base, local)`
  records the adaptations that already exist, so a copy adapted before
  `cedit` existed is picked up whole.

Both sources are read into a variable and passed through
`mathguard.warn_fragile_math` before `parse_doc` sees them — the upstream
file under its `--from` label, the working copy under the doc's own. The math
itself is preserved by `canonicalise`/`parse_doc`, so that call only reports
what protection could not reach. Then
`write_base` → `set_entry` → `save_manifest` → `set_overlay` →
`save_overlay`.

**`cmd_diff`** (`cli.py:103`) — overlay against base, for the docs named or
all tracked ones. `--unified` short-circuits to `difflib.unified_diff` over
`base.canonical` vs `local.canonical` (labelled `base/<doc>` → `<doc>`) and
never calls `local_edits`, which is why it still works under structural
drift. The structured path catches `StructuralDrift` per document, prints it
to stderr and sets rc 2 while continuing with the remaining docs.

**`_upstream_file(doc, entry, from_arg)`** (`cli.py:135`) — resolves the
incoming file: the `--from` argument, else the recorded `entry["upstream"]`,
else `StateError`. A directory is joined with the doc's own relative path, so
one `--from <dir>` serves every tracked document at once.

**`cmd_sync`** (`cli.py:144`) — the deep path above, guarded in this order:

1. nothing tracked → rc 2;
2. `--from` is a *file* while several docs are being synced → rc 2 (a file
   cannot mirror many doc paths);
3. per doc, `entry["conflicts"]` non-empty → rc 2 for that doc — **invariant 3**;
4. per doc, the upstream file does not exist → rc 2;
5. canonicalised upstream equal to the base → `up to date`, nothing written;
6. `StructuralDrift` / `StructureMismatch` out of `merge` → stderr, rc 2.

Between 5 and 6 both sources go through `mathguard.warn_fragile_math` —
*after* the up-to-date short-circuit, so a no-op sync stays silent, and
before `merge`, because by then the canonical form has already been taken.
It is the fallback alarm only: `canonicalise` and `parse_doc` carry every
locatable `$…$` span through untouched, so the call fires solely on spans
protection could not reach. The warning is stderr text and changes no exit
code.

`--dry-run` / `-n` reports (`result.as_text()` plus every conflict) and
returns before the first write — the math warning still fires, which is the
point of a dry run. The return is
`rc or (1 if any_conflicts else 0)` (`cli.py:214-216`): a hard error outranks
a conflict.

**`cmd_status`** (`cli.py:219`) — per doc: overlay size, unresolved conflict
count, base hash, `synced_at`, recorded upstream. `StructuralDrift` is caught
and *reported*, not raised — the line reads `STRUCTURAL DRIFT (see cedit
diff)` — because status must stay readable on a broken working copy. Note the
asymmetry with `diff`/`sync`: **nothing tracked is exit 0 here**, printing
`nothing tracked`, since "no state yet" is a legitimate state to report.
Returns 1 when any doc has conflicts.

**`_match_conflict(conflicts, key)`** (`cli.py:246`) — accepts a full
`<hash>:<occurrence>` key or a unique prefix (`key.rstrip(":")`), and raises
`StateError` listing the open keys when nothing matches, or the ambiguous
candidates when several do.

**`cmd_resolve`** (`cli.py:257`) — four outcomes:

| Invocation | Effect |
| --- | --- |
| `--show`, or no `--take` | `_print_conflict(..., full=True)`, exit 0. Read-only |
| `--take local` | the working file already holds the local text, so only the manifest record is dropped; `_refresh_overlay` re-keys the edit against the new base — the `git rerere` move |
| `--take local` on an `ORPHAN` | **refused**, exit 2: keeping a block upstream deleted is a structural edit (phase 2). The text stays in the manifest |
| `--take upstream` | on an `ORPHAN`, drop the record (deletion accepted). Otherwise `warn_fragile_math` on the working copy, locate the block in it by `(kind, node_type, text, info)`, `splice_block` the upstream text in, `render_verified`, write, drop the record, refresh the overlay |

The `--take upstream` lookup is exact-match by construction (`cli.py:292-297`);
if the user has since hand-edited that block it returns `None` and the command
exits 2 telling them to fix the text by hand and use `--take local` — it never
guesses which block was meant.

**`_refresh_overlay(state, doc)`** (`cli.py:313`) — re-derives the whole
overlay for one doc from the base snapshot and the current working copy.
Called after every resolution that changes either side.

### The argparse surface

`build_arg_parser` (`cli.py:334`). Global `--state-dir` (default `.cedit` —
resolved in `state.State`, not here, so the default is `None` at this level)
and global `--version`. `sub = parser.add_subparsers(dest="command",
required=True)`; each subparser sets `func` via `set_defaults`.

| Subcommand | Positional | Options |
| --- | --- | --- |
| `snapshot` | `doc` | `--from` (`dest="from_"`, **required**) |
| `diff` | `docs` (`nargs="*"`) | `--unified` |
| `sync` | `docs` (`nargs="*"`) | `--from` (`dest="from_"`), `-n` / `--dry-run` |
| `status` | `docs` (`nargs="*"`) | — |
| `resolve` | `doc`, `key` | `--take {local,upstream}`, `--show` |
| `md` | — | a nested subparser group; `mdcli.add_md_group(sub)` owns it |

`--from` is `dest="from_"` everywhere because `from` is a keyword; the
attribute is `args.from_`.

`md` is the one subparser `cli.py` does not define itself: it calls
`mdcli.add_md_group(sub)` (`cli.py:378`) and the verbs live in `mdcli.py`.
The nesting is deliberate — it keeps top-level `--help` honest that those
verbs obey a different contract (no state, and `--state-dir` is inert).

### `--version` — reporting what the parser is

Three small pieces sit just above the parser, and the reason they are
verbose rather than a bare version number is invariant 2: every hash in a
consumer's `.cedit/` state is a function of the parsing stack **and** of the
mdformat plugins installed beside it, which `mdcore.utils.make_parser`
enumerates from the environment rather than naming.

**`_STACK`** — the seven distributions `requirements.txt` pins, in print
order. Only the *names* live here; the versions come from
`importlib.metadata` at run time, because reporting the pin while the user
runs something else is the failure the flag exists to diagnose.

**`_dist_version(name)`** — one lookup, returning `(not installed)` instead
of raising `PackageNotFoundError`. The suite itself runs from an uninstalled
checkout, so a naive lookup here breaks every test at import.

**`_version_block()`** — the four-part block: `cedit <version>` (from
`cedit.__version__`, the distribution metadata, never a second literal),
the running Python, the wrapped stack line, and
`sorted(mdformat.plugins.PARSER_EXTENSIONS)`. That last line is what
[hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md)'s
failure-mode table asks an affected user to compare against the baseline's.

**`_VersionAction`** — a custom `argparse.Action` rather than
`action="version"`, for two independent reasons. argparse takes the version
*string* at parser-construction time, so the built-in would make every
`cedit sync` pay for enumerating installed distributions; and it prints that
string through the help formatter, which reflows it into one ragged
paragraph. Only the first line reaches `--help`, via the parser's
`description` — the whole block on every help screen would bury the usage.

### Exit-code policy — invariant 4

`main` (`cli.py:383`) wraps the dispatch in one `try` and maps
`StateError`, `StructuralDrift`, `StructureMismatch`, `MarkdownCliError` and
`FileNotFoundError` to **2**. Anything else propagates as a traceback,
deliberately: an unexpected exception is a bug, not a user error.

`0` clean · `1` unresolved conflicts, recorded by `cmd_sync` or found by
`cmd_status` · `2` errors. The two commands that can return 1 both compute it
the same way — a boolean accumulated across docs, applied only after `rc` is
known to be 0.

The `md` group is held to the same contract without extending it. Only
`md canonicalize --check` returns 1, and it means the same kind of thing the
workflow commands mean by it — *a human needs to look at this file* — so a
CI job can keep reading 1 as "not broken, not clean". Every other verb
returns 0 or 2.

## `cedit/mdcli.py` — the `md` group, stateless parser views

Five verbs that open no state at all. They exist because `mdcore/` is
otherwise unobservable: it is frozen because every consumer's hashes depend
on it, and per
[hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md) the failure mode is
*quiet*. Before this group the only instruments were
`tests/parser_contract.py` — one fixed fixture — and ad-hoc `python3 -c`.

| Verb | Emits |
| --- | --- |
| `canonicalize [file\|-]` | the mdformat round-trip — the exact bytes `.cedit/base/<doc>` would hold, `$…$` math and a table row's over-the-header text included and unmoved. `-i` rewrites via `store.atomic_write_text`; `--check` writes nothing and exits 1 when the input is not already canonical (mutually exclusive with `-i`). All three modes call `mathguard.warn_fragile_math` and `rowguard.warn_row_overflow` on the input first — stderr only, so stdout stays the data channel, and silent unless a span or a row could not be protected |
| `ast [file\|-]` | indented tree dump; each line is `type [tag] [info=] [[kind]] [#hash] ["preview"]`. `--hashes` adds the Merkle hash, `--raw` skips canonicalisation |
| `json [file\|-]` | `--tokens` (default) the flat `Token.as_dict()` stream; `--tree` a nested dict carrying `hash` and `kind` |
| `from-json [file\|-]` | Markdown rendered from a `--tokens` stream |
| `blocks [file\|-]` | the `blocks.Block` sequence the merge keys on — `kind`, `node_type`, `#hash:occurrence`, `info`, heading trail, text. `--json` for machine output, which also carries `doc_hash` |

Helpers: `_read` / `_label` (stdin is `-`), `_tree(md, *, raw)` (parse +
`tree_diff.hash_tree`), `_kind` (UNIT / OPAQUE / `""`), `_preview`,
`_node_json`, `_token`.

Three things are load-bearing:

- **`_token` rebuilds children recursively.** `Token(**d)` leaves `children`
  as a list of *dicts*, and nothing complains until mdformat's renderer dies
  much later on `'dict' object has no attribute 'nesting'`. This is what
  makes `json --tokens` → `from-json` a real round-trip rather than a dump;
  `test_token_json_round_trips_back_to_the_canonical_form` pins it.
- **The default is canonical, not raw.** Every verb canonicalises first, so
  the hashes printed are the hashes `.cedit/` records. `--raw` (on `ast` and
  `json` only) parses the file as it sits, which is how you see what the
  round-trip changed. `blocks` has no `--raw` on purpose: raw hashes would
  look authoritative and match nothing in any manifest.
- **`blocks` goes through `blocks.parse_doc`**, the same call `merge3` makes
  — it does not recompute anything. `test_blocks_keys_match_the_recorded_parser_baseline`
  cross-checks its output against `tests/parser-baseline.json`, so the drift
  check and this verb cannot disagree.

## `cedit/merge3.py` — the merge matrix, executed

Two module constants name the conflict flavours: `CONFLICT = "conflict"` and
`ORPHAN = "orphan"` (`merge3.py:30-31`). Both are the `reason` field of a
`Conflict`, and both are compared by value in `cli` and `state`.

### `StructuralDrift` (`merge3.py:34`)

`RuntimeError` subclass carrying `.changes` — the per-block report. Its
message is assembled in `__init__` from the doc label and the change list, so
printing the exception *is* the report; no caller formats it. Raised only by
`local_edits`.

### Dataclasses

**`LocalEdit`** (`merge3.py:47`) — one locally replaced block, keyed by its
*base* identity.

| Field | Meaning |
| --- | --- |
| `base_index: int` | position in `base.blocks` — the join key `merge` uses to look edits up |
| `kind: str` | `blocks.UNIT` or `blocks.OPAQUE` |
| `node_type: str` | `paragraph` / `heading` / `td` / `fence` / … |
| `hash: str` | the base block's 16-hex Merkle hash |
| `occurrence: int` | per-hash index in document order, 0-based |
| `context: str` | heading trail |
| `base_text` / `base_info` | the block as upstream had it |
| `local_text` / `local_info` | the block as the user has it |
| `sim: float` | similarity that paired the two |

`key` (property) is `f"{hash}:{occurrence}"`. `as_dict()` is the overlay
serialisation — note it drops `base_index` and `sim`: both are recomputed on
every derivation, so persisting them would only invite staleness.

**`Conflict`** (`merge3.py:81`) — both sides changed one block, or upstream
deleted an edited one. Fields: `key`, `reason`, `kind`, `node_type`,
`context`, `base_text`, `base_info`, `local_text`, `local_info`,
`upstream_text: str | None`, `upstream_info`. **`upstream_text` is `None`
exactly for an orphan** — that is the discriminator, alongside `reason`.
`as_dict()` / `from_dict(key, data)` round-trip it through
`manifest.json`; `from_dict` defaults every missing field to `""` except
`upstream_text`, which defaults to `None`.

**`MergeResult`** (`merge3.py:124`) — `merged` (the new working-copy
Markdown), `upstream_canonical` (canonical U, the next base snapshot),
`upstream_doc_hash` (Merkle root of canonical U), the `reapplied: list[LocalEdit]`
and `conflicts: list[Conflict]` lists, and five counters: `unchanged`,
`moved`, `updated`, `removed`, `inserted`. `orphans` (property) filters
`conflicts` by `reason == ORPHAN`. `as_text()` is the one-line summary
`cmd_sync` prints — it always names reapplied edits, updated blocks and the
conflict count, and mentions inserted / removed / moved only when non-zero.

### `local_edits(base, local, *, doc_label)` (`merge3.py:176`)

Derives the overlay, and **is the phase-1 boundary** (invariant 5). It aligns
L against B, hands the fates to `_describe_structural`, and raises
`StructuralDrift` if that returns anything. Because `cmd_snapshot`,
`cmd_diff`, `cmd_status`, `cmd_resolve` and `merge` all funnel through this
one function, every entry point rejects structural drift identically — there
is no second implementation to keep in sync.

Blocks whose fate is not `EDITED` are skipped; each `EDITED` fate becomes one
`LocalEdit` carrying base identity and both texts.

`_describe_structural(base_fates, base_blocks, inserted)` (`merge3.py:155`)
produces the human-readable lines: `deleted <type> #<key>: …` for a `DELETED`
fate, `moved` or `moved+edited` for any `fate.moved`, and `inserted <type>: …`
for every block `align` reported as new. `_snippet(text, width=60)`
(`merge3.py:171`) flattens whitespace and ellipsises.

### `merge(base_md, local_md, upstream_md, *, doc_label)` (`merge3.py:203`)

Parses all three revisions, derives the overlay indexed by base position
(`{e.base_index: e for e in local_edits(base, local)}`), aligns U against B,
seeds `MergeResult` with U's canonical text and doc hash and
`inserted = len(up_inserted)`, then walks `base.blocks` once
(`merge3.py:225-246`):

| Upstream fate | Local edit | Code | Outcome |
| --- | --- | --- | --- |
| `SAME` | none | `result.unchanged += 1` | nothing to do |
| `SAME` | yes | `_splice_or_conflict(edit, fate, result)` | **REAPPLY** |
| `EDITED` | none | `result.updated += 1` | **UPDATE** — upstream text stands, already in U's tree |
| `EDITED` | yes | `conflicts.append(_conflict(..., CONFLICT))` **and** `_splice(edit, fate.other)` | **CONFLICT** |
| `DELETED` | none | `result.removed += 1` | block gone by construction |
| `DELETED` | yes | `conflicts.append(_conflict(..., ORPHAN))` | **ORPHAN** |

`fate.moved` increments `result.moved` on the `SAME` branch *before* the edit
is considered, so a moved block that also carries an edit counts as both moved
and reapplied.

The CONFLICT row is invariant 3 in two lines: the conflict is recorded **and**
the local text is spliced into U's node, so the file `cmd_sync` writes keeps
the adaptation. UPDATE needs no splice at all — the merged document already
*is* U's tree.

There is no branch that writes upstream text over a local edit. The only way
upstream text reaches the working file for an edited block is the explicit
`resolve --take upstream`.

### Splice helpers

- `_splice(edit, target)` (`merge3.py:252`) — thin wrapper over
  `blocks.splice_block`, imported inside the function body.
- `_splice_or_conflict(edit, fate, result)` (`merge3.py:257`) — appends to
  `reapplied` on success; on `False` (a unit with no `inline` child — an empty
  table cell) it **degrades to a conflict** rather than dropping the edit
  silently.
- `_conflict(edit, fate, reason)` (`merge3.py:266`) — builds the `Conflict`
  from the edit plus `fate.other`. `upstream_text` is `None` for an orphan;
  `upstream_info` is `""` for an orphan *or* when `fate.other is None`.

## `cedit/align.py` — flat block-sequence alignment

Three status constants — `SAME`, `EDITED`, `DELETED` (`align.py:37-39`) —
whose values are their own names.

**`Fate`** (`align.py:43`): `status: str`, `moved: bool`,
`other: Block | None` (the counterpart, `None` only when `DELETED`),
`sim: float`.

**`_sim(a, b)`** (`align.py:52`) — `0.0` when `kind` or `node_type` differ,
otherwise `tree_diff.ratio` over `Block.compare_text`. A fence never pairs
with a paragraph, whatever the text similarity.

**`align(base, other)`** (`align.py:58`) returns
`(fates parallel to base, blocks of other that are new)` in four passes:

1. **LCS over Merkle hashes.** `SequenceMatcher(None, [b.hash …], [x.hash …],
   autojunk=False)`. `equal` opcodes become `Fate(SAME, False, other[j], 1.0)`;
   `delete` and `insert` opcodes feed the pools.
2. **Greedy best-first pairing inside each `replace` window.** Every
   (base, other) pair in the window is scored and sorted descending; pairs at
   or above `tree_diff.SIM_THRESHOLD` (0.4) whose ends are both still free
   become `Fate(EDITED, False, …)`.
3. **The 1-for-1 positional fallback** (`align.py:100-106`) — the one pass
   that is not similarity-driven at all, and the comment at that site
   explains why. When a `replace` window holds exactly one block on
   each side and they share `kind` and `node_type`, they are paired *whatever*
   the text score: `a` → `a-adapted` in a table cell scores 0.18, but
   positional evidence is conclusive. Without this, a short local edit would be
   misread as structural drift and rejected.
4. **Global move pass, then global fuzzy pass.** A pooled delete and a pooled
   insert with the *same* hash is a move → `Fate(SAME, True, …, 1.0)`. What
   remains is scored across the whole document and paired above
   `tree_diff.FUZZY_THRESHOLD` (0.6) → `Fate(EDITED, True, …)` — moved *and*
   edited, the CAT-tool fuzzy match at block granularity. The scored list is
   sorted descending, so the loop `break`s at the first sub-threshold score.

Anything still unpaired becomes `Fate(DELETED, False, None, 0.0)`, and
`inserted` is every `other` block no fate claimed.

Both `moved` and `DELETED` outcomes are *fatal* when this runs against the
local copy (`_describe_structural` reports them) and *informational* when it
runs against upstream (`merge` counts them). Same function, two readings.

## `cedit/blocks.py` — extraction, splicing, render-and-verify

`UNIT = "unit"` / `OPAQUE = "opaque"` (`blocks.py:35-36`) are the two block
kinds:

- **units** — the nodes owning an `inline` child (`heading`, `paragraph`,
  `th`, `td`), exactly `tree_diff.UNIT_PARENTS`;
- **opaque blocks** — `tree_diff.OPAQUE`: `fence`, `code_block`, `html_block`,
  `front_matter`, `hr`. `tree_diff`'s own planning surface only ever copies
  these; here they are first-class, because the motivating local edit *is* a
  rewritten code fence.

Two more constants: `SINGLE_LINE_TYPES = {"th", "td"}` (`blocks.py:40`), cells
where a spliced newline would end the GFM row, and `_TASKLIST_CHECKBOX`
(`blocks.py:45`), the `html_inline` marker that must survive a splice.

**`StructureMismatch`** (`blocks.py:48`) — `RuntimeError`. Raised only by
`render_verified`, and the contract is that the caller must not write the
file.

### `Block` (`blocks.py:59`)

| Field | Meaning |
| --- | --- |
| `kind` | `UNIT` \| `OPAQUE` |
| `node_type` | `paragraph` / `heading` / `td` / `fence` / `front_matter` / … |
| `hash` | `tree_diff.hash_tree`'s 16-hex-char Merkle hash |
| `occurrence` | per-hash index in document order, 0-based |
| `text` | unit: the inline source. opaque: the token content |
| `info` | fence info string (`bash`, `zsh`); `""` otherwise |
| `context` | heading trail |
| `node` | the live `SyntaxTreeNode` — `field(repr=False)`, and the handle the splice mutates |

`key` (property) → `f"{hash}:{occurrence}"`. `compare_text` (property) →
`f"{info}\n{text}"` when `info` is set, else `text`: the info string is part
of the editable surface, so ` ```bash ` → ` ```zsh ` scores as an edit rather
than a replacement.

The `occurrence` index is why the merge can tell the third copy of a repeated
command from the first — a distinction translation never needed.

### `ParsedDoc` (`blocks.py:81`)

`canonical: str`, `tokens: list` (mutable and renderable — what the splice
edits and `render_verified` renders), `root: SyntaxTreeNode`,
`blocks: list[Block]`, `math: dict[str, str]`,
`rows: tuple[rowguard.RowOverflow, ...]`. `doc_hash` (property) is
`root.h`, the Merkle root recorded as `base_doc_hash` in the manifest.

`math` is the document's sentinel map (`mathguard`) and `rows` its lifted
table-row surplus (`rowguard`). The split they encode is the thing to hold on
to: **`tokens` and every hash are over the protected text; `canonical` and
every `Block.text` are restored.** Sentinels therefore never reach an overlay
entry, a conflict record or `cedit md blocks`, and the renderer never sees a
backslash it would escape. `rows` is the asymmetric one: a splice extends
`math` (text arriving that way can hold math) but never `rows`, because no
block holds a row's surplus — it is not in any cell.

### `canonicalise` and `parse_doc`

`canonicalise(md)` (`blocks.py:96`) is the mdformat round-trip **every hash in
`.cedit/` is taken over**, wrapped in `rowguard.protect` / `restore` and then
`mathguard.protect` / `restore`: the round-trip runs over sentinels and over
rows the parser would truncate, and the original `$…$` bytes and row surplus
go back into the result, so both are byte-exact through it (CED-27, CED-30).
The order is load-bearing — `rowguard` rewrites the source, and `mathguard`'s
offsets are taken over whatever it is handed.

`parse_doc(md, *, canonical=False)` (`blocks.py:101`) protects, canonicalises
unless told the input already is (`canonical=True` is used for base snapshots,
which were written canonical), parses, builds the tree, calls
`tree_diff.hash_tree` to annotate every node with `.h`, then walks: a unit or
an `OPAQUE` node becomes a `Block` and the walk does **not** descend into it;
anything else recurses into its children. Occurrence indices are assigned in a
second pass over the flat list, so they follow document order.

Both routes to the same document reach the same sentinels — `protect` is the
inverse of `restore`, and a sentinel is derived from the span it stands for —
so a base snapshot parsed with `canonical=True` and a working copy parsed
without it still hash alike. That is what keeps the alignment working over a
document containing math.

This walk is the whole reason the merge is "flat": containers (lists,
blockquotes, tables) are traversed but never themselves blocks.

### Structural signature

`block_signature(md)` (`blocks.py:140`) → a nested `(type, …)` tuple of the
document's *block* structure. It stops at `inline` (returning `("inline",)`),
so what is *inside* an edit block may differ while what *contains* it may
not. Non-root heads are `f"{type}:{tag}"`.

`_first_difference(a, b, path="")` (`blocks.py:156`) walks two signatures in
parallel and returns a single human-readable path to the first divergence —
extra child, missing child, or differing head. Only used to build the
`StructureMismatch` message.

### `splice_block(doc, block, text, info="") -> bool` (`blocks.py:177`)

Replaces the block's editable content **in `doc`'s tree, in place**, and
returns `False` when there is nothing to splice into. `doc` is there for the
sentinel map: `text` arrives restored (it came from a `Block.text` or a
conflict record), so its own math is protected on the way in and registered
with `doc.math`, which is what lets `render_verified` put it back.

- **Opaque** → set `token.content = text`, and `token.info = info` as well when
  the node is a `fence`. Always `True`, and no protection — mdformat writes a
  fence, an HTML block or front matter out verbatim, backslashes included.
- **Unit** → find the `inline` child; **`None` → return `False`** (an empty
  table cell — the caller decides what that means, and
  `merge3._splice_or_conflict` turns it into a conflict). Protect the text,
  and for a `th`/`td` collapse whitespace to a single line. Re-tokenize with
  `mdcore.utils.parse_inline`, so text starting with `- ` stays a paragraph
  instead of becoming a list. If the original inline started with a task-list
  checkbox `html_inline`, that token is re-inserted at position 0 — it is
  block structure parked in an inline child and must be carried across, never
  replaced. Finally set both `inline.token.children` and
  `inline.token.content`.

Block structure always comes from the tree being spliced *into* and is never
re-derived from the replacement text. That is the reassembly invariant.

### `render_verified(doc, *, label) -> str` (`blocks.py:206`)

Renders `doc.tokens` (post-splice), **restores `doc.math` into the output**,
takes `block_signature` of `doc.canonical` and of the restored output, and
raises `StructureMismatch` with `_first_difference` when they differ. A
splice-only design's one invisible failure mode is a replacement that
re-parses into different block structure; this is the gate, and it runs on
**every** render — the merge (`merge3.py:248`) and `resolve --take upstream`
(`cli.py:304`) alike.

**What it structurally cannot catch**, and why `mathguard` and `rowguard`
exist: a rewrite *inside* one block's inline content, and text that never
reached a block at all. `block_signature` stops at `inline` by
design, and both signatures are taken over text the round-trip has already
produced, so an unprotected `$\rightarrow$` → `$\\rightarrow$` would compare
equal on both sides and pass. That is why the math is kept out of the
renderer's way rather than checked afterwards;
`tests/test_mathguard.py::test_the_render_path_preserves_it_too` pins the
render path itself, so the claim stays measured rather than asserted.

## `cedit/mathguard.py` — the `$...$` math guard

A detector, a protector and a reporter. `blocks` is the only importer, and
nothing here participates in alignment or the merge — but since CED-27 it
*does* sit on the hashing path, because the tree is built over the text it
rewrites.

The defect: GitHub renders `$...$` and `$$...$$` as math, the pinned parser
has no such syntax, and so a backslash inside such a span is ordinary text
that `ast_to_markdown` correctly escapes — `$\rightarrow$` would become
`$\\rightarrow$`, which GitHub reads as a *line break inside math*. The page
changes. Every stage downstream of `canonicalise` is blind to it (see
`render_verified` above), the hashes would all be taken over the rewritten
text, and cedit exits 0. That is a silent clobber, which invariant 3 forbids.

CED-26 detected it; **CED-27 prevents it**, by keeping the span out of the
round-trip altogether:

```
source ──protect──► sentinel ──parse──► tokens ──render──► ──restore──► canonical
```

| Symbol | Behaviour |
| --- | --- |
| `MathSpan` (`mathguard.py:88`) | frozen dataclass: `line` (1-based), `delim` (`"$"` / `"$$"`), `text` (the run as written), `start`/`end` (absolute source offsets, `None` when the span could not be located) |
| `Protected` (`mathguard.py:296`) | frozen dataclass: `text` (the source with sentinels in place), `spans` (sentinel → original), `unprotected` (the `MathSpan`s left alone). `.restore()` is the inverse |
| `_mask_code_spans(src)` (`mathguard.py:106`) | blanks inline code spans to `\x00`, **preserving length** so every later offset stays valid. CommonMark's rule: a run of N backticks is closed by the next run of exactly N; an unmatched run is literal text; `\` escapes the next character |
| `_matching_backticks(src, start, run)` (`mathguard.py:135`) | end offset of the next backtick run of exactly `run`, or `None` |
| `_inline_close(masked, open_at)` (`mathguard.py:151`) | GitHub's inline delimiter rules — no whitespace after the opener, none before the closer, no newline inside. This is what keeps `$100 and $200` from being a span at all |
| `_spans(masked)` (`mathguard.py:175`) | yields `(delim, start, end)`; `$$` is tried first and may cross lines, `$` may not |
| `_line_offsets(md)` (`mathguard.py:202`) | absolute offset of every line start |
| `_content_line_offsets(...)` (`mathguard.py:211`) | where each line of an inline token's `content` sits in the source. A shared `cursor` per source line resolves the cells of one table row left to right instead of all matching the first |
| `_absolute(offsets, content, pos)` (`mathguard.py:239`) | a content offset → a source offset |
| `find_fragile_math(md)` (`mathguard.py:247`) | every span whose **content holds a backslash**, over the *source* as written, each with the offsets `protect` needs |
| `_sentinel(text, doc, taken)` (`mathguard.py:310`) | `ceditmath` + 16 hex of `sha256(span)`, counted up until it collides with nothing in `doc` and with no other span |
| `protect(md)` (`mathguard.py:328`) | → `Protected`. Rewrites the source at the offsets, never by matching the span text |
| `restore(text, spans)` (`mathguard.py:352`) | puts the originals back, **longest sentinel first** |
| `warn_fragile_math(md, label, *, stream=None)` (`mathguard.py:368`) | reports only `protect(md).unprotected` to stderr and returns it. **Never touches the exit code** |

Design points, and the three gaps the CED-27 prototype had to close:

- **It iterates `inline` tokens, not lines.** Only an `inline` token carries
  the raw source of its own region (`.content`) together with the line it
  starts on (`.map`), so fences, indented code, HTML blocks and front matter
  are excluded *for free* — they are simply other token types. Table cells
  and headings are included for free by the same rule. It also bounds a span
  to one inline token, so a `$$` run can never swallow a blank line and
  merge two paragraphs when it is replaced.
- **A backslash is the whole trigger.** Every `$`-bearing construct without
  one is byte-stable today, prose dollar amounts included, so the false
  positive surface is small — and `tests/test_mathguard.py` re-measures both
  columns through `canonicalise` on every run rather than trusting the list.
- **Spans are rewritten by offset, not by `str.replace` on their text.** The
  same span text may also sit in a fence or a code span, or twice on one
  line; the offsets distinguish them and text matching does not. The derived
  offsets are verified against the source (`md[start:end] == text`) before
  anything is rewritten.
- **The sentinel is content-derived and collision-checked.** Derived, so the
  same span always yields the same sentinel — that is what makes `protect`
  the inverse of `restore` and keeps hashes reproducible across machines and
  across `parse_doc`'s two routes. Checked, so a document that already
  contains that literal text gets a different one.
- **Protection is per span and all-or-nothing.** A span whose offsets cannot
  be derived is left alone and reported. The reachable case is a `$…$` span
  in a table cell that also holds `\|`: markdown-it hands the cell back
  already unescaped, so its content is not in the source verbatim. That, and
  only that, is what `warn_fragile_math` now prints.

Call sites: `blocks.canonicalise`, `blocks.parse_doc`, `blocks.splice_block`
and `blocks.render_verified` for the protection — between them every path
that writes. `warn_fragile_math` keeps CED-26's four wirings: `cmd_snapshot`
on both sources, `cmd_sync` on both sources after the up-to-date
short-circuit, `cmd_resolve --take upstream` on the working copy, and
`mdcli.cmd_md_canonicalize` on its input. `cmd_diff` and `cmd_status`
deliberately stay silent — they write nothing, and `md canonicalize --check`
is the standalone probe.

Making `$...$` actually parse as math is still rejected, not deferred, and
preserving it is not the same thing — nothing keys on the *contents* of a
span, and a ```` ```math ```` fence remains the spelling that renders. Every
published `mdformat-dollarmath` requires `mdformat>=0.7,<0.8` against the
pinned `mdformat==1.0.0` (pip returns `ResolutionImpossible`), and
`mdformat-myst`, which has no upper bound, pulls in a second frontmatter
plugin beside the pinned `mdformat-frontmatter==2.1.2` — a parser-identity
change, hence a hash move across *every* document rather than only the ones
holding math.

## `cedit/rowguard.py` — the table-row guard

The same shape as `mathguard` — a detector, a protector and a reporter, with
`blocks` as the only importer — answering the same class of defect: content
the parser discards before cedit's tree exists, which no later stage can see.
The mechanism differs, and that difference is the design.

**What is lost.** A GFM table's header row fixes the column count for the
whole table, and markdown-it's body-row loop is `for i in range(columnCount)`
(`rules_block/table.py`), so cells past that count are never read. The common
spelling is an annotation after the closing pipe, but an extra cell or an
*unescaped* `|` inside a code span produces the same truncation — which is
why detection asks the parser where it truncates instead of scanning for
pipes. The identical trailing text under a wider header is a legitimate cell
and must be left to canonicalisation.

**Why a sentinel cannot work here.** A `mathguard` sentinel works because the
fragile bytes sit somewhere the parser reads: swap them in place and the
round-trip carries the sentinel through. Here the *position* is what gets
dropped, so a sentinel written past the last kept cell is discarded exactly
as the text was. The surplus is therefore **lifted out of the source before
the parse and appended back onto its own row after the render**, keyed by the
row's ordinal among the document's body rows. Ordinals are stable because the
splice never adds, removes or reorders a row, and `render_verified` refuses
to write if block structure moved at all.

| Symbol | What it does |
| --- | --- |
| `RowGuardError` (`rowguard.py:72`) | raised when a lifted surplus has no row to go back onto. `cli.main` maps it to exit 2; losing the bytes here is the one thing this module exists to prevent, so it is never dropped quietly |
| `RowOverflow` (`rowguard.py:83`) | frozen dataclass: `row` (0-based ordinal among **all** body rows in the document — the key `restore` uses), `line` (1-based, in the source), `text` (the surplus verbatim, trailing whitespace excluded) |
| `Protected` (`rowguard.py:99`) | frozen dataclass: `text` (the source with each surplus lifted out), `overflows`, `unprotected`. `.restore(text)` appends them back — note it takes the *rendered* text, unlike `mathguard.Protected.restore()` |
| `_unescaped_pipes(line)` (`rowguard.py:115`) | the offsets `escapedSplit` cuts on. It tracks a one-character `isEscaped` flag, so a pipe is a separator unless the character immediately before it is a backslash — `\\|` counts as escaped there too, and matching that matters more than being right about it |
| `_body_rows(tokens)` (`rowguard.py:128`) | `(source line, header column count)` per body row, in token order. Header and delimiter rows are excluded because trailing text on either makes the two disagree, the table is not recognised at all, and the line survives as a paragraph |
| `_cut(line, columns)` (`rowguard.py:155`) | offset of the pipe closing the last kept cell, or `None`. Reproduces markdown-it's enclosing-pipe pops — front first, then back on what is left — and returns `None` when what trails is only whitespace and pipes |
| `find_row_overflow(md)` (`rowguard.py:175`) | every droppable surplus, over the *source* as written. Short-circuits on `"\|" not in md` — the branch almost every parse takes |
| `_fingerprint(tokens)` (`rowguard.py:207`) | everything about a token stream a hash or a render can read: type, tag, content, info, markup, nesting, level, block, hidden, map, attrs, children |
| `protect(md)` (`rowguard.py:218`) | → `Protected`. **Accepts the lift only if the parser cannot tell**: both sides are parsed and fingerprinted, and a mismatch abandons the whole lift rather than trusting it |
| `restore(text, overflows)` (`rowguard.py:246`) | re-parses `text` to locate its body rows and appends each surplus onto its own |
| `warn_row_overflow(md, label, *, stream=None)` (`rowguard.py:267`) | reports only `protect(md).unprotected` to stderr and returns it. **Never touches the exit code** |

Design points:

- **It is hash-neutral, by construction and by check.** The parser was already
  discarding these bytes, so handing it the row without them yields the
  identical token stream — which `protect` asserts on every document rather
  than arguing. That is what makes CED-30 shippable as a hotfix: a
  `.cedit/base/` snapshot written before the guard still hashes to what the
  manifest recorded, so no consumer sees a false conflict, and the recovered
  text reappears in the base on the next `sync`. Only the canonical *bytes*
  move, and only additively.
- **The lift is all-or-nothing per document**, not per row. A wrong cut is
  indistinguishable from a right one at the row level; the fingerprint
  comparison is a whole-document check, so one bad row abandons the lot and
  reports every overflow. No input is known to reach it — the prefix rule
  follows blockquotes and list indentation — which is why
  `tests/test_rowguard.py` forces a bad cut to exercise the branch.
- **Order matters against `mathguard`.** `rowguard.protect` runs first, on the
  source as written: it shortens row lines, and `mathguard`'s offsets are
  taken over whatever it is handed. Restoring runs the other way round.
- **The surplus belongs to no block.** No cell contains it, so it rides with
  its row: a splice never sees it, `Block.text` never holds it, and a `sync`
  keeps whatever the incoming upstream revision's row carries. Preserving the
  bytes is the fix; making them mergeable is phase 2's problem, not this
  module's.

Call sites: `blocks.canonicalise`, `blocks.parse_doc` and
`blocks.render_verified` for the protection — `blocks.splice_block` is the
one `mathguard` wiring it does **not** share, and deliberately. Its
`warn_row_overflow` takes the same five wirings as `warn_fragile_math`:
`cmd_snapshot` on both sources, `cmd_sync` on both sources, `cmd_resolve
--take upstream` on the working copy, and `mdcli.cmd_md_canonicalize` on its
input.

## `cedit/state.py` — the `.cedit/` directory

| Path | Contents | Committed |
| --- | --- | --- |
| `.cedit/base/<doc>` | canonical base snapshot (B) | yes |
| `.cedit/manifest.json` | per-doc ledger + unresolved conflicts | yes |
| `.cedit/overlay.json` | derived local-edit overlay | yes, like a lockfile |

Base snapshots are files, not git blob refs, because B comes from a
*different* repository — there is no local blob to point at.

**Constants** (`state.py:21-23`): `MANIFEST_SCHEMA = "cedit-manifest/v1"`,
`OVERLAY_SCHEMA = "cedit-overlay/v1"`, `DEFAULT_STATE_DIR = ".cedit"`.
`StateError(RuntimeError)` (`state.py:26`) is what `cli.main` maps to exit 2.

**`norm_doc(doc)`** (`state.py:30`) — `os.path.normpath`, then rejects an
absolute path or one whose first segment is `..`. Every command normalises its
doc arguments through this, so manifest keys are always repo-relative and a
doc cannot address outside the tree.

**`State(root=".", state_dir=None)`** (`state.py:40`) — resolves `root` to an
absolute path, `self.dir` to `root/(state_dir or ".cedit")`, and reads both
JSON files in `__init__`, falling back to an empty `{"schema": …, "docs": {}}`
when a file is absent. Saves are atomic and always re-sort `docs` so diffs
stay local.

| Method | Purpose |
| --- | --- |
| `doc_path(doc)` / `base_path(doc)` (`state.py:57`, `:60`) | working copy under `root`; snapshot under `.cedit/base/` |
| `tracked()` (`state.py:65`) | sorted manifest doc keys |
| `entry(doc)` (`state.py:68`) | the manifest entry, raising `StateError` when untracked — the untracked check the commands rely on |
| `is_tracked(doc)` (`state.py:74`) | membership only; used by `cmd_snapshot`'s refusal |
| `set_entry(doc, *, upstream, base_doc_hash, conflicts=None)` (`state.py:77`) | upserts `upstream`, `base_doc_hash`, `synced_at`; writes `conflicts` only when passed, and `setdefault`s it to `{}` so the key always exists |
| `conflicts(doc)` (`state.py:90`) | rehydrates the raw dict into `{key: Conflict}` via `Conflict.from_dict` |
| `save_manifest()` / `save_overlay()` (`state.py:94`, `:108`) | atomic write of a docs-sorted copy |
| `set_overlay(doc, edits)` (`state.py:102`) | replaces the doc's entry with `derived_at` + `[edit.as_dict()]` |
| `read_base(doc)` (`state.py:116`) | raises `StateError` naming the path and asking whether `.cedit/base/` was committed |
| `write_base(doc, canonical_md)` (`state.py:123`) | atomic write of the snapshot |

**Authored vs derived.** `manifest.json` is authoritative: `upstream`,
`base_doc_hash`, `synced_at`, and `conflicts` (the only place all three
conflict texts live). `overlay.json` is *derived* — always recomputable from
the base snapshot plus the working copy, which is exactly what
`_refresh_overlay` does. Delete it and the next command regenerates it;
delete `manifest.json` and the open conflicts are gone. Note the consequence
for `resolve`: `--take local` deletes a manifest record and lets the *derived*
overlay pick the edit back up against the new base.

`state.py` imports from `merge3` (`Conflict`, `LocalEdit`), so the dependency
runs state → merge3, never the reverse.

## `cedit/store.py` — durable writes

| Symbol | Behaviour |
| --- | --- |
| `utc_now()` (`store.py:15`) | ISO 8601 UTC, second precision, `Z` suffix — the `synced_at` / `derived_at` format |
| `dumps(obj)` (`store.py:20`) | `json.dumps(ensure_ascii=False, indent=2)` plus a trailing newline. UTF-8 stays UTF-8 in state files |
| `atomic_write_text(path, text)` (`store.py:24`) | `makedirs` the parent, `mkstemp` **in the same directory** (prefix `.tmp-cedit-`), write, `flush`, `fsync`, `os.replace`. Unlinks the temp file and re-raises on any `BaseException` |
| `read_text(path)` (`store.py:44`) | UTF-8 read |
| `load_json(path)` (`store.py:49`) | UTF-8 JSON read |

Same directory is the point: `rename(2)` is only atomic within one
filesystem. A reader never sees a half-written state file, and a crash leaves
the previous good version in place.

## `cedit/mdcore/` — FROZEN

**Do not refactor, reformat or "improve" anything under `cedit/mdcore/`.** It
holds the parser and the diff engine, and a change to canonicalisation,
hashing or segmentation moves every hash already recorded in consumers'
`.cedit/` state, turning their next `sync` into a wall of false conflicts
against blocks nobody touched. Deliberate changes are possible and have a
runbook of their own:
[.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md) — how to
tell a hash-moving change from a hash-neutral one, the drift check
(`tests/parser_contract.py`) that decides it, and what consumers do when
hashes moved. See also *Reuse rules* in SPEC.md and invariant 1 in AGENTS.md.

That includes the parts cedit does not use: they are inert, and leaving them
alone keeps this module's diff readable. Removing them is hash-neutral and
allowed — as its own change, with the drift check green either side of it.

### `mdcore/utils.py` — the pinned parser

`make_parser()` (`utils.py:16`) is the single configuration every hash in
`.cedit/` is taken over, and the reason `requirements.txt` pins the parsing
stack exactly (invariant 2):

- `MarkdownIt("gfm-like2")`;
- `linkify = False`;
- `tasklists = False` — `gfm-like2` parses task lists natively but emits no
  checkbox token, while `mdformat_gfm`'s renderer was written against
  `mdit_py_plugins.tasklists`, which does. The native implementation is off so
  the plugin owns task lists. Hash-neutral;
- `alerts = False` — `> [!NOTE]` would parse into `alert` nodes mdformat
  cannot render at all. Off, they are ordinary blockquotes that round-trip
  byte-for-byte;
- `options["mdformat"] = {"keep_orphans": True}`, seeded **before** the plugin
  loop below. Two jobs in one line. It exists at all because `update_mdit`
  hooks read that key while the parser is being built, long before
  `ast_to_markdown` sets it — `mdformat_footnote`'s does so unguarded and
  raises `KeyError: 'mdformat'` without it (CED-25). And `keep_orphans` is on
  because that plugin's default *deletes* footnote definitions nothing
  references; canonicalisation is what produces `.cedit/base/`, so a deletion
  here is content lost before render-and-verify can compare anything;
- then **every installed mdformat parser extension** is appended to
  `parser_extension` and `update_mdit`-ed. The set of installed plugins is
  therefore part of the parser identity — which is why adding an mdformat
  plugin to the environment is a hash-moving change, exactly like bumping a
  pin.

| Symbol | Purpose |
| --- | --- |
| `markdown_to_ast(raw_markdown)` (`utils.py:59`) | parse to markdown-it tokens |
| `parse_inline(text)` (`utils.py:64`) | tokenize as *inline* only — `parseInline(text, {})[0].children or []`. The splice needs this so `- ` stays a paragraph |
| `ast_to_markdown(tokens)` (`utils.py:74`) | render back through `MDRenderer` with `mdformat` options `number=True`, `wrap="keep"`, `compact_tables=True`, `keep_orphans=True`. This assignment *replaces* `make_parser`'s seed, so `keep_orphans` is repeated to stop the render context contradicting the parse context. Never overwrite `options["parser_extension"]` here |

### `mdcore/tree_diff.py` — hashing, segmentation, similarity

What **cedit actually calls**:

| Symbol | Called from | Role |
| --- | --- | --- |
| `hash_tree(node)` (`tree_diff.py:76`) | `blocks.parse_doc` | annotates every node with `.h` (16-hex sha256 prefix). `hash(node) = H(type, tag, info, own_text, hash(c1)…hash(cn))`; a unit's identity is its inline source. **`map` (line numbers) and `level` are deliberately excluded**, so an insert above a block does not change its hash |
| `is_unit(node)` (`:52`), `OPAQUE` (`:38`) | `blocks.parse_doc` | the two block classes |
| `own_text(node)` (`:66`), `attr(node, name)` (`:56`) | `blocks.parse_doc`, `blocks.block_signature` | safe accessors — the root node raises on `tag`/`content`/`info` |
| `_unit_source(node)` (`:103`) | `blocks.parse_doc` | a unit's inline `.content` — its identity |
| `_heading_trail(node)` (`:136`) | `blocks.parse_doc` | the `context` string, ancestors joined with ` › ` |
| `ratio(a, b)` (`:120`) | `align._sim` | normalised text similarity, `autojunk=False` (not optional — difflib's junk heuristic skews and de-symmetrises character-sequence scores past 200 items) |
| `SIM_THRESHOLD = 0.4` (`:117`) | `align.align` | pairing floor inside a replace window |
| `FUZZY_THRESHOLD = 0.6` (`:156`) | `align.align` | floor for the global moved-and-edited pass |
| `_focus(old, new)` (`:172`), `_clip(text, start)` (`:166`) | `cli._pair`, `cli._print_conflict` | display clipping, `WIDTH = 110` |

`norm(text)` (`:43`) collapses whitespace before hashing and before every
similarity score, which is why an upstream reflow (80 cols → 72) is a no-op
for the overlay.

That table is the whole module: every top-level symbol in `tree_diff.py` is
reached from cedit. It was not always — roughly half the file was a
translation-planning surface inherited from the project this code was
vendored from, unreachable here since the day it arrived and deleted in
CED-19 once nothing re-vendored it, hash-neutrally and measured
(`tests/parser_contract.py` green on both sides).

`align.py` does the pairing this module deliberately does not: `tree_diff`
gives a block its identity (a hash) and a way to score two blocks against
each other (`ratio`, the thresholds), and `align.align` turns those into a
mapping from every base block to its counterpart — over *flat* block
sequences, pairing opaque blocks and keeping duplicate occurrences distinct,
both of which the merge needs and neither of which falls out of hashing
alone.

## Where each invariant lives

Line numbers are accurate as of the commit this file landed on; the symbol
names are the durable reference.

| # (AGENTS.md) | Enforced / carried by |
| --- | --- |
| 1 — `mdcore/` frozen | Convention plus one check: the freeze notices at `mdcore/__init__.py`, `mdcore/tree_diff.py:1-17` and `mdcore/utils.py:1-9`, and SPEC.md's *Reuse rules*. Nothing can catch a *refactor* — review has to — but `tests/parser_contract.py` catches any refactor that changed behaviour |
| 2 — exact pins | `requirements.txt` (the rationale is in the file itself) → `mdcore/utils.make_parser` (`utils.py:16`) → `blocks.canonicalise` (`blocks.py:96`) → every `Block.hash` and `ParsedDoc.doc_hash` |
| 3 — no silent clobber | `merge3.merge` (`merge3.py:240-241`) records the conflict **and** splices the local text; `Conflict` carries all three versions (`merge3.py:81`) and `state.set_entry` persists them; `cli.cmd_sync` (`cli.py:159-163`) refuses to sync a doc with open conflicts; `cli.cmd_resolve` (`cli.py:257`) is the only path that takes upstream text. The two clobbers the merge cannot see are prevented rather than reported: a `$…$` span the round-trip rewrites *inside* a block (`mathguard.protect`/`restore` in `blocks.canonicalise`, `parse_doc`, `splice_block` and `render_verified`), and text a table body row carries past the header's last column, which the parser drops before the tree exists (`rowguard.protect`/`restore` in the same places bar `splice_block`). `warn_fragile_math` and `warn_row_overflow` are left on the write paths for the cases protection cannot reach |
| 4 — exit codes | `cli.main` (`cli.py:377-379`) maps four exception types to 2; `cli.cmd_sync` (`cli.py:214-216`) and `cli.cmd_status` (`cli.py:243`) are the only sources of 1. `mathguard` is the deliberate counter-example: it reports a real defect and still returns nothing. Preserving the math is what makes that comfortable rather than merely contractual — there is now nothing to fail on |
| 5 — replacements only | `merge3.local_edits` (`merge3.py:184-187`) raises `StructuralDrift` on any local insert/delete/move, reported per block by `_describe_structural` (`merge3.py:155`); the merged document is U's tree rendered by `render_verified(upstream, …)` (`merge3.py:248`), and `blocks.splice_block` is the only mutation. `cli.cmd_resolve` refuses `--take local` on an orphan (`cli.py:268-273`) for the same reason |

## Tests

`tests/test_merge3.py` drives the merge matrix directly — one test per cell
plus the edge cases that shaped the code (`test_local_insertion_is_structural_drift`,
`test_duplicate_occurrence_edit_applies_to_the_right_copy`,
`test_upstream_move_carries_the_edit_along`,
`test_upstream_reflow_is_a_noop_for_the_edit`,
`test_table_cell_edit_reapplies_without_breaking_the_table`,
`test_front_matter_edit_reapplies`).

`tests/test_cli.py` drives the end-to-end lifecycle through `cli.main` in a
`tmp_path` repo (`test_full_lifecycle`), plus resolution
(`test_resolve_take_local_rekeys_the_edit`, `test_orphan_resolution`),
`test_dry_run_writes_nothing` and the two clean-error paths.

`tests/test_mdcli.py` drives the `md` group through `cli.main`, pinning
contracts rather than formatting: the token JSON really round-trips
(`test_token_json_round_trips_back_to_the_canonical_form`), `md blocks`
agrees with `parse_doc` *and* with `tests/parser-baseline.json`
(`test_blocks_json_reports_exactly_what_the_merge_keys_on`,
`test_blocks_keys_match_the_recorded_parser_baseline`), and the exit codes
stay inside invariant 4 — 1 only from `canonicalize --check`, 2 for every
bad input, parametrised over the verbs in
`test_a_missing_file_is_a_clean_exit_2`. `test_state_dir_is_accepted_and_ignored`
holds the stateless claim: pointed at a `--state-dir`, the verbs must not
create it.

`tests/test_mathguard.py` holds the math guard to the claims that make it
worth having. Preservation: every case in the `FRAGILE` and `STABLE` lists is
re-measured through `canonicalise` on each run
(`test_fragile_math_round_trips_byte_exact`,
`test_the_stable_column_is_byte_stable`,
`test_canonicalisation_is_idempotent`) *before* the detector is asked about
it, so a parser change that moved a case between columns fails here rather
than quietly invalidating the guard. The second write path is covered
separately — `test_the_render_path_preserves_it_too` runs the same corpus
through `render_verified`, which is what `sync` and `resolve` actually write,
and `test_a_splice_carries_math_in_the_text_it_splices_in` covers text that
arrives by splice rather than by parse.
`test_blocks_read_as_the_document_does_not_as_sentinels` pins the boundary:
sentinels stay in the token stream and never reach an overlay entry or a
conflict record. The three gaps the CED-27 prototype papered over each have
their own test — offsets rather than text matching
(`test_spans_are_located_by_offset_not_by_matching_their_text`), a
collision-checked sentinel
(`test_the_sentinel_is_inert_and_checked_against_the_document`) and
idempotence. `test_a_span_that_cannot_be_located_is_reported` and
`test_an_unlocatable_span_is_left_alone_rather_than_rewritten_wrongly` cover
the fallback. `tests/test_rowguard.py` is the same instrument for the table-row
guard, with one column the math guard has no equivalent of:
`test_lifting_the_surplus_moves_no_hash` and
`test_a_base_snapshot_written_before_the_guard_still_matches` re-derive the
hash-neutrality claim on every run, which is what lets CED-30 ship as a hotfix
without a re-baselining note. `test_trailing_text_that_fits_the_header_is_a_cell_not_a_surplus`
pins the reason detection consults the parser rather than counting pipes; `tests/test_cli.py` and `tests/test_mdcli.py` pin the three
write paths end to end, including QA's `sync` reproduction
(`test_sync_does_not_rewrite_a_math_line_neither_side_touched`).

`tests/test_packaging.py` covers the two packaging facts that rot silently:
`cedit.__version__` resolving from distribution metadata with a
`0.0.0+source` fallback for an uninstalled checkout
(`test_version_falls_back_in_an_uninstalled_checkout` reloads the module
with `importlib.metadata.version` patched to raise), and
`test_pyproject_pins_match_requirements_txt`, which fails if pyproject's
`dependencies` and `requirements.txt` drift apart — invariant 2 has to hold
for `pip install cedit` consumers too, not just source checkouts.
`test_readme_links_are_absolute` holds the line `README.md` is also the
package's PyPI long description: PyPI does not rewrite relative links, so
one resolves against `pypi.org/project/cedit/` and 404s while looking
perfectly fine in a GitHub preview. And
`test_supported_pythons_are_the_tested_pythons` keeps the `Programming
Language :: Python :: 3.x` classifiers, `requires-python` and `tests.yml`'s
matrix in agreement — three lists that mean one thing, in three files, none
of which imports the others. Advisory matrix legs (`advisory: true`, a
prerelease riding along under `continue-on-error`) are excluded: they are
early warning, not claimed support.

```bash
venv/bin/python3 -m pytest                                   # 105 tests, no network, <2s
venv/bin/python3 -m pytest tests/test_merge3.py -k reapply   # one test / one file
venv/bin/python3 -m cedit --help                             # the CLI
```

Use `venv/bin/python3`, never a bare `python3` — the interpreter needs the
pinned parsing stack. `.github/workflows/tests.yml` runs the same suite on
3.10 – 3.14, but it gates nothing (see AGENTS.md) — this local run is still
the gate.

## Changing cedit

Everything above describes the code as it stands. This section is the other
direction: given a change you want to make, what does it touch, and what
does it break in a consumer repo that already has `.cedit/` state committed.

Read [the blast radius](#the-blast-radius) first. It is the one thing that
distinguishes a change you can make freely from a change that costs every
consumer a manual recovery, and it is not visible from any single file.

### The blast radius

The hashes in a consumer's `.cedit/` are taken over exactly one pipeline —
`make_parser` → `canonicalise` → `hash_tree` (`utils.py:16`, `blocks.py:96`,
`tree_diff.py:86`). Any change that perturbs that pipeline changes what the
same Markdown hashes to, everywhere, retroactively.

| Change | Moves hashes? | Consequence |
| --- | --- | --- |
| Bump a pin in `requirements.txt` / `pyproject.toml` | **yes, possibly** | invariant 2 — a minor release can change what the parser emits |
| Install (or stop installing) an mdformat plugin | **yes, possibly** | `make_parser` appends *every installed* extension, so the environment is part of the parser identity |
| Touch `make_parser`'s options, or `ast_to_markdown`'s mdformat options | **yes** | changes the canonical form itself, not just the hash |
| Touch `hash_tree`, `norm`, `own_text`, `_unit_source` | **yes** | the hash function, directly |
| Change `UNIT_PARENTS` or `OPAQUE` (`tree_diff.py:42,45`) | **yes** | re-segments the document: different blocks, therefore different keys, even though the hash function is unchanged |
| Change `SIM_THRESHOLD`, `FUZZY_THRESHOLD`, `align`'s passes | no | pairing only — recomputed on every run |
| Change the merge matrix in `merge3.merge` | no | decides over hashes, does not produce them |
| Change `splice_block`, `render_verified`, `cli` output, `store`, `state` | no | downstream of hashing |
| Change `mathguard`'s **detection** (`find_fragile_math`, `_spans`, `_inline_close`, `_mask_code_spans`) | **yes, for documents holding `$…$` math** | detection decides what gets protected, so widening or narrowing it changes the canonical form of exactly those documents — and nothing else. This is how CED-27 itself moved hashes |
| Change `mathguard`'s **sentinel** (`_PREFIX`, `_DIGEST`, `_sentinel`) | **yes, for documents holding `$…$` math** | the tree is built over the sentinel, so its spelling is a hash input. The canonical *bytes* do not move — `restore` puts the same math back — which makes this the cheaper half of the damage (see hash-stability.md) |
| Change `mathguard.warn_fragile_math` or the message text | no | stderr only, and downstream of everything |
| Change `rowguard`'s **detection** (`find_row_overflow`, `_body_rows`, `_cut`, `_unescaped_pipes`) | **no — but it moves canonical bytes for documents holding an over-the-header table row** | the lifted text is outside every block and is stripped before hashing, so `protect` can and does assert the token stream is unchanged. Widening or narrowing detection therefore changes only what `.cedit/base/` *stores* for those documents, never what anything hashes to. Measure which documents, as CED-30 did |
| Change `rowguard.restore`'s keying (the row ordinal), or `warn_row_overflow` | no | `restore` is downstream of the render; the warning is stderr only |

The first five rows are all invariant-1/2 territory and four of them are in
frozen code you should not be editing at all — the row exists to say what
*would* happen, not to license it. The two `mathguard` rows are the one
hash-moving surface *outside* `mdcore/`, and they move hashes for a named
subset of documents rather than for all of them: measure which, as CED-27
did, instead of stopping at "hash-moving". The `rowguard` rows are the
instructive contrast — a guard that sits on the same path and still moves
no hash, because what it carries was never in the tree. Which class a guard
falls into is measured, not assumed from where it lives. Where a hash-moving change is
genuinely required, it goes through
[.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md): classify
it, re-record the baseline in the same commit, and say so in the release
notes.

**What actually breaks in a consumer repo**, concretely, because "moves
every hash" is vague about damage:

1. **Conflict keys in `manifest.json` become unmatchable.** The overlay is
   derived and simply re-derives itself, but conflicts are authored state
   (`state.py` — authored vs derived). A recorded conflict is keyed
   `<hash>:<occurrence>`; after a hash move, `cedit resolve <doc> <key>`
   cannot find the block, and `_match_conflict` (`cli.py:246`) reports the
   open keys as if the user mistyped.
2. **The committed base snapshots are stale canonical form.** They were
   written by the *old* `ast_to_markdown`. The next `sync` canonicalises
   upstream with the new one and compares (`cli.py:174`), so a document that
   did not change upstream at all is no longer `up to date`, and
   `local_edits(base, working)` reads the renderer delta as user edits — a
   wall of false conflicts against blocks nobody touched.
3. **`base_doc_hash` in the manifest goes stale.** This one is cosmetic:
   nothing verifies it, it is written by `set_entry` and printed by
   `cmd_status`. Do not let it reassure you — the absence of a check is why
   1 and 2 surface as confusing merges rather than as a clean error.

There is no schema-version gate to catch this: `State.__init__`
(`state.py:48-53`) uses `MANIFEST_SCHEMA` / `OVERLAY_SCHEMA` only as the
default for a *missing* file and never validates the `schema` key of one it
reads. If you ever do ship a hash-moving change, that check — and a
`cedit migrate` that re-snapshots bases and re-keys conflicts — is the
prerequisite, not an afterthought.

### Recipe: a new subcommand

First decide *which* surface it belongs on. A command that opens `.cedit/`
and talks about tracked documents is a workflow subcommand and follows the
six steps below. A stateless view — a file or stdin in, stdout out — is a
new verb in `mdcli.add_md_group`, and costs far less: no doc-count churn
(step 5 does not apply, since "five" still means the five stateful ones),
and the only exit codes available to it are 0 and 2 unless you can argue,
as `canonicalize --check` does, that 1 really means "a human needs to look".

It is cheaper, not free. A new verb still has to be **listed in five
places**, and CED-24 was the task of paying that debt down for the group's
first five: the verb table and a worked example on the guide's
[`md` — stateless parser views](userguide/command-reference/md-parser-views.md)
page — a real captured run against the
[five-minute tour](userguide/getting-started/five-minute-tour.md) document,
per that page's own rule, never hand-written output — the `md` column of the
exit-code matrix in the guide's
[appendix](userguide/help/appendix.md#exit-codes), the usage block in
`README.md` (*Looking at the parser directly*), the verb table in this
file's `mdcli.py` section, and `tests/test_mdcli.py`. The `--help` transcript
on that same parser-views page lists the *group*, not its verbs, so a new
verb does not touch it.

Six places, and the last three are what gets forgotten:

1. `cli.build_arg_parser` (`cli.py:334`) — `sub.add_parser(...)`, then
   `set_defaults(func=cmd_yours)`. `--from` is `dest="from_"` by convention
   (`from` is a keyword).
2. `cli.cmd_yours` — take `args`, return an int. Raise `StateError` for
   anything the user can fix; `main` maps it to 2. Do not `sys.exit`.
3. Decide the exit code deliberately — invariant 4. `1` means "unresolved
   conflicts", nothing else; only `cmd_sync` and `cmd_status` produce it
   today, both as a bool accumulated across docs and applied only once `rc`
   is known to be 0.
4. `tests/test_cli.py` — drive it through `cli.main` in a `tmp_path` repo,
   as the existing tests do; assert the exit code, not just the output.
5. **The count "five" and the literal subcommand list are hard-coded in
   eight doc locations** — in `README.md` the documentation table, the
   *Looking at the parser directly* usage block and the layout table;
   `AGENTS.md`'s architecture table; and in the guide the
   [contents list](userguide/index.md), the
   [The five subcommands](userguide/command-reference/index.md) page, and
   both lines of the `--help` transcript on
   [`md` — stateless parser views](userguide/command-reference/md-parser-views.md).
   The per-command exit-code matrix in the guide's
   [appendix](userguide/help/appendix.md#exit-codes) names the commands
   without counting them, and `SPEC.md` §CLI deliberately says "same
   subcommand set" instead of a number. Nothing tests any of this. These
   used to be line numbers and went stale exactly as predicted the first
   time the guide moved (CED-32), so they are locations now — grep for
   `five subcommands` and for the literal
   `{snapshot,diff,sync,status,resolve,md}`, which is the string the
   `--help` transcript actually carries now that the group is wired in.
6. If it can write, route it through `store.atomic_write_text` and mirror
   `cmd_sync`'s ordering: working file first, state second.

### Recipe: a new block kind

The block classes are `tree_diff.UNIT_PARENTS` and `tree_diff.OPAQUE`
(`tree_diff.py:42,45`) — **frozen**, and this is hash-moving by row 5 of the
table above. Assuming that is settled through
[.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md), the rest
of the work is:

1. `blocks.parse_doc` (`blocks.py:101`) — the walk already keys off those
   two sets and does not descend into a block, so a new member usually needs
   no change here. Confirm it does not contain nodes you still want walked.
2. `blocks.splice_block(doc, block, …)` (`blocks.py:177`) — the mutation. Opaque nodes set
   `token.content` (plus `token.info` for a fence); units go through
   `parse_inline`. A kind that is neither needs its own branch, and it must
   return `False` rather than half-splice when there is nothing to write
   into — `merge3._splice_or_conflict` turns `False` into a conflict, which
   is the safe degradation.
3. `Block.compare_text` (`blocks.py:75`) — if the new kind has an
   attribute that is part of its editable surface the way `info` is for a
   fence, it belongs here, or an edit to it will score as a replacement
   instead of an edit.
4. `blocks.block_signature` (`blocks.py:140`) — the render-verify gate. It
   stops at `inline`; if the new kind's structure must be checked more
   finely, this is where.
5. Add a `tests/test_merge3.py` case in the shape of
   `test_front_matter_edit_reapplies` — the existing per-kind precedent.

### Recipe: changing alignment behaviour

`align.align` (`align.py:58`) is outside the frozen core, and is the safe
place to experiment: nothing it does reaches a stored hash. The four passes
run LCS → in-window greedy → 1-for-1 positional fallback → global move then
global fuzzy, and the order matters — the positional fallback
(`align.py:100-106`) exists because a short edit in a table cell scores 0.18
and would otherwise be misread as structural drift and *rejected*, not
merely mispaired.

Two readings of the same output, and a change must satisfy both: against the
local copy, `moved` and `DELETED` are fatal (`_describe_structural` raises
`StructuralDrift`); against upstream, they are counters. Loosening pairing
therefore trades false structural-drift rejections for wrong reapplications
— errors of different severity, since one refuses to write and the other
writes the wrong thing. Prefer the refusal.

### Recipe: a new field in the state files

`manifest.json` is authored, `overlay.json` is derived. Which one you are
adding to decides the work:

- **Derived** (overlay) — add it to `LocalEdit` and to `LocalEdit.as_dict`
  (`merge3.py:47`), and to nothing else. Note the existing precedent:
  `base_index` and `sim` are deliberately *not* serialised because they are
  recomputed on every derivation, and persisting a recomputed value only
  invites staleness. Apply the same test to your field.
- **Authored** (manifest) — `Conflict.as_dict` / `from_dict`
  (`merge3.py:81`) and `state.set_entry` (`state.py:77`). `from_dict` must
  default the new field for entries written by an older cedit, exactly as it
  defaults every field to `""` today and `upstream_text` to `None`. There is
  no migration step to lean on (see the blast radius above), so
  backward-compatible defaults are the whole compatibility story.

Both files are written through `store.atomic_write_text` with docs re-sorted
on every save, so state diffs stay local — keep any new container sorted for
the same reason.

### Where phase 2 and phase 3 attach

SPEC.md §Phases defines them; these are the seams they land on.

**Phase 2, structural local edits.** The wall is one function:
`merge3.local_edits` (`merge3.py:184-187`) raises `StructuralDrift` on
anything `_describe_structural` reports. Because `cmd_snapshot`, `cmd_diff`,
`cmd_status`, `cmd_resolve` and `merge` all funnel through it, lifting the
restriction is one change, not five — that funnelling is deliberate, so keep
it. What follows from lifting it: `LocalEdit` grows an anchor (the preceding
base unit's hash, per SPEC) and an operation kind, `merge`'s single pass over
`base.blocks` (`merge3.py:225-246`) has to emit insertions positioned
relative to that anchor rather than only splicing in place, and
`cmd_resolve`'s refusal of `--take local` on an orphan (`cli.py:268-273`)
becomes decidable instead of categorical. The render-verify gate
(`render_verified`) is what keeps this honest — it will catch a positioned
insertion that re-parses into different structure, which is the failure mode
phase 2 introduces.

**Phase 3, assisted rebase.** Attaches at exactly one row of the matrix: the
CONFLICT branch (`merge3.py:240-241`), which today records the conflict and
splices the local text. A machine-proposed port is an extra field on
`Conflict` plus a `review_status` on the resulting `LocalEdit` — it must not
change what the working file gets, or invariant 3 is gone. `resolve` stays
the only gate.

### Before you commit

```bash
venv/bin/python3 -m pytest      # the gate — tests.yml is not a required check
```

Then, in order of how easily each is forgotten:

- Did you move hashes? If yes, stop and re-read the blast radius — this is
  a release-note-and-migration change, not a patch.
- Did the change alter the doc-visible surface (a flag, an exit code, an
  output line)? The guide's
  [command reference](userguide/command-reference/index.md) is per-flag and
  will drift silently.
- Did you edit anything under `cedit/mdcore/`? That is invariant 1 — read
  [.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md) and run
  `venv/bin/python3 tests/parser_contract.py`.
- Did you touch `.github/workflows/`? Read
  [.claude/rules/release-pipeline.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/release-pipeline.md)
  first — and never put a CI skip marker in a commit subject.
- Did you add a Python version, a classifier or a matrix leg? All three
  move together or `test_supported_pythons_are_the_tested_pythons` fails.
- Line numbers in this file are accurate as of the commit that last touched
  it; the symbol names are the durable reference. If you moved code far,
  fix the references you noticed — do not audit the whole file.
