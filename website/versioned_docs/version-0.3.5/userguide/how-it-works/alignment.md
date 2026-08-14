---
slug: /userguide/alignment
sidebar_position: 11
---
# What alignment buys you

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
