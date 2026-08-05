"""The parsing core: the pinned parser and the Merkle-hash diff engine.

`utils` is the parser configuration; `tree_diff` the hashing, segmentation
and similarity engine. Everything in `.cedit/` state is keyed by these —
treat this package as frozen, change it only together with the pins in
`requirements.txt`, and prove the result with `tests/parser_contract.py`.
See `.claude/rules/hash-stability.md`.
"""
