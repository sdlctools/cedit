# Manual release

How to drive a release by hand from a local checkout with `gh` + `git`, for
the cases where `release.yml` cannot finish on its own. It mirrors that
workflow step for step, in the same order, with the same invariants — this
is the automation transcribed for a human, not a different process.

**This file is a reference, not an instruction set.** Like
[release-pipeline.md](release-pipeline.md) it is deliberately not
`@`-imported by `AGENTS.md` — read it when an automated release has stalled,
or when you already know the release you are about to cut carries workflow
changes.

Where the other documents stop:

| Document | Answers |
| --- | --- |
| [AGENTS.md](../../AGENTS.md) | branch naming, Jira keys, gitflow parents, the local pytest gate |
| [release-pipeline.md](release-pipeline.md) | what the three workflows do automatically, and how they break |
| **this file** | how to do the same thing by hand when they cannot |

## When you need this

### 1. The release changes a file under `.github/workflows/`

This is the common case, and it is not a misconfiguration — it cannot be
fixed inside this repo.

`release.yml`'s back-merge step merges `main` into `development`. When a
workflow file changed on both branches, that merge commit *updates a file
under `.github/workflows/`*, and the push is rejected:

```
! [remote rejected] development -> development (refusing to allow a GitHub App
  to create or update workflow `.github/workflows/<name>.yml` without
  `workflows` permission)
```

**`GITHUB_TOKEN` can never hold that permission.** `workflows` is not one of
the keys a workflow's `permissions:` block accepts — the valid set is
`actions`, `artifact-metadata`, `attestations`, `checks`, `code-quality`,
`contents`, `deployments`, `discussions`, `id-token`, `issues`, `packages`,
`pages`, `pull-requests`, `security-events`, `vulnerability-alerts`. Adding
`workflows: write` there does not grant the scope; it makes the file fail
validation, so the workflow stops running altogether. GitHub withholds
workflow-file write from `GITHUB_TOKEN` on purpose, so a workflow cannot
rewrite workflows and escalate its own privileges.

The only credentials that *can* push workflow files are a classic PAT with
the `workflow` scope, a fine-grained PAT or GitHub App with Workflows:
write, or **an ordinary SSH push by a human** — SSH is not an App or OAuth
token and is not subject to the restriction at all. This repo's remote is
SSH (`git@github.com:sdlctools/cedit.git`), which is why the manual path
works with no extra token.

This is also why the branch ruleset is not the problem here. That is a
separate gate, already handled — see *Preconditions* below.

### 2. Finishing a release that stalled part-way

`release.yml` runs its steps in one job, in order. A failure at step *n*
leaves steps 1…*n*−1 done and *n*+1…7 not done, and **re-running the job
does not work** — step 2 aborts on `Tag ... already exists`. Resume by hand
from where it stopped: see *Resuming a partial release*.

## Preconditions

Verify once; they rarely change.

| Requirement | Check | Notes |
| --- | --- | --- |
| `gh` authenticated | `gh auth status` | needs `repo`; `workflow` too if you ever push over HTTPS |
| SSH remote | `git remote -v` | `git@github.com:…`. An HTTPS remote pushes with an OAuth token and *is* subject to the workflow-scope rule |
| Ruleset bypass | `gh api repos/sdlctools/cedit/rulesets/20455647 --jq .current_user_can_bypass` | must be `always` — `main`/`development` are PR-only under the `direct-commit-protect-main` ruleset, and the manual sequence pushes to both directly |
| Build tooling | `venv/bin/python3 -m build --version` | `venv/bin/pip install build twine` if absent |
| PyPI API token | `~/.pypirc` or `$TWINE_PASSWORD` | **required** — see below |

### PyPI: Trusted Publishing does not work locally

`release.yml` uploads via Trusted Publishing (OIDC), which mints a
short-lived credential from the *runner's* identity. There is no local
equivalent — a laptop cannot present that identity. A manual upload needs a
real **PyPI API token** for the `cedit` project:

1. pypi.org → Account settings → API tokens → *Add API token*, scoped to
   the `cedit` project.
2. Either export it per-shell:
   ```bash
   export TWINE_USERNAME=__token__
   export TWINE_PASSWORD='pypi-AgEIcHlwaS5vcmc…'
   ```
   or put it in `~/.pypirc` (`chmod 600`):
   ```ini
   [pypi]
     username = __token__
     password = pypi-AgEIcHlwaS5vcmc…
   ```

The token is a long-lived secret on your machine. It does not go in the
repo, in CI secrets, or in a commit.

## Choosing a mode

Merging the release PR into `main` fires `release.yml` **whether or not you
intend to work by hand**. Two ways to deal with that:

**Mode A — let it run, finish what it could not** (recommended). The
automation does steps 1–6 correctly; only the back-merge and everything
after it fails. You pick up from there. Fewer manual steps, so fewer places
to get the version wrong.

**Mode B — full manual.** Disable the workflow before merging, so nothing
fires:

