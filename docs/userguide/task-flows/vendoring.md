---
slug: /userguide/vendoring
sidebar_position: 13
---
# Vendoring a document

You have a file from somewhere else and you want to own a local variant of it.

```bash
# 1. get upstream onto disk — your transport, not cedit's job
mkdir -p vendor/skills && cp ~/upstream-repo/skills/deploy.md vendor/skills/

# 2. start tracking; this vendors the file if it does not exist yet
cedit snapshot skills/deploy.md --from vendor/skills/deploy.md

# 3. adapt the working copy in your editor, then check what you did
cedit diff

# 4. commit BOTH the document and the state
git add skills/deploy.md .cedit
git commit -m "vendor the deploy skill, adapted for zsh"
```

Step 4 is not optional. `.cedit/base/` *is* the merge's memory: without the base
snapshot there is no third revision, and a later sync cannot tell your edits
apart from upstream's. Committing it is what makes the next update work on a
teammate's checkout and in CI.

If your vendoring script re-copies the whole upstream tree, keep `vendor/` in the
repo too (or regenerate it before each sync). `--from` needs to point at
something that exists at sync time.
