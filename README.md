# cedit — continuous editing of vendored Markdown

Keep **local adaptations** of vendored Markdown alive across **upstream
updates**: a persistent block-level overlay, re-applied by 3-way structural
merge on the document's AST. Vendored a skill whose commands assume `bash`
but your environment runs `zsh`? Rewrite the fences once — every later
`sync` re-applies your rewrite over whatever upstream changed, and tells
you precisely (per block, with all three versions) when upstream touched
the same thing you did.

How to drive it: [USERGUIDE.md](USERGUIDE.md) — the full guide, with a
five-minute tour, a per-flag command reference, worked conflict resolutions
and troubleshooting. Design: [SPEC.md](SPEC.md). Grown out of the
`markdown-localization` research repo, whose pinned parser and Merkle-hash
diff engine are vendored in [`cedit/mdcore/`](cedit/mdcore/).

## Setup

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # the parsing stack is pinned EXACTLY — see the file
venv/bin/pip install -e .                  # puts `cedit` on the path so it runs from any directory
venv/bin/python3 -m pytest                 # 24 tests, no network
```

## Quickstart

Activate the venv (`source venv/bin/activate`), then run from the root of
the repository holding your vendored copies — a *different* repo than this
one, which is what the editable install above is for. State lives in
`.cedit/` (commit it — the base snapshots *are* the merge's memory).

```bash
# 1. start tracking (vendors the file if it doesn't exist yet)
python3 -m cedit snapshot skills/SKILL.md --from vendor/skills/SKILL.md

# 2. adapt the file in place — e.g. rewrite bash fences for zsh — then:
python3 -m cedit diff
# [edit opaque fence] #c564262de9cbba0f:0  sim=0.98
#     ctx  : 1. Discovery and healthcheck
#     base : bash "${CLAUDE_PLUGIN_ROOT}/.../ensure_local_env.sh" || exit 1
#     local: zsh "${CLAUDE_PLUGIN_ROOT}/.../ensure_local_env.sh" || exit 1

# 3. upstream evolved — merge it in (your edits re-apply, even across moves
#    and reflows; upstream changes to blocks you didn't touch flow in)
python3 -m cedit sync --from vendor
# skills/SKILL.md: 1 edit(s) reapplied, 1 block(s) updated from upstream, 1 conflict(s)
# [CONFLICT opaque fence] #c564262de9cbba0f:0
#     base    : bash ".../ensure_local_env.sh" || exit 1
#     upstream: bash ".../ensure_local_env.sh" --quiet || exit 1
#     local   : zsh ".../ensure_local_env.sh" || exit 1  (kept in the working file)

# 4. a conflict means upstream changed the very block you adapted — decide:
python3 -m cedit resolve skills/SKILL.md c564262de9cbba0f --show           # all three versions
python3 -m cedit resolve skills/SKILL.md c564262de9cbba0f --take local    # keep the adaptation
python3 -m cedit resolve skills/SKILL.md c564262de9cbba0f --take upstream # take upstream's text

python3 -m cedit status
# skills/SKILL.md: 2 local edit(s), 0 unresolved conflict(s); base 92b023942934d656 ...
```

Exit codes: `0` clean, `1` unresolved conflicts, `2` errors. A document
with open conflicts refuses to sync again until they're resolved, and the
working file always keeps *your* text on a conflict — resolution is
explicit, never a silent clobber.

Everything above in depth — every flag, every output line, the conflict
lifecycle end to end, the `.cedit/` layout and a troubleshooting table — is
in [USERGUIDE.md](USERGUIDE.md).

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
| `tests/` | merge matrix + end-to-end CLI lifecycle |
