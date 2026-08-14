---
slug: /userguide/cookbook
sidebar_position: 17
---
# Cookbook

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
([the `md` verbs](../command-reference/md-parser-views.md)):

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
preserve ([Limits, stated plainly](limits.md)): a file the round-trip would rewrite
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