```bash
gh workflow disable "Release"
# ... merge the release PR into main via the UI or `gh pr merge` ...
gh workflow enable "Release"          # DO NOT SKIP
```

Leaving `Release` disabled means the *next* release silently does nothing —
no tag, no PyPI upload, no failed run to notice. Re-enable it in the same
sitting. `gh workflow list --all` shows the state; `Release` must read
`active`.

Disabling `Release` does not affect `Transition Jira Issue on PR Merge`,
which still fires on the same merge. That is intended.

## The sequence

Run from a clean checkout of the repo. Set the two variables once and the
rest is copy-paste.

### 0. Resolve the version

```bash
git fetch origin --tags --prune

# The version comes from the BRANCH NAME — release/sprint-<X.Y.Z>, no 'v'.
# For a hotfix/*, patch-bump `prev` instead.
NEXT=v0.1.7
HEAD_REF=release/sprint-0.1.7

# Previous release: latest PLAIN tag. --exclude '*-*' drops vX.Y.Z-dev.N,
# which `sort -V` would otherwise rank ABOVE the release it derives from.
PREV="$(git describe --tags --abbrev=0 --match 'v[0-9]*' --exclude '*-*')"
MERGE_SHA="$(git rev-parse origin/main)"     # the merge commit of the release PR

echo "prev=$PREV next=$NEXT sha=$MERGE_SHA"
```

`NEXT` must match the branch name exactly. The branch name is the source of
truth for a release's version — that single rule is what keeps the cut and
the release from disagreeing about what is shipping.

### 1. Tag the merge commit

```bash
git tag -a "$NEXT" -m "Release $NEXT" "$MERGE_SHA"
git push origin "$NEXT"
```

Never overwrite an existing tag. If it exists, the release already got this
far — skip to the step that has not run.

### 2. Publish the GitHub Release

```bash
gh release create "$NEXT" --title "$NEXT" \
  --generate-notes --notes-start-tag "$PREV"
```

Drop `--notes-start-tag` on the very first release, when `PREV` is empty.

### 3. Bump `pyproject.toml` on `main`

```bash
NEXT_NO_V="${NEXT#v}"
git checkout -B main origin/main
sed -i -E 's/^version = ".*"$/version = "'"${NEXT_NO_V}"'"/' pyproject.toml
grep -q "version = \"${NEXT_NO_V}\"" pyproject.toml   # fail loudly if the regex missed
git add pyproject.toml
git commit -m "chore: bump version to ${NEXT_NO_V}"
git push origin main
```

The regex is anchored at column zero and `version = ` appears exactly once
that way in `pyproject.toml`. Keep it that way, or this rewrites the wrong
field.

### 4. Build from the bumped tree, and verify

```bash
venv/bin/pip install --upgrade build twine
rm -rf dist build
venv/bin/python3 -m build

# Assert the built version IS the tag, before anything is uploaded.
ls -1 dist
test -f "dist/cedit-${NEXT_NO_V}-py3-none-any.whl"
test -f "dist/cedit-${NEXT_NO_V}.tar.gz"
test "$(find dist -maxdepth 1 -type f | wc -l)" -eq 2
venv/bin/python3 -m twine check dist/*
```

**Do not build before step 3.** At the tagged merge commit,
`pyproject.toml` still carries whatever `development` last stamped — a dev
version like `0.1.6-dev.5`. Build from that tree and you upload `0.1.6.dev5`,
which PyPI sorts *below* `0.1.6`, and **PyPI filenames are immutable**: the
version is burned, uncorrectable by re-uploading. Step 3 is the only point
at which the working tree holds the release version.

### 4b. Cut the docs version

`release.yml` does this immediately after the build, on `main`, and for the
same ordering reason: it touches only `website/`, which never reaches the
distribution, so it stays out of the bump→build pair.

```bash
git checkout main                    # still on main from step 3
cd website
npm ci
npm run docs:version -- "${NEXT_NO_V}"
cd ..
git add website/versioned_docs website/versioned_sidebars website/versions.json
git commit -m "docs: cut docs version ${NEXT_NO_V}"
git push origin main
```

Skip it if `website/versioned_docs/version-${NEXT_NO_V}` already exists — the
automated step guards on exactly that, and a second cut of the same version
fails. The snapshot is what a reader still on `${NEXT_NO_V}` will be served
after the *next* release moves the current docs on; cutting it late is
harmless, forgetting it means that reader silently gets a newer cedit's docs.

### 5. Back-merge `main` into `development`

The step the automation cannot do. `--no-ff` keeps the sync commit explicit
rather than fast-forwarding and hiding that `main` moved.

```bash
git fetch origin development
git checkout -B development origin/development
git merge --no-ff origin/main -m "chore: sync main into development after ${NEXT}"
# resolve conflicts here if any, then `git commit`
git push origin development
```

This push carries the workflow-file changes that rejected the runner. Over
SSH, as a human, it goes through.

Never force-push `development`. If the merge is a mess, abort
(`git merge --abort`), push a `sync/main-to-dev-${NEXT}` branch and open a
PR — the same fallback `release.yml` uses.

