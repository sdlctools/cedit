---
slug: /userguide/status-resolve
sidebar_label: status / resolve
sidebar_position: 7
---
# `status` and `resolve`

## `status`

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

## `resolve`

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
  *structural* edit, which is phase 2
  ([Limits, stated plainly](../help/limits.md)). Your text stays recorded in the
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
what you wrote (see [A conflict, end to end](../task-flows/conflict-end-to-end.md)).
