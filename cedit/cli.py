"""cedit — continuous editing of vendored Markdown (SPEC.md).

    cedit snapshot <doc> --from <upstream-file>
    cedit diff [<doc>...] [--unified]
    cedit sync [<doc>...] [--from <upstream dir-or-file>] [-n]
    cedit status [<doc>...]
    cedit resolve <doc> <hash[:occ]> --take local|upstream | --show
    cedit md canonicalize|ast|json|from-json|blocks [<file>|-]

One entry point (`python3 -m cedit` runs it too), the same subcommands for a
human and for CI. Exit codes: 0 clean, 1 conflicts recorded or found, 2 errors.

The five workflow subcommands are stateful — each opens `.cedit/` and talks
about tracked documents. The `md` group (`mdcli.py`) is not: those are
stateless views of the parsing core, and the only one that can return 1 is
`canonicalize --check`.
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys

from .blocks import StructureMismatch, canonicalise, parse_doc, splice_block, render_verified
from .mdcli import MarkdownCliError, add_md_group
from .mdcore import tree_diff
from .merge3 import ORPHAN, Conflict, StructuralDrift, local_edits, merge
from .state import State, StateError, norm_doc
from .store import atomic_write_text, read_text


# --------------------------------------------------------------------------
# Display
# --------------------------------------------------------------------------


def _pair(a: str, b: str) -> tuple[str, str]:
    return tree_diff._focus(a, b)


def _print_edit(edit) -> None:
    print(f"[edit {edit.kind} {edit.node_type}] #{edit.key}"
          + (f"  sim={edit.sim:.2f}" if edit.sim else ""))
    if edit.context:
        print(f"    ctx  : {edit.context}")
    if edit.base_info != edit.local_info:
        print(f"    info : {edit.base_info or '(none)'} -> {edit.local_info or '(none)'}")
    base_frag, local_frag = _pair(edit.base_text, edit.local_text)
    print(f"    base : {base_frag}")
    print(f"    local: {local_frag}")
    print()


def _print_conflict(doc: str, conflict: Conflict, *, full: bool = False) -> None:
    show = (lambda s: s) if full else (lambda s: tree_diff._clip(s or ""))
    print(f"[{conflict.reason.upper()} {conflict.kind} {conflict.node_type}] "
          f"#{conflict.key}")
    if conflict.context:
        print(f"    ctx     : {conflict.context}")
    print(f"    base    : {show(conflict.base_text)}")
    if conflict.reason == ORPHAN:
        print("    upstream: (deleted)")
    else:
        if conflict.base_info != conflict.upstream_info:
            print(f"    up info : {conflict.base_info or '(none)'} -> "
                  f"{conflict.upstream_info or '(none)'}")
        print(f"    upstream: {show(conflict.upstream_text or '')}")
    print(f"    local   : {show(conflict.local_text)}"
          + ("" if conflict.reason == ORPHAN else "  (kept in the working file)"))
    print(f"    resolve : cedit resolve {doc} "
          f"{conflict.key} --take local|upstream")
    print()


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def cmd_snapshot(args) -> int:
    state = State(state_dir=args.state_dir)
    doc = norm_doc(args.doc)
    if state.is_tracked(doc):
        print(f"{doc}: already tracked — use `cedit sync` to take a new "
              f"upstream revision", file=sys.stderr)
        return 2

    base = parse_doc(read_text(args.from_))
    doc_file = state.doc_path(doc)
    if os.path.exists(doc_file):
        local = parse_doc(read_text(doc_file))
        edits = local_edits(base, local, doc_label=doc)
    else:
        # Initial vendoring: the working copy starts as the canonical base.
        atomic_write_text(doc_file, base.canonical)
        edits = []

    state.write_base(doc, base.canonical)
    state.set_entry(doc, upstream=args.from_, base_doc_hash=base.doc_hash)
    state.save_manifest()
    state.set_overlay(doc, edits)
    state.save_overlay()
    print(f"{doc}: tracking (base {base.doc_hash}, from {args.from_}), "
          f"{len(edits)} local edit(s) recorded")
    return 0


def cmd_diff(args) -> int:
    state = State(state_dir=args.state_dir)
    docs = [norm_doc(d) for d in args.docs] or state.tracked()
    if not docs:
        print("nothing tracked — run `cedit snapshot` first", file=sys.stderr)
        return 2

    rc = 0
    for doc in docs:
        state.entry(doc)  # raises StateError when untracked
        base = parse_doc(state.read_base(doc), canonical=True)
        local = parse_doc(read_text(state.doc_path(doc)))
        if args.unified:
            sys.stdout.writelines(difflib.unified_diff(
                base.canonical.splitlines(keepends=True),
                local.canonical.splitlines(keepends=True),
                fromfile=f"base/{doc}", tofile=doc,
            ))
            continue
        try:
            edits = local_edits(base, local, doc_label=doc)
        except StructuralDrift as exc:
            print(exc, file=sys.stderr)
            rc = 2
            continue
        print(f"{doc}: {len(edits)} local edit(s)"
              + ("" if edits else " — in sync with base"))
        for edit in edits:
            _print_edit(edit)
    return rc


def _upstream_file(doc: str, entry: dict, from_arg: str | None) -> str:
    source = from_arg or entry.get("upstream", "")
    if not source:
        raise StateError(f"{doc}: no --from given and no upstream recorded")
    if os.path.isdir(source):
        return os.path.join(source, doc)
    return source


def cmd_sync(args) -> int:
    state = State(state_dir=args.state_dir)
    docs = [norm_doc(d) for d in args.docs] or state.tracked()
    if not docs:
        print("nothing tracked — run `cedit snapshot` first", file=sys.stderr)
        return 2
    if args.from_ and not os.path.isdir(args.from_) and len(docs) > 1:
        print("--from is a file but several documents are being synced — "
              "pass a directory, or one document", file=sys.stderr)
        return 2

    rc = 0
    any_conflicts = False
    for doc in docs:
        entry = state.entry(doc)
        if entry.get("conflicts"):
            print(f"{doc}: {len(entry['conflicts'])} unresolved conflict(s) — "
                  f"resolve them before syncing again", file=sys.stderr)
            rc = 2
            continue

        upstream_path = _upstream_file(doc, entry, args.from_)
        if not os.path.exists(upstream_path):
            print(f"{doc}: upstream file not found: {upstream_path}",
                  file=sys.stderr)
            rc = 2
            continue

        base_md = state.read_base(doc)
        upstream_md = canonicalise(read_text(upstream_path))
        if upstream_md == base_md:
            print(f"{doc}: up to date")
            continue

        try:
            result = merge(base_md, read_text(state.doc_path(doc)),
                           upstream_md, doc_label=doc)
        except (StructuralDrift, StructureMismatch) as exc:
            print(exc, file=sys.stderr)
            rc = 2
            continue

        print(f"{doc}: {result.as_text()}"
              + (" [dry run — nothing written]" if args.dry_run else ""))
        for conflict in result.conflicts:
            _print_conflict(doc, conflict)
        if result.conflicts:
            any_conflicts = True
        if args.dry_run:
            continue

        # Write ordering (SPEC.md): the working file BEFORE base/manifest.
        # A crash between the two leaves a merged working copy against the
        # old base — the next sync just re-derives it as local edits and
        # converges. The reverse order would record a sync that never
        # happened.
        atomic_write_text(state.doc_path(doc), result.merged)
        state.write_base(doc, result.upstream_canonical)
        state.set_entry(
            doc,
            upstream=args.from_ or entry.get("upstream", ""),
            base_doc_hash=result.upstream_doc_hash,
            conflicts={c.key: c.as_dict() for c in result.conflicts},
        )
        state.save_manifest()
        new_base = parse_doc(result.upstream_canonical, canonical=True)
        state.set_overlay(doc, local_edits(new_base, parse_doc(result.merged),
                                           doc_label=doc))
        state.save_overlay()

    if rc:
        return rc
    return 1 if any_conflicts else 0


def cmd_status(args) -> int:
    state = State(state_dir=args.state_dir)
    docs = [norm_doc(d) for d in args.docs] or state.tracked()
    if not docs:
        print("nothing tracked")
        return 0

    any_conflicts = False
    for doc in docs:
        entry = state.entry(doc)
        conflicts = entry.get("conflicts", {})
        any_conflicts = any_conflicts or bool(conflicts)
        try:
            edits = local_edits(
                parse_doc(state.read_base(doc), canonical=True),
                parse_doc(read_text(state.doc_path(doc))),
                doc_label=doc,
            )
            edit_note = f"{len(edits)} local edit(s)"
        except StructuralDrift:
            edit_note = "STRUCTURAL DRIFT (see `cedit diff`)"
        print(f"{doc}: {edit_note}, {len(conflicts)} unresolved conflict(s); "
              f"base {entry['base_doc_hash']} synced {entry['synced_at']} "
              f"(upstream: {entry.get('upstream') or 'unset'})")
    return 1 if any_conflicts else 0


def _match_conflict(conflicts: dict[str, Conflict], key: str) -> Conflict:
    hits = [k for k in conflicts
            if k == key or k.startswith(key.rstrip(":"))]
    if not hits:
        raise StateError(f"no conflict matches {key!r} "
                         f"(open ones: {', '.join(sorted(conflicts)) or 'none'})")
    if len(hits) > 1:
        raise StateError(f"{key!r} is ambiguous: {', '.join(sorted(hits))}")
    return conflicts[hits[0]]


def cmd_resolve(args) -> int:
    state = State(state_dir=args.state_dir)
    doc = norm_doc(args.doc)
    entry = state.entry(doc)
    conflict = _match_conflict(state.conflicts(doc), args.key)

    if args.show or not args.take:
        _print_conflict(doc, conflict, full=True)
        return 0

    if args.take == "local":
        if conflict.reason == ORPHAN:
            print(f"{doc} #{conflict.key}: upstream deleted this block — "
                  f"keeping it would be a structural edit (phase 2). Its text "
                  f"is preserved in the manifest; `--take upstream` accepts "
                  f"the deletion.", file=sys.stderr)
            return 2
        # The working file already holds the local text (the merge kept it);
        # dropping the record re-keys the edit to the new base on the next
        # overlay derivation — the `git rerere` move.
        del entry["conflicts"][conflict.key]
        state.save_manifest()
        _refresh_overlay(state, doc)
        print(f"{doc} #{conflict.key}: kept local text — it is now an "
              f"ordinary overlay edit against the new base")
        return 0

    # --take upstream
    if conflict.reason == ORPHAN:
        del entry["conflicts"][conflict.key]
        state.save_manifest()
        print(f"{doc} #{conflict.key}: upstream deletion accepted")
        return 0

    local = parse_doc(read_text(state.doc_path(doc)))
    target = next(
        (b for b in local.blocks
         if b.kind == conflict.kind and b.node_type == conflict.node_type
         and b.text == conflict.local_text and b.info == conflict.local_info),
        None,
    )
    if target is None:
        print(f"{doc} #{conflict.key}: the conflicted block is no longer in "
              f"the file as recorded (edited since?) — fix the text by hand, "
              f"then `resolve --take local`", file=sys.stderr)
        return 2
    splice_block(target, conflict.upstream_text or "", conflict.upstream_info)
    rendered = render_verified(local, label=doc)
    atomic_write_text(state.doc_path(doc), rendered)
    del entry["conflicts"][conflict.key]
    state.save_manifest()
    _refresh_overlay(state, doc)
    print(f"{doc} #{conflict.key}: upstream text taken")
    return 0


def _refresh_overlay(state: State, doc: str) -> None:
    state.set_overlay(doc, local_edits(
        parse_doc(state.read_base(doc), canonical=True),
        parse_doc(read_text(state.doc_path(doc))),
        doc_label=doc,
    ))
    state.save_overlay()


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cedit",
        description="Keep local adaptations of vendored Markdown alive "
                    "across upstream updates (see SPEC.md).",
    )
    parser.add_argument("--state-dir", default=None,
                        help="state directory (default: .cedit); ignored by "
                             "the stateless `md` subcommands")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("snapshot", help="start tracking a document")
    p.add_argument("doc")
    p.add_argument("--from", dest="from_", required=True,
                   help="the upstream revision this copy is based on")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("diff", help="show local edits against the base")
    p.add_argument("docs", nargs="*")
    p.add_argument("--unified", action="store_true",
                   help="plain unified diff of canonical base vs local")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("sync", help="3-way merge a new upstream revision in")
    p.add_argument("docs", nargs="*")
    p.add_argument("--from", dest="from_", default=None,
                   help="upstream directory (mirroring doc paths) or file; "
                        "default: each doc's recorded upstream")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="merge and report, write nothing")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("status", help="per-document overlay/conflict summary")
    p.add_argument("docs", nargs="*")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("resolve", help="settle one recorded conflict")
    p.add_argument("doc")
    p.add_argument("key", help="conflict key: <hash> or <hash>:<occurrence>")
    p.add_argument("--take", choices=("local", "upstream"), default=None)
    p.add_argument("--show", action="store_true",
                   help="print the three versions in full")
    p.set_defaults(func=cmd_resolve)

    add_md_group(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return args.func(args)
    except (StateError, StructuralDrift, StructureMismatch, MarkdownCliError,
            FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
