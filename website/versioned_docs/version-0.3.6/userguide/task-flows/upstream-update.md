---
slug: /userguide/upstream-update
sidebar_position: 14
---
# Taking an upstream update

The day-to-day loop:

```bash
# 1. refresh your upstream mirror — again, your transport
git -C vendor pull        # or a submodule update, or a re-copy

# 2. look before you leap
cedit sync --from vendor --dry-run

# 3. do it
cedit sync --from vendor

# 4. read what changed, in the language of your own adaptations
cedit diff
git diff skills/

# 5. commit the document and the state together
git add skills .cedit && git commit -m "sync skills from upstream"
```

Exit code 0 means it merged clean. Exit code 1 means one or more conflicts were
recorded — jump to [A conflict, end to end](conflict-end-to-end.md). Exit code 2 means
nothing merged; read the message.

In CI, the useful gate is `status`, which needs no upstream at all:

```bash
cedit status || echo "conflicts are open in this branch"
```

Exit 1 there means "a human must decide"; exit 2 means the state itself is
broken (a missing base snapshot, usually an incomplete commit).
