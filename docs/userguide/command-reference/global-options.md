---
slug: /userguide/global-options
sidebar_position: 5
---
# Global options

One global flag, and it goes **before** the subcommand:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--state-dir` | `.cedit` | state directory, relative to the working directory (ignored by `md`) |
| `-h`, `--help` | — | usage; also available per subcommand |

```console
$ cedit --help
usage: cedit [-h] [--state-dir STATE_DIR]
             {snapshot,diff,sync,status,resolve,md} ...

Keep local adaptations of vendored Markdown alive across upstream updates (see
SPEC.md).

positional arguments:
  {snapshot,diff,sync,status,resolve,md}
    snapshot            start tracking a document
    diff                show local edits against the base
    sync                3-way merge a new upstream revision in
    status              per-document overlay/conflict summary
    resolve             settle one recorded conflict
    md                  stateless parser views: canonicalize / ast / json /
                        blocks

options:
  -h, --help            show this help message and exit
  --state-dir STATE_DIR
                        state directory (default: .cedit); ignored by the
                        stateless `md` subcommands
```

`md` is the odd one out and [`md` — stateless parser views](md-parser-views.md)
covers it: a group of stateless verbs that
never open `.cedit/`, which is why `--state-dir` does nothing for them.

`--state-dir` gives you a second, independent set of tracking state over the
same files — useful for a dry experiment you do not want in the committed
`.cedit/`:

```console
$ cedit --state-dir .cedit-alt status
nothing tracked
```
