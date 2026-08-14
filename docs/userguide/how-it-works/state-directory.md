---
slug: /userguide/state
sidebar_label: The .cedit/ directory
sidebar_position: 12
---
# The `.cedit/` state directory

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
