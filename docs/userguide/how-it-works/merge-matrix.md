---
slug: /userguide/merge-matrix
sidebar_label: The merge matrix
sidebar_position: 10
---
# The merge matrix in practice

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
