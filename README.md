# cedit — continuous editing of vendored Markdown

[![PyPI](https://img.shields.io/pypi/v/cedit)](https://pypi.org/project/cedit/)
[![Python versions](https://img.shields.io/pypi/pyversions/cedit)](https://pypi.org/project/cedit/)
[![Tests](https://github.com/sdlctools/cedit/actions/workflows/tests.yml/badge.svg)](https://github.com/sdlctools/cedit/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/pypi/l/cedit)](https://github.com/sdlctools/cedit/blob/main/LICENSE)

Keep **local adaptations** of vendored Markdown alive across **upstream
updates**: a persistent block-level overlay, re-applied by 3-way structural
merge on the document's AST. Vendored a skill whose commands assume `bash`
but your environment runs `zsh`? Rewrite the fences once — every later
`sync` re-applies your rewrite over whatever upstream changed, and tells
you precisely (per block, with all three versions) when upstream touched
the same thing you did.

## Documentation

| Document | What's in it |
| --- | --- |
| [USERGUIDE.md](https://github.com/sdlctools/cedit/blob/main/USERGUIDE.md) | **How to drive it** — a five-minute tour, a per-flag reference for all five subcommands, the conflict lifecycle worked end to end, the `.cedit/` layout, a cookbook and a troubleshooting table |
| [SPEC.md](https://github.com/sdlctools/cedit/blob/main/SPEC.md) | **The design** — the merge matrix, the normative sync algorithm, the state format, the reuse rules, and what is phase 1 vs. phase 2 vs. never |
| [AGENTS.md](https://github.com/sdlctools/cedit/blob/main/AGENTS.md) | **Changing cedit itself** — build and test commands, the architecture in one table, and the five invariants a change must not violate. `CLAUDE.md` exists only to pull this in, so every AI assistant reads the same file |
| [.claude/rules/cedit-source-map.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/cedit-source-map.md) | **The code, module by module** — every function, dataclass field and constant, the end-to-end call graph from `cli.main` down to the splice, and where each invariant is actually enforced |
| [.claude/rules/release-pipeline.md](https://github.com/sdlctools/cedit/blob/main/.claude/rules/release-pipeline.md) | **How this repo ships** — the two tag shapes, the dev-build / cut / release flow end to end, who owns the version at each step, the five workflow invariants, and a failure-mode table |

Using cedit? You want USERGUIDE.md. The last three are for working *on* it.

cedit grew out of the `markdown-localization` research repo, whose pinned
parser and Merkle-hash diff engine are vendored — frozen — in
[`cedit/mdcore/`](https://github.com/sdlctools/cedit/tree/main/cedit/mdcore/).

## Install

```bash
pipx install cedit   # or: pip install cedit
cedit --help
```

That installs the `cedit` command **and** the importable package with the
pinned parsing stack as real dependencies. The docs write `cedit
<subcommand>` throughout; `python3 -m cedit <subcommand>` is the same entry
point with the same arguments, and is what you want when cedit lives in a
virtualenv you'd rather not activate.

**Install cedit into an environment of its own** — that's what `pipx` above
buys you; a dedicated virtualenv does the same. `mdcore/utils.make_parser`
appends *every installed* mdformat parser extension, so the set of mdformat
plugins present in the environment is part of the parser identity. Dropping
cedit into a shared environment that already carries other mdformat plugins
can move the hashes in your `.cedit/` state even though cedit's own pins are
honoured — and moved hashes read as conflicts against blocks nobody touched.

### Working on cedit itself

Developing *cedit* rather than using it? Work from a source checkout:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # the parsing stack is pinned EXACTLY — see the file
venv/bin/pip install -e .                  # optional: only to run cedit from another repo
venv/bin/python3 -m pytest                 # 28 tests, no network
```

## Quickstart

Run from the root of the repository holding your vendored copies — a
*different* repo than this one. State lives in `.cedit/` (commit it — the
base snapshots *are* the merge's memory).

```bash
# 1. start tracking (vendors the file if it doesn't exist yet)
cedit snapshot skills/SKILL.md --from vendor/skills/SKILL.md

# 2. adapt the file in place — e.g. rewrite bash fences for zsh — then:
cedit diff
# [edit opaque fence] #c564262de9cbba0f:0  sim=0.98
#     ctx  : 1. Discovery and healthcheck
#     base : bash "${CLAUDE_PLUGIN_ROOT}/.../ensure_local_env.sh" || exit 1
#     local: zsh "${CLAUDE_PLUGIN_ROOT}/.../ensure_local_env.sh" || exit 1

# 3. upstream evolved — merge it in (your edits re-apply, even across moves
#    and reflows; upstream changes to blocks you didn't touch flow in)
cedit sync --from vendor
# skills/SKILL.md: 1 edit(s) reapplied, 1 block(s) updated from upstream, 1 conflict(s)
# [CONFLICT opaque fence] #c564262de9cbba0f:0
#     base    : bash ".../ensure_local_env.sh" || exit 1
#     upstream: bash ".../ensure_local_env.sh" --quiet || exit 1
#     local   : zsh ".../ensure_local_env.sh" || exit 1  (kept in the working file)

# 4. a conflict means upstream changed the very block you adapted — decide:
cedit resolve skills/SKILL.md c564262de9cbba0f --show           # all three versions
cedit resolve skills/SKILL.md c564262de9cbba0f --take local    # keep the adaptation
cedit resolve skills/SKILL.md c564262de9cbba0f --take upstream # take upstream's text

cedit status
# skills/SKILL.md: 2 local edit(s), 0 unresolved conflict(s); base 92b023942934d656 ...
```

Exit codes: `0` clean, `1` unresolved conflicts, `2` errors. A document
with open conflicts refuses to sync again until they're resolved, and the
working file always keeps *your* text on a conflict — resolution is
explicit, never a silent clobber.

Everything above in depth — every flag, every output line, the conflict
lifecycle end to end, the `.cedit/` layout and a troubleshooting table — is
in [USERGUIDE.md](https://github.com/sdlctools/cedit/blob/main/USERGUIDE.md).

## What it will not do (yet)

- Local **structural** changes — inserting, deleting or moving whole
  blocks — are detected and rejected with a per-block report (phase 2 in
  the spec). Phase 1 merges *replacements*: prose rewrites, fence
  rewrites, table-cell tweaks, front-matter edits.
- Fetching upstream. `--from` takes a directory (mirroring your doc
  paths) or a file; git submodules, subtrees or curl are your transport.

## Layout

| Path | |
| --- | --- |
| `cedit/__main__.py` | the `python3 -m cedit` entry point |
| `cedit/cli.py` | the five subcommands: snapshot / diff / sync / status / resolve |
| `cedit/merge3.py` | the 3-way merge matrix + overlay derivation |
| `cedit/align.py` | block-sequence alignment (LCS over Merkle hashes, moves, fuzzy) |
| `cedit/blocks.py` | block extraction, splicing, render-and-verify |
| `cedit/state.py` | `.cedit/` — base snapshots, manifest (+ conflicts), overlay |
| `cedit/store.py` | atomic writes: temp file + `rename(2)`, so a crash never leaves half-written state |
| `cedit/mdcore/` | **vendored, frozen**: pinned parser + tree_diff from markdown-localization |
| `tests/` | merge matrix + end-to-end CLI lifecycle + packaging metadata |
| `pyproject.toml` | packaging metadata: the exact runtime pins, the `cedit` console script, explicit package discovery |
| `.github/workflows/tests.yml` | the suite on 3.10 – 3.13, installed from `requirements.txt` |

## Status

**Alpha** (`Development Status :: 3 - Alpha`). The merge is phase 1: it
re-applies *replacements* — prose, fences, table cells, front matter — and
**rejects local structural changes** (inserting, deleting or moving whole
blocks) with a per-block report rather than guessing. Structural local edits
are phase 2 in
[SPEC.md](https://github.com/sdlctools/cedit/blob/main/SPEC.md). The CLI
surface, the exit codes and the `.cedit/` state format are what phase 2 will
build on, but nothing here is promised stable before 1.0 — pin the version if
that matters to you.

## License

MIT — see
[LICENSE](https://github.com/sdlctools/cedit/blob/main/LICENSE).