### 6. Delete the release branch

```bash
git push origin --delete "$HEAD_REF"
```

A stale release branch blocks the next `Cut release` run with
*Branch … already exists*.

### 7. Upload to PyPI

Last, deliberately. Its realistic failure is credentials, and running it
last means such a failure leaves everything else already done.

```bash
venv/bin/python3 -m twine upload dist/*
```

### 7b. Publish the docs site

In CI this is `release.yml`'s `publish-docs` job, and it runs the *same*
command this step does — so by hand you are not approximating the automation,
you are running it yourself. A by-hand release never runs `release.yml`, so
nothing dispatches on its own and this step is not optional:

```bash
gh workflow run "Docs site" --ref main
gh run list --workflow "Docs site" --limit 1
```

If the run fails at *Deploy* with *Get Pages site failed*, Pages was never
enabled: Settings → Pages → Source → **GitHub Actions**, then dispatch again.

### 8. Verify

```bash
git ls-remote --tags origin | grep "$NEXT"                    # tag pushed
gh release view "$NEXT" --json tagName,publishedAt            # release exists
curl -s https://pypi.org/pypi/cedit/json \
  | python3 -c "import sys,json; print(sorted(json.load(sys.stdin)['releases']))"
git rev-list --count origin/development..origin/main          # 0 => back-merge done
git show origin/development:pyproject.toml | grep '^version'  # carries the release version
gh workflow list --all | grep Release                         # 'active' if you used Mode B
git show origin/main:website/versions.json                    # newest entry is ${NEXT_NO_V}
curl -sI "https://sdlctools.github.io/cedit/" | head -1        # site is up
```

## Resuming a partial release

Find where it stopped, then run only the remaining steps above. Each check
is independent:

| Check | If it fails, run |
| --- | --- |
| `git ls-remote --tags origin \| grep "$NEXT"` | step 1 |
| `gh release view "$NEXT"` | step 2 |
| `git show origin/main:pyproject.toml \| grep '^version'` shows `${NEXT_NO_V}` | step 3 |
| `curl -s https://pypi.org/pypi/cedit/json` lists `${NEXT_NO_V}` | steps 4 + 7 |
| `git show origin/main:website/versions.json` lists `${NEXT_NO_V}` | step 4b |
| `git rev-list --count origin/development..origin/main` is `0` | step 5 |
| `git ls-remote --heads origin \| grep "$HEAD_REF"` is empty | step 6 |
| the site's version dropdown offers `${NEXT_NO_V}` | step 7b |

**Do not re-run the failed `release.yml` job to catch up.** Its first action
is to create the tag, which now exists, so it aborts before reaching the
steps you actually need.

## Invariants — do not violate these

1. **Build after the version bump, never from the tagged tree.** Step 4
   depends on step 3 having run. PyPI filenames are immutable, so this
   mistake cannot be undone — only abandoned by burning a version number.

2. **The branch name is the version.** `release/sprint-<X.Y.Z>`, no leading
   `v`. To ship a different version, rename or re-cut the branch; do not
   improvise a different `NEXT` here than the branch says. A manual release
   that disagrees with the branch name is indistinguishable later from a
   mistake.

3. **Re-enable `Release` if you disabled it** (Mode B). A disabled workflow
   fails silently and permanently, with no run to notice.

4. **Never force-push `main` or `development`.** Your bypass makes it
   possible, which is exactly why it is worth stating. Resolve divergence
   with a merge or a PR.

5. **The PyPI token stays on your machine.** Not in the repo, not in CI
   secrets, not in a commit. If it leaks, revoke it on pypi.org first and
   re-issue second.

## Failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `refusing to allow a GitHub App to create or update workflow` | the runner's `GITHUB_TOKEN`, which cannot hold the scope | this document — finish by hand from step 5 |
| `refusing to allow an OAuth App to create or update workflow` | you pushed over an **HTTPS** remote, not SSH | `git remote set-url origin git@github.com:sdlctools/cedit.git`, or re-auth `gh` with the `workflow` scope |
| `GH013: … Changes must be made through a pull request` | you are not covered by the ruleset bypass list | check `current_user_can_bypass`; add your role under Settings → Rules → `direct-commit-protect-main` |
| `Tag ... already exists` | the release got at least to step 1 | do not overwrite — resume from the first step that has not run |
| `twine upload`: `403 Invalid or non-existent authentication` | no token, wrong token, or username is not `__token__` | re-issue a project-scoped token; username is literally `__token__` |
| `twine upload`: `400 File already exists` | that exact version was already uploaded | nothing to do — PyPI cannot be overwritten; the release is published |
| Built filenames do not match `$NEXT` | built before the bump (invariant 1) | `rm -rf dist build`, redo steps 3–4. Nothing was uploaded, so the version is not burned |
| No `vX.Y.Z-dev.1` after the manual release | your back-merge push *does* trigger `Tag development with dev build` (unlike the runner's) — so you should normally see one | if absent, check the run; a `[skip ci]` tip suppresses it |
