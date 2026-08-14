---
slug: /userguide/appendix
sidebar_position: 19
---
# Appendix

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | clean — nothing to do, or everything merged |
| `1` | unresolved conflicts: a `sync` recorded them, or a `status` found them; or a file `md canonicalize --check` found not canonical |
| `2` | error — nothing was merged |

Per command:

| Code | `snapshot` | `diff` | `sync` | `status` | `resolve` |
| --- | --- | --- | --- | --- | --- |
| `0` | now tracking | reported | merged clean, or up to date | reported | settled, or `--show` |
| `1` | — | — | conflicts recorded | conflicts open | — |
| `2` | already tracked, bad path, unreadable `--from`, structural drift | nothing tracked, untracked doc, structural drift | nothing tracked, conflicts already open, missing upstream, structural drift, structure mismatch | untracked doc, missing base, missing working copy | no/ambiguous key, `--take local` on an orphan, block edited since |

And for the `md` group ([the `md` verbs](../command-reference/md-parser-views.md)):

| Code | `md canonicalize` | `md ast` / `md json` / `md blocks` | `md from-json` |
| --- | --- | --- | --- |
| `0` | written, or `--check` passed | printed | rendered |
| `1` | `--check` on a non-canonical file | — | — |
| `2` | missing file, `-i` on stdin | missing file | invalid JSON, wrong shape, not a token |

Two rules a CI script depends on: `1` never means "broken" and `2` never means
"needs a human". Within one `sync` run over several documents, `2` wins — an
error anywhere means the run's conflict count is not the whole story. `md
canonicalize --check` keeps that reading: unformatted is a thing a human
fixes, not a breakage.

**Warnings are outside this table.** The `$...$` math warning
([Limits, stated plainly](limits.md)) is stderr text and nothing else: it never
adds a code, never upgrades one, and a document that gained a math span still
returns what it returned before — preserving the math gave cedit nothing to
fail on. Anything that needs to fail a build gates on
`md canonicalize --check`.

## State layout

| Path | Contents | Committed |
| --- | --- | --- |
| `<doc>` | your working copy (**L**) | yes — it is the product |
| `.cedit/base/<doc>` | canonicalized base snapshot (**B**) | **yes** — the merge is impossible without it |
| `.cedit/manifest.json` | per-doc upstream, base hash, sync time, unresolved conflicts | yes |
| `.cedit/overlay.json` | derived local-edit overlay | yes, like a lockfile |

## `manifest.json` shape

```json
{
  "schema": "cedit-manifest/v1",
  "docs": {
    "<doc path>": {
      "upstream": "<--from as last given>",
      "base_doc_hash": "<16 hex chars>",
      "synced_at": "<UTC ISO-8601>",
      "conflicts": {
        "<hash>:<occurrence>": {
          "reason": "conflict | orphan",
          "kind": "opaque | unit",
          "node_type": "fence | paragraph | heading | td | th | front_matter | ...",
          "context": "<heading trail>",
          "base_text": "...", "base_info": "...",
          "local_text": "...", "local_info": "...",
          "upstream_text": "... | null (orphan)", "upstream_info": "..."
        }
      }
    }
  }
}
```

## `overlay.json` shape

```json
{
  "schema": "cedit-overlay/v1",
  "docs": {
    "<doc path>": {
      "derived_at": "<UTC ISO-8601>",
      "edits": [
        {
          "kind": "opaque | unit",
          "node_type": "fence | paragraph | ...",
          "hash": "<16 hex chars>",
          "occurrence": 0,
          "context": "<heading trail>",
          "base_text": "...", "base_info": "...",
          "local_text": "...", "local_info": "..."
        }
      ]
    }
  }
}
```

Both files serialize documents in sorted key order, UTF-8, `ensure_ascii=False`,
so diffs stay local and reviewable.

## Defaults and constants

| Thing | Value | Where |
| --- | --- | --- |
| state directory | `.cedit` | `state.DEFAULT_STATE_DIR` |
| manifest schema | `cedit-manifest/v1` | `state.MANIFEST_SCHEMA` |
| overlay schema | `cedit-overlay/v1` | `state.OVERLAY_SCHEMA` |
| hash width | 16 hex chars | `mdcore.tree_diff.hash_tree` |
| edit-pairing threshold | `0.4` | `mdcore.tree_diff.SIM_THRESHOLD` |
| fuzzy (moved+edited) threshold | `0.6` | `mdcore.tree_diff.FUZZY_THRESHOLD` |
| display clip width | 110 chars | `mdcore.tree_diff.WIDTH` |
| opaque node types | `fence`, `code_block`, `html_block`, `front_matter`, `hr` | `mdcore.tree_diff.OPAQUE` |
| unit node types | `heading`, `paragraph`, `th`, `td` | `mdcore.tree_diff.UNIT_PARENTS` |

## Things cedit deliberately will not do

- **Fetch upstream.** `--from` reads what is already on disk.
- **Write conflict markers into the document.** `=======` is a setext heading
  underline; a marked-up file would stop parsing as itself and every hash
  downstream would move.
- **Merge local structural changes.** Phase 1 is replacements only, and the
  refusal is per block with a report.
- **Clobber your text.** On a conflict the working file keeps the local version,
  always.
- **Rewrite `$...$` math.** It cannot parse it as math, but it preserves the
  span byte for byte on every write path. The one construct it cannot protect —
  a span in a table cell holding `\|` — is warned about on stderr first
  ([Limits, stated plainly](limits.md)).
- **Sync a document with open conflicts.** It would merge against a base you
  never accepted.
- **Commit anything.** The document and `.cedit/` are yours to commit, together.

## See also

| Document | What it covers |
| --- | --- |
| [README.md](https://github.com/sdlctools/cedit/blob/main/README.md) | the two-minute version: setup, quickstart, layout |
| [SPEC.md](../../SPEC.md) | the normative design — merge matrix, sync algorithm, state format, reuse rules, phases |
| [AGENTS.md](https://github.com/sdlctools/cedit/blob/main/AGENTS.md) | working on cedit itself: orientation, invariants, repo workflow |
| [ARCHITECTURE.md](../../ARCHITECTURE.md) | the implementation module by module, and the recipes for extending it |
| [cedit-canonicalization-reference.md](../../cedit-canonicalization-reference.md) | every Markdown element and how `cedit md canonicalize` transforms it, known caveats, and quick test commands |
