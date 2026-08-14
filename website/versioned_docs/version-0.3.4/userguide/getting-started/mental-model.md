---
slug: /userguide/mental-model
sidebar_position: 1
---
# The mental model

Five commands over one tracked document:

```
   snapshot ──►  (you edit the file)  ──►  sync  ──►  (clean)
      │                   │                  │
      │                 diff                 └─► conflict ──► resolve ──► sync
      │            what have I changed?
      └─ start tracking                    status  (read-only, any time)
```

Three ideas explain almost everything.

**Three revisions, one merge.** Every tracked document has a *base* (**B**, the
upstream revision you last synced against, snapshotted under `.cedit/base/`), a
*local* copy (**L**, the file you edit in place), and an *upstream* (**U**, the
new revision you hand to `sync`). `sync` aligns L against B to learn what you
changed, aligns U against B to learn what upstream changed, and decides every
block by crossing the two. The merged document is always **U's structure** with
your texts spliced in.

**Blocks are content-addressed, and fences count.** A "block" is a paragraph, a
heading, a table cell — or a code fence, a raw HTML block, or the YAML front
matter. Its identity is a 16-hex-char Merkle hash of its canonical content, not
its position or line number. That is why a rewritten fence is a first-class
edit, why an upstream *move* of a block you edited costs nothing, and why
rewrapping a paragraph at a different width changes nothing at all.

**Nothing is ever silently clobbered.** When upstream changes the very block you
adapted, the working file keeps **your** text and the conflict is recorded with
all three versions. The document then refuses to sync again until you settle it
with `resolve`. There are no conflict markers in the file — `=======` is a
setext heading underline, so a marked-up Markdown file would stop parsing as the
document it was; conflicts live in `.cedit/manifest.json` instead.
