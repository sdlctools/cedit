"""The 3-way structural merge — SPEC.md's merge matrix, executed.

Three revisions: **B** (base — the upstream the local copy was last synced
against), **L** (the user's working copy), **U** (the incoming upstream).
Two alignments — `align(B, L)` derives the local-edit overlay, `align(B, U)`
classifies upstream — and one pass over B's blocks decides everything:

| upstream fate | locally edited | outcome                                  |
| SAME / moved  | no             | (nothing)                                |
| SAME / moved  | yes            | REAPPLY — splice local text into U's node |
| EDITED        | no             | UPDATE — upstream text stands            |
| EDITED        | yes            | CONFLICT — keep local, record all three  |
| DELETED       | no             | (block gone, by construction)            |
| DELETED       | yes            | ORPHAN — a conflict flavor               |

The merged document is **U's tree** with splices — never assembled from
fragments — so upstream structure is preserved by construction, exactly the
reassembly invariant. Phase 1 supports local *replacements* only: a local
structural change (inserted, deleted or moved block) raises
`StructuralDrift` before anything is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .align import DELETED, EDITED, SAME, Fate, align
from .blocks import Block, ParsedDoc, parse_doc, render_verified

CONFLICT = "conflict"
ORPHAN = "orphan"


class StructuralDrift(RuntimeError):
    """The local copy differs from base in *structure*, not just content —
    phase 1 cannot merge that. `.changes` lists every offending block."""

    def __init__(self, doc_label: str, changes: list[str]):
        self.changes = changes
        detail = "\n  ".join(changes)
        super().__init__(
            f"{doc_label}: local structural changes are not supported yet "
            f"(phase 1 merges replacements only):\n  {detail}"
        )


@dataclass
class LocalEdit:
    """One locally replaced block, keyed by its *base* identity."""

    base_index: int
    kind: str
    node_type: str
    hash: str
    occurrence: int
    context: str
    base_text: str
    base_info: str
    local_text: str
    local_info: str
    sim: float

    @property
    def key(self) -> str:
        return f"{self.hash}:{self.occurrence}"

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "node_type": self.node_type,
            "hash": self.hash,
            "occurrence": self.occurrence,
            "context": self.context,
            "base_text": self.base_text,
            "base_info": self.base_info,
            "local_text": self.local_text,
            "local_info": self.local_info,
        }


@dataclass
class Conflict:
    """Both sides changed one block (or upstream deleted an edited one).

    Carries all three texts so resolution never needs history spelunking.
    `upstream_text` is None for an orphan — upstream deleted the block.
    """

    key: str            # base "<hash>:<occurrence>"
    reason: str         # CONFLICT | ORPHAN
    kind: str
    node_type: str
    context: str
    base_text: str
    base_info: str
    local_text: str
    local_info: str
    upstream_text: str | None
    upstream_info: str

    def as_dict(self) -> dict:
        return {
            "reason": self.reason,
            "kind": self.kind,
            "node_type": self.node_type,
            "context": self.context,
            "base_text": self.base_text,
            "base_info": self.base_info,
            "local_text": self.local_text,
            "local_info": self.local_info,
            "upstream_text": self.upstream_text,
            "upstream_info": self.upstream_info,
        }

    @classmethod
    def from_dict(cls, key: str, data: dict) -> "Conflict":
        return cls(key=key, **{k: data.get(k, "" if k != "upstream_text" else None)
                               for k in ("reason", "kind", "node_type", "context",
                                         "base_text", "base_info", "local_text",
                                         "local_info", "upstream_text",
                                         "upstream_info")})


@dataclass
class MergeResult:
    merged: str                       # the new working-copy Markdown
    upstream_canonical: str = ""      # canonical U — the next base snapshot
    upstream_doc_hash: str = ""       # Merkle root of canonical U
    reapplied: list[LocalEdit] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    unchanged: int = 0                # untouched on both sides
    moved: int = 0                    # upstream moved, local edit followed or none
    updated: int = 0                  # upstream change taken
    removed: int = 0                  # upstream deleted an unedited block
    inserted: int = 0                 # upstream-new blocks

    @property
    def orphans(self) -> list[Conflict]:
        return [c for c in self.conflicts if c.reason == ORPHAN]

    def as_text(self) -> str:
        parts = [f"{len(self.reapplied)} edit(s) reapplied",
                 f"{self.updated} block(s) updated from upstream"]
        if self.inserted:
            parts.append(f"{self.inserted} inserted")
        if self.removed:
            parts.append(f"{self.removed} removed")
        if self.moved:
            parts.append(f"{self.moved} moved")
        n_conf = len(self.conflicts)
        parts.append(f"{n_conf} conflict(s)" if n_conf else "no conflicts")
        return ", ".join(parts)


def _describe_structural(base_fates: list[Fate], base_blocks: list[Block],
                         inserted: list[Block]) -> list[str]:
    out = []
    for block, fate in zip(base_blocks, base_fates):
        if fate.status == DELETED:
            out.append(f"deleted {block.node_type} #{block.key}: "
                       f"{_snippet(block.compare_text)}")
        elif fate.moved:
            verb = "moved" if fate.status == SAME else "moved+edited"
            out.append(f"{verb} {block.node_type} #{block.key}: "
                       f"{_snippet(block.compare_text)}")
    out.extend(f"inserted {b.node_type}: {_snippet(b.compare_text)}"
               for b in inserted)
    return out


def _snippet(text: str, width: int = 60) -> str:
    flat = " ".join(text.split())
    return flat[:width] + ("…" if len(flat) > width else "")


def local_edits(base: ParsedDoc, local: ParsedDoc, *,
                doc_label: str = "<doc>") -> list[LocalEdit]:
    """Derive the overlay: what the user changed, relative to base.

    Raises StructuralDrift on any local insert/delete/move — the phase-1
    boundary, enforced here so *every* caller (snapshot, diff, sync) rejects
    the same way.
    """
    fates, inserted = align(base.blocks, local.blocks)
    structural = _describe_structural(fates, base.blocks, inserted)
    if structural:
        raise StructuralDrift(doc_label, structural)

    edits: list[LocalEdit] = []
    for index, (block, fate) in enumerate(zip(base.blocks, fates)):
        if fate.status != EDITED:
            continue
        other = fate.other
        edits.append(LocalEdit(
            base_index=index, kind=block.kind, node_type=block.node_type,
            hash=block.hash, occurrence=block.occurrence, context=block.context,
            base_text=block.text, base_info=block.info,
            local_text=other.text, local_info=other.info, sim=fate.sim,
        ))
    return edits


def merge(base_md: str, local_md: str, upstream_md: str, *,
          doc_label: str = "<doc>") -> MergeResult:
    """Merge upstream_md's changes with the local edits — SPEC.md §sync.

    Returns the merged document (upstream structure, local texts spliced) and
    the classification of every base block. Raises StructuralDrift if the
    local copy changed structurally, StructureMismatch if the merged render
    would corrupt block structure (never written in that case).
    """
    base = parse_doc(base_md)
    local = parse_doc(local_md)
    upstream = parse_doc(upstream_md)

    edits = {e.base_index: e for e in
             local_edits(base, local, doc_label=doc_label)}

    up_fates, up_inserted = align(base.blocks, upstream.blocks)

    result = MergeResult(merged="", upstream_canonical=upstream.canonical,
                         upstream_doc_hash=upstream.doc_hash)
    result.inserted = len(up_inserted)

    for index, (block, fate) in enumerate(zip(base.blocks, up_fates)):
        edit = edits.get(index)
        if fate.status == SAME:
            if fate.moved:
                result.moved += 1
            if edit is None:
                result.unchanged += 1
                continue
            _splice_or_conflict(upstream, edit, fate, result)
        elif fate.status == EDITED:
            if edit is None:
                result.updated += 1
                continue
            # Both sides changed it: keep the local text in the working file
            # (never clobber the adaptation), record all three versions.
            result.conflicts.append(_conflict(edit, fate, CONFLICT))
            _splice(upstream, edit, fate.other)
        else:  # DELETED upstream
            if edit is None:
                result.removed += 1
                continue
            result.conflicts.append(_conflict(edit, fate, ORPHAN))

    result.merged = render_verified(upstream, label=doc_label)
    return result


def _splice(doc: ParsedDoc, edit: LocalEdit, target: Block) -> bool:
    from .blocks import splice_block
    return splice_block(doc, target, edit.local_text, edit.local_info)


def _splice_or_conflict(doc: ParsedDoc, edit: LocalEdit, fate: Fate,
                        result: MergeResult) -> None:
    if _splice(doc, edit, fate.other):
        result.reapplied.append(edit)
    else:
        # Nothing to splice into (empty-cell unit) — degrade to a conflict
        # rather than dropping the edit silently.
        result.conflicts.append(_conflict(edit, fate, CONFLICT))


def _conflict(edit: LocalEdit, fate: Fate, reason: str) -> Conflict:
    other = fate.other
    return Conflict(
        key=edit.key, reason=reason, kind=edit.kind, node_type=edit.node_type,
        context=edit.context, base_text=edit.base_text, base_info=edit.base_info,
        local_text=edit.local_text, local_info=edit.local_info,
        upstream_text=None if reason == ORPHAN else other.text,
        upstream_info="" if reason == ORPHAN or other is None else other.info,
    )
