# cedit source map

Code-level reference for the `cedit` implementation: what every module,
function and dataclass actually does, how a call flows from `cli.main` down
to the splice, and where each of AGENTS.md's five invariants is enforced.

**This file is a reference, not an instruction set.** It is deliberately not
`@`-imported by `AGENTS.md` — read it when you are about to change code,
not on every session.

Where the other documents stop:

| Document | Answers |
| --- | --- |
| [README.md](../../README.md) | setup, quickstart, exit codes, repo layout |
| [USERGUIDE.md](../../USERGUIDE.md) | command reference, task flows, conflict lifecycle, troubleshooting |
| [SPEC.md](../../SPEC.md) | normative design — merge matrix, sync algorithm, state format, reuse rules, phases |
| [AGENTS.md](../../AGENTS.md) | orientation and the five invariants |
| **this file** | the implementation that realises them |

Nothing here restates behaviour those four define. Where a design decision
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
└── merge3.merge(B, L, U)
    ├── blocks.parse_doc  ×3                → ParsedDoc(canonical, tokens, root, blocks)
    │   ├── mdcore.utils.markdown_to_ast     the one pinned parser
    │   └── mdcore.tree_diff.hash_tree       Merkle hash per node → Block.hash
    ├── merge3.local_edits(B, L)            the overlay
    │   ├── align.align(B.blocks, L.blocks)  → [Fate], [inserted Block]
    │   ├── merge3._describe_structural      any local insert/delete/move …
    │   └── raise merge3.StructuralDrift      … aborts here, before anything is written
    ├── align.align(B.blocks, U.blocks)     what upstream did
    ├── one pass over B.blocks              the merge matrix (below)
    │   └── blocks.splice_block(U-node, local_text, local_info)
    └── blocks.render_verified(U)           re-parse own output, compare block_signature
                                            → raise blocks.StructureMismatch, or the Markdown
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

Imports its whole working set at the top (`cli.py:20-24`): `blocks`
(`StructureMismatch`, `canonicalise`, `parse_doc`, `splice_block`,
`render_verified`), `mdcore.tree_diff`, `merge3` (`ORPHAN`, `Conflict`,
`StructuralDrift`, `local_edits`, `merge`), `state` (`State`, `StateError`,
`norm_doc`), `store` (`atomic_write_text`, `read_text`).

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

Then `write_base` → `set_entry` → `save_manifest` → `set_overlay` →
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

`--dry-run` / `-n` reports (`result.as_text()` plus every conflict) and
returns before the first write. The return is
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
| `--take upstream` | on an `ORPHAN`, drop the record (deletion accepted). Otherwise locate the block in the working copy by `(kind, node_type, text, info)`, `splice_block` the upstream text in, `render_verified`, write, drop the record, refresh the overlay |

The `--take upstream` lookup is exact-match by construction (`cli.py:292-297`);
if the user has since hand-edited that block it returns `None` and the command
exits 2 telling them to fix the text by hand and use `--take local` — it never
guesses which block was meant.

**`_refresh_overlay(state, doc)`** (`cli.py:313`) — re-derives the whole
overlay for one doc from the base snapshot and the current working copy.
Called after every resolution that changes either side.

### The argparse surface

`build_arg_parser` (`cli.py:327`). Global `--state-dir` (default `.cedit` —
resolved in `state.State`, not here, so the default is `None` at this level).
`sub = parser.add_subparsers(dest="command", required=True)`; each subparser
sets `func` via `set_defaults`.

| Subcommand | Positional | Options |
| --- | --- | --- |
| `snapshot` | `doc` | `--from` (`dest="from_"`, **required**) |
| `diff` | `docs` (`nargs="*"`) | `--unified` |
| `sync` | `docs` (`nargs="*"`) | `--from` (`dest="from_"`), `-n` / `--dry-run` |
| `status` | `docs` (`nargs="*"`) | — |
| `resolve` | `doc`, `key` | `--take {local,upstream}`, `--show` |

`--from` is `dest="from_"` everywhere because `from` is a keyword; the
attribute is `args.from_`.

### Exit-code policy — invariant 4

`main` (`cli.py:373`) wraps the dispatch in one `try` and maps
`StateError`, `StructuralDrift`, `StructureMismatch` and `FileNotFoundError`
to **2**. Anything else propagates as a traceback, deliberately: an unexpected
exception is a bug, not a user error.

`0` clean · `1` unresolved conflicts, recorded by `cmd_sync` or found by
`cmd_status` · `2` errors. The two commands that can return 1 both compute it
the same way — a boolean accumulated across docs, applied only after `rc` is
known to be 0.

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

Three status constants — `SAME`, `EDITED`, `DELETED` (`align.py:21-23`) —
whose values are their own names.

**`Fate`** (`align.py:26`): `status: str`, `moved: bool`,
`other: Block | None` (the counterpart, `None` only when `DELETED`),
`sim: float`.

