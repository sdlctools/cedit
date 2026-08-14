---
slug: /userguide/commands
sidebar_label: The five subcommands
sidebar_position: 4
---
# The five subcommands

| Command | Reads | Writes | Exit codes |
| --- | --- | --- | --- |
| `snapshot` | the upstream file, the working copy if it exists | the working copy (if absent), `.cedit/` | 0, 2 |
| `diff` | base snapshot, working copy | nothing | 0, 2 |
| `sync` | base snapshot, working copy, upstream | the working copy, `.cedit/` | 0, 1, 2 |
| `status` | base snapshot, working copy, manifest | nothing | 0, 1, 2 |
| `resolve` | manifest, working copy | the working copy (`--take upstream` only), `.cedit/` | 0, 2 |

`diff` and `status` are read-only and safe at any moment. `sync` is the only
command that merges. `resolve` is the only command that can clear a conflict.

Alongside them sits `cedit md` — five *stateless* verbs that read no
`.cedit/` state and work on any Markdown file, tracked or not. They are not
part of the workflow above; they are how you look at what the parser sees.
The [`md` verbs](md-parser-views.md) cover them.
