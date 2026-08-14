# AGENTS.md

Read this before touching the codebase. It is the single entrypoint for
**any** AI coding assistant working here; `CLAUDE.md` exists only to pull
this file in, so add project instructions here and nowhere else.

Depth lives elsewhere: [README.md](README.md) is the user-facing usage
(setup, quickstart, exit codes, layout), [the user guide](docs/userguide/) is the
task-oriented how-to (command reference, flows, conflict lifecycle,
troubleshooting), [SPEC.md](docs/SPEC.md) is the normative design (merge matrix,
sync algorithm, state format, reuse rules, phases), and
[ARCHITECTURE.md](docs/ARCHITECTURE.md) is the code-level map of the
implementation (every module's functions, dataclasses and constants, the
call graph, where each invariant below is enforced, and the change recipes
plus hash blast radius for extending it) — **read it before changing
code.**
[.claude/rules/release-pipeline.md](.claude/rules/release-pipeline.md) does
the same for the three versioning workflows (dev builds, release cut,
release) — read it before touching `.github/workflows/` or cutting a
release, and
[.claude/rules/manual-release.md](.claude/rules/manual-release.md) is the
by-hand runbook for the releases that automation cannot finish (any release
that changes a workflow file). [.claude/rules/hash-stability.md](.claude/rules/hash-stability.md)
is the runbook for invariants 1 and 2 below: changing the parser, the diff
engine or the pins without silently moving every hash in every consumer's
state, and the drift check that proves you did not. This file is the
orientation and the rules — it does not restate any of them.

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
venv/bin/python3 -m pytest                 # 105 tests, no network, <2s
venv/bin/python3 -m pytest tests/test_merge3.py -k reapply   # one test / one file
venv/bin/python3 -m cedit --help           # the CLI
```

That is the flow for working **on** cedit. *Consumers* install the published
package instead — `pipx install cedit`, which also puts a `cedit` console
script on PATH (`[project.scripts]` in `pyproject.toml`); README.md leads
with that. The editable install above now installs the same console script,
so `venv/bin/cedit` works too.

`conftest.py` at the repo root exists so that pytest puts the repository
root on `sys.path` and the `cedit` package imports **without installation** —
which is why the test lines above work whether or not you ran the editable
install.

Use `venv/bin/python3`, not a bare `python3` — the interpreter needs the
pinned parsing stack, so a bare `python3 -m cedit` fails on
`ModuleNotFoundError`. README.md and the user guide write plain `cedit`
because they address someone who installed the published package; here that
same entry point is `venv/bin/cedit` or `venv/bin/python3 -m cedit`. Tests
do not need the editable install — the root `conftest.py` covers them.

Packaging and publishing live in `pyproject.toml` (metadata, the exact
runtime pins, explicit `cedit` + `cedit.mdcore` discovery) and in
`release.yml`'s build/verify/publish steps — see
[.claude/rules/release-pipeline.md](.claude/rules/release-pipeline.md)
before touching either.

## Architecture

| Module | Responsibility |
| --- | --- |
| `cedit/cli.py` | the five subcommands — snapshot / diff / sync / status / resolve — plus exit-code policy |
| `cedit/mdcli.py` | the `md` group — stateless parser views (canonicalize / ast / json / from-json / blocks), the only window onto the frozen core |
| `cedit/merge3.py` | the merge matrix executed: REAPPLY / UPDATE / CONFLICT / ORPHAN per base block |
| `cedit/align.py` | flat block-sequence alignment: LCS over Merkle hashes, similarity pairing, move and fuzzy passes |
| `cedit/blocks.py` | block extraction (inline units + opaque blocks), splicing, render-and-verify |
| `cedit/mathguard.py` | the `$...$` math guard — protects spans canonicalisation would rewrite behind a sentinel and restores them afterwards, so they survive byte-exact; warns on **stderr only** about the few it cannot locate, never touching the exit code |
| `cedit/rowguard.py` | the table-row guard — lifts what a body row carries past the header's last column out of the source before the parse (which would discard it) and appends it back onto its row after the render, byte-exact; **hash-neutral by construction and by check**, and warns on stderr like `mathguard` about the rows it cannot lift |
| `cedit/state.py` | `.cedit/` — base snapshots, manifest (+ conflicts), derived overlay |
| `cedit/store.py` | atomic writes: temp file in the target dir + `rename(2)` |
| `cedit/mdcore/` | **frozen**: `utils` (the pinned parser), `tree_diff` (hashing, segmentation, similarity) — every recorded hash is a function of these |
| `cedit/__main__.py` | `python3 -m cedit` entry — delegates to `cli.main` |
| `tests/` | `test_merge3.py` (the merge matrix), `test_cli.py` (end-to-end lifecycle), `test_mdcli.py` (the `md` group), `test_mathguard.py` (math-guard precision, both columns re-measured each run), `test_rowguard.py` (table-row preservation, detection precision, and the hash-neutrality claim), `test_packaging.py` (version resolution, pin drift, README link absoluteness, docs kept out of the distribution), `test_parser_contract.py` (the drift check — invariant 2, enforced) |
| `docs/` | the **published** documents — the user guide (`userguide/`, split into chapters), `SPEC.md`, `ARCHITECTURE.md`, `cedit-canonicalization-reference.md`. Plain Markdown, rendered by the site, not rewritten for it |
| `website/` | the Docusaurus site that publishes `docs/` — its own `package.json`, config, sidebar, landing page and `.gitignore`; never part of the sdist or the wheel. See *The docs site* below |

A `sync` flows in one direction: **parse** B (base), L (local working copy)
and U (incoming upstream) into block sequences → **align** L against B (the
local-edit overlay) and U against B (what upstream did) → **decide** every
base block through the merge matrix → **splice** the REAPPLY/resolved-local
texts into U's tree → **render and verify** (re-parse the rendered output,
refuse to write if block structure moved) → **write** the working file
first, then `.cedit/` state.

## The docs site

`docs/` is published at **<https://sdlctools.github.io/cedit/>** by the
Docusaurus site in `website/`. Docusaurus *renders* Markdown, it does not
replace it: every document under `docs/` is still a plain `.md` file that
reads correctly on GitHub and in an editor, and nothing here is written in
another format.

**What is published, and what deliberately is not.** Everything in `docs/`
is. `AGENTS.md`, `CLAUDE.md` and `.claude/rules/` are not, and they stay at
the repository root: they are read by AI tooling from fixed paths —
`CLAUDE.md` `@`-imports `AGENTS.md`, the rules files are opened by relative
path — and publishing them serves no reader. `README.md` also stays, because
it is the PyPI long description (`readme = "README.md"`).

**The user guide is a directory, not a file.** `docs/userguide/` holds an
index page and 19 chapters in five groups, each group a subdirectory with a
`_category_.json`. It was one 2,200-line file until CED-32; the split is what
makes the left sidebar a table of contents instead of a single entry. Order
comes from `sidebar_position` in each page's front matter and `position` in
each `_category_.json` — `website/sidebars.js` autogenerates from those, so
a new chapter is added by creating one file, in one place.

**Slugs are flat, and that is deliberate.** A chapter at
`docs/userguide/help/limits.md` is served at `/docs/userguide/limits`, not
`/docs/userguide/help/limits`, because every page sets an explicit `slug:`.
The grouping is an editorial decision about the sidebar and may be
reorganised; the URL is printed into a user's terminal by `mathguard`,
`rowguard` and `linkguard` and must survive that. Move a chapter between
groups freely — keep its slug.

**Four link rules**, and a build failure or a silent 404 is what breaks when
one is ignored:

- *Between published docs* — relative (`](../SPEC.md)`). Docusaurus rewrites
  those to site routes, and `markdown.hooks.onBrokenMarkdownLinks: 'throw'`
  fails the build if one stops resolving. Mind the depth: a guide chapter is
  two levels below `docs/`.
- *Between guide chapters* — relative too (`](../help/limits.md)`), never the
  published URL. The relative form is what Docusaurus can check.
- *From a published doc to an unpublished one* — absolute
  `https://github.com/sdlctools/cedit/blob/main/…`. There is no site route to
  point at.
