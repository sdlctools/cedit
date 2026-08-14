---
slug: /userguide/prerequisites
sidebar_position: 2
---
# Prerequisites

cedit runs from the root of the repository that holds your vendored copies —
a *different* repository from the one cedit itself lives in. Install it once:

```bash
pipx install cedit   # or: pip install cedit
cedit --help
```

Every example below is written as `cedit <subcommand>`. `python3 -m cedit
<subcommand>` is the same entry point with the same arguments, so use
whichever you prefer — the module form is what you want when cedit is
installed in a virtualenv you'd rather not activate:
`/path/to/venv/bin/python3 -m cedit …`.

**Install cedit into an environment of its own.** `pipx` above does that for
you; a dedicated virtualenv does the same. The reason is the pins below:
`mdcore/utils.make_parser` appends *every installed* mdformat parser
extension, so the set of mdformat plugins in the environment is part of the
parser identity. A shared environment carrying other mdformat plugins can
move the hashes in your `.cedit/` state even though cedit's own pinned
dependencies were honoured.

Working on cedit itself rather than using it? Install from a clone instead:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # the parsing stack, pinned EXACTLY
venv/bin/pip install -e .                  # puts `cedit` on the venv's path
venv/bin/python3 -m pytest                 # 105 tests, no network, <2s
```

**The pins are load-bearing.** `requirements.txt` pins `markdown-it-py`,
`mdit-py-plugins`, `mdformat`, `mdformat-gfm`, `mdformat-frontmatter`,
`mdformat-footnote` and `linkify-it-py` to exact versions. Every hash in `.cedit/` — base document
hashes, overlay keys, conflict keys — is taken over that one parser
configuration. A minor upgrade can change what the parser emits, which silently
moves every hash and turns your next sync into a wall of false conflicts.
Upgrade one pin at a time and run the suite.

**Run from the repository root.** Tracked documents are addressed by a path
relative to the root, and the state directory is resolved from the working
directory. Running from a subdirectory does not error — it just finds no state:

```console
$ cd sub && cedit status
nothing tracked
```

cedit never fetches anything. Getting upstream onto your disk — a git submodule,
a subtree, `curl`, a vendoring script — is your transport. `--from` takes a
directory that mirrors your document paths, or a single file.
