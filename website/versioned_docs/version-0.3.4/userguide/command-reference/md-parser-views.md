---
slug: /userguide/md
sidebar_label: md parser views
sidebar_position: 8
---
# `md` — stateless parser views

Everything above is stateful: it opens `.cedit/` and talks about tracked
documents. `cedit md` is the opposite — a file (or `-` for stdin) in, stdout
out, no state read or written, `--state-dir` ignored. Use it to see what the
parser does to a document, whether or not that document is tracked at all.

| Verb | Does |
| --- | --- |
| `md canonicalize [file]` | print the mdformat round-trip — the exact bytes `.cedit/base/` stores |
| `md ast [file]` | print the parse tree, indented |
| `md json [file]` | the same parse as JSON — the flat token stream, or `--tree` |
| `md from-json [file]` | render a token stream from `md json` back to Markdown |
| `md blocks [file]` | print the edit blocks the merge keys on, with their hashes |

Exit codes: `0`, `2` for errors, and `1` from `canonicalize --check` only.

### `md canonicalize`

Every example below runs against `vendor/skills/deploy.md` from the
[the five-minute tour](../getting-started/five-minute-tour.md), or against a file cut out of it, so the hashes
are the same ones you saw there.

```console
$ cedit md canonicalize vendor/skills/deploy.md > canonical.md   # to stdout
$ cedit md canonicalize -i skills/deploy.md                      # rewrite atomically
skills/deploy.md: already canonical
```

A tracked document reports `already canonical` because `snapshot` wrote it
canonical in the first place — `-i` earns its keep on documents cedit has never
seen. `messy.md` below is the tour's document as someone might have hand-written
it — setext headings, and the healthcheck indented rather than fenced:

```bash
cat > messy.md <<'EOF'
Deploy skill
============

Preflight
---------

    bash scripts/healthcheck.sh --strict
EOF
```

````console
$ cedit md canonicalize messy.md
# Deploy skill

## Preflight

```
bash scripts/healthcheck.sh --strict
```
$ cp messy.md scratch.md
$ cedit md canonicalize -i scratch.md
scratch.md: canonicalised
$ cedit md canonicalize -i scratch.md
scratch.md: already canonical
````

`--check` writes nothing at all and exits **1** when the input is not already
canonical — the shape a CI job or a pre-commit hook wants
([Cookbook](../help/cookbook.md) has the gate):

```console
$ cedit md canonicalize --check messy.md
messy.md: not canonical
$ echo $?
1
```

`-i` and `--check` are mutually exclusive, and `-i` needs a real file — the
file argument defaults to stdin, where there is nothing to rewrite in place
([Troubleshooting](../help/troubleshooting.md)).

`$...$` math survives all three modes byte for byte, so a document whose only
unusual feature is a `$\rightarrow$` is simply canonical — stdout stays the
canonical bytes and nothing else:

```console
$ cedit md canonicalize --check docs/GH-CLI.md
$ echo $?
0
```

See [Limits, stated plainly](../help/limits.md) for the one construct that is still
rewritten, and what to write instead of it.

### `md blocks`

The one to reach for when a key is a mystery. It prints the same
`<hash>:<occurrence>` addresses a conflict report prints and `resolve` takes —
note `#7b47884c75de548e:0`, the fence the tour adapts and later conflicts on.
The addresses are those of the document you point it at, so to read the ones
cedit is keyed to, point it at the base snapshot (`.cedit/base/<doc>`) or at
the upstream revision that base was taken from:

```console
$ cedit md blocks vendor/skills/deploy.md
vendor/skills/deploy.md: 7 block(s), doc 9ef5a0dbdc298d85
[block unit heading] #21c9f999ed623912:0
    text : Deploy skill

[block unit paragraph] #84cd52d314d7df83:0
    ctx  : Deploy skill
    text : This skill takes a build from the artifact store and puts it on staging.

[block unit heading] #bd367afe9f8a1d46:0
    ctx  : Deploy skill
    text : Preflight

[block unit paragraph] #806bee9eb45a7cc0:0
    ctx  : Preflight
    text : Run the healthcheck before anything else:

[block opaque fence] #7b47884c75de548e:0
    ctx  : Preflight
    info : bash
    text : bash scripts/healthcheck.sh --strict

[block unit heading] #ac2aee0b1c35c287:0
    ctx  : Preflight
    text : Deploy

[block opaque fence] #300a5f90b873e850:0
    ctx  : Deploy
    info : bash
    text : bash scripts/deploy.sh --env staging
```

