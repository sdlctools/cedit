---
slug: /userguide/conflict
sidebar_position: 15
---
# A conflict, end to end

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
([Limits, stated plainly](../help/limits.md)). Your text is preserved in the
manifest either way — copy it somewhere
before accepting if you still want it.
