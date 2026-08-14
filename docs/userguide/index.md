---
slug: /userguide
sidebar_label: User guide
sidebar_position: 1
---

# `cedit` user guide

A practical guide to `cedit/cli.py`, the command line that keeps your local
adaptations of vendored Markdown alive across upstream updates. This is the
*how-to*: worked examples, real output, and the flows you will actually run.
For the *why* behind the design, read [SPEC.md](../SPEC.md); for a two-minute
overview, [README.md](https://github.com/sdlctools/cedit/blob/main/README.md).

Every command and every block of output below was run for real — against this
repository or a throwaway directory — and pasted unedited.

![cedit compares document ASTs and tracks the changes between them](../../assets/ast-trees-comparison-and-changes-tracking.png)

## Contents

**Getting started** — what cedit is doing, and a first run end to end.

- [The mental model](getting-started/mental-model.md)
- [Prerequisites](getting-started/prerequisites.md)
- [Five-minute tour](getting-started/five-minute-tour.md)

**Command reference** — every subcommand, every flag, with real output.

- [The five subcommands](command-reference/index.md)
- [Global options](command-reference/global-options.md)
- [`snapshot`, `diff` and `sync`](command-reference/snapshot-diff-sync.md)
- [`status` and `resolve`](command-reference/status-resolve.md)
- [`md` — stateless parser views](command-reference/md-parser-views.md)

**How it works** — what the merge keys on, and why it survives a reflow.

- [What cedit sees: blocks, hashes, keys](how-it-works/blocks-hashes-keys.md)
- [The merge matrix in practice](how-it-works/merge-matrix.md)
- [What alignment buys you](how-it-works/alignment.md)
- [The `.cedit/` state directory](how-it-works/state-directory.md)

**Task flows** — the three things you will actually do.

- [Vendoring a document](task-flows/vendoring.md)
- [Taking an upstream update](task-flows/upstream-update.md)
- [A conflict, end to end](task-flows/conflict-end-to-end.md)

**Help** — the limits, the recipes, and what a message means.

- [Limits, stated plainly](help/limits.md)
- [Cookbook](help/cookbook.md)
- [Troubleshooting](help/troubleshooting.md)
- [Appendix](help/appendix.md)

______________________________________________________________________

New to cedit? Read [The mental model](getting-started/mental-model.md), then
run the [five-minute tour](getting-started/five-minute-tour.md). Everything
else is reference you can come back to.
