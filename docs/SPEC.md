---
id: spec
slug: /spec
sidebar_label: Spec
sidebar_position: 2
---

# cedit — continuous editing of vendored Markdown

Keep **local adaptations** of a vendored Markdown document alive across
**upstream updates**. Motivating case: a skill like
`md/skills/jira-task-assigner/SKILL.md` is copied into an environment where
`bash` doesn't exist — a few fenced commands are rewritten for `zsh`, and
everything else (the prose, the step ordering, the tables) should keep
tracking upstream. Today that consumer either freezes the file (loses
upstream fixes) or re-edits it after every update (loses their changes, or
merges by hand). cedit makes the local changes a durable, re-appliable
overlay and turns "update from upstream" into a structural 3-way merge that
either succeeds silently or reports a precise, unit-level conflict.

**What to call it.** The mechanism has prior art under several names:
quilt-style *patch queues* (Debian, kernel), `git rerere` (reuse recorded
conflict resolutions), ports/overlay patching (Gentoo, Homebrew formula
patches), and "downstream fork maintenance" generally. The honest one-line
description is: *a persistent block-level overlay, re-applied by 3-way
structural merge*. Working name: **cedit** (continuous editing).

This is a research POC. Its parser configuration, hashing and diff engine
live frozen in `cedit/mdcore/` (see *Reuse rules* below), because every hash
cedit records is a function of them.

## The model — three revisions, two alignments, one merge

Every tracked document has three revisions:

