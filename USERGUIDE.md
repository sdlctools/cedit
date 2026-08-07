# `cedit` user guide

A practical guide to `cedit/cli.py`, the command line that keeps your local
adaptations of vendored Markdown alive across upstream updates. This is the
*how-to*: worked examples, real output, and the flows you will actually run.
For the *why* behind the design, read [SPEC.md](SPEC.md); for a two-minute
overview, [README.md](README.md).

Every command and every block of output below was run for real — against this
repository or a throwaway directory — and pasted unedited.

![cedit compares document ASTs and tracks the changes between them](assets/ast-trees-comparison-and-changes-tracking.png)

**Contents**

1. [The mental model](#1-the-mental-model)
1. [Prerequisites](#2-prerequisites)
1. [The five subcommands](#3-the-five-subcommands)
1. [Five-minute tour](#4-five-minute-tour)
1. [Command reference](#5-command-reference)
1. [What cedit sees: blocks, hashes, keys](#6-what-cedit-sees-blocks-hashes-keys)
1. [The merge matrix in practice](#7-the-merge-matrix-in-practice)
1. [Flow: vendoring a document](#8-flow-vendoring-a-document)
1. [Flow: taking an upstream update](#9-flow-taking-an-upstream-update)
1. [Flow: a conflict, end to end](#10-flow-a-conflict-end-to-end)
1. [What alignment buys you](#11-what-alignment-buys-you)
1. [The `.cedit/` state directory](#12-the-cedit-state-directory)
1. [Limits, stated plainly](#13-limits-stated-plainly)
1. [Cookbook](#14-cookbook)
1. [Troubleshooting](#15-troubleshooting)
1. [Appendix](#16-appendix)

______________________________________________________________________

## 1. The mental model

Five commands over one tracked document:

```
   snapshot ──►  (you edit the file)  ──►  sync  ──►  (clean)
      │                   │                  │
      │                 diff                 └─► conflict ──► resolve ──► sync
      │            what have I changed?
      └─ start tracking                    status  (read-only, any time)
```

Three ideas explain almost everything.

**Three revisions, one merge.** Every tracked document has a *base* (**B**, the
upstream revision you last synced against, snapshotted under `.cedit/base/`), a
*local* copy (**L**, the file you edit in place), and an *upstream* (**U**, the
new revision you hand to `sync`). `sync` aligns L against B to learn what you
changed, aligns U against B to learn what upstream changed, and decides every
block by crossing the two. The merged document is always **U's structure** with
your texts spliced in.

**Blocks are content-addressed, and fences count.** A "block" is a paragraph, a
heading, a table cell — or a code fence, a raw HTML block, or the YAML front
matter. Its identity is a 16-hex-char Merkle hash of its canonical content, not
its position or line number. That is why a rewritten fence is a first-class
edit, why an upstream *move* of a block you edited costs nothing, and why
rewrapping a paragraph at a different width changes nothing at all.

**Nothing is ever silently clobbered.** When upstream changes the very block you
adapted, the working file keeps **your** text and the conflict is recorded with
all three versions. The document then refuses to sync again until you settle it
with `resolve`. There are no conflict markers in the file — `=======` is a
setext heading underline, so a marked-up Markdown file would stop parsing as the
document it was; conflicts live in `.cedit/manifest.json` instead.

______________________________________________________________________

## 2. Prerequisites

cedit runs from the root of the repository that holds your vendored copies —
a *different* repository from the one cedit itself lives in. Install it once:

```bash
pipx install cedit   # or: pip install cedit
cedit --help
```

Every example below is written as `cedit <subcommand>`. `python3 -m cedit
<subcommand>` is the same entry point with the same arguments, so use
whichever you prefer — the module form is what you want when cedit is
installed in a virtualenv you'd rather not activate:
`/path/to/venv/bin/python3 -m cedit …`.

**Install cedit into an environment of its own.** `pipx` above does that for
you; a dedicated virtualenv does the same. The reason is the pins below:
`mdcore/utils.make_parser` appends *every installed* mdformat parser
extension, so the set of mdformat plugins in the environment is part of the
parser identity. A shared environment carrying other mdformat plugins can
move the hashes in your `.cedit/` state even though cedit's own pinned
dependencies were honoured.

Working on cedit itself rather than using it? Install from a clone instead:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # the parsing stack, pinned EXACTLY
venv/bin/pip install -e .                  # puts `cedit` on the venv's path
venv/bin/python3 -m pytest                 # 105 tests, no network, <2s
```

**The pins are load-bearing.** `requirements.txt` pins `markdown-it-py`,
`mdit-py-plugins`, `mdformat`, `mdformat-gfm`, `mdformat-frontmatter`,
`mdformat-footnote` and `linkify-it-py` to exact versions. Every hash in `.cedit/` — base document
hashes, overlay keys, conflict keys — is taken over that one parser
configuration. A minor upgrade can change what the parser emits, which silently
moves every hash and turns your next sync into a wall of false conflicts.
Upgrade one pin at a time and run the suite.

**Run from the repository root.** Tracked documents are addressed by a path
relative to the root, and the state directory is resolved from the working
directory. Running from a subdirectory does not error — it just finds no state:

```console
$ cd sub && cedit status
nothing tracked
```

cedit never fetches anything. Getting upstream onto your disk — a git submodule,
a subtree, `curl`, a vendoring script — is your transport. `--from` takes a
directory that mirrors your document paths, or a single file.

______________________________________________________________________

## 3. The five subcommands

| Command | Reads | Writes | Exit codes |
| --- | --- | --- | --- |
| `snapshot` | the upstream file, the working copy if it exists | the working copy (if absent), `.cedit/` | 0, 2 |
| `diff` | base snapshot, working copy | nothing | 0, 2 |
| `sync` | base snapshot, working copy, upstream | the working copy, `.cedit/` | 0, 1, 2 |
| `status` | base snapshot, working copy, manifest | nothing | 0, 1, 2 |
| `resolve` | manifest, working copy | the working copy (`--take upstream` only), `.cedit/` | 0, 2 |

`diff` and `status` are read-only and safe at any moment. `sync` is the only
command that merges. `resolve` is the only command that can clear a conflict.

Alongside them sits `cedit md` — five *stateless* verbs that read no
`.cedit/` state and work on any Markdown file, tracked or not. They are not
part of the workflow above; they are how you look at what the parser sees.
[§5.7](#57-md--stateless-parser-views) covers them.

______________________________________________________________________

## 4. Five-minute tour

A complete round trip in a throwaway directory: vendor a skill, adapt it, take
two upstream revisions, hit a conflict, settle it. Copy-paste each block in
order, with the venv activated.

````bash
mkdir -p /tmp/cedit-tour/vendor/skills && cd /tmp/cedit-tour

cat > vendor/skills/deploy.md <<'EOF'
# Deploy skill

This skill takes a build from the artifact store and puts it on staging.

## Preflight

Run the healthcheck before anything else:

```bash
bash scripts/healthcheck.sh --strict
```

## Deploy

```bash
bash scripts/deploy.sh --env staging
```
EOF

cedit snapshot skills/deploy.md --from vendor/skills/deploy.md
````

```console
skills/deploy.md: tracking (base 9ef5a0dbdc298d85, from vendor/skills/deploy.md), 0 local edit(s) recorded
```

`vendor/` is your upstream mirror; `skills/deploy.md` is the document you are
going to own. It did not exist, so `snapshot` vendored it — the working copy now
holds the canonicalized upstream text, and `.cedit/` holds the base snapshot the
merge will remember.

Now adapt it. Your environment has no `bash`, so rewrite the healthcheck fence:

```bash
perl -0pi -e 's/```bash\nbash scripts\/healthcheck/```zsh\nzsh scripts\/healthcheck/' skills/deploy.md
cedit diff
```

```console
skills/deploy.md: 1 local edit(s)
[edit opaque fence] #7b47884c75de548e:0  sim=0.93
    ctx  : Preflight
    info : bash -> zsh
    base : bash scripts/healthcheck.sh --strict
    local: zsh scripts/healthcheck.sh --strict

```

One edit, on one fence, at one address. The `info : bash -> zsh` line is the
fence's info string — the ```` ```bash ```` marker itself is part of what you
edited, not decoration around it.

Upstream evolves: the intro gets a sentence, and the *other* fence gains a flag.

```bash
sed -i 's/puts it on staging./puts it on staging, then promotes it to production./' vendor/skills/deploy.md
sed -i 's/deploy.sh --env staging/deploy.sh --env staging --wait/' vendor/skills/deploy.md
cedit sync --from vendor
```

```console
skills/deploy.md: 1 edit(s) reapplied, 2 block(s) updated from upstream, no conflicts
```

Read that as: your zsh rewrite went back in, upstream's two changes came through,
nobody stepped on anybody. The file now has upstream's new prose, upstream's
`--wait`, and your `zsh` fence.

Now the interesting case. Upstream touches the very fence you rewrote:

```bash
sed -i 's/healthcheck.sh --strict/healthcheck.sh --strict --timeout 60/' vendor/skills/deploy.md
cedit sync --from vendor
echo "rc=$?"
```

```console
skills/deploy.md: 0 edit(s) reapplied, 0 block(s) updated from upstream, 1 conflict(s)
[CONFLICT opaque fence] #7b47884c75de548e:0
    ctx     : Preflight
    base    : bash scripts/healthcheck.sh --strict
    upstream: bash scripts/healthcheck.sh --strict --timeout 60
    local   : zsh scripts/healthcheck.sh --strict  (kept in the working file)
    resolve : cedit resolve skills/deploy.md 7b47884c75de548e:0 --take local|upstream

rc=1
```

Exit code 1 — "a human is needed", distinct from 2, "something is broken". Your
zsh line is still in the file; upstream's version is recorded, not applied. Keep
the adaptation:

```bash
cedit resolve skills/deploy.md 7b47884c75de548e --take local
cedit sync --from vendor
cedit status
```

```console
skills/deploy.md #7b47884c75de548e:0: kept local text — it is now an ordinary overlay edit against the new base
skills/deploy.md: up to date
skills/deploy.md: 1 local edit(s), 0 unresolved conflict(s); base d47b5d46bb5134d8 synced 2026-08-05T00:01:42Z (upstream: vendor)
```

That last state is the whole point. You did not just dismiss a conflict — the
adaptation was **re-keyed to the new upstream block**, so it is an ordinary
overlay edit again, and the next upstream revision that leaves that fence alone
will re-apply it without asking. This is the `git rerere` move.

______________________________________________________________________

## 5. Command reference

### 5.1 Global options

One global flag, and it goes **before** the subcommand:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--state-dir` | `.cedit` | state directory, relative to the working directory (ignored by `md`) |
| `-h`, `--help` | — | usage; also available per subcommand |

```console
$ cedit --help
usage: cedit [-h] [--state-dir STATE_DIR]
             {snapshot,diff,sync,status,resolve,md} ...

Keep local adaptations of vendored Markdown alive across upstream updates (see
SPEC.md).

positional arguments:
  {snapshot,diff,sync,status,resolve,md}
    snapshot            start tracking a document
    diff                show local edits against the base
    sync                3-way merge a new upstream revision in
    status              per-document overlay/conflict summary
    resolve             settle one recorded conflict
    md                  stateless parser views: canonicalize / ast / json /
                        blocks

options:
  -h, --help            show this help message and exit
  --state-dir STATE_DIR
                        state directory (default: .cedit); ignored by the
                        stateless `md` subcommands
```

`md` is the odd one out and §5.7 covers it: a group of stateless verbs that
never open `.cedit/`, which is why `--state-dir` does nothing for them.

`--state-dir` gives you a second, independent set of tracking state over the
same files — useful for a dry experiment you do not want in the committed
`.cedit/`:

```console
$ cedit --state-dir .cedit-alt status
nothing tracked
```

### 5.2 `snapshot`

Start tracking one document. Run once per document, ever.

```bash
cedit snapshot skills/deploy.md --from vendor/skills/deploy.md
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `doc` | — | positional, required: the document path, relative to the repo root |
| `--from` | — | **required**: the upstream *file* this copy is based on |

Two cases, and `snapshot` picks between them by whether the document already
exists on disk:

- **It does not exist** — the initial vendoring. The canonicalized upstream text
  is written as the working copy, and zero edits are recorded.
- **It exists** — you adapted your vendored copy before ever using cedit. The
  file is left exactly as it is, and the difference against upstream is recorded
  as your overlay:

```console
$ cedit snapshot G.md --from vendor/G.md
G.md: tracking (base 7f3d2b74871ef834, from vendor/G.md), 1 local edit(s) recorded
$ cedit diff
G.md: 1 local edit(s)
[edit opaque fence] #a77bdf7f48c7f708:0  sim=0.80
    ctx  : G
    info : bash -> zsh
    base : bash run.sh
    local: zsh run.sh
```

The line reads `tracking (base <doc-hash>, from <path>), N local edit(s)
recorded`. The doc hash is the Merkle root of the canonicalized base — the same
value `status` reports later, and the thing that tells you two documents are
literally the same revision.

`--from` here is a **file**, not a directory: this is the one command that has
no per-document path convention to lean on. The path is recorded in the manifest
and becomes the default `--from` for later syncs.

Snapshotting twice is an error, not a re-vendoring:

```console
$ cedit snapshot A.md --from vendor/A.md
A.md: already tracked — use `cedit sync` to take a new upstream revision
```

### 5.3 `diff`

Show what you have changed, relative to the base snapshot. Reads nothing but
`.cedit/base/` and your working copy; writes nothing at all.

```bash
cedit diff                      # every tracked document
cedit diff skills/deploy.md     # one document
cedit diff --unified            # git-style, for reviewers
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `docs...` | every tracked document | positional, repeatable: which documents to report |
| `--unified` | off | plain unified diff of canonical base vs. working copy |

The default view is per block:

```console
skills/deploy/SKILL.md: 1 local edit(s)
[edit opaque fence] #7b47884c75de548e:0  sim=0.93
    ctx  : Preflight
    info : bash -> zsh
    base : bash scripts/healthcheck.sh --strict
    local: zsh scripts/healthcheck.sh --strict
```

Line by line:

- **`<doc>: N local edit(s)`** — the count, followed by ` — in sync with base`
  when it is zero.
- **`[edit <kind> <node_type>] #<hash>:<occurrence>`** — `kind` is `opaque` (a
  fence, raw HTML, front matter, a horizontal rule) or `unit` (a heading,
  paragraph, or table cell). `node_type` is the markdown-it node. The `#…:…`
  part is the block's **address in the base**: content hash plus occurrence
  index. That address is what you pass to `resolve`.
- **`sim=0.93`** — how similar the two texts are, 0…1. It is omitted entirely
  when the score is 0, which happens on short blocks paired on *positional*
  evidence rather than textual similarity (see [§11](#11-what-alignment-buys-you)):

```console
G.md: 1 local edit(s)
[edit unit td] #5c6f9f76aa6e8e7f:0
    ctx  : G
    base : you
    local: the release manager
```

- **`ctx :`** — the heading trail above the block, joined with ` › `. This is
  how you find the block in a long document.
- **`info :`** — printed only when the fence info string changed, as
  `bash -> zsh`. The info string is part of the edited surface, which is why
  ```` ```bash ```` → ```` ```zsh ```` is a real edit and not a no-op.
- **`base :` / `local:`** — the two texts, clipped to 110 characters *around
  their first difference*, so an edit deep in a long block is still visible.

`--unified` gives reviewers the familiar syntax. It is a rendering of the same
overlay, never the stored form:

````console
$ cedit diff --unified
--- base/skills/deploy/SKILL.md
+++ skills/deploy/SKILL.md
@@ -11,8 +11,8 @@
 
 Run the healthcheck before anything else:
 
-```bash
-bash scripts/healthcheck.sh --strict
+```zsh
+zsh scripts/healthcheck.sh --strict
 ```
 
 If it exits non-zero, stop and fix the environment first.
````

`--unified` also keeps working when the block view cannot run — it compares text,
so a structural local change (§13) does not stop it. That makes it the tool for
*seeing* the drift the block view refuses to merge.

### 5.4 `sync`

The 3-way merge: take a new upstream revision, re-apply your overlay on top.

```bash
cedit sync --from vendor              # every tracked doc, upstream dir
cedit sync skills/deploy.md --from vendor/skills/deploy.md
cedit sync --from vendor --dry-run    # report, write nothing
cedit sync                            # each doc's recorded upstream
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `docs...` | every tracked document | positional, repeatable: which documents to sync |
| `--from` | each document's recorded upstream | upstream **directory** (mirroring document paths) or a single **file** |
| `-n`, `--dry-run` | off | merge and report, write nothing |

`--from` resolution, per document: a directory is joined with the document's own
relative path (`vendor` + `skills/deploy.md` → `vendor/skills/deploy.md`); a file
is used as-is. Passing a file while several documents are in scope is refused,
because one file cannot be the upstream of two documents:

```console
$ cedit sync --from vendor/skills/A.md
--from is a file but several documents are being synced — pass a directory, or one document
$ cedit sync skills/A.md --from vendor/skills/A.md
skills/A.md: up to date
```

Whatever you pass is **recorded** as that document's upstream and becomes the
default for the next bare `sync`.

The report line is one per document. When upstream's canonical text equals the
base, nothing is computed at all:

```console
skills/A.md: up to date
skills/B.md: 1 edit(s) reapplied, 1 block(s) updated from upstream, no conflicts
```

The counters, in the order they can appear:

| Counter | Counts |
| --- | --- |
| `N edit(s) reapplied` | your edits that were spliced into upstream's tree |
| `N block(s) updated from upstream` | blocks upstream changed that you had not touched |
| `N inserted` | blocks upstream added (omitted when zero) |
| `N removed` | blocks upstream deleted that you had not touched (omitted when zero) |
| `N moved` | blocks upstream moved without changing (omitted when zero) |
| `N conflict(s)` / `no conflicts` | blocks both sides changed, plus orphans |

Blocks nobody touched are not reported at all, so a revision that only reflows
text reports zeros across the board. A dry run appends its own marker:

```console
skills/deploy/SKILL.md: 1 edit(s) reapplied, 2 block(s) updated from upstream, no conflicts [dry run — nothing written]
```

`--dry-run` writes nothing whatsoever — not the working copy, not the base
snapshot, not the manifest. Use it to see what an upstream revision would do
before you let it near a dirty working tree.

Every conflict is then printed in full (see [§10](#10-flow-a-conflict-end-to-end)),
and the command exits 1. Errors — an upstream file that does not exist, a
document with conflicts still open, a local structural change — exit 2, and 2
wins over 1 when a run hits both.

**Write ordering.** The working file is written *before* the base snapshot and
manifest, deliberately. A crash between the two leaves an already-merged working
copy against the old base, which the next sync simply re-derives as local edits
and converges on. The reverse order would record a sync that never happened.

### 5.5 `status`

Per-document summary. Read-only, no upstream needed, safe at any time — this is
the command a CI job runs.

```bash
cedit status
cedit status skills/deploy.md
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `docs...` | every tracked document | positional, repeatable: which documents to report |

```console
$ cedit status
skills/A.md: 1 local edit(s), 0 unresolved conflict(s); base 191ead45bd56de1e synced 2026-08-05T00:00:20Z (upstream: vendor/skills/A.md)
skills/B.md: 1 local edit(s), 0 unresolved conflict(s); base 8949953623be4edb synced 2026-08-05T00:00:20Z (upstream: vendor/skills/B.md)
```

- **`N local edit(s)`** — recomputed live from the base and your working copy,
  not read from `overlay.json`. It is always current, even if you edited the file
  five seconds ago.
- **`N unresolved conflict(s)`** — read from the manifest. Any document with a
  non-zero count makes the command exit **1**.
- **`base <hash> synced <timestamp>`** — which upstream revision you are merged
  against, and when. Two checkouts reporting the same base hash for a document
  are on the same upstream revision.
- **`(upstream: …)`** — the recorded `--from`, or `unset`.

With nothing tracked at all, `status` is a clean no-op — exit **0**, unlike
`diff` and `sync`, which treat it as an error:

```console
$ cedit status
nothing tracked
```

A document with a local structural change reports that in place of the edit
count — and, note, does **not** change the exit code:

```console
$ cedit status; echo "rc=$?"
skills/deploy/SKILL.md: STRUCTURAL DRIFT (see `cedit diff`), 0 unresolved conflict(s); base 1325c1dfe3186353 synced 2026-08-04T23:58:47Z (upstream: vendor/skills/deploy/SKILL.md)
rc=0
```

Only conflicts drive exit 1. If you gate CI on drift as well, grep the output
for `STRUCTURAL DRIFT` or run `diff`, which exits 2 on it.

### 5.6 `resolve`

Settle exactly one recorded conflict.

```bash
cedit resolve skills/deploy.md 7b47884c75de548e --show
cedit resolve skills/deploy.md 7b47884c75de548e --take local
cedit resolve skills/deploy.md 7b47884c75de548e:0 --take upstream
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `doc` | — | positional, required: the document |
| `key` | — | positional, required: conflict key — `<hash>` or `<hash>:<occurrence>` |
| `--take` | none | `local` keeps your text, `upstream` splices upstream's |
| `--show` | off | print all three versions in full, change nothing |

**The key** is what `sync` printed on the conflict line, `<hash>:<occurrence>`.
Any unambiguous prefix works, so the bare hash is normally enough. Ambiguity is
refused rather than guessed:

```console
$ cedit resolve G.md f --take local
'f' is ambiguous: f78f8a455566e4e5:0, f86b66327dc68b6d:0
$ cedit resolve skills/deploy/SKILL.md 5 --take local
no conflict matches '5' (open ones: 2a37ee9b554dd0c8:0)
```

**`--show`** (and a bare `resolve` with no `--take`, which does the same) prints
the three versions unclipped, so you can read a long block in full before
deciding:

```console
$ cedit resolve GUIDE.md 7b47884c75de548e --show
[CONFLICT opaque fence] #7b47884c75de548e:0
    ctx     : Preflight
    base    : bash scripts/healthcheck.sh --strict

    upstream: bash scripts/healthcheck.sh --strict --timeout 60

    local   : zsh scripts/healthcheck.sh --strict
  (kept in the working file)
    resolve : cedit resolve GUIDE.md 7b47884c75de548e:0 --take local|upstream
```

(The blank lines are the blocks' own trailing newlines — `--show` is verbatim,
where the `sync` report is clipped to one line per version.)

**`--take local`** keeps what is already in the working file. Nothing is
written to the document; the conflict record is dropped and the overlay is
re-derived, which re-keys your text to the **new** upstream block:

```console
$ cedit resolve skills/deploy/SKILL.md 7b47884c75de548e --take local
skills/deploy/SKILL.md #7b47884c75de548e:0: kept local text — it is now an ordinary overlay edit against the new base
```

**`--take upstream`** splices upstream's recorded text into the working file,
re-renders it (verifying block structure survived), and drops the record:

```console
$ cedit resolve skills/deploy/SKILL.md 7b47884c75de548e:0 --take upstream
skills/deploy/SKILL.md #7b47884c75de548e:0: upstream text taken
```

After it, the block matches upstream exactly, so your overlay for that block is
gone — `status` reports one fewer local edit.

Two refusals worth knowing:

- On an **orphan** — upstream deleted the block your edit lived on — `--take
  local` cannot be honoured, because keeping a block upstream removed is a
  *structural* edit, which is phase 2 (§13). Your text stays recorded in the
  manifest:

```console
$ cedit resolve skills/deploy/SKILL.md 2a37ee9b554dd0c8 --take local
skills/deploy/SKILL.md #2a37ee9b554dd0c8:0: upstream deleted this block — keeping it would be a structural edit (phase 2). Its text is preserved in the manifest; `--take upstream` accepts the deletion.
$ cedit resolve skills/deploy/SKILL.md 2a37ee9b554dd0c8 --take upstream
skills/deploy/SKILL.md #2a37ee9b554dd0c8:0: upstream deletion accepted
```

- If you **hand-edited** the conflicted block since the sync, `--take upstream`
  can no longer find it as recorded and refuses rather than splicing over your
  work:

```console
$ cedit resolve GUIDE.md 7b47884c75de548e --take upstream
GUIDE.md #7b47884c75de548e:0: the conflicted block is no longer in the file as recorded (edited since?) — fix the text by hand, then `resolve --take local`
```

That is not a dead end — it is the *third* resolution, and the intended one for
a real conflict: write the merged text yourself, then `--take local` to accept
what you wrote (see [§10](#10-flow-a-conflict-end-to-end)).

### 5.7 `md` — stateless parser views

Everything above is stateful: it opens `.cedit/` and talks about tracked
documents. `cedit md` is the opposite — a file (or `-` for stdin) in, stdout
out, no state read or written, `--state-dir` ignored. Use it to see what the
parser does to a document, whether or not that document is tracked at all.

| Verb | Does |
| --- | --- |
| `md canonicalize [file]` | print the mdformat round-trip — the exact bytes `.cedit/base/` stores |
| `md ast [file]` | print the parse tree, indented |
| `md json [file]` | the same parse as JSON — the flat token stream, or `--tree` |
| `md from-json [file]` | render a token stream from `md json` back to Markdown |
| `md blocks [file]` | print the edit blocks the merge keys on, with their hashes |

Exit codes: `0`, `2` for errors, and `1` from `canonicalize --check` only.

#### `md canonicalize`

Every example below runs against `vendor/skills/deploy.md` from the
[§4 tour](#4-five-minute-tour), or against a file cut out of it, so the hashes
are the same ones you saw there.

```console
$ cedit md canonicalize vendor/skills/deploy.md > canonical.md   # to stdout
$ cedit md canonicalize -i skills/deploy.md                      # rewrite atomically
skills/deploy.md: already canonical
```

A tracked document reports `already canonical` because `snapshot` wrote it
canonical in the first place — `-i` earns its keep on documents cedit has never
seen. `messy.md` below is the tour's document as someone might have hand-written
it — setext headings, and the healthcheck indented rather than fenced:

```bash
cat > messy.md <<'EOF'
Deploy skill
============

Preflight
---------

    bash scripts/healthcheck.sh --strict
EOF
```

````console
$ cedit md canonicalize messy.md
# Deploy skill

## Preflight

```
bash scripts/healthcheck.sh --strict
```
$ cp messy.md scratch.md
$ cedit md canonicalize -i scratch.md
scratch.md: canonicalised
$ cedit md canonicalize -i scratch.md
scratch.md: already canonical
````

`--check` writes nothing at all and exits **1** when the input is not already
canonical — the shape a CI job or a pre-commit hook wants
([§14](#14-cookbook) has the gate):

```console
$ cedit md canonicalize --check messy.md
messy.md: not canonical
$ echo $?
1
```

`-i` and `--check` are mutually exclusive, and `-i` needs a real file — the
file argument defaults to stdin, where there is nothing to rewrite in place
([§15](#15-troubleshooting)).

`$...$` math survives all three modes byte for byte, so a document whose only
unusual feature is a `$\rightarrow$` is simply canonical — stdout stays the
canonical bytes and nothing else:

```console
$ cedit md canonicalize --check docs/GH-CLI.md
$ echo $?
0
```

See [§13](#13-limits-stated-plainly) for the one construct that is still
rewritten, and what to write instead of it.

#### `md blocks`

The one to reach for when a key is a mystery. It prints the same
`<hash>:<occurrence>` addresses a conflict report prints and `resolve` takes —
note `#7b47884c75de548e:0`, the fence the tour adapts and later conflicts on.
The addresses are those of the document you point it at, so to read the ones
cedit is keyed to, point it at the base snapshot (`.cedit/base/<doc>`) or at
the upstream revision that base was taken from:

```console
$ cedit md blocks vendor/skills/deploy.md
vendor/skills/deploy.md: 7 block(s), doc 9ef5a0dbdc298d85
[block unit heading] #21c9f999ed623912:0
    text : Deploy skill

[block unit paragraph] #84cd52d314d7df83:0
    ctx  : Deploy skill
    text : This skill takes a build from the artifact store and puts it on staging.

[block unit heading] #bd367afe9f8a1d46:0
    ctx  : Deploy skill
    text : Preflight

[block unit paragraph] #806bee9eb45a7cc0:0
    ctx  : Preflight
    text : Run the healthcheck before anything else:

[block opaque fence] #7b47884c75de548e:0
    ctx  : Preflight
    info : bash
    text : bash scripts/healthcheck.sh --strict

[block unit heading] #ac2aee0b1c35c287:0
    ctx  : Preflight
    text : Deploy

[block opaque fence] #300a5f90b873e850:0
    ctx  : Deploy
    info : bash
    text : bash scripts/deploy.sh --env staging
```

The `doc 9ef5a0dbdc298d85` on the first line is the document hash `snapshot`
recorded in the tour. The `text` lines are clipped to keep the dump skimmable;
`--json` gives the same content machine-readably, with every block's text
untruncated — here, the one block the tour goes on to adapt:

```console
$ cedit md blocks --json vendor/skills/deploy.md \
    | jq '.blocks[] | select(.key == "7b47884c75de548e:0")'
{
  "key": "7b47884c75de548e:0",
  "hash": "7b47884c75de548e",
  "occurrence": 0,
  "kind": "opaque",
  "node_type": "fence",
  "info": "bash",
  "context": "Preflight",
  "text": "bash scripts/healthcheck.sh --strict\n"
}
```

The top level is `{"doc_hash": …, "blocks": [ … ]}`, one object per block in
document order, with `hash` and `occurrence` split out beside the `key` that
joins them. `text` is the block's exact text, trailing newline and all — the
`ctx` of the human dump is `context`, the heading trail the block sits under.

#### `md ast` and `md json`

`md ast` marks which nodes are blocks (`[unit]` / `[opaque]`) and, with
`--hashes`, annotates every node with its Merkle hash. Non-block nodes
(`inline`, `text`) are hashed too — only the marked ones can carry an edit:

```console
$ cedit md ast --hashes vendor/skills/deploy.md
heading h1 [unit] #21c9f999ed623912
  inline #ab6b185c940f4549 "Deploy skill"
    text #e748d4cb302780c9 "Deploy skill"
paragraph p [unit] #84cd52d314d7df83
  inline #9dfe68ce256805b3 "This skill takes a build from the artifact store and puts it…"
    text #db19acb54f85b5c6 "This skill takes a build from the artifact store and puts it…"
heading h2 [unit] #bd367afe9f8a1d46
  inline #73670a1f9db979d3 "Preflight"
    text #418698cd26d4a38c "Preflight"
paragraph p [unit] #806bee9eb45a7cc0
  inline #767ec645d62c94a1 "Run the healthcheck before anything else:"
    text #013477f31375a242 "Run the healthcheck before anything else:"
fence code info=bash [opaque] #7b47884c75de548e "bash scripts/healthcheck.sh --strict"
heading h2 [unit] #ac2aee0b1c35c287
  inline #999cc16acd1eb9fb "Deploy"
    text #31d6651178022693 "Deploy"
fence code info=bash [opaque] #300a5f90b873e850 "bash scripts/deploy.sh --env staging"
```

Both canonicalise first by default, so the hashes shown are the hashes
`.cedit/` records. `--raw` parses the file exactly as it sits on disk, and
diffing the two is how you see what the round trip changed — on `messy.md`
from above:

```console
$ diff <(cedit md ast --raw --hashes messy.md) <(cedit md ast --hashes messy.md)
7c7
< code_block code [opaque] #6b17a57843ce0f7a "bash scripts/healthcheck.sh --strict"
---
> fence code [opaque] #e236e87c672f4a83 "bash scripts/healthcheck.sh --strict"
```

One line, out of seven. The setext headings are *not* on it: `Deploy skill`
underlined with `====` and `# Deploy skill` are the same node with the same own
text, so they hash identically — `#21c9f999ed623912`, the same hash the tour
prints. That is [§6](#6-what-cedit-sees-blocks-hashes-keys)'s "formatting churn
is free", measured. The indented code block is not churn: the round trip makes
it a *fence*, a different node type with a different hash, so the address cedit
will key it by is `#e236e87c672f4a83` and nothing in the file as written says
so. (`md blocks` has no `--raw`: raw hashes would match nothing in any
manifest.)

`md json` emits the flat markdown-it token stream by default — the same parse
as `md ast`, without the tree. The tour's Preflight fence, on its own:

```bash
sed -n '9,11p' vendor/skills/deploy.md > fence.md
```

````console
$ cat fence.md
```bash
bash scripts/healthcheck.sh --strict
```
$ cedit md json fence.md
[
  {
    "type": "fence",
    "tag": "code",
    "nesting": 0,
    "attrs": null,
    "map": [
      0,
      3
    ],
    "level": 0,
    "children": null,
    "content": "bash scripts/healthcheck.sh --strict\n",
    "markup": "```",
    "info": "bash",
    "meta": {},
    "block": true,
    "hidden": false
  }
]
````

One block, one token, every field markdown-it needs to render it back —
including `markup`, which the hash ignores and the renderer does not. That is
what makes the shape **lossless**, and it is the shape `md from-json` consumes.
`--tokens` spells that default out, for a pipeline that would rather say which
shape it means than rely on which one is default:

```console
$ diff <(cedit md json fence.md) <(cedit md json --tokens fence.md)
$ echo $?
0
```

`--tree` gives a nested shape instead, with `hash` and `kind` per node — the
same information `md ast --hashes` prints, addressable by a JSON tool. Take the
Preflight heading and its fence:

```bash
sed -n '5p;9,11p' vendor/skills/deploy.md > preflight.md
```

```console
$ cedit md json --tree preflight.md
{
  "type": "root",
  "children": [
    {
      "type": "heading",
      "tag": "h2",
      "info": "",
      "content": "",
      "hash": "bd367afe9f8a1d46",
      "kind": "unit",
      "children": [
        {
          "type": "inline",
          "tag": "",
          "info": "",
          "content": "Preflight",
          "hash": "73670a1f9db979d3",
          "children": [
            {
              "type": "text",
              "tag": "",
              "info": "",
              "content": "Preflight",
              "hash": "418698cd26d4a38c",
              "children": []
            }
          ]
        }
      ]
    },
    {
      "type": "fence",
      "tag": "code",
      "info": "bash",
      "content": "bash scripts/healthcheck.sh --strict\n",
      "hash": "7b47884c75de548e",
      "kind": "opaque",
      "children": []
    }
  ]
}
```

The hashes are the tour's, block identity being a property of the block and not
of the file it was cut from. `kind` is present only on the nodes that can carry
an edit, which makes `.. | select(.kind?)` the whole block list — and since
both shapes take `--raw` on the same terms as `md ast`, that is the round trip's
effect on block identity in two lines:

```console
$ cedit md json --raw --tree messy.md | jq -r '.. | select(.kind?) | "\(.hash) \(.kind) \(.type)"'
21c9f999ed623912 unit heading
bd367afe9f8a1d46 unit heading
6b17a57843ce0f7a opaque code_block
$ cedit md json --tree messy.md | jq -r '.. | select(.kind?) | "\(.hash) \(.kind) \(.type)"'
21c9f999ed623912 unit heading
bd367afe9f8a1d46 unit heading
e236e87c672f4a83 opaque fence
```

It reads better than the token stream, but it is for inspection **only** —
`from-json` takes the token stream, not the tree, and says so if you hand it
the wrong one.

#### `md from-json`

The inverse of `md json`: a token stream in, Markdown out. Feed it the file
from above and you get the fence back, byte for byte:

````console
$ cedit md json fence.md | cedit md from-json
```bash
bash scripts/healthcheck.sh --strict
```
````

Which is the point — the pair is a lossless round trip, so it composes into a
check that the parser can rebuild what it read:

```console
$ cedit md json vendor/skills/deploy.md | cedit md from-json \
    | diff - <(cedit md canonicalize vendor/skills/deploy.md)
$ echo $?
0
```

Empty diff, exit 0: tokens → Markdown → the same canonical bytes `.cedit/base/`
would hold. It reads a file or stdin like every other verb, so the stream can
come from anywhere — an `md json` you filtered, or one you generated. What it
will not take is the `--tree` shape ([§15](#15-troubleshooting) has the error).

______________________________________________________________________

## 6. What cedit sees: blocks, hashes, keys

A document is a flat sequence of **edit blocks** in document order. There are two
kinds, and both diff, overlay and merge identically:

| Kind | Node types | What the text is |
| --- | --- | --- |
| `unit` | `heading`, `paragraph`, `th`, `td` | the inline source of the block |
| `opaque` | `fence`, `code_block`, `html_block`, `front_matter`, `hr` | the token's own content (plus the fence info string) |

The `unit` set is exactly `tree_diff`'s translation units. The `opaque` set is
cedit's addition: to a translator a code fence is never translated, so it is
just copied — here it is the *motivating* edit, so it is a first-class block
with its own identity.

Nothing in this section has to be taken on trust: `cedit md blocks <file>`
prints precisely what it describes — every block's kind, node type, hash,
occurrence and heading context — for any Markdown file, tracked or not, and
`cedit md canonicalize` prints the canonical form the hashes are taken over.
[§5.7](#57-md--stateless-parser-views) is the reference for both; running them
against a document as you read this is the fastest way to make the rest
concrete.

**Identity is a hash.** Each block carries the 16-hex-char Merkle hash the
vendored `tree_diff.hash_tree` assigns over the canonicalized document.
Everything downstream is keyed by it: the overlay, the conflicts, the `resolve`
argument.

**Duplicates are disambiguated by occurrence.** Two byte-identical fences in one
document have the same hash, so a block's full address is
`<hash>:<occurrence>`, occurrence counted in document order from 0. That is what
lets you adapt just one copy of a repeated command:

```console
RUNBOOK.md: 2 local edit(s)
[edit opaque fence] #2b8e761f4dae633c:1  sim=0.67
    ctx  : Production
    base : bash scripts/deploy.sh
    local: bash scripts/deploy.sh --env production --confirm

[edit unit td] #286d36272b08407b:0  sim=0.83
    ctx  : Production
    base : release manager
    local: release manager + SRE
```

The `:1` says: the *second* of the two identical `bash scripts/deploy.sh` fences.
(That positional half of the address has a sharp edge when upstream reorders —
see [§11](#11-what-alignment-buys-you).)

**Canonicalization comes first.** Before anything is hashed, the document goes
through an `mdformat` round trip. This is why formatting churn is free — and why
your working copy may be reformatted the moment you `snapshot` it. A vendored
table written with `| --- |` separators comes back canonicalized:

```console
| Step | Owner | Blocking |
| -- | -- | -- |
| preflight | release engineer | yes |
```

That is the canonical form, once, on the first snapshot. It does not keep
changing.

**Front matter is one block.** Editing a single key overlays the whole front
matter, and an upstream change to any *other* key in it is a conflict on the
whole block:

```console
$ cedit diff
SKILL.md: 1 local edit(s)
[edit opaque front_matter] #3989fd03ddc7beae:0  sim=0.89
    base : …ame: deploy version: 1 model: sonnet
    local: …ame: deploy version: 1 model: opus

$ cedit sync --from vendor
SKILL.md: 0 edit(s) reapplied, 0 block(s) updated from upstream, 1 conflict(s)
[CONFLICT opaque front_matter] #3989fd03ddc7beae:0
    base    : name: deploy version: 1 model: sonnet
    upstream: name: deploy version: 2 model: sonnet
    local   : name: deploy version: 1 model: opus  (kept in the working file)
    resolve : cedit resolve SKILL.md 3989fd03ddc7beae:0 --take local|upstream
```

You changed `model`, upstream changed `version`, and the two never touched — but
the block is the unit, so it conflicts. Splitting front matter per key is future
work; until then, expect front-matter edits to need a hand-merge (`--show`, edit,
`--take local`) whenever upstream touches that block. `ctx` is empty here because
front matter sits above every heading.

______________________________________________________________________

## 7. The merge matrix in practice

`sync` decides every block of the **base** by crossing two questions: what did
upstream do to it, and did you edit it?

| Upstream did | You edited it | Outcome | In the report |
| --- | --- | --- | --- |
| nothing | no | nothing to do | (not counted) |
| nothing, or moved it verbatim | **yes** | **REAPPLY** — your text is spliced at its new position | `N edit(s) reapplied` |
| changed it | no | **UPDATE** — upstream's text stands | `N block(s) updated from upstream` |
| changed it | **yes** | **CONFLICT** — your text stays in the file, all three recorded | `N conflict(s)` + a `[CONFLICT …]` block |
| deleted it | no | it is simply gone | `N removed` |
| deleted it | **yes** | **ORPHAN** — a conflict flavour | `N conflict(s)` + an `[ORPHAN …]` block |
| added a new block | — | upstream's block is taken | `N inserted` |

Two consequences worth internalising:

**The structure is always upstream's.** The merged document is U's tree with
your texts spliced into it. Nothing is assembled from fragments, so upstream's
section order, new sections and deletions all arrive intact — and the render is
re-parsed and compared before it is written, so a splice that would corrupt block
structure is refused rather than shipped.

**A conflict is narrow.** It is one block, not one file. Every *other* block in
the same document merges normally in that same run; the conflict just parks one
decision. What it does block is the *next* sync of that document, so you can
never merge against a base you never accepted:

```console
$ cedit sync --from vendor; echo "rc=$?"
skills/deploy/SKILL.md: 1 unresolved conflict(s) — resolve them before syncing again
rc=2
```

______________________________________________________________________

## 8. Flow: vendoring a document

You have a file from somewhere else and you want to own a local variant of it.

```bash
# 1. get upstream onto disk — your transport, not cedit's job
mkdir -p vendor/skills && cp ~/upstream-repo/skills/deploy.md vendor/skills/

# 2. start tracking; this vendors the file if it does not exist yet
cedit snapshot skills/deploy.md --from vendor/skills/deploy.md

# 3. adapt the working copy in your editor, then check what you did
cedit diff

# 4. commit BOTH the document and the state
git add skills/deploy.md .cedit
git commit -m "vendor the deploy skill, adapted for zsh"
```

Step 4 is not optional. `.cedit/base/` *is* the merge's memory: without the base
snapshot there is no third revision, and a later sync cannot tell your edits
apart from upstream's. Committing it is what makes the next update work on a
teammate's checkout and in CI.

If your vendoring script re-copies the whole upstream tree, keep `vendor/` in the
repo too (or regenerate it before each sync). `--from` needs to point at
something that exists at sync time.

______________________________________________________________________

## 9. Flow: taking an upstream update

The day-to-day loop:

```bash
# 1. refresh your upstream mirror — again, your transport
git -C vendor pull        # or a submodule update, or a re-copy

# 2. look before you leap
cedit sync --from vendor --dry-run

# 3. do it
cedit sync --from vendor

# 4. read what changed, in the language of your own adaptations
cedit diff
git diff skills/

# 5. commit the document and the state together
git add skills .cedit && git commit -m "sync skills from upstream"
```

Exit code 0 means it merged clean. Exit code 1 means one or more conflicts were
recorded — jump to [§10](#10-flow-a-conflict-end-to-end). Exit code 2 means
nothing merged; read the message.

In CI, the useful gate is `status`, which needs no upstream at all:

```bash
cedit status || echo "conflicts are open in this branch"
```

Exit 1 there means "a human must decide"; exit 2 means the state itself is
broken (a missing base snapshot, usually an incomplete commit).

______________________________________________________________________

## 10. Flow: a conflict, end to end

The complete lifecycle, run for real. Setup: a vendored skill, a fence rewritten
for zsh, and an upstream revision that touches that same fence.

**1. The sync reports it and exits 1.**

```console
$ cedit sync --from vendor; echo "rc=$?"
skills/deploy/SKILL.md: 0 edit(s) reapplied, 0 block(s) updated from upstream, 1 conflict(s)
[CONFLICT opaque fence] #7b47884c75de548e:0
    ctx     : Preflight
    base    : bash scripts/healthcheck.sh --strict
    upstream: bash scripts/healthcheck.sh --strict --timeout 60
    local   : zsh scripts/healthcheck.sh --strict  (kept in the working file)
    resolve : cedit resolve skills/deploy/SKILL.md 7b47884c75de548e:0 --take local|upstream

rc=1
```

The rest of the document merged. The working file holds **your** text — the
`(kept in the working file)` marker is literal — and upstream's version is
recorded, not applied.

**2. Everything is in the state, and the document is fenced off.**

```console
$ cedit status; echo "rc=$?"
skills/deploy/SKILL.md: 1 local edit(s), 1 unresolved conflict(s); base c27422f7d48bd272 synced 2026-08-04T23:57:54Z (upstream: vendor)
rc=1
$ cedit sync --from vendor; echo "rc=$?"
skills/deploy/SKILL.md: 1 unresolved conflict(s) — resolve them before syncing again
rc=2
```

The manifest carries all three texts, so resolution never needs history
spelunking:

```json
"conflicts": {
  "7b47884c75de548e:0": {
    "reason": "conflict",
    "kind": "opaque",
    "node_type": "fence",
    "context": "Preflight",
    "base_text": "bash scripts/healthcheck.sh --strict\n",
    "base_info": "bash",
    "local_text": "zsh scripts/healthcheck.sh --strict\n",
    "local_info": "zsh",
    "upstream_text": "bash scripts/healthcheck.sh --strict --timeout 60\n",
    "upstream_info": "bash"
  }
}
```

**3. Read all three in full.**

```bash
cedit resolve skills/deploy/SKILL.md 7b47884c75de548e --show
```

**4. Decide.** There are three real answers.

*Keep the adaptation* — upstream's change does not matter to you:

```console
$ cedit resolve skills/deploy/SKILL.md 7b47884c75de548e --take local
skills/deploy/SKILL.md #7b47884c75de548e:0: kept local text — it is now an ordinary overlay edit against the new base
```

Look at what that did to the overlay. Before, your edit was keyed to the old
block `7b47884c75de548e` with `base_text` ending `--strict`; after, it is keyed
to upstream's **new** block and carries upstream's new text as its base:

```json
{
  "kind": "opaque",
  "node_type": "fence",
  "hash": "ee1e29c213192d2c",
  "occurrence": 0,
  "context": "Preflight",
  "base_text": "bash scripts/healthcheck.sh --strict --timeout 60\n",
  "base_info": "bash",
  "local_text": "zsh scripts/healthcheck.sh --strict\n",
  "local_info": "zsh"
}
```

That is the `git rerere` move: the same conflict will not be raised twice.

*Take upstream* — their change supersedes yours:

```console
$ cedit resolve skills/deploy/SKILL.md 7b47884c75de548e:0 --take upstream
skills/deploy/SKILL.md #7b47884c75de548e:0: upstream text taken
$ cedit status
skills/deploy/SKILL.md: 0 local edit(s), 0 unresolved conflict(s); base c27422f7d48bd272 synced 2026-08-04T23:58:11Z (upstream: vendor)
```

The fence in the file is now upstream's, and your overlay for it is gone.

*Merge both by hand* — the usual answer for a real conflict. Edit the block in
your editor to say what you actually want (here: zsh **and** upstream's new
flag), then accept what you wrote. (This run used a bare `GUIDE.md` holding the
same conflicted fence; the shape is identical.)

```console
$ cedit resolve GUIDE.md 7b47884c75de548e --take local
GUIDE.md #7b47884c75de548e:0: kept local text — it is now an ordinary overlay edit against the new base
$ cedit status
GUIDE.md: 1 local edit(s), 0 unresolved conflict(s); base 9e36dbe0b336f3bc synced 2026-08-05T00:00:38Z (upstream: vendor)
```

```json
{
  "hash": "ee1e29c213192d2c",
  "base_text": "bash scripts/healthcheck.sh --strict --timeout 60\n",
  "base_info": "bash",
  "local_text": "zsh scripts/healthcheck.sh --strict --timeout 60\n",
  "local_info": "zsh"
}
```

The hand-merged text is now the overlay, keyed to upstream's current block. Note
that `--take upstream` would have *refused* at this point — the block no longer
matches what was recorded — which is exactly the safety you want after editing by
hand.

**5. Confirm and commit.** Whichever branch you took, the document is clean and
syncs again:

```console
$ cedit sync --from vendor
skills/deploy/SKILL.md: up to date
```

```bash
git add skills .cedit && git commit -m "sync + resolve: keep the zsh preflight"
```

**Orphans.** The other conflict flavour: upstream deleted a block you had edited.

```console
$ cedit sync --from vendor; echo "rc=$?"
skills/deploy/SKILL.md: 0 edit(s) reapplied, 0 block(s) updated from upstream, 1 conflict(s)
[ORPHAN unit paragraph] #2a37ee9b554dd0c8:0
    ctx     : Preflight
    base    : If it exits non-zero, stop and fix the environment first.
    upstream: (deleted)
    local   : If it exits non-zero, page the on-call engineer before doing anything else.
    resolve : cedit resolve skills/deploy/SKILL.md 2a37ee9b554dd0c8:0 --take local|upstream

rc=1
```

Only `--take upstream` (accept the deletion) is available; `--take local` is
refused, because re-inserting a block upstream removed is a structural edit
(§13). Your text is preserved in the manifest either way — copy it somewhere
before accepting if you still want it.

______________________________________________________________________

## 11. What alignment buys you

The alignment is LCS over Merkle hashes, then greedy similarity pairing inside
each changed window, then a global pass for moves, then a fuzzy pass for blocks
that moved *and* changed. Concretely:

**Upstream moves cost nothing.** Here upstream swapped two whole sections and
reworded a paragraph; the local edit was a zsh rewrite of the production fence.

```console
$ cedit sync --from vendor
RUNBOOK.md: 1 edit(s) reapplied, 0 block(s) updated from upstream, 1 inserted, 1 removed, 2 moved, no conflicts
```

````markdown
# Runbook

## Production

Deploy to production:

```zsh
zsh scripts/deploy.sh --env production --confirm
```

## Staging

Deploy to staging, which is safe to re-run
as often as you like:

```bash
bash scripts/deploy.sh --env staging
```
````

The adaptation followed its block into the new section order. The
`1 inserted, 1 removed` pair is upstream's rewritten staging paragraph: too
different from its predecessor to be paired as an edit, so it reads as a delete
plus an insert. Since you had not edited it, the outcome is identical either
way — upstream's text stands.

**Reflows cost nothing.** Rewrapping a paragraph changes its bytes and not its
hash:

```console
$ cedit sync --from vendor
GUIDE.md: 0 edit(s) reapplied, 0 block(s) updated from upstream, no conflicts
```

Zero updates, no conflicts — the paragraph is the same block, and the merge saw
nothing to decide. The file does adopt upstream's line breaks, because the
structure always comes from upstream. Better still, this holds when the reflowed
paragraph is the one you rewrote — a pure reflow is a REAPPLY, not a conflict:

```console
$ cedit sync --from vendor
GUIDE.md: 1 edit(s) reapplied, 0 block(s) updated from upstream, no conflicts
$ cat GUIDE.md
# Guide

The rollback procedure is documented separately, in our own operations handbook.
```

**The similarity score, and when it is ignored.** `sim=` in the `diff` output is
`difflib`'s ratio over the two texts, with the fence info string included. Two
thresholds from the vendored engine matter: **0.4** to pair two blocks as an edit
inside a changed window, **0.6** for the fuzzy pass that pairs a block that both
moved and changed. Below those, blocks are read as unrelated.

One rule overrides the score: when a changed window holds **exactly one** block
of the same kind and type on each side, that is an edit regardless of how
different the texts are. Positional evidence is conclusive there, and without the
rule a short cell edit would be misread as structural drift — which is why this
scores 0 and is still an edit:

```console
G.md: 1 local edit(s)
[edit unit td] #5c6f9f76aa6e8e7f:0
    ctx  : G
    base : you
    local: the release manager
```

**The caveat: identical blocks are told apart only by position.** Occurrence
index is document order, so if upstream *reorders* two byte-identical blocks,
"the second one" is still the second one — and an edit on it re-applies to
whichever copy now sits in that slot. In this run the user edited the production
fence (occurrence `:1` of two identical `bash scripts/deploy.sh` fences) and
upstream then moved the production section above staging:

```console
$ cedit sync --from vendor
RUNBOOK.md: 2 edit(s) reapplied, 1 block(s) updated from upstream, 2 moved, no conflicts
```

````markdown
## Production

Deploy to production with the standard script:

```bash
bash scripts/deploy.sh
```

## Staging

Deploy to staging with the standard script, which is safe to
re-run as often as you like:

```bash
bash scripts/deploy.sh --env production --confirm
```
````

The edit landed under **Staging**. The table-cell edit in the same run followed
its content correctly, because that cell is unique. If you are adapting one of
several byte-identical blocks, make it distinguishable (a comment line in the
fence is enough) or re-check the result after a sync that reports moves.

When upstream *removes* one of the duplicates, the edit is not guessed onto a
survivor — it degrades to an orphan conflict and you decide:

```console
$ cedit sync --from vendor; echo "rc=$?"
G.md: 0 edit(s) reapplied, 0 block(s) updated from upstream, 1 inserted, 1 conflict(s)
[ORPHAN opaque fence] #95e06da1cc708132:1
    ctx     : B
    base    : bash x.sh
    upstream: (deleted)
    local   : zsh x.sh
    resolve : cedit resolve G.md 95e06da1cc708132:1 --take local|upstream

rc=1
```

When upstream *adds* another copy, the edit stays on its occurrence index and
re-applies there, which is the right answer as long as the new copy was not
inserted before it.

______________________________________________________________________

## 12. The `.cedit/` state directory

```
skills/**.md              your working copies (L)      committed — they are the product
.cedit/base/**.md         base snapshots (B)           committed — the merge's memory
.cedit/manifest.json      per-doc ledger + conflicts   committed
.cedit/overlay.json       derived local-edit overlay   committed, like a lockfile
```

Commit all of it. `.cedit/base/` is not a cache: it is the third revision the
3-way merge needs, and it comes from a *different* repository, so there is no
git blob to point at instead. Without it, a sync cannot run at all:

```console
$ cedit status
G.md: base snapshot missing (/tmp/cedit-lost/.cedit/base/G.md) — was `.cedit/base/` committed?
```

**`.cedit/base/<path>`** mirrors your document paths and holds the canonicalized
upstream text. Diffing it against your working copy is exactly what `diff
--unified` prints.

**`manifest.json`** is the ledger — one entry per document, plus any unresolved
conflicts with all three texts:

```json
{
  "schema": "cedit-manifest/v1",
  "docs": {
    "skills/deploy/SKILL.md": {
      "upstream": "vendor/skills/deploy/SKILL.md",
      "base_doc_hash": "1325c1dfe3186353",
      "synced_at": "2026-08-04T23:57:26Z",
      "conflicts": {}
    }
  }
}
```

**`overlay.json`** is your adaptations, one entry per edited block:

```json
{
  "schema": "cedit-overlay/v1",
  "docs": {
    "skills/deploy/SKILL.md": {
      "derived_at": "2026-08-04T23:57:44Z",
      "edits": [
        {
          "kind": "opaque",
          "node_type": "fence",
          "hash": "7b47884c75de548e",
          "occurrence": 0,
          "context": "Preflight",
          "base_text": "bash scripts/healthcheck.sh --strict\n",
          "base_info": "bash",
          "local_text": "zsh scripts/healthcheck.sh --strict\n",
          "local_info": "zsh"
        }
      ]
    }
  }
}
```

It is **derived**, not authoritative: your working copy is the single source of
truth, and the overlay is recomputed from base-vs-working-copy every time. This
is the anti-quilt decision — you edit the document, never a patch file, so the
overlay cannot go stale the way a hand-maintained patch does. It is committed
anyway because "what have we customized here" is exactly what a reviewer wants to
see in a PR diff.

One thing to know about its freshness: **`overlay.json` is rewritten by
`snapshot`, `sync` and `resolve` — not by `diff` or `status`.** Those two
recompute the overlay live and print it without saving, so immediately after you
edit a file, `diff` shows the edit while `overlay.json` still shows the previous
state:

```console
$ cedit diff
skills/deploy/SKILL.md: 1 local edit(s)
[edit opaque fence] #7b47884c75de548e:0  sim=0.93
...
$ cat .cedit/overlay.json
{
  "schema": "cedit-overlay/v1",
  "docs": {
    "skills/deploy/SKILL.md": {
      "derived_at": "2026-08-04T23:57:26Z",
      "edits": []
    }
  }
}
```

Trust `diff`; the file catches up at the next sync. All state files are written
atomically (temp file plus `rename(2)`), so a crash never leaves half-written
JSON.

______________________________________________________________________

## 13. Limits, stated plainly

**Local structural changes are refused.** Phase 1 merges *replacements* — prose
rewrites, fence rewrites, table-cell tweaks, front-matter edits. Inserting,
deleting or moving whole blocks in your working copy is detected and reported per
block, and nothing is merged:

```console
$ cedit diff; echo "rc=$?"
skills/deploy/SKILL.md: local structural changes are not supported yet (phase 1 merges replacements only):
  inserted paragraph: We also run a smoke test afterwards.
rc=2
$ cedit sync --from vendor; echo "rc=$?"
skills/deploy/SKILL.md: local structural changes are not supported yet (phase 1 merges replacements only):
  inserted paragraph: We also run a smoke test afterwards.
rc=2
```

This is a design boundary, not a bug: the merged document's structure always
comes from upstream and the splice is the only mutation, which is what makes the
whole thing safe. Structural local edits are phase 2 in [SPEC.md](SPEC.md).

Your options today: revert the structural change and express it as a replacement
(fold the extra sentence into an existing paragraph), or keep it and stop
syncing that document, or push the addition upstream. `diff --unified` keeps
working throughout, so you can always see what the drift is:

```console
$ cedit diff --unified
--- base/skills/deploy/SKILL.md
+++ skills/deploy/SKILL.md
@@ -27,3 +27,5 @@
 | -- | -- | -- |
 | preflight | release engineer | yes |
 | deploy | release engineer | yes |
+
+We also run a smoke test afterwards.
```

**`$...$` LaTeX math is not *parsed* as math — but it is preserved byte for
byte.** GitHub renders `$...$` and `$$...$$` as math. cedit's parser does not
know that syntax, so to it the dollars are ordinary text — which would be
harmless until the span contains a **backslash**. Left alone, `$\rightarrow$`
canonicalises to `$\\rightarrow$`, a correct CommonMark escape of a literal
backslash and a *line break* inside GitHub's math; the page renders
differently, and nothing downstream could notice, because the block structure
is unchanged and every hash would be taken over the already-rewritten text.

cedit does not leave it alone. Before a document is parsed, every such span is
swapped for an inert placeholder, and the original bytes go back into the
output afterwards — so the round-trip cannot touch it. That holds on every path
that writes: `snapshot`, `sync`, `resolve --take upstream` and
`md canonicalize` (including `-i`).

```console
$ cat docs/GH-CLI.md
2. Navigate to **Actions** $\rightarrow$ **General**.
$ cedit md canonicalize -i docs/GH-CLI.md; echo "rc=$?"
docs/GH-CLI.md: already canonical
rc=0
$ cedit sync --from vendor; echo "rc=$?"
docs/GH-CLI.md: 1 edit(s) reapplied, 2 block(s) updated from upstream, no conflicts
rc=0
```

Nothing is said about it, because there is nothing to say: a preserved span is
not a warning. Detection is what drives the preservation, and it is narrow on
purpose — only a `$`/`$$` span whose content holds a backslash, and only
outside code spans, fenced blocks, indented code, HTML blocks and front matter.
`$100 and $200`, `$x + y = z$`, `$a_i b_j$`, `$[a,b]$` and `` `$\rightarrow$` ``
were byte-stable before and are untouched now.

There is one construct the preservation cannot reach, and cedit does warn about
that one — a `$...$` span in a **table cell that also contains `\|`**. The
parser hands back the cell already unescaped, so the span cannot be located in
your source to protect it, and it is rewritten the old way:

```console
$ cedit sync --from vendor; echo "rc=$?"
docs/TABLES.md: warning: 1 dollar-delimited math span(s) could not be located in the source
    line 12: $x | y \alpha$
    cedit preserves $...$ byte for byte by rewriting the source around it, and
    cannot for these — canonicalisation will escape the backslash ($\x -> $\\x),
    which GitHub reads inside math as a line break, so the rendered maths changes.
    Use a ```math fence for display math, and the Unicode character or a code span
    inline (USERGUIDE.md §13).
docs/TABLES.md: 1 edit(s) reapplied, 2 block(s) updated from upstream
rc=0
```

**The exit code does not move** — a warning is not a conflict and not an error
([§16](#exit-codes)). If you want CI to fail on it, gate on
`cedit md canonicalize --check <file>`, which exits 1 for any file whose
canonical form differs.

For that one case, and any time you would rather not rely on the placeholder,
write this instead:

| Instead of | Write | Why |
| --- | --- | --- |
| `$$ \frac{a}{b} $$` | a ```` ```math ```` fence | round-trips byte for byte with nothing to protect, and GitHub renders it as display math |
| `$\rightarrow$` | the character — `→` | what this repo's own docs use; no escaping involved |
| `$\alpha$` as *text* about the syntax | a code span — `` `$\alpha$` `` | code spans are never rewritten |

````markdown
```math
\frac{a}{b}
```
````

Making `$...$` parse as math is still not on the roadmap — preserving it is not
the same as understanding it, and nothing keys on the contents of a span. Every
published `mdformat-dollarmath` requires `mdformat<0.8` against the pinned
`mdformat==1.0.0`, and `mdformat-myst` would add a second frontmatter plugin —
a parser-identity change in its own right (see
[.claude/rules/hash-stability.md](.claude/rules/hash-stability.md)).

**If you tracked a document with `$...$` math before cedit 0.4.0**, its
`.cedit/base/` snapshot holds the rewritten form, and this release moves it.
Re-baseline that document — the recipe is *Re-baselining a document* in
[.claude/rules/hash-stability.md](.claude/rules/hash-stability.md); your
adaptations live in the working copy, so none of them are lost. Documents with
no such math are unaffected: their hashes and canonical bytes do not move.

**Upstream is not fetched.** `--from` takes a directory or a file that already
exists on disk. Submodules, subtrees, `curl`, a sync script — your transport.

**Front matter is one block.** See [§6](#6-what-cedit-sees-blocks-hashes-keys).

**Identical blocks are addressed by position.** See
[§11](#11-what-alignment-buys-you).

**No LLM-assisted rebase.** When both sides change a block, cedit reports it; it
does not try to port your adaptation onto the new upstream text. That is phase 3.

______________________________________________________________________

## 14. Cookbook

**See what an upstream revision would do, without touching anything**

```bash
cedit sync --from vendor --dry-run
```

**Adopt a copy you already adapted by hand** — point `snapshot` at the upstream
revision it was forked from; the difference becomes your overlay, and the file is
left untouched.

```bash
cedit snapshot skills/deploy.md --from vendor/skills/deploy.md
```

**Sync one document while others have open conflicts** — name it, and the rest
are not even looked at.

```bash
cedit sync skills/deploy.md --from vendor
```

**Review adaptations in a PR** — `.cedit/overlay.json` *is* the review artifact;
its diff is the list of what you customized. For a reviewer who wants familiar
syntax:

```bash
cedit diff --unified > /tmp/adaptations.patch
```

**Gate CI on unresolved conflicts** — `status` needs no upstream and no network.

```bash
cedit status    # 0 clean, 1 conflicts open, 2 state broken
```

**Turn a conflict key back into a block** — `md blocks` prints the same
`<hash>:<occurrence>` addresses `resolve` takes, so it answers both directions
of the question: what a key names, and what the key of a given block is.
Point it at the base, which is what those addresses are keyed to
([§5.7](#57-md--stateless-parser-views)):

```bash
cedit md blocks .cedit/base/skills/deploy.md    # the base the next sync merges from
cedit md blocks vendor/skills/deploy.md         # the upstream revision it will merge
```

**Find a conflict's key without scrolling** — the sync that recorded it printed
the key with a ready-made `resolve` line. If that scrollback is gone, ask
`resolve`: any key it cannot match lists the open ones.

```console
$ cedit resolve skills/deploy.md none
no conflict matches 'none' (open ones: 7b47884c75de548e:0)
```

That listing, not `md blocks`, is the one to reach for here: an open conflict's
key names the block in the base cedit merged *from*, and the sync that recorded
it has already advanced the base past that block — so the key is in the
manifest and in no file on disk.

**Gate a repository on canonical Markdown** — `canonicalize --check` writes
nothing and exits 1 per file, which is the shape a pre-commit hook or a CI step
wants. Non-canonical Markdown is not an error in itself; catching it before the
snapshot is what stops the first `cedit` command anyone runs from reformatting
their file.

```bash
git ls-files '*.md' | xargs -n1 cedit md canonicalize --check
```

`xargs` exits **123** when any invocation exited 1 — non-zero is the signal;
the exact code is `xargs`'s, not cedit's.

The same command is still the gate for the one `$...$` construct cedit cannot
preserve ([§13](#13-limits-stated-plainly)): a file the round-trip would rewrite
is by definition not canonical, and the warning on stderr names the lines.
cedit itself only warns — a math span never moves an exit code — so this is
where a build failure comes from if you want one.

**See what the round trip will do before you snapshot** — the canonical form is
what gets stored and hashed, so this is the diff you actually care about:

```bash
cedit md canonicalize skills/deploy.md | diff skills/deploy.md -
```

**Recover the text of a block you lost to an orphan** — it is recorded before you
accept the deletion:

```bash
cedit resolve skills/deploy.md <hash> --show
```

**Experiment without disturbing committed state**

```bash
cedit --state-dir .cedit-scratch snapshot skills/deploy.md --from vendor/skills/deploy.md
```

**Re-vendor from scratch** — there is no `untrack`. Delete the document's entry
from `manifest.json` and `overlay.json` plus its file under `.cedit/base/`, then
`snapshot` it again. Your working copy is untouched, so the new snapshot records
your current adaptations as the overlay.

**Check two checkouts are on the same upstream revision** — compare the
`base <hash>` that `status` reports.

______________________________________________________________________

## 15. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `nothing tracked` from a repo that *is* tracked | you are not at the repository root | `cd` to the root — state is resolved from the working directory |
| `<doc>: not tracked — run cedit snapshot first` | typo in the path, or never snapshotted | check `cedit status` for the exact keys |
| `already tracked — use cedit sync` | `snapshot` run twice | use `sync`, or re-vendor (see the cookbook) |
| `tracked documents are addressed by a path relative to the repository root` | an absolute path or one starting `../` | pass the repo-relative path |
| `base snapshot missing … was .cedit/base/ committed?` | `.cedit/base/` not committed, or a partial checkout | restore it from git; without B nothing can merge |
| `[Errno 2] No such file or directory: '…/G.md'` | the tracked working copy was deleted or moved | restore it, or re-vendor under the new path |
| `upstream file not found: <path>` | `--from` directory does not mirror your doc paths | the file must be at `<dir>/<doc-path>` exactly |
| `--from is a file but several documents are being synced` | one file cannot be two upstreams | pass a directory, or name one document |
| `local structural changes are not supported yet` | you inserted/deleted/moved a whole block | see [§13](#13-limits-stated-plainly); `diff --unified` still shows it |
| `N unresolved conflict(s) — resolve them before syncing again` | a previous sync recorded conflicts | `resolve` each one, then sync |
| `no conflict matches '<key>'` | wrong or already-resolved key | the message lists the open keys |
| `'<key>' is ambiguous` | prefix matches several conflicts | pass more of the hash, or the full `<hash>:<occurrence>` |
| `upstream deleted this block — keeping it would be a structural edit` | `--take local` on an orphan | `--take upstream` accepts the deletion; the text stays in the manifest |
| `the conflicted block is no longer in the file as recorded` | you hand-edited it after the sync | that is the hand-merge path: `--take local` accepts what you wrote |
| `rendered block structure differs` | a splice would have corrupted the document | **nothing was written**; check the local text for stray Markdown (a list marker, a `|`) |
| a sync you expected to be clean is a wall of conflicts | the parsing stack was upgraded, moving every hash | pin `requirements.txt` back; hashes are only comparable within one parser configuration. Confirm it before you go looking elsewhere — see below |
| `--in-place needs a file, not stdin` | `md canonicalize -i` with no file, or with `-`; the file argument defaults to stdin | name the file. `-i` rewrites a path atomically, and a pipe has none |
| `<stdin>: invalid JSON — Expecting value: …` | `md from-json` was handed something that is not JSON at all | it consumes `md json` output; check what the pipe upstream of it actually printed |
| `expected a token stream as emitted by cedit md json, got a dict` | `md json --tree` piped into `md from-json` | drop `--tree` — the flat token stream is the rebuildable shape, the tree is for reading ([§5.7](#57-md--stateless-parser-views)) |
| your edit re-applied to the wrong copy of an identical block | occurrence index is positional and upstream reordered | see [§11](#11-what-alignment-buys-you); make the block distinguishable |
| `status` reports `STRUCTURAL DRIFT` but exits 0 | only conflicts drive exit 1 | gate on `diff` (exits 2) if you need drift to fail CI |
| `warning: N dollar-delimited math span(s) could not be located in the source` | a `$...$` span in a table cell that also holds `\|` — the parser hands the cell back unescaped, so cedit cannot protect it and the backslash gets escaped | rewrite that span: a ```` ```math ```` fence, `→`, or a code span. See [§13](#13-limits-stated-plainly). The exit code is unaffected; `md canonicalize --check` is the CI gate |
| your rendered maths grew stray line breaks after a sync | the above, unnoticed — the warning goes to **stderr**, which a `>` redirect does not capture. Every other `$...$` span is preserved byte for byte | `cedit md canonicalize --check <doc>`; then fix the spans and re-run |
| a sync you expected to be clean is a wall of conflicts, and the documents contain `$...$` math | cedit 0.4.0 preserves that math; before it, `.cedit/base/` recorded the rewritten form, so the base moved under you | re-baseline those documents — *Re-baselining a document* in [.claude/rules/hash-stability.md](.claude/rules/hash-stability.md). Only math-bearing documents are affected |

**Conflicts on blocks nobody touched.** That is what a moved hash looks like
from the outside, and two commands settle it without guessing. `.cedit/base/`
holds canonical text by construction, so if the parser you are running now
disagrees with what is stored there, the canonical form itself moved:

```console
$ cedit md canonicalize --check .cedit/base/skills/deploy.md
.cedit/base/skills/deploy.md: not canonical
```

Exit 0 from that and conflicts anyway means the stored bytes are intact and
only the hash *values* moved: `cedit md blocks .cedit/base/skills/deploy.md`
prints the keys the current parser assigns, and any that no longer appear in
`.cedit/overlay.json` are the ones that moved. Either way the document is not
the problem — restore the pinned stack.

**A conflict you cannot decide.** Do nothing — an unresolved conflict is a stable
state. The working file keeps your text, every other block already merged, and
the document simply refuses further syncs until you come back to it.

**A merge you want to undo.** cedit has no undo; git does. The document and
`.cedit/` are committed together for exactly this reason — `git checkout` the
pair and you are back to the previous base.

______________________________________________________________________

## 16. Appendix

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | clean — nothing to do, or everything merged |
| `1` | unresolved conflicts: a `sync` recorded them, or a `status` found them; or a file `md canonicalize --check` found not canonical |
| `2` | error — nothing was merged |

Per command:

| Code | `snapshot` | `diff` | `sync` | `status` | `resolve` |
| --- | --- | --- | --- | --- | --- |
| `0` | now tracking | reported | merged clean, or up to date | reported | settled, or `--show` |
| `1` | — | — | conflicts recorded | conflicts open | — |
| `2` | already tracked, bad path, unreadable `--from`, structural drift | nothing tracked, untracked doc, structural drift | nothing tracked, conflicts already open, missing upstream, structural drift, structure mismatch | untracked doc, missing base, missing working copy | no/ambiguous key, `--take local` on an orphan, block edited since |

And for the `md` group ([§5.7](#57-md--stateless-parser-views)):

| Code | `md canonicalize` | `md ast` / `md json` / `md blocks` | `md from-json` |
| --- | --- | --- | --- |
| `0` | written, or `--check` passed | printed | rendered |
| `1` | `--check` on a non-canonical file | — | — |
| `2` | missing file, `-i` on stdin | missing file | invalid JSON, wrong shape, not a token |

Two rules a CI script depends on: `1` never means "broken" and `2` never means
"needs a human". Within one `sync` run over several documents, `2` wins — an
error anywhere means the run's conflict count is not the whole story. `md
canonicalize --check` keeps that reading: unformatted is a thing a human
fixes, not a breakage.

**Warnings are outside this table.** The `$...$` math warning
([§13](#13-limits-stated-plainly)) is stderr text and nothing else: it never
adds a code, never upgrades one, and a document that gained a math span still
returns what it returned before — preserving the math gave cedit nothing to
fail on. Anything that needs to fail a build gates on
`md canonicalize --check`.

### State layout

| Path | Contents | Committed |
| --- | --- | --- |
| `<doc>` | your working copy (**L**) | yes — it is the product |
| `.cedit/base/<doc>` | canonicalized base snapshot (**B**) | **yes** — the merge is impossible without it |
| `.cedit/manifest.json` | per-doc upstream, base hash, sync time, unresolved conflicts | yes |
| `.cedit/overlay.json` | derived local-edit overlay | yes, like a lockfile |

### `manifest.json` shape

```json
{
  "schema": "cedit-manifest/v1",
  "docs": {
    "<doc path>": {
      "upstream": "<--from as last given>",
      "base_doc_hash": "<16 hex chars>",
      "synced_at": "<UTC ISO-8601>",
      "conflicts": {
        "<hash>:<occurrence>": {
          "reason": "conflict | orphan",
          "kind": "opaque | unit",
          "node_type": "fence | paragraph | heading | td | th | front_matter | ...",
          "context": "<heading trail>",
          "base_text": "...", "base_info": "...",
          "local_text": "...", "local_info": "...",
          "upstream_text": "... | null (orphan)", "upstream_info": "..."
        }
      }
    }
  }
}
```

### `overlay.json` shape

```json
{
  "schema": "cedit-overlay/v1",
  "docs": {
    "<doc path>": {
      "derived_at": "<UTC ISO-8601>",
      "edits": [
        {
          "kind": "opaque | unit",
          "node_type": "fence | paragraph | ...",
          "hash": "<16 hex chars>",
          "occurrence": 0,
          "context": "<heading trail>",
          "base_text": "...", "base_info": "...",
          "local_text": "...", "local_info": "..."
        }
      ]
    }
  }
}
```

Both files serialize documents in sorted key order, UTF-8, `ensure_ascii=False`,
so diffs stay local and reviewable.

### Defaults and constants

| Thing | Value | Where |
| --- | --- | --- |
| state directory | `.cedit` | `state.DEFAULT_STATE_DIR` |
| manifest schema | `cedit-manifest/v1` | `state.MANIFEST_SCHEMA` |
| overlay schema | `cedit-overlay/v1` | `state.OVERLAY_SCHEMA` |
| hash width | 16 hex chars | `mdcore.tree_diff.hash_tree` |
| edit-pairing threshold | `0.4` | `mdcore.tree_diff.SIM_THRESHOLD` |
| fuzzy (moved+edited) threshold | `0.6` | `mdcore.tree_diff.FUZZY_THRESHOLD` |
| display clip width | 110 chars | `mdcore.tree_diff.WIDTH` |
| opaque node types | `fence`, `code_block`, `html_block`, `front_matter`, `hr` | `mdcore.tree_diff.OPAQUE` |
| unit node types | `heading`, `paragraph`, `th`, `td` | `mdcore.tree_diff.UNIT_PARENTS` |

### Things cedit deliberately will not do

- **Fetch upstream.** `--from` reads what is already on disk.
- **Write conflict markers into the document.** `=======` is a setext heading
  underline; a marked-up file would stop parsing as itself and every hash
  downstream would move.
- **Merge local structural changes.** Phase 1 is replacements only, and the
  refusal is per block with a report.
- **Clobber your text.** On a conflict the working file keeps the local version,
  always.
- **Rewrite `$...$` math.** It cannot parse it as math, but it preserves the
  span byte for byte on every write path. The one construct it cannot protect —
  a span in a table cell holding `\|` — is warned about on stderr first
  ([§13](#13-limits-stated-plainly)).
- **Sync a document with open conflicts.** It would merge against a base you
  never accepted.
- **Commit anything.** The document and `.cedit/` are yours to commit, together.

### See also

| Document | What it covers |
| --- | --- |
| [README.md](README.md) | the two-minute version: setup, quickstart, layout |
| [SPEC.md](SPEC.md) | the normative design — merge matrix, sync algorithm, state format, reuse rules, phases |
| [AGENTS.md](AGENTS.md) | working on cedit itself: orientation, invariants, repo workflow |
| [ARCHITECTURE.md](ARCHITECTURE.md) | the implementation module by module, and the recipes for extending it |
