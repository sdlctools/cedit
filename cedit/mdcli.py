"""`cedit md` — stateless views of the frozen parsing core.

The five workflow subcommands in `cli.py` are all stateful: every one of
them opens `.cedit/` and talks about *tracked* documents. These are the
opposite — pure functions from a file (or stdin) to stdout, touching no
state, so `--state-dir` means nothing to them.

They exist because `cedit/mdcore/` is otherwise unobservable. It is frozen
precisely because every hash in every consumer's `.cedit/` is a function of
it, and `.claude/rules/hash-stability.md` says the danger is that a change
there is *quiet* — the only instruments were `tests/parser_contract.py`, on
one fixed fixture, and ad-hoc `python3 -c`. These verbs point the real
parser at any document: what its canonical form is (`canonicalize` — the
bytes `.cedit/base/` would hold), what the parser saw (`ast`, `json`), and
what the merge would key on (`blocks` — kind, Merkle hash and occurrence,
i.e. exactly what a conflict key names).

Exit codes stay the contract of AGENTS.md invariant 4, and nothing here
invents a third meaning for 1: only `canonicalize --check` returns it, for
"a human needs to look at this file". Everything else is 0 or 2.
"""

from __future__ import annotations

import json
import sys

from markdown_it.token import Token
from markdown_it.tree import SyntaxTreeNode

from .blocks import OPAQUE, UNIT, canonicalise, parse_doc
from .linkguard import warn_link_refs
from .mathguard import warn_fragile_math
from .mdcore import tree_diff
from .mdcore.utils import ast_to_markdown, markdown_to_ast
from .rowguard import warn_row_overflow
from .store import atomic_write_text, dumps, read_text

# The conventional stdin spelling, so these verbs compose in a pipeline.
STDIN = "-"

# Enough of a node's own text to recognise it by; the tree dump is meant to
# be skimmed, and `blocks` is where full text belongs.
PREVIEW = 60


class MarkdownCliError(RuntimeError):
    """Bad input to a `cedit md` verb — reported by `cli.main` as exit 2."""


# --------------------------------------------------------------------------
# Input / display helpers
# --------------------------------------------------------------------------


def _read(path: str) -> str:
    return sys.stdin.read() if path == STDIN else read_text(path)


def _label(path: str) -> str:
    return "<stdin>" if path == STDIN else path


def _tree(md: str, *, raw: bool) -> SyntaxTreeNode:
    """Parse to a hashed tree.

    `raw` parses the file exactly as it sits on disk; the default
    canonicalises first, which is what cedit itself always does — so the
    hashes printed here are the hashes `.cedit/` would record. Comparing the
    two is how you see what the mdformat round-trip actually changed.
    """
    root = SyntaxTreeNode(markdown_to_ast(md if raw else canonicalise(md)))
    tree_diff.hash_tree(root)
    return root


def _kind(node: SyntaxTreeNode) -> str:
    """UNIT / OPAQUE / "" — whether the merge treats this node as a block."""
    if tree_diff.is_unit(node):
        return UNIT
    return OPAQUE if node.type in tree_diff.OPAQUE else ""


def _preview(text: str) -> str:
    body = tree_diff.norm(text)
    return f'"{body[:PREVIEW]}…"' if len(body) > PREVIEW else f'"{body}"'


# --------------------------------------------------------------------------
# Verbs
# --------------------------------------------------------------------------


def cmd_md_canonicalize(args) -> int:
    source = _read(args.file)
    # Stderr, in every mode — the exit code is untouched, and `--check`'s 1
    # is the more useful signal for a CI job either way.
    warn_fragile_math(source, _label(args.file))
    warn_link_refs(source, _label(args.file))
    warn_row_overflow(source, _label(args.file))
    canonical = canonicalise(source)

    if args.check:
        if canonical == source:
            return 0
        print(f"{_label(args.file)}: not canonical", file=sys.stderr)
        return 1

    if args.in_place:
        if args.file == STDIN:
            raise MarkdownCliError("--in-place needs a file, not stdin")
        if canonical == source:
            print(f"{args.file}: already canonical")
            return 0
        atomic_write_text(args.file, canonical)
        print(f"{args.file}: canonicalised")
        return 0

    sys.stdout.write(canonical)
    return 0


def cmd_md_ast(args) -> int:
    root = _tree(_read(args.file), raw=args.raw)

    def walk(node: SyntaxTreeNode, depth: int) -> None:
        if node.type != "root":
            parts = [node.type]
            tag = tree_diff.attr(node, "tag")
            if tag and tag != node.type:
                parts.append(tag)
            info = tree_diff.attr(node, "info")
            if info:
                parts.append(f"info={info}")
            kind = _kind(node)
            if kind:
                parts.append(f"[{kind}]")
            if args.hashes:
                parts.append(f"#{node.h}")
            text = tree_diff.own_text(node)
            if text:
                parts.append(_preview(text))
            print("  " * (depth - 1) + " ".join(parts))
        for child in node.children:
            walk(child, depth + 1)

    walk(root, 0)
    return 0


