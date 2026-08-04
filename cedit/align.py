"""Aligning two block sequences — the pairing `tree_diff.plan` cannot give us.

`plan()` answers the localization question ("which units need the LLM") and
deliberately does not pair opaque blocks (a changed fence is just COPY) nor
distinguish duplicate occurrences (same source ⇒ same translation). The
merge needs both, so this module aligns the *flat block sequences* directly,
with the same machinery `tree_diff` uses per sibling level: LCS over Merkle
hashes, greedy best-first similarity pairing inside each replace window, a
global same-hash pass for moves, and a global fuzzy pass for moved-and-edited
blocks. Thresholds are `tree_diff`'s — one definition of "similar enough".
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .blocks import Block
from .mdcore import tree_diff

SAME = "SAME"
EDITED = "EDITED"
DELETED = "DELETED"


@dataclass
class Fate:
    """What became of one base block on the other side of an alignment."""

    status: str          # SAME | EDITED | DELETED
    moved: bool
    other: Block | None  # counterpart block (None when DELETED)
    sim: float


def _sim(a: Block, b: Block) -> float:
    if a.kind != b.kind or a.node_type != b.node_type:
        return 0.0
    return tree_diff.ratio(a.compare_text, b.compare_text)


def align(base: list[Block], other: list[Block]) -> tuple[list[Fate], list[Block]]:
    """Map every base block to its fate in `other`.

    Returns (fates parallel to `base`, blocks of `other` that are new).
    """
    fates: list[Fate | None] = [None] * len(base)
    used_other: set[int] = set()
    del_pool: list[int] = []
    ins_pool: list[int] = []

    sm = SequenceMatcher(None, [b.hash for b in base], [x.hash for x in other],
                         autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                fates[i1 + k] = Fate(SAME, False, other[j1 + k], 1.0)
                used_other.add(j1 + k)
        elif tag == "delete":
            del_pool.extend(range(i1, i2))
        elif tag == "insert":
            ins_pool.extend(range(j1, j2))
        else:  # replace — greedy best-first pairing inside the window
            scored = sorted(
                ((_sim(base[i], other[j]), i, j)
                 for i in range(i1, i2) for j in range(j1, j2)),
                key=lambda t: -t[0],
            )
            paired_i: set[int] = set()
            paired_j: set[int] = set()
            for score, i, j in scored:
                if score < tree_diff.SIM_THRESHOLD or i in paired_i or j in paired_j:
                    continue
                paired_i.add(i)
                paired_j.add(j)
                fates[i] = Fate(EDITED, False, other[j], score)
                used_other.add(j)
            # A 1-for-1 replacement of like with like is an edit regardless of
            # text similarity: `a` → `a-adapted` in a table cell scores 0.18,
            # but positional evidence is conclusive when the window holds
            # exactly one block on each side. (Translation never needed this —
            # a mis-split there just retranslates; here it would misread an
            # edit as structural drift.)
            if (i2 - i1, j2 - j1) == (1, 1) and i1 not in paired_i:
                a, b = base[i1], other[j1]
                if a.kind == b.kind and a.node_type == b.node_type:
                    paired_i.add(i1)
                    paired_j.add(j1)
                    fates[i1] = Fate(EDITED, False, b, _sim(a, b))
                    used_other.add(j1)
            del_pool.extend(i for i in range(i1, i2) if i not in paired_i)
            ins_pool.extend(j for j in range(j1, j2) if j not in paired_j)

    # Global move pass: a deleted and an inserted block with the same hash is
    # a move — content identical, wherever it landed.
    remaining_ins = [j for j in ins_pool if j not in used_other]
    by_hash: dict[str, list[int]] = {}
    for j in remaining_ins:
        by_hash.setdefault(other[j].hash, []).append(j)
    still_deleted: list[int] = []
    for i in del_pool:
        bucket = by_hash.get(base[i].hash)
        if bucket:
            j = bucket.pop(0)
            fates[i] = Fate(SAME, True, other[j], 1.0)
            used_other.add(j)
        else:
            still_deleted.append(i)

    # Global fuzzy pass: moved *and* edited — the CAT-tool fuzzy match, at
    # block granularity.
    leftover_ins = [j for j in remaining_ins if j not in used_other]
    scored = sorted(
        ((_sim(base[i], other[j]), i, j)
         for i in still_deleted for j in leftover_ins),
        key=lambda t: -t[0],
    )
    for score, i, j in scored:
        if score < tree_diff.FUZZY_THRESHOLD:
            break
        if fates[i] is not None or j in used_other:
            continue
        fates[i] = Fate(EDITED, True, other[j], score)
        used_other.add(j)

    for i, fate in enumerate(fates):
        if fate is None:
            fates[i] = Fate(DELETED, False, None, 0.0)

    inserted = [other[j] for j in range(len(other)) if j not in used_other]
    return fates, inserted  # type: ignore[return-value]
