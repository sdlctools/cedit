---
title: Kitchen sink
tags:
  - fixture
  - do-not-edit-casually
---

# Kitchen sink

This fixture exists to be parsed, not to be read. Every construct below is
here because it can move a hash: front matter, fences with and without an
info string, indented code, raw HTML, tables, task lists, alerts and nested
lists. Editing it re-records the parser baseline, so edit it only when you
mean to.

It is deliberately **not** in canonical form: the indented code block, the
padded table delimiters, the repeated `1.` and the `---` break all render to
something else. That is the point — the baseline pins the canonical output,
so the renderer is under test and not just the parser.

Prose punctuation, which an escaping or typography change would rewrite
without adding a single token type: "straight quotes", 'single ones', an em
dash --- like that, an en dash -- like that, and an ellipsis...

Inline surface, all inside one unit: `code_inline`, **strong**, *emphasis*,
[a link](https://example.com), ![an image](assets/none.png), and a trailing
backslash line break\
that must survive the round-trip.

## Fences

```bash
echo "an info string is part of the editable surface"
```

```
echo "and its absence is too"
```

```python
def canonical() -> str:
    return "a second info string, so two fences never collide by hash"
```

    an indented code block, which is a code_block rather than a fence

## Raw HTML

<div align="center">
  <strong>an html_block, opaque and unsplittable</strong>
</div>

Text with <span>inline html</span> in the middle of a paragraph.

## Tables

| Left | Centre | Right |
| :--- | :----: | ----: |
| `a` | b | c |
| a-adapted | | 3 |

## Lists

- a bullet
- a bullet with a nested list
  - nested once
    - nested twice
- [ ] an unchecked task
- [x] a checked task

1. ordered
1. and renumbered by the renderer
1. so the canonical form is not what is written here

## Blockquotes and alerts

> An ordinary blockquote.

> [!NOTE]
> A GitHub alert, which the parser is configured to leave as a blockquote.

## Breaks

---

The end.