- *In `README.md`* — absolute, and pointing at the **site** for everything
  under `docs/`. `tests/test_packaging.py::test_readme_links_are_absolute`
  enforces the first half; nothing can enforce the second, so a `blob/main/`
  URL to a moved file 404s quietly.

**Do not cite a doc by line number.** ARCHITECTURE.md used to, and every one
of those citations broke the moment the guide moved. Name the page.

**An image a doc references lives under `docs/`.** `docusaurus docs:version`
snapshots that directory and nothing else, so an image outside it resolves in
the working tree and *not* in the snapshot — a hard build failure that first
appears in the release run, once the broken snapshot is already committed and
a cut version cannot be re-cut. v0.3.4 shipped that way, with the guide's
diagram at the repository root reached as `../../assets/`.
`tests/test_packaging.py::test_docs_images_resolve_from_inside_docs` scans
`docs/` and every cut version for it now.

Same rule for the paths cedit *prints*. A docstring or comment naming a
document uses the repo-relative path (`docs/SPEC.md`); anything that reaches
a user's terminal — the guards' stderr warnings, `cedit --help` — uses the
published URL, because that reader installed cedit and has no checkout.

```bash
cd website && npm ci && npm run build   # what CI builds; fails on a broken link
cd website && npm start                 # live reload against ../docs
```

