# Release pipeline

Operational reference for the three workflows that version this repo:
`tag-development-rc.yml` (dev builds), `cut-release.yml` (release cut) and
`release.yml` (tag, publish, back-merge, cleanup). It covers what fires
what, who owns the version number at each step, and the failure modes that
are not obvious from reading the YAML.

**This file is a reference, not an instruction set.** Like
[cedit-source-map.md](cedit-source-map.md) it is deliberately not
`@`-imported by `AGENTS.md` — read it when you are about to touch
`.github/workflows/`, cut a release, or explain why a release did not
happen.

Where the other documents stop:

| Document | Answers |
| --- | --- |
| [AGENTS.md](../../AGENTS.md) | branch naming, Jira keys, gitflow parents, the local pytest gate |
| the SDLC policy | *why* the phases exist (feature freeze, QA on the branch, hotfix path) |
| [manual-release.md](manual-release.md) | how to drive the same release by hand when the automation cannot finish |
| **this file** | what the automation actually does, and how it breaks |

## The version space

Two tag shapes, and the difference matters to every version query in the
pipeline:

| Shape | Created by | On | Meaning |
| --- | --- | --- | --- |
| `vX.Y.Z` | `release.yml` | the merge commit on `main` | a real release; a GitHub Release exists |
| `vX.Y.Z-dev.N` | `tag-development-rc.yml` | a commit on `development` | a dev build; `X.Y.Z` is the *last* release, `N` counts pushes since |

`X.Y.Z` in a dev tag never moves on its own. It is pinned to the newest
plain release tag and only changes when a real release ships, at which
point `N` restarts from 1.

Both version-resolving workflows therefore filter to **plain** tags —
`cut-release.yml:61-64` (`grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$'`) and
`release.yml:73` (`--exclude '*-*'`). This is not cosmetic: `sort -V` ranks
`v0.1.0-dev.4` *above* `v0.1.0`, so an unfiltered "latest tag" would feed a
prerelease into SemVer arithmetic that rejects it, and the release cut would
fail. Any new tag query in these files must keep the filter.

## The flow, end to end

```
push to development ──► tag-development-rc.yml
                        stamp pyproject + commit + tag vX.Y.Z-dev.N       (loop, per push)

human runs "Cut release" (bump: patch|minor|major)
                     ──► cut-release.yml
                        latest plain tag + bump  ─► X.Y.Z
                        branch release/sprint-X.Y.Z off development
                        empty commit "chore: cut release/sprint-X.Y.Z"    ◄── load-bearing, see below
                        draft PR into main

QA on the branch (fix PRs into release/sprint-X.Y.Z, never features)

human marks the draft PR ready and merges it into main
                     ──► release.yml
                        version from the BRANCH NAME (not a tag, not a label)
                        tag vX.Y.Z on the merge commit
                        gh release create (notes from the previous plain tag)
                        bump pyproject on main, push
                        build sdist+wheel from the BUMPED tree, verify, twine check
                        back-merge main -> development (PR on conflict)
                        delete release/sprint-X.Y.Z
                        upload dist/ to PyPI (Trusted Publishing, OIDC)
```

A `hotfix/*` PR merged into `main` enters the same `release.yml` at the
same point, differing only in version resolution: no branch-name parse, a
forced patch bump off the latest plain tag (`release.yml:108-128`). A
hotfix before the first release is an error, by design.

## Who owns the version number

| Step | Source of truth |
| --- | --- |
| dev build | latest plain tag + `-dev.<N+1>` — derived, never authored |
| release cut | latest plain tag + the dispatch `bump` input |
| release | **the branch name**, `release/sprint-<X.Y.Z>`, no leading `v` |
| hotfix | latest plain tag, patch-bumped |

`release.yml:89-92` accepts exactly one spelling and fails loudly on
anything else — no fallback to tag arithmetic, no PR label. To ship a
different version, rename or re-cut the branch. That single rule is why the
cut and the release cannot disagree about what is being shipped.

