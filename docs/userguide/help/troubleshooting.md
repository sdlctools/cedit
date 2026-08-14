---
slug: /userguide/troubleshooting
sidebar_position: 18
---
# Troubleshooting

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
| `local structural changes are not supported yet` | you inserted/deleted/moved a whole block | see [Limits, stated plainly](limits.md); `diff --unified` still shows it |
| `N unresolved conflict(s) — resolve them before syncing again` | a previous sync recorded conflicts | `resolve` each one, then sync |
| `no conflict matches '<key>'` | wrong or already-resolved key | the message lists the open keys |
| `'<key>' is ambiguous` | prefix matches several conflicts | pass more of the hash, or the full `<hash>:<occurrence>` |
| `upstream deleted this block — keeping it would be a structural edit` | `--take local` on an orphan | `--take upstream` accepts the deletion; the text stays in the manifest |
| `the conflicted block is no longer in the file as recorded` | you hand-edited it after the sync | that is the hand-merge path: `--take local` accepts what you wrote |
| `rendered block structure differs` | a splice would have corrupted the document | **nothing was written**; check the local text for stray Markdown (a list marker, a `|`) |
| a sync you expected to be clean is a wall of conflicts | the parsing stack was upgraded, moving every hash | pin `requirements.txt` back; hashes are only comparable within one parser configuration. Confirm it before you go looking elsewhere — see below |
| `--in-place needs a file, not stdin` | `md canonicalize -i` with no file, or with `-`; the file argument defaults to stdin | name the file. `-i` rewrites a path atomically, and a pipe has none |
| `<stdin>: invalid JSON — Expecting value: …` | `md from-json` was handed something that is not JSON at all | it consumes `md json` output; check what the pipe upstream of it actually printed |
| `expected a token stream as emitted by cedit md json, got a dict` | `md json --tree` piped into `md from-json` | drop `--tree` — the flat token stream is the rebuildable shape, the tree is for reading ([the `md` verbs](../command-reference/md-parser-views.md)) |
| your edit re-applied to the wrong copy of an identical block | occurrence index is positional and upstream reordered | see [What alignment buys you](../how-it-works/alignment.md); make the block distinguishable |
| `status` reports `STRUCTURAL DRIFT` but exits 0 | only conflicts drive exit 1 | gate on `diff` (exits 2) if you need drift to fail CI |
| `warning: N dollar-delimited math span(s) could not be located in the source` | a `$...$` span in a table cell that also holds `\|` — the parser hands the cell back unescaped, so cedit cannot protect it and the backslash gets escaped | rewrite that span: a ```` ```math ```` fence, `→`, or a code span. See [Limits, stated plainly](limits.md). The exit code is unaffected; `md canonicalize --check` is the CI gate |
| your rendered maths grew stray line breaks after a sync | the above, unnoticed — the warning goes to **stderr**, which a `>` redirect does not capture. Every other `$...$` span is preserved byte for byte | `cedit md canonicalize --check <doc>`; then fix the spans and re-run |
| a sync you expected to be clean is a wall of conflicts, and the documents contain `$...$` math | cedit 0.4.0 preserves that math; before it, `.cedit/base/` recorded the rewritten form, so the base moved under you | re-baseline those documents — *Re-baselining a document* in [.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md). Only math-bearing documents are affected |

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