The `doc 9ef5a0dbdc298d85` on the first line is the document hash `snapshot`
recorded in the tour. The `text` lines are clipped to keep the dump skimmable;
`--json` gives the same content machine-readably, with every block's text
untruncated — here, the one block the tour goes on to adapt:

```console
$ cedit md blocks --json vendor/skills/deploy.md \
    | jq '.blocks[] | select(.key == "7b47884c75de548e:0")'
{
  "key": "7b47884c75de548e:0",
  "hash": "7b47884c75de548e",
  "occurrence": 0,
  "kind": "opaque",
  "node_type": "fence",
  "info": "bash",
  "context": "Preflight",
  "text": "bash scripts/healthcheck.sh --strict\n"
}
```

The top level is `{"doc_hash": …, "blocks": [ … ]}`, one object per block in
document order, with `hash` and `occurrence` split out beside the `key` that
joins them. `text` is the block's exact text, trailing newline and all — the
`ctx` of the human dump is `context`, the heading trail the block sits under.

### `md ast` and `md json`

`md ast` marks which nodes are blocks (`[unit]` / `[opaque]`) and, with
`--hashes`, annotates every node with its Merkle hash. Non-block nodes
(`inline`, `text`) are hashed too — only the marked ones can carry an edit:

```console
$ cedit md ast --hashes vendor/skills/deploy.md
heading h1 [unit] #21c9f999ed623912
  inline #ab6b185c940f4549 "Deploy skill"
    text #e748d4cb302780c9 "Deploy skill"
paragraph p [unit] #84cd52d314d7df83
  inline #9dfe68ce256805b3 "This skill takes a build from the artifact store and puts it…"
    text #db19acb54f85b5c6 "This skill takes a build from the artifact store and puts it…"
heading h2 [unit] #bd367afe9f8a1d46
  inline #73670a1f9db979d3 "Preflight"
    text #418698cd26d4a38c "Preflight"
paragraph p [unit] #806bee9eb45a7cc0
  inline #767ec645d62c94a1 "Run the healthcheck before anything else:"
    text #013477f31375a242 "Run the healthcheck before anything else:"
fence code info=bash [opaque] #7b47884c75de548e "bash scripts/healthcheck.sh --strict"
heading h2 [unit] #ac2aee0b1c35c287
  inline #999cc16acd1eb9fb "Deploy"
    text #31d6651178022693 "Deploy"
fence code info=bash [opaque] #300a5f90b873e850 "bash scripts/deploy.sh --env staging"
```

Both canonicalise first by default, so the hashes shown are the hashes
`.cedit/` records. `--raw` parses the file exactly as it sits on disk, and
diffing the two is how you see what the round trip changed — on `messy.md`
from above:

```console
$ diff <(cedit md ast --raw --hashes messy.md) <(cedit md ast --hashes messy.md)
7c7
< code_block code [opaque] #6b17a57843ce0f7a "bash scripts/healthcheck.sh --strict"
---
> fence code [opaque] #e236e87c672f4a83 "bash scripts/healthcheck.sh --strict"
```

One line, out of seven. The setext headings are *not* on it: `Deploy skill`
underlined with `====` and `# Deploy skill` are the same node with the same own
text, so they hash identically — `#21c9f999ed623912`, the same hash the tour
prints. That is [Blocks, hashes, keys](../how-it-works/blocks-hashes-keys.md)'s "formatting churn
is free", measured. The indented code block is not churn: the round trip makes
it a *fence*, a different node type with a different hash, so the address cedit
will key it by is `#e236e87c672f4a83` and nothing in the file as written says
so. (`md blocks` has no `--raw`: raw hashes would match nothing in any
manifest.)

