---
slug: /userguide/global-options
sidebar_position: 5
---
# Global options

Two global flags, and they go **before** the subcommand:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--state-dir` | `.cedit` | state directory, relative to the working directory (ignored by `md`) |
| `--version` | — | the build, the parsing stack and the installed mdformat plugins; exits immediately |
| `-h`, `--help` | — | usage; also available per subcommand |

```console
$ cedit --help
usage: cedit [-h] [--version] [--state-dir STATE_DIR]
             {snapshot,diff,sync,status,resolve,md} ...

cedit 0.3.6 — keep local adaptations of vendored Markdown alive across
upstream updates (see https://sdlctools.github.io/cedit/docs/spec).

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
  --version             show the version, the parsing stack and the installed
                        mdformat plugins, and exit
  --state-dir STATE_DIR
                        state directory (default: .cedit); ignored by the
                        stateless `md` subcommands
```

`md` is the odd one out and [`md` — stateless parser views](md-parser-views.md)
covers it: a group of stateless verbs that
never open `.cedit/`, which is why `--state-dir` does nothing for them.

## `--version` — which cedit, built against what

`cedit --help` names the build on its first line, which is enough to answer
"which cedit". `--version` answers the larger question — *which parser* —
because that is what your recorded hashes actually depend on:

```console
$ cedit --version
cedit 0.3.6
Python 3.14.6
parsing stack: markdown-it-py 4.2.0, mdit-py-plugins 0.6.1, mdformat 1.0.0,
               mdformat-gfm 1.0.0, mdformat-frontmatter 2.1.2,
               mdformat-footnote 0.1.3, linkify-it-py 2.1.0
mdformat plugins: footnote, frontmatter, gfm, tables
```

Every line is resolved from the environment cedit is actually running in, not
from a list baked into the release — reporting the pin while you run something
else would defeat the point.

The last line is the one worth knowing about. cedit's parser loads **every
mdformat plugin installed alongside it**, so an unrelated `pip install` into a
shared environment can change what the parser is without touching any of
cedit's pins, and move the hashes in your `.cedit/` state. That is why
[Prerequisites](../getting-started/prerequisites.md) asks you to install cedit
into an environment of its own — and if a `sync` ever reports conflicts on
blocks nobody touched, this line is the first thing to compare against a
colleague's.

## `--state-dir` — a second, independent overlay

`--state-dir` gives you a second, independent set of tracking state over the
same files — useful for a dry experiment you do not want in the committed
`.cedit/`:

```console
$ cedit --state-dir .cedit-alt status
nothing tracked
```
