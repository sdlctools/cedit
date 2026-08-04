# AGENTS.md

Read this before touching the codebase. It is the single entrypoint for
**any** AI coding assistant working here; `CLAUDE.md` exists only to pull
this file in, so add project instructions here and nowhere else.

Depth lives elsewhere: [README.md](README.md) is the user-facing usage
(setup, quickstart, exit codes, layout), [SPEC.md](SPEC.md) is the normative
design (merge matrix, sync algorithm, state format, reuse rules, phases).
This file is the orientation and the rules — it does not restate either.

## What this is

`cedit` is a CLI that keeps **local adaptations of vendored Markdown** alive
across **upstream updates**. The adaptations are stored as a persistent
block-level overlay, re-applied on every update by a 3-way structural merge
over the document's AST rather than over lines. Vendor a skill whose fences
assume `bash` in a `zsh` environment, rewrite them once, and every later
`sync` re-applies the rewrite over whatever upstream changed — or reports a
precise, per-block conflict when upstream touched the same block you did.

## Build, test, run

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # the parsing stack is pinned EXACTLY — see below
venv/bin/pip install -e .                  # only needed to run cedit from another repo, not for tests
venv/bin/python3 -m pytest                 # 24 tests, no network, <1s
venv/bin/python3 -m pytest tests/test_merge3.py -k reapply   # one test / one file
venv/bin/python3 -m cedit --help           # the CLI
```

`conftest.py` at the repo root exists so that pytest puts the repository
root on `sys.path` and the `cedit` package imports **without installation** —
which is why the test lines above work whether or not you ran the editable
install.

Use `venv/bin/python3`, not a bare `python3` — the interpreter needs the
pinned parsing stack, so a bare `python3 -m cedit` fails on
`ModuleNotFoundError`. README.md's quickstart writes plain `python3 -m cedit`
because it assumes an activated venv (`source venv/bin/activate`) and the
editable install; that is the same interpreter by another name. Tests do not
need the editable install — the root `conftest.py` covers them.

## Architecture

| Module | Responsibility |
| --- | --- |
| `cedit/cli.py` | the five subcommands — snapshot / diff / sync / status / resolve — plus exit-code policy |
| `cedit/merge3.py` | the merge matrix executed: REAPPLY / UPDATE / CONFLICT / ORPHAN per base block |
| `cedit/align.py` | flat block-sequence alignment: LCS over Merkle hashes, similarity pairing, move and fuzzy passes |
| `cedit/blocks.py` | block extraction (inline units + opaque blocks), splicing, render-and-verify |
| `cedit/state.py` | `.cedit/` — base snapshots, manifest (+ conflicts), derived overlay |
| `cedit/store.py` | atomic writes: temp file in the target dir + `rename(2)` |
| `cedit/mdcore/` | **vendored, frozen** from markdown-localization: `utils` (pinned parser), `tree_diff` (hashing, segmentation, similarity) |
| `cedit/__main__.py` | `python3 -m cedit` entry — delegates to `cli.main` |
| `tests/` | `test_merge3.py` (the merge matrix), `test_cli.py` (end-to-end lifecycle) |

A `sync` flows in one direction: **parse** B (base), L (local working copy)
and U (incoming upstream) into block sequences → **align** L against B (the
local-edit overlay) and U against B (what upstream did) → **decide** every
base block through the merge matrix → **splice** the REAPPLY/resolved-local
texts into U's tree → **render and verify** (re-parse the rendered output,
refuse to write if block structure moved) → **write** the working file
first, then `.cedit/` state.

## Invariants — do not violate these

1. **`cedit/mdcore/` is vendored and frozen.** It is a copy of the
   markdown-localization repo's parser and diff engine. Do not refactor,
   reformat or "improve" it: a change to hashing or segmentation moves every
   hash already recorded in consumers' `.cedit/` state. Changes belong
   upstream and arrive here as a re-vendoring. See *Reuse rules* in SPEC.md.

2. **The parsing stack in `requirements.txt` is pinned exactly on purpose.**
   Every hash in `.cedit/` state — base doc hashes, overlay keys, conflict
   keys — is taken over the one parser configuration in
   `mdcore/utils.make_parser`, which *is* those packages. A minor upgrade can
   change what the parser emits, silently moving every hash and turning the
   next sync into a wall of false conflicts. Upgrade one pin at a time and
   run the suite.

3. **Conflict handling is explicit, never a silent clobber.** On conflict the
   working file keeps the **local** text and all three versions (base,
   upstream, local) are recorded in state, so nothing is lost and resolution
   needs no history spelunking. A document with open conflicts refuses to
   sync again until they are resolved — otherwise a second sync would merge
   against a base the user never accepted.

4. **Exit codes are contract**, for humans and for CI alike: `0` clean, `1`
   unresolved conflicts (recorded by a sync or found by a status), `2`
   errors. Do not collapse 1 into 2 or into 0; a CI job distinguishes "needs
   a human" from "broken".

5. **Phase 1 merges replacements only.** Local *structural* changes —
   inserting, deleting or moving whole blocks — are detected and rejected
   with a per-block report **by design**, not as a bug to patch casually. The
   merged document's structure always comes from upstream and the splice is
   the only mutation; that invariant is what makes the vendored machinery
   reusable. Structural local edits are phase 2 in SPEC.md.

## Repo workflow

Gitflow: `development` is the base branch, `main` is production. Branches are
named `feature/<KEY>-<slug>` or `hotfix/<KEY>-<slug>` and are **provisioned by
the jira-sdlc skills, not by hand**; each carries a
`branch.<name>.parentbranch` git config entry that is its PR base. Commit
subjects lead with the Jira key (`CED-7 Add ...`).

`.github/workflows/` holds gitflow release automation, Jira transition on
merge, and the AI PR reviewer. **There is no CI test job** — the local
`venv/bin/python3 -m pytest` run is the gate. Run it before every commit.