**`_sim(a, b)`** (`align.py:36`) — `0.0` when `kind` or `node_type` differ,
otherwise `tree_diff.ratio` over `Block.compare_text`. A fence never pairs
with a paragraph, whatever the text similarity.

**`align(base, other)`** (`align.py:42`) returns
`(fates parallel to base, blocks of other that are new)` in four passes:

1. **LCS over Merkle hashes.** `SequenceMatcher(None, [b.hash …], [x.hash …],
   autojunk=False)`. `equal` opcodes become `Fate(SAME, False, other[j], 1.0)`;
   `delete` and `insert` opcodes feed the pools.
2. **Greedy best-first pairing inside each `replace` window.** Every
   (base, other) pair in the window is scored and sorted descending; pairs at
   or above `tree_diff.SIM_THRESHOLD` (0.4) whose ends are both still free
   become `Fate(EDITED, False, …)`.
3. **The 1-for-1 positional fallback** (`align.py:84-90`) — cedit's one
   deliberate divergence from the localization heuristics, and the comment at
   that site explains why. When a `replace` window holds exactly one block on
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
  `front_matter`, `hr`. The localization pipeline only ever copies these; here
  they are first-class, because the motivating local edit *is* a rewritten
  code fence.

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
`blocks: list[Block]`. `doc_hash` (property) is `root.h`, the Merkle root
recorded as `base_doc_hash` in the manifest.

### `canonicalise` and `parse_doc`

`canonicalise(md)` (`blocks.py:96`) is `ast_to_markdown(markdown_to_ast(md))`
— the mdformat round-trip **every hash in `.cedit/` is taken over**.

`parse_doc(md, *, canonical=False)` (`blocks.py:101`) canonicalises unless
told the input already is (`canonical=True` is used for base snapshots, which
were written canonical), parses, builds the tree, calls `tree_diff.hash_tree`
to annotate every node with `.h`, then walks: a unit or an `OPAQUE` node
becomes a `Block` and the walk does **not** descend into it; anything else
recurses into its children. Occurrence indices are assigned in a second pass
over the flat list, so they follow document order.

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

### `splice_block(block, text, info="") -> bool` (`blocks.py:177`)

Replaces the block's editable content **in its tree, in place**, and returns
`False` when there is nothing to splice into.

- **Opaque** → set `token.content = text`, and `token.info = info` as well when
  the node is a `fence`. Always `True`.
- **Unit** → find the `inline` child; **`None` → return `False`** (an empty
  table cell — the caller decides what that means, and
  `merge3._splice_or_conflict` turns it into a conflict). For a `th`/`td`,
  collapse whitespace to a single line first. Re-tokenize with
  `mdcore.utils.parse_inline`, so text starting with `- ` stays a paragraph
  instead of becoming a list. If the original inline started with a task-list
  checkbox `html_inline`, that token is re-inserted at position 0 — it is
  block structure parked in an inline child and must be carried across, never
  replaced. Finally set both `inline.token.children` and
  `inline.token.content`.

Block structure always comes from the tree being spliced *into* and is never
re-derived from the replacement text. That is the reassembly invariant.

### `render_verified(doc, *, label) -> str` (`blocks.py:206`)

Renders `doc.tokens` (post-splice), takes `block_signature` of
`doc.canonical` and of the rendered output, and raises `StructureMismatch`
with `_first_difference` when they differ. A splice-only design's one
invisible failure mode is a replacement that re-parses into different block
structure; this is the gate, and it runs on **every** render — the merge
(`merge3.py:248`) and `resolve --take upstream` (`cli.py:304`) alike.

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

## `cedit/mdcore/` — VENDORED AND FROZEN

**Do not refactor, reformat or "improve" anything under `cedit/mdcore/`.** It
is a verbatim copy of the markdown-localization repo's parser and diff
engine. A change to hashing or segmentation moves every hash already recorded
in consumers' `.cedit/` state, turning their next `sync` into a wall of false
conflicts against blocks nobody touched. Fixes belong upstream and arrive here
as a re-vendoring. See *Reuse rules* in SPEC.md and invariant 1 in AGENTS.md.

That includes the parts cedit does not use. The package is vendored whole, on
purpose, so re-vendoring is a copy rather than a merge — do not "tidy up" the
unused surface.

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
- then **every installed mdformat parser extension** is appended to
  `parser_extension` and `update_mdit`-ed. The set of installed plugins is
  therefore part of the parser identity — which is why adding an mdformat
  plugin to the environment is a hash-moving change, exactly like bumping a
  pin.

| Symbol | Purpose |
| --- | --- |
| `markdown_to_ast(raw_markdown)` (`utils.py:43`) | parse to markdown-it tokens |
| `parse_inline(text)` (`utils.py:48`) | tokenize as *inline* only — `parseInline(text, {})[0].children or []`. The splice needs this so `- ` stays a paragraph |
| `ast_to_markdown(tokens)` (`utils.py:58`) | render back through `MDRenderer` with `mdformat` options `number=True`, `wrap="keep"`, `compact_tables=True`. Never overwrite `options["parser_extension"]` here |