def _node_json(node: SyntaxTreeNode) -> dict:
    out: dict = {"type": node.type}
    if node.type != "root":
        out["tag"] = tree_diff.attr(node, "tag")
        out["info"] = tree_diff.attr(node, "info")
        out["content"] = tree_diff.own_text(node)
        out["hash"] = node.h
        kind = _kind(node)
        if kind:
            out["kind"] = kind
    out["children"] = [_node_json(c) for c in node.children]
    return out


def cmd_md_json(args) -> int:
    source = _read(args.file)
    if args.tree:
        payload = _node_json(_tree(source, raw=args.raw))
    else:
        payload = [t.as_dict() for t in
                   markdown_to_ast(source if args.raw else canonicalise(source))]
    sys.stdout.write(dumps(payload))
    return 0


def _token(obj) -> Token:
    """Rebuild one `Token` from `Token.as_dict()` output.

    Recursively, which is the whole subtlety: `Token(**d)` leaves `children`
    as a list of *dicts*, and the failure surfaces much later inside
    mdformat's renderer as `'dict' object has no attribute 'nesting'`.
    """
    if not isinstance(obj, dict):
        raise MarkdownCliError(f"expected a token object, got {type(obj).__name__}")
    fields = dict(obj)
    children = fields.get("children")
    fields["children"] = [_token(c) for c in children] if children else None
    try:
        return Token(**fields)
    except TypeError as exc:
        raise MarkdownCliError(f"not a markdown-it token: {exc}") from exc


def cmd_md_from_json(args) -> int:
    text = _read(args.file)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MarkdownCliError(f"{_label(args.file)}: invalid JSON — {exc}") from exc
    if not isinstance(payload, list):
        raise MarkdownCliError(
            f"{_label(args.file)}: expected a token stream as emitted by "
            f"`cedit md json`, got a {type(payload).__name__} — the `--tree` "
            f"shape is for reading, not for rebuilding")
    sys.stdout.write(ast_to_markdown([_token(t) for t in payload]))
    return 0


def cmd_md_blocks(args) -> int:
    doc = parse_doc(_read(args.file))

    if args.json:
        sys.stdout.write(dumps({
            "doc_hash": doc.doc_hash,
            "blocks": [{
                "key": b.key,
                "hash": b.hash,
                "occurrence": b.occurrence,
                "kind": b.kind,
                "node_type": b.node_type,
                "info": b.info,
                "context": b.context,
                "text": b.text,
            } for b in doc.blocks],
        }))
        return 0

    print(f"{_label(args.file)}: {len(doc.blocks)} block(s), doc {doc.doc_hash}")
    for block in doc.blocks:
        print(f"[block {block.kind} {block.node_type}] #{block.key}")
        if block.context:
            print(f"    ctx  : {block.context}")
        if block.info:
            print(f"    info : {block.info}")
        print(f"    text : {tree_diff._clip(block.text)}")
        print()
    return 0


# --------------------------------------------------------------------------
# Argument parsing — the `md` group, wired in by `cli.build_arg_parser`
# --------------------------------------------------------------------------


def _add_file(parser, *, help_suffix: str = "") -> None:
    parser.add_argument("file", nargs="?", default=STDIN,
                        help=f"Markdown file, or `-` for stdin (default){help_suffix}")


def _add_raw(parser) -> None:
    parser.add_argument("--raw", action="store_true",
                        help="parse the input as-is instead of canonicalising "
                             "it first; the default is what cedit itself sees")


def add_md_group(sub) -> None:
    """Attach the `md` subcommand group to `cli`'s subparser action."""
    group = sub.add_parser(
        "md",
        help="stateless parser views: canonicalize / ast / json / blocks",
        description="Views of the parsing core that touch no `.cedit/` state "
                    "(so --state-dir is ignored). Exit codes: 0 ok, 1 only "
                    "from `canonicalize --check`, 2 errors.",
    )
    verbs = group.add_subparsers(dest="md_command", required=True)

    p = verbs.add_parser("canonicalize",
                         help="the mdformat round-trip — the bytes .cedit/base/ holds")
    _add_file(p)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("-i", "--in-place", action="store_true",
                      help="rewrite the file (atomically) instead of writing stdout")
    mode.add_argument("--check", action="store_true",
                      help="write nothing; exit 1 if the input is not already canonical")
    p.set_defaults(func=cmd_md_canonicalize)

    p = verbs.add_parser("ast", help="indented tree dump of what the parser saw")
    _add_file(p)
    _add_raw(p)
    p.add_argument("--hashes", action="store_true",
                   help="annotate every node with its Merkle hash")
    p.set_defaults(func=cmd_md_ast)

    p = verbs.add_parser("json", help="the same, as JSON")
    _add_file(p)
    _add_raw(p)
    shape = p.add_mutually_exclusive_group()
    shape.add_argument("--tokens", action="store_true",
                       help="flat markdown-it token stream (default) — the "
                            "lossless shape, accepted back by `md from-json`")
    shape.add_argument("--tree", action="store_true",
                       help="nested tree with hashes; for reading, not rebuildable")
    p.set_defaults(func=cmd_md_json)

    p = verbs.add_parser("from-json",
                         help="render a token stream from `md json` back to Markdown")
    _add_file(p, help_suffix=" holding a token stream")
    p.set_defaults(func=cmd_md_from_json)

    p = verbs.add_parser("blocks",
                         help="the edit blocks the merge keys on, with hashes")
    _add_file(p)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_md_blocks)