`md json` emits the flat markdown-it token stream by default — the same parse
as `md ast`, without the tree. The tour's Preflight fence, on its own:

```bash
sed -n '9,11p' vendor/skills/deploy.md > fence.md
```

````console
$ cat fence.md
```bash
bash scripts/healthcheck.sh --strict
```
$ cedit md json fence.md
[
  {
    "type": "fence",
    "tag": "code",
    "nesting": 0,
    "attrs": null,
    "map": [
      0,
      3
    ],
    "level": 0,
    "children": null,
    "content": "bash scripts/healthcheck.sh --strict\n",
    "markup": "```",
    "info": "bash",
    "meta": {},
    "block": true,
    "hidden": false
  }
]
````

One block, one token, every field markdown-it needs to render it back —
including `markup`, which the hash ignores and the renderer does not. That is
what makes the shape **lossless**, and it is the shape `md from-json` consumes.
`--tokens` spells that default out, for a pipeline that would rather say which
shape it means than rely on which one is default:

```console
$ diff <(cedit md json fence.md) <(cedit md json --tokens fence.md)
$ echo $?
0
```

`--tree` gives a nested shape instead, with `hash` and `kind` per node — the
same information `md ast --hashes` prints, addressable by a JSON tool. Take the
Preflight heading and its fence:

```bash
sed -n '5p;9,11p' vendor/skills/deploy.md > preflight.md
```

```console
$ cedit md json --tree preflight.md
{
  "type": "root",
  "children": [
    {
      "type": "heading",
      "tag": "h2",
      "info": "",
      "content": "",
      "hash": "bd367afe9f8a1d46",
      "kind": "unit",
      "children": [
        {
          "type": "inline",
          "tag": "",
          "info": "",
          "content": "Preflight",
          "hash": "73670a1f9db979d3",
          "children": [
            {
              "type": "text",
              "tag": "",
              "info": "",
              "content": "Preflight",
              "hash": "418698cd26d4a38c",
              "children": []
            }
          ]
        }
      ]
    },
    {
      "type": "fence",
      "tag": "code",
      "info": "bash",
      "content": "bash scripts/healthcheck.sh --strict\n",
      "hash": "7b47884c75de548e",
      "kind": "opaque",
      "children": []
    }
  ]
}
```

The hashes are the tour's, block identity being a property of the block and not
of the file it was cut from. `kind` is present only on the nodes that can carry
an edit, which makes `.. | select(.kind?)` the whole block list — and since
both shapes take `--raw` on the same terms as `md ast`, that is the round trip's
effect on block identity in two lines:

```console
$ cedit md json --raw --tree messy.md | jq -r '.. | select(.kind?) | "\(.hash) \(.kind) \(.type)"'
21c9f999ed623912 unit heading
bd367afe9f8a1d46 unit heading
6b17a57843ce0f7a opaque code_block
$ cedit md json --tree messy.md | jq -r '.. | select(.kind?) | "\(.hash) \(.kind) \(.type)"'
21c9f999ed623912 unit heading
bd367afe9f8a1d46 unit heading
e236e87c672f4a83 opaque fence
```

It reads better than the token stream, but it is for inspection **only** —
`from-json` takes the token stream, not the tree, and says so if you hand it
the wrong one.

### `md from-json`

The inverse of `md json`: a token stream in, Markdown out. Feed it the file
from above and you get the fence back, byte for byte:

````console
$ cedit md json fence.md | cedit md from-json
```bash
bash scripts/healthcheck.sh --strict
```
````

Which is the point — the pair is a lossless round trip, so it composes into a
check that the parser can rebuild what it read:

```console
$ cedit md json vendor/skills/deploy.md | cedit md from-json \
    | diff - <(cedit md canonicalize vendor/skills/deploy.md)
$ echo $?
0
```

Empty diff, exit 0: tokens → Markdown → the same canonical bytes `.cedit/base/`
would hold. It reads a file or stdin like every other verb, so the stream can
come from anywhere — an `md json` you filtered, or one you generated. What it
will not take is the `--tree` shape ([Troubleshooting](../help/troubleshooting.md) has the error).
