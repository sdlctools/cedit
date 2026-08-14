---
slug: /userguide/snapshot-diff-sync
sidebar_label: snapshot / diff / sync
sidebar_position: 6
---
# `snapshot`, `diff` and `sync`

## `snapshot`

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

## `diff`

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
  evidence rather than textual similarity (see [What alignment buys you](../how-it-works/alignment.md)):

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
so a structural local change ([Limits, stated plainly](../help/limits.md))
does not stop it. That makes it the tool for
*seeing* the drift the block view refuses to merge.

## `sync`

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

Every conflict is then printed in full (see [A conflict, end to end](../task-flows/conflict-end-to-end.md)),
and the command exits 1. Errors — an upstream file that does not exist, a
document with conflicts still open, a local structural change — exit 2, and 2
wins over 1 when a run hits both.

**Write ordering.** The working file is written *before* the base snapshot and
manifest, deliberately. A crash between the two leaves an already-merged working
copy against the old base, which the next sync simply re-derives as local edits
and converges on. The reverse order would record a sync that never happened.