### `mdcore/tree_diff.py` — hashing, segmentation, similarity

What **cedit actually calls**:

| Symbol | Called from | Role |
| --- | --- | --- |
| `hash_tree(node)` (`tree_diff.py:86`) | `blocks.parse_doc` | annotates every node with `.h` (16-hex sha256 prefix) and `.size`. `hash(node) = H(type, tag, info, own_text, hash(c1)…hash(cn))`; a unit's identity is its inline source. **`map` (line numbers) and `level` are deliberately excluded**, so an insert above a block does not change its hash |
| `is_unit(node)` (`:62`), `OPAQUE` (`:45`) | `blocks.parse_doc` | the two block classes |
| `own_text(node)` (`:76`), `attr(node, name)` (`:66`) | `blocks.parse_doc`, `blocks.block_signature` | safe accessors — the root node raises on `tag`/`content`/`info` |
| `_unit_source(node)` (`:117`) | `blocks.parse_doc` | a unit's inline `.content` — its identity |
| `_heading_trail(node)` (`:312`) | `blocks.parse_doc` | the `context` string, ancestors joined with ` › ` |
| `ratio(a, b)` (`:149`) | `align._sim` | normalised text similarity, `autojunk=False` (not optional — difflib's junk heuristic skews and de-symmetrises character-sequence scores past 200 items) |
| `SIM_THRESHOLD = 0.4` (`:146`) | `align.align` | pairing floor inside a replace window |
| `FUZZY_THRESHOLD = 0.6` (`:434`) | `align.align` | floor for the global moved-and-edited pass |
| `_focus(old, new)` (`:505`), `_clip(text, start)` (`:499`) | `cli._pair`, `cli._print_conflict` | display clipping, `WIDTH = 110` |

`norm(text)` (`:53`) collapses whitespace before hashing and before every
similarity score, which is why an upstream reflow (80 cols → 72) is a no-op
for the overlay.

What is vendored but **unused by cedit** — the localization pipeline's own
surface, kept so the copy stays verbatim: `plan` (`:395`) and `WorkItem`
(`:300`), `diff_trees` (`:197`) with `_diff_node` / `_diff_children` /
`_align_window` / `_detect_moves` and `Op` / `KINDS`, `similarity` (`:160`),
`tm_keys` (`:478`), `_placeholders` (`:339`), `_units_under` (`:358`),
`_opaque_under` (`:368`), `_fuzzy_pair` (`:437`),
`NON_TRANSLATABLE_INLINE` (`:48`).

`align.py` exists precisely because `plan()` answers a different question: it
does not pair opaque blocks (a changed fence is just `COPY`) and does not
distinguish duplicate occurrences (same source ⇒ same translation). The merge
needs both, so `align` re-implements the pairing over flat block sequences
using `tree_diff`'s thresholds — one definition of "similar enough", two
consumers.

## Where each invariant lives

Line numbers are accurate as of the commit this file landed on; the symbol
names are the durable reference.

| # (AGENTS.md) | Enforced / carried by |
| --- | --- |
| 1 — `mdcore/` frozen | Convention, not code: `cedit/mdcore/__init__.py`, the vendoring notices at `mdcore/tree_diff.py:1-21` and `mdcore/utils.py:1-9`, and SPEC.md's *Reuse rules*. Nothing in the program can catch a refactor here — review has to |
| 2 — exact pins | `requirements.txt` (the rationale is in the file itself) → `mdcore/utils.make_parser` (`utils.py:16`) → `blocks.canonicalise` (`blocks.py:96`) → every `Block.hash` and `ParsedDoc.doc_hash` |
| 3 — no silent clobber | `merge3.merge` (`merge3.py:240-241`) records the conflict **and** splices the local text; `Conflict` carries all three versions (`merge3.py:81`) and `state.set_entry` persists them; `cli.cmd_sync` (`cli.py:159-163`) refuses to sync a doc with open conflicts; `cli.cmd_resolve` (`cli.py:257`) is the only path that takes upstream text |
| 4 — exit codes | `cli.main` (`cli.py:377-379`) maps four exception types to 2; `cli.cmd_sync` (`cli.py:214-216`) and `cli.cmd_status` (`cli.py:243`) are the only sources of 1 |
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
venv/bin/python3 -m pytest                                   # 29 tests, no network, <1s
venv/bin/python3 -m pytest tests/test_merge3.py -k reapply   # one test / one file
venv/bin/python3 -m cedit --help                             # the CLI
```

Use `venv/bin/python3`, never a bare `python3` — the interpreter needs the
pinned parsing stack. `.github/workflows/tests.yml` runs the same suite on
3.12 – 3.14, but it gates nothing (see AGENTS.md) — this local run is still
the gate.
