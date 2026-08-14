---
slug: /userguide/limits
sidebar_position: 16
---
# Limits, stated plainly

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
whole thing safe. Structural local edits are phase 2 in [SPEC.md](../../SPEC.md).

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
    inline — the user guide, *Limits, stated plainly*:
    https://sdlctools.github.io/cedit/docs/userguide/limits
docs/TABLES.md: 1 edit(s) reapplied, 2 block(s) updated from upstream
rc=0
```

**The exit code does not move** — a warning is not a conflict and not an error
([Exit codes](appendix.md#exit-codes)). If you want CI to fail on it, gate on
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
[.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md)).

**If you tracked a document with `$...$` math before cedit 0.4.0**, its
`.cedit/base/` snapshot holds the rewritten form, and this release moves it.
Re-baseline that document — the recipe is *Re-baselining a document* in
[.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md); your
adaptations live in the working copy, so none of them are lost. Documents with
no such math are unaffected: their hashes and canonical bytes do not move.

**Link reference definitions are inlined when used, and unused ones are dropped.**
Markdown allows link references to be defined separately from their use:

```markdown
[ref]: https://example.com

Link to [ref].
```

The pinned parser (mdformat) inlines these definitions on render, converting them
to direct links. Used references are preserved:

```console
$ cedit md canonicalize
[ref]: https://example.com

Link to [ref].
Link to [ref](https://example.com).
```

However, **unused definitions are silently dropped** — content loss with no
warning. cedit detects this and warns you:

```console
$ cedit md canonicalize docs/LINKS.md
docs/LINKS.md: warning: 1 link reference definition(s) would be lost during canonicalisation
    line 1: [unused]: https://example.com/never-used
    Link reference definitions (e.g., '[label]: https://...') are inlined when used,
    but unused definitions are silently dropped. Either use the reference or convert it
    to a direct link. See the user guide for details:
    https://sdlctools.github.io/cedit/docs/userguide/limits
```

The warning is stderr-only and does not affect the exit code. To make CI fail on
it, use `cedit md canonicalize --check <file>`, which exits 1 for any file whose
canonical form differs — including one with unused link references.

To fix it, either use the reference somewhere in your document or convert it to
a direct link:

```markdown
# Instead of an unused definition:
[unused]: https://example.com

# Write this:
[text](https://example.com)
```

The warning appears on every `cedit md canonicalize` and on `sync`/`resolve`/`snapshot`
— anywhere the canonical form is computed. A document with no unused references
says nothing.

**A table row can carry more than its header declares — and that text is kept.**
A GFM table's header row fixes the column count for the whole table, and the
parser truncates every body row to it. Anything past the last kept cell is
discarded before cedit's tree exists — an annotation parked after the closing
pipe, an extra cell, or the tail of a row that an *unescaped* `|` inside a code
span split further than you meant it to:

```markdown
| Jira type | API value |
| --- | --- |
| Sub-task | `Subtask` |   <- no hyphen for this project (see §11)
```

Left alone, that row canonicalises to `| Sub-task | \`Subtask\` |` and the
pointer is gone — with no warning and exit 0, because the block structure is
unchanged and every hash is taken over a tree the text never reached.

cedit does not leave it alone. Before a document is parsed, each row's surplus
is lifted out; after the render it is appended back onto the same row, byte for
byte. That holds on every path that writes: `snapshot`, `sync`,
`resolve --take upstream` and `md canonicalize` (including `-i`).

```console
$ cedit md canonicalize -i docs/JIRA-REST.md; echo "rc=$?"
docs/JIRA-REST.md: already canonical
rc=0
```

Nothing is said about it, because there is nothing to say. Detection asks the
parser where it truncates rather than scanning for pipes, so the *same* line
under a three-column header is a genuine third cell and is canonicalised
normally — and a row whose surplus is only whitespace and stray `|` is still
normalised away, because that is punctuation, not content.

Two consequences worth knowing:

- **Your hashes do not move.** The parser was already discarding these bytes, so
  handing it the row without them produces the identical tree — cedit checks
  that on every document rather than assuming it. A `.cedit/base/` snapshot
  written before this release still matches block for block; the recovered text
  reappears in the base on the next `sync`. This is not the re-baselining case
  described in [.claude/rules/hash-stability.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/hash-stability.md).
- **The recovered text is not part of any block**, because no cell contains it.
  It rides with its row, so a `sync` keeps whatever the incoming upstream
  revision's row carries, and an edit you make to that text alone is not merged.
  Preserving the bytes is what this guard is for; making them mergeable is not
  something phase 1 can offer ([SPEC.md](../../SPEC.md)).

If the text matters enough to merge, give the table another column and put it in
a cell, or escape the `|` that split the row (`\|`) so the cells you meant are
the cells the parser sees.

In the rare case cedit cannot lift a row's surplus cleanly, it says so and
leaves the row alone rather than rewriting it into bytes nobody wrote — stderr
only, and **the exit code does not move** ([Exit codes](appendix.md#exit-codes)):

```console
$ cedit sync --from vendor; echo "rc=$?"
docs/TABLES.md: warning: 1 table row(s) carry text past the header's last column that could not be preserved
    line 12: | a | b | note
    A GFM table's header row fixes the column count, and cedit's parser discards
    whatever a body row carries past it — an annotation after the closing pipe, or an
    extra cell. cedit normally lifts that text out and puts it back verbatim, and
    cannot for these. Give the table another column, or move the note into a cell
    — the user guide, *Limits, stated plainly*:
    https://sdlctools.github.io/cedit/docs/userguide/limits
docs/TABLES.md: 1 edit(s) reapplied, 2 block(s) updated from upstream
rc=0
```

**Upstream is not fetched.** `--from` takes a directory or a file that already
exists on disk. Submodules, subtrees, `curl`, a sync script — your transport.

**Front matter is one block.** See [Blocks, hashes, keys](../how-it-works/blocks-hashes-keys.md).

**Identical blocks are addressed by position.** See
[What alignment buys you](../how-it-works/alignment.md).

**No LLM-assisted rebase.** When both sides change a block, cedit reports it; it
does not try to port your adaptation onto the new upstream text. That is phase 3.