**Versions are cut by the release, not by hand.** `release.yml` runs
`docusaurus docs:version <X.Y.Z>` on `main` after the version bump and the
PyPI build, then *dispatches* `docs.yml` against `main` to publish it — a
`GITHUB_TOKEN` push triggers no workflow (a dispatch always does), and a run
whose ref is not `main` is refused by the Pages environment. Invariant 7 in
[.claude/rules/release-pipeline.md](.claude/rules/release-pipeline.md) has
both halves and the design that got this wrong once. This matters
more here than on a typical library: a hash-moving release is a breaking
change to consumers' on-disk `.cedit/` state, and a reader on an older cedit
needs the docs that describe the parser their hashes were taken under.

**A release that changes `docs.yml` or `release.yml` cannot finish in CI.**
That is expected, not a defect — see the failure-mode table in
[.claude/rules/release-pipeline.md](.claude/rules/release-pipeline.md) and
finish it by hand from
[.claude/rules/manual-release.md](.claude/rules/manual-release.md).

**Pages must be enabled once, by a human**: Settings → Pages → Source →
*GitHub Actions*. Until then `docs.yml` fails at the deploy step.

## Invariants — do not violate these

1. **`cedit/mdcore/` is frozen.** It holds the parser (`utils`) and the
   hashing/segmentation engine (`tree_diff`), and every hash in every
   consumer's `.cedit/` state is a function of them. Do not refactor,
   reformat or "improve" it: a change to canonicalisation, hashing or
   segmentation moves hashes recorded on machines you will never see, and
   turns their next sync into a wall of false conflicts against blocks
   nobody touched. Deliberate changes are possible — they go through
   [.claude/rules/hash-stability.md](.claude/rules/hash-stability.md). See
   also *Reuse rules* in docs/SPEC.md.

2. **The parsing stack in `requirements.txt` is pinned exactly on purpose.**
   Every hash in `.cedit/` state — base doc hashes, overlay keys, conflict
   keys — is taken over the one parser configuration in
   `mdcore/utils.make_parser`, which *is* those packages, **plus whatever
   mdformat plugins are installed** — `make_parser` appends every one it
   finds, so an unrelated `pip install` can move every hash. A minor upgrade
   can change what the parser emits just as silently. Upgrade one pin at a
   time and run `venv/bin/python3 tests/parser_contract.py`; the rest of the
   suite cannot see a consistent hash move.

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
   reusable. Structural local edits are phase 2 in docs/SPEC.md.

## Repo workflow

Gitflow: `development` is the base branch, `main` is production. Branches are
named `feature/<KEY>-<slug>` or `hotfix/<KEY>-<slug>` and are **provisioned by
the jira-sdlc skills, not by hand**; each carries a
`branch.<name>.parentbranch` git config entry that is its PR base. Commit
subjects lead with the Jira key (`CED-7 Add ...`).

`.github/workflows/` holds gitflow release automation, Jira transition on
merge, the AI PR reviewer, and `tests.yml` — the suite on Python 3.10, 3.11,
3.12, 3.13 and 3.14, installed from `requirements.txt`, on every push to
`development`/`main` and every pull request, plus an advisory 3.15 leg that
reports but cannot fail the job.

**The matrix, the classifiers and `requires-python` are one list.** Claiming a
version no leg runs is the defect `tests.yml` was added to close, so change
all three in the same commit —
`tests/test_packaging.py::test_supported_pythons_are_the_tested_pythons`
fails if they drift. Advisory legs are excluded from that check by design:
they are not claimed support.

**`tests.yml` gates nothing.** It is not a required status check, on purpose:
a PR whose head commit carries `[skip ci]` emits *no* workflow runs at all
(invariant 1 in
[.claude/rules/release-pipeline.md](.claude/rules/release-pipeline.md)), so a
required check would never report and the PR would be permanently
unmergeable. Nor does it cover what a maintainer's machine does — it runs on
Linux only. **The local `venv/bin/python3 -m pytest` run is still the gate.
Run it before every commit;** CI's job is the version matrix you cannot run
locally.