| Revision | Symbol | Where it lives |
| --- | --- | --- |
| base — the upstream revision the local copy was last synced against | **B** | `.cedit/base/<path>` (canonicalized snapshot, committed) |
| local — the working file the user edits in place | **L** | the document itself |
| upstream — the new revision being synced in | **U** | supplied to `sync` (a directory or file; fetching/vendoring is the user's transport, out of scope) |

`sync` computes two alignments with the existing engine's primitives and
merges them:

```
local_edits      = align(blocks(B), blocks(L))   # what the user changed
upstream_changes = align(blocks(B), blocks(U))   # what upstream changed
```

`align` (`cedit/align.py`) is a flat block-sequence alignment built from
`tree_diff`'s pieces — LCS over Merkle hashes, greedy similarity pairing in
each replace window, a global same-hash move pass, a global fuzzy pass for
moved-and-edited blocks, the same thresholds. It works over the *flat* block
sequence rather than the tree because the question the merge asks is a
question about pairs: for every block of B, which block of L (or U) is it
now. Opaque blocks are paired like any other — the motivating local edit is
a rewritten code fence — and two byte-identical blocks stay distinct, since
a user may have adapted only the third copy of a repeated command. One rule
is editing-specific: a 1-for-1 replacement of a like-typed block inside one
replace window is an **edit** regardless of text similarity (`a` →
`a-adapted` in a table cell scores 0.18; for translation a mis-split just
retranslates, here it would misread an edit as structural drift).

The merge is decided **per block of B**, keyed by hash — the same
16-hex-char Merkle hashes `tree_diff.hash_tree` produces, over the same
pinned parser (`mdcore/utils.make_parser`). Because the key is a content hash,
an upstream *move* of a unit the user edited costs nothing: the edit
re-applies at the unit's new position. Reflow and formatting churn cost
nothing either — canonicalization runs before every hash, and is exactly as
load-bearing as the hashing itself.

## Edit blocks = inline units **plus opaque blocks**

**The vocabulary, mapped once.** `mdcore/` was vendored from a Markdown
*localization* research project, where translating a document was the
product, and its identifiers and comments still carry that idiom. The names
stay — renaming inside `mdcore/` is the refactor *Reuse rules* forbids, and
every hash a consumer recorded is keyed to that code — so the mapping is
written down here, once, and the code points at it instead of re-deriving it:

| there | here | what it is in cedit |
| --- | --- | --- |
| *translation unit* (`UNIT_PARENTS`, `is_unit`) | **inline unit** | a `heading` / `paragraph` / `th` / `td` — a node owning an `inline` child, whose inline source is the text a local adaptation rewrites |
| *fuzzy match* (`FUZZY_THRESHOLD`) | **moved-and-edited pairing** | one block recognised in another that upstream both relocated and rewrote |
| *translation memory* reuse | **re-applying an overlay** | splicing a recorded local edit onto the block it belongs to in the incoming revision |

The concepts survive the move because both problems are the same one — decide
which block of the new document *is* which block of the old, then act per
block. What differs is the act: translating a segment, versus re-applying an
adaptation to it.

`tree_diff` segments a document into those inline units — the prose-bearing
blocks. The critical difference for editing: the motivating edit is a **code
fence**, and in `tree_diff` fences, raw HTML and front matter are *opaque* —
hashed, so a change to one is noticed, but never inline units. For cedit the
editable set is therefore the union:

- **inline units** (heading / paragraph / th / td) — keyed by unit hash;
- **opaque blocks** (fence / html\_block / front matter) — keyed by their
  own content hash, which `hash_tree` gives them like any other node.

Both kinds diff, overlay, and merge identically; only the splice differs
(inline content vs. whole-token replacement). Granularity caveat: an opaque
block is one unit — editing one line of the YAML front matter overlays the
whole front-matter block, and an upstream front-matter change is then a
conflict on the whole block. Acceptable for the POC; splitting front matter
per key is future work.

**Duplicate hashes.** Two byte-identical blocks stay distinct: a user may
have adapted only the *third* copy of a repeated command, and re-applying
that edit to all three would be wrong. (This is one place the vendored
engine's assumption does not carry over — "same source ⇒ same translation"
holds for translating, not for adapting.) Overlay keys are therefore
`(hash, occurrence_index)` in document order. If the occurrence count of an
edited hash changes upstream, that edit degrades to a conflict rather than
guessing.

## The merge matrix

For each base unit, cross what `align(B, U)` says upstream did with whether
`align(B, L)` says the user edited it. Both sides speak the same three
verdicts — `SAME`, `EDITED`, `DELETED`, each carrying whether the unit also
*moved*:

| `align(B, U)` says | locally edited? | outcome |
| --- | --- | --- |
| `SAME` | no | — (identical everywhere) |
| `SAME`, moved or not | **yes** | **REAPPLY** — splice the local text at the unit's (possibly new) position |
| `EDITED` | no | **UPDATE** — take upstream |
| `EDITED` | **yes** | **CONFLICT** — three texts recorded, see below |
| `DELETED` (retired upstream) | no | take upstream's deletion |
| `DELETED` (retired upstream) | **yes** | **ORPHAN** — a conflict flavor: the unit your edit lived on no longer exists |
| a unit of U with no base counterpart (upstream insert) | — | take upstream |

A move is never a decision input, only a report line: the merge is keyed by
content hash, so an upstream move of an edited unit re-applies at its new
position for free.

Units the user *inserted or deleted* locally (structure changes, not
replacements) are phase 2 — see *Phases*. Phase 1 rejects them at
`snapshot`/`sync` time with a clear message rather than mis-merging: the
merged document's structure always comes from **U** — the splice is the
only mutation — which is what makes the frozen machinery reusable here.

## Why an AST overlay, not git patches

The user-visible question — "generate the diff in AST mode or git's?" —
is decided for AST, for reasons that predate cedit:

1. **Line diffs die on canonicalization.** A reflow from 80 to 72 columns
   invalidates every hunk context; hash-keyed units call it a no-op.
2. **Moves.** `patch(1)` loses a hunk whose context moved; a content hash
   *is* the address, so moved units re-apply for free.
3. **Conflict markers are not valid Markdown.** `=======` is a setext
   heading underline — a git-style conflict block turns the preceding line
   into an H1 on the next parse; `<<<<<<<` becomes paragraph prose. A
   conflict-marked file no longer round-trips, which breaks every hash
   downstream. So conflicts must live *outside* the document (below).
4. Git-format output is still available as a **view**: `cedit diff` prints
   a human-readable unit report by default and can emit a plain unified
   diff of canonicalized B vs. L for reviewers who want familiar syntax.
   It's a rendering of the overlay, never the stored form.

## Conflicts

On CONFLICT/ORPHAN the working file keeps the **local** text (never
clobber the user's adaptation), and the conflict is recorded in the state
file with all three texts — base, upstream, local — so nothing is lost and
resolution needs no history spelunking. `status` lists unresolved conflicts
until each is settled:

```bash
cedit resolve <path> <hash> --take local      # keep the adaptation; re-key it to the new upstream unit
cedit resolve <path> <hash> --take upstream   # drop the adaptation, splice upstream text
cedit resolve <path> <hash> --show            # print all three versions in full; edit the file by
                                              # hand, then --take local to accept what you wrote
```

`--take local` is the `git rerere` move: the local text is re-keyed to the
*new* upstream unit's hash, so the next sync re-applies it without asking
again. An unresolved conflict blocks nothing else — every other unit in the
document merges normally.

## State — `.cedit/` in the consumer repo

| Path | Contents | Committed? |
| --- | --- | --- |
| tracked docs (e.g. `skills/**.md`) | **L** — the user's working copies | yes (they're the product) |
| `.cedit/base/<mirrored path>` | **B** — canonicalized base snapshots | **yes** — the merge is impossible without B, and a git blob ref doesn't work here because B comes from a *different* repo |
| `.cedit/manifest.json` | per-doc: upstream source id, base doc hash, last sync, unresolved conflicts (with the three texts) | **yes** |
| `.cedit/overlay.json` | the derived local-edit overlay: `(hash, occurrence) → {base_text, local_text}` per doc | **yes** — but *derived*: L is the single source of truth, the overlay is recomputed from `align(B, L)` at every `snapshot`, `sync` and `resolve`. Committed anyway because "what have we customized" is exactly what a reviewer wants to see in a PR diff, like a lockfile |
| sync reports | per-run outcome counts + conflict details | no — run artifact |

Deriving the overlay instead of maintaining it as source of truth is the
anti-quilt decision: the user edits the document, never a patch file, so
the overlay can't go stale — the failure mode where a hand-maintained patch
silently stops applying does not exist.

## Sync algorithm (normative)

1. Canonicalize B (already canonical), L, U with the shared parser.
2. `local_edits = align(blocks(B), blocks(L))`. Phase 1: any structural
   local change (insert/delete/move of a block) aborts with a per-block
   report.
3. `upstream_changes = align(blocks(B), blocks(U))`.
4. Decide every base unit by the merge matrix; decide every upstream-new
   unit as *take upstream*.
5. Build the merged document: **U's tree**, splicing REAPPLY/resolved-local
   texts by hash — under the splice/verify invariants below: splice is the
   only mutation, re-parse the rendered output and refuse to write if block
   structure moved.
6. Write atomically (temp file + rename).
7. Update `.cedit/base/<path>` to canonicalized U, rewrite manifest
   (including new conflicts), regenerate the overlay by aligning the new
   base against the new working copy.
8. Print the report: `reapplied / updated / conflicts / orphans` counts and
   each conflict's location (the heading trail).

Ordering rule: the working file is written **before** base/manifest. A
crash between the two leaves an already-merged L against the old B — the
next sync's `align(B, L)` just sees the merged result as local edits
against the old base and converges; the reverse order would record a sync
that never happened.

## CLI (POC surface — implemented in `cedit/cli.py`)

```bash
cedit snapshot <path> --from <upstream-file>   # start tracking; vendors the file if absent
cedit diff [<path>...] [--unified]             # the overlay (human view; --unified for git-style)
cedit sync [<path>...] [--from <dir-or-file>] [-n]   # the 3-way merge; --from defaults to
                                                     # each doc's recorded upstream
cedit status [<path>...]                       # per-doc edits, conflicts, base freshness
cedit resolve <path> <hash[:occ]> --take local|upstream | --show
```

Alongside them, and outside this surface, sits one **stateless** group —
implemented in `cedit/mdcli.py`, opening no `.cedit/` at all:

```bash
cedit md canonicalize [file|-] [-i | --check]  # the mdformat round-trip .cedit/base/ stores
cedit md ast [file|-] [--hashes] [--raw]       # the parse tree, indented
cedit md json [file|-] [--tokens | --tree] [--raw]   # the same, as JSON
cedit md from-json [file|-]                    # a --tokens stream back to Markdown
cedit md blocks [file|-] [--json]              # the edit blocks the merge keys on
```

It is a *view* on the frozen core below, not part of the model: nothing here
reads or writes state, so no rule in this document constrains it beyond the
exit codes. It exists because the *Reuse rules* make `mdcore/` unobservable —
see the user guide,
[`md` — stateless parser views](userguide/command-reference/md-parser-views.md).

One entry point, same subcommand set for a human and a future CI job. Exit
codes: 0 clean, 1 unresolved conflicts exist (a sync that recorded them, a
status that sees them), 2 errors. `md canonicalize --check` is the one
exception to that reading of 1, and a deliberately narrow one — it still means
*a human needs to look at this file*, never *this is broken*. A doc with open
conflicts refuses to sync again until they are resolved.

## Reuse rules — what must not fork

`cedit/mdcore/` holds the two modules every recorded hash is a function of —
`utils.py` (the pinned parser) and `tree_diff.py` (hashing, segmentation,
similarity) — and `requirements.txt` pins the stack they are assembled from.
They are frozen: not because they are sacred, but because a consumer's
`.cedit/` state is keyed to them, and a change nobody classified re-keys it
silently. Deliberate changes go through
[.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md) — how to
tell a hash-moving change from a hash-neutral one, the drift check that
decides it, and what consumers do when hashes moved. The invariants:

- **Parser**: `mdcore/utils.make_parser`, pinned stack, canonical
  round-trip. cedit adds no parser options. Every hash in `.cedit/` state
  is taken over it — moving a pin without re-validating moves every hash
  and turns the next sync into a wall of false conflicts.
- **Hashing/segmentation**: `mdcore.tree_diff`'s `hash_tree`, `is_unit` and
  `OPAQUE`, `_unit_source`, `ratio` and the thresholds — never re-derived,
  only consumed (`cedit/blocks.py`, `cedit/align.py`).
- **Splice/verify**: cedit's own, in `cedit/blocks.py` — outside the frozen core, and
  it must not drift from the hashing it splices around. Structure comes
  from the tree being spliced into; the only mutations are an `inline`
  token's children/content and an opaque token's `content` + `info`;
  replacements re-parse through `parse_inline`; whitespace collapses in
  table cells; the task-list checkbox token is carried across; every render
  re-parses its own output and refuses on a moved block structure.
- **Atomic writes**: cedit's own, in `cedit/store.py` — a temp file in the
  target directory plus `rename(2)`, never a direct write.

## Phases

1. **POC — built:** replacements only — inline units + opaque blocks. This
   fully covers the motivating zsh case (fences) plus prose tweaks. Single
   upstream file/dir as `--from`. The test suite (`tests/`) covers the
   whole merge matrix (edit / move / move+edit / delete / reflow /
   duplicate occurrences / table cells / front matter) plus the end-to-end
   CLI lifecycle: an upstream change to an *unedited* fence UPDATEs, to an
   *edited* fence CONFLICTs, and both `resolve` paths converge to a clean
   next sync.
2. **Structural local edits:** locally inserted blocks anchored to the
   hash of the preceding base unit (fallback: following unit, then heading
   trail); anchor retired upstream ⇒ ORPHAN. Local deletions recorded as
   `(hash, occurrence) → delete` overlay entries.
3. **Assisted rebase (optional):** the analog of a CAT tool's fuzzy
   match — on CONFLICT, an LLM ports the local adaptation onto the new
   upstream text ("re-apply *zsh* to the new command"), entering the overlay
   only as `review_status: machine` pending `resolve`. Same philosophy as
   every other gate here: assist, never silently decide.

## Non-goals

- Fetching upstream (git submodule, subtree, curl — the user's transport).
- Merging *upstream's* structure with local structure changes beyond the
  anchoring model above; cedit is not a general tree 3-way merge.
- Multi-consumer coordination (two machines editing the same vendored
  copy) — that's git's job on the consumer repo.
- **Understanding syntax the pinned parser does not have** — `$...$` /
  `$$...$$` LaTeX math above all. Teaching the parser that syntax would be a
  *parser identity* change — a hash move for every consumer, over a construct
  that already has a working spelling (a ```` ```math ```` fence round-trips
  byte for byte). Not understanding it is not a licence to damage it, though:
  canonicalisation would escape a backslash inside such a span
  (`$\rightarrow$` → `$\\rightarrow$`), which GitHub renders as a line break
  inside math, and no later stage could detect it — the block structure is
  unchanged and every hash would be taken over the rewritten text. So cedit
  **preserves** the span instead, by holding it out of the round-trip behind
  a sentinel and restoring it afterwards (`cedit/mathguard.py`;
  [Limits, stated plainly](userguide/help/limits.md)). Nothing keys on
  what is inside a span, and nothing
  renders it: it is carried, not understood. The handful of spans that
  cannot be located in the source to be held out — a table cell holding
  `\|` — are **warned about on stderr**, exit code untouched, which is the
  same gate philosophy as everywhere else here: surface it, never silently
  decide.
- **Making a table row mean more than the parser reads.** A GFM header row
  fixes the column count, and anything a body row carries past it — an
  annotation after the closing pipe, an extra cell — is discarded before
  cedit's tree exists. Teaching the parser otherwise is the same
  parser-identity change as the math case, and GitHub truncates those rows
  too. Again, not reading it is not a licence to lose it: cedit lifts the
  text out of the source before the parse and appends it back onto its own
  row after the render (`cedit/rowguard.py`;
  [Limits, stated plainly](userguide/help/limits.md)), so the bytes
  survive even though nothing keys on them. It is carried, not understood —
  and because it belongs to no block, it is not merged either: the merged
  document keeps the row upstream sent.
