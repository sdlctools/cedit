"""Aligning two block sequences — which block became which.

The merge is decided per block of the base document, so for every base block
it needs the one block on the other side that *is* that block: unchanged,
edited, moved, or gone. That is a pairing problem over the flat block
sequence `blocks.parse_doc` produces — opaque blocks (a rewritten code fence
is the motivating local edit) paired like any other, and two byte-identical
blocks kept distinct, because a user may have adapted only the third copy of
a repeated command.

Four passes, cheapest evidence first:

1. LCS over the blocks' Merkle hashes pairs everything that did not change
   and localises the rest into `replace` windows. Positional comparison
   would not do: inserting one block shifts every following one, and the
   whole tail would read as dirty.
2. Inside a window, greedy best-first similarity pairing above
   `SIM_THRESHOLD` — plus one positional rule, that a 1-for-1 replacement of
   a like-typed block is an edit whatever it scores.
3. A global same-hash pass over what is left: a deleted and an inserted
   block with the same hash is a move, wherever it landed.
4. A global fuzzy pass above `FUZZY_THRESHOLD` for blocks that were moved
   *and* edited — the one case no single window can see.

Hashes, the similarity scorer and both thresholds come from `tree_diff`: one
definition of "similar enough", and the same hashes `.cedit/` state records.
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
            # exactly one block on each side. Calling it unrelated instead
            # would report a delete plus an insert — structural drift, which
            # phase 1 rejects — where the user only rewrote a cell.
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

    # Global fuzzy pass: a block upstream moved *and* edited — the one case no
    # single window can see. "Fuzzy" in `FUZZY_THRESHOLD`'s CAT-tool sense.
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