## Invariants — do not violate these

### 1. The release branch's tip commit must not carry a CI skip marker

`cut-release.yml:110` adds an empty `chore: cut release/sprint-X.Y.Z`
commit. **It is load-bearing, not cosmetic.** Delete it and the release
pipeline silently stops working.

`tag-development-rc.yml:103` commits the dev stamp with `[skip ci]` in the
message, so `development`'s tip almost always carries that marker. A branch
cut off `development` with no commits of its own inherits that commit *as
its own tip*. GitHub reads the skip marker off the **HEAD commit of the
pull_request event**, so merging such a PR into `main` emits **no workflow
runs at all** — not `release.yml`, not the Jira transition, nothing. No
tag, no GitHub Release, no version bump, no back-merge, no branch delete,
and no failed run to notice. The empty commit clears the marker.

Verified by A/B on throwaway branches: bot-authored (GITHUB_TOKEN) PRs,
drafts marked ready, and human PRs all fire normally; a `[skip ci]` tip
fires nothing; the same branch plus one empty commit fires again.

Corollaries:

- **Never put the literal skip marker in a commit subject that can become a
  PR head tip.** A commit that merely *describes* the marker suppresses its
  own PR's runs. This bit the very commit that fixed it.
- If `[skip ci]` is ever removed from `tag-development-rc.yml`, the cut
  commit may go too — but not before, and the two comments cross-reference
  each other for that reason.
- **`tests.yml` must not become a required status check** while the marker
  is in play. It is not one of the three versioning workflows and touches
  nothing here, but it is subject to the same suppression: a required check
  on a PR that emits no runs never *fails*, it never *reports*, which
  branch protection treats as pending forever — an unmergeable PR with no
  failed run to point at. The exposure is narrow (feature branches carry
  their own commits, and the cut commit clears the marker for release
  branches), but "narrow" and "safe" are not the same thing. The workflow's
  own header comment says this too, so whoever flips the setting reads it
  from either end.

### 2. Pushes made by `GITHUB_TOKEN` do not trigger workflows

A human merging a token-created PR *does* trigger them; a `git push` from
inside a workflow does not. Consequences in this pipeline:

- `release.yml:217`'s back-merge to `development` creates **no** dev build.
  The first `vX.Y.Z-dev.1` of the new cycle appears on the next ordinary
  push, not on the sync commit.
- `release.yml:203`'s version-bump push to `main` triggers nothing either.
- If a workflow ever needs to trigger another workflow, it needs a PAT or a
  GitHub App token, not `secrets.GITHUB_TOKEN` — see the auth note at
  `release.yml:15-20`.

### 3. The dev-build loop is broken by the marker, and only by it

`tag-development-rc.yml` pushes to the branch that triggers it. Three
things keep that from looping: `[skip ci]` on the stamp commit, the
already-tagged guard (`tag-development-rc.yml:49`), and the
`tag-development-dev` concurrency group that serializes runs. The marker is
the primary stop. Removing it makes the guard the only stop, and a failure
between the commit push and the tag push then becomes an infinite commit
loop — which is why the fix for invariant 1 went into `cut-release.yml`
instead.

### 4. Every workflow declares its own `permissions:` block

The repository default for `GITHUB_TOKEN` is **read**. Nothing in these
three workflows relies on that default, and nothing new should: a workflow
that omits the block cannot tag, push, or open a PR, and fails at the first
write with a permission error.

### 5. `gh pr create --draft` needs the org/repo setting

"Allow GitHub Actions to create and approve pull requests" must stay ON, or
`cut-release.yml`'s draft PR step fails. Same setting covers
`release.yml`'s conflict-path sync PR.

### 6. The PyPI build must run *after* the version bump, never on the tagged tree

