---
slug: /userguide/blocks
sidebar_label: Blocks, hashes, keys
sidebar_position: 9
---
# What cedit sees: blocks, hashes, keys

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
The [`md` verbs](../command-reference/md-parser-views.md) are the reference for both; running them
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
see [What alignment buys you](alignment.md).)

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