`release.yml` tags the merge commit **before** it bumps `pyproject.toml`,
and `cut-release.yml` never stamps `pyproject.toml` at all — only
`tag-development-rc.yml` and `release.yml` do. So at the commit that gets
tagged `vX.Y.Z`, `pyproject.toml` still carries whatever `development` last
stamped: a dev version like `0.1.2-dev.5`.

Build from that tree and you upload `0.1.2.dev5`, which PyPI sorts *below*
`0.1.2` rather than above it — and **PyPI filenames are immutable**, so the
mistake cannot be corrected by re-uploading or re-running. The version is
burned.

Hence the build step sits immediately after *Bump pyproject.toml*, which is
the only point in the job where the working tree holds the release version,
and it asserts that `dist/` contains exactly `cedit-<X.Y.Z>-py3-none-any.whl`
and `cedit-<X.Y.Z>.tar.gz` before anything is uploaded. Any step that moves
the build earlier, or points it at `merge_commit_sha`, reintroduces this.

The **upload** is deliberately the last step of the job, after the
back-merge and the branch delete. Its realistic failure is the OIDC
exchange, which a human fixes on pypi.org; running it last means that
failure leaves everything else already done. Trusted Publishing also needs
`id-token: write` in the workflow's `permissions:` block (invariant 4) and a
**pending publisher** configured on pypi.org for this repository *and this
workflow filename* — rename `release.yml` and the OIDC exchange stops
matching.

## Failure modes and what they mean

| Symptom | Cause | Fix |
| --- | --- | --- |
| Release PR merged, **zero** runs on the merge | head tip carries a skip marker (invariant 1) | re-cut the branch so its tip is the `chore: cut` commit; recover the missed release as below |
| `Release` runs but fails at *Resolve version* | branch is not `release/sprint-<X.Y.Z>` — a leading `v`, a suffix, a rename | rename or re-cut the branch; do not patch the regex |
| `Cut release` fails: *Branch … already exists* | a previous release never completed, so `release.yml` never deleted it | delete the stale branch, then re-run the cut |
| `gh pr create`: *No commits between …* | `main` already contains everything on the cut branch | the `chore: cut` commit prevents this; if seen, the commit was removed |
| `Release` fails: *Tag … already exists* | the same version was released, or a tag was pushed by hand | do not overwrite; re-cut at the next version |
| Back-merge opened a PR instead of pushing | `main` and `development` diverged | resolve the sync PR by hand — never force-push `development` |
| `Release` fails at *Back-merge*: *refusing to allow a GitHub App to create or update workflow … without `workflows` permission* | the release changed a file under `.github/workflows/`, and `GITHUB_TOKEN` **cannot** hold that scope — it is not a valid `permissions:` key, and adding one breaks the file's validation | not fixable in CI: finish the release by hand from the back-merge onward — [manual-release.md](manual-release.md) |
| No `vX.Y.Z-dev.1` after a release | invariant 2, not a bug | it appears on the next push to `development` |
| `Release` fails at *Publish to PyPI*, everything else done | no pending publisher on pypi.org for this repo + workflow, or the OIDC exchange was refused | configure the Trusted Publisher, then upload `dist/` by hand from a checkout of `main` (which carries the bumped version) — do **not** re-run the job, the tag step would fail |
| `Release` fails at *Build sdist + wheel and verify* | the built version does not match the tag — the build ran against a tree that was not bumped (invariant 6) | fix the step order; nothing was uploaded, so the version is not burned |

### Recovering a release that never fired

The pipeline is idempotent enough to just re-run once the branch is sane:

1. `git push origin --delete release/sprint-<X.Y.Z>` — the stale branch
   blocks the next cut.
2. Re-run **Cut release** with the same bump. The version is derived from
   the latest plain tag, so a missed release does not skip a number.
3. Merge the new draft PR. `release.yml` tags, publishes the GitHub
   Release, bumps, builds, back-merges, cleans up and uploads to PyPI.

`main` having already received the content is fine: the cut commit
guarantees a non-empty diff, and the tag lands on the new merge commit.
