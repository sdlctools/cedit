# Markdown Elements — `cedit md canonicalize` Handling Reference

| Category | Input Forms | Canonical Output | Notes |
|----------|-------------|------------------|-------|
| **Headings** | ATX (`# H1`–`###### H6`), Setext (`H1 Alt===`, `H2 Alt---`) | ATX only (`# H1`, `## H2`) | Setext → ATX conversion |
| **Paragraphs** | Hard wraps, single line | Reflowed (preserves hard breaks with trailing spaces) | Line width ~80 chars |
| **Unordered Lists** | `-`, `*`, `+` markers | `- ` only | Marker normalized |
| **Ordered Lists** | `1.`, `1)`, `#.` | `1. ` only | Renumbered sequentially |
| **Nested Lists** | 2/4 space indent | 2-space indent | Consistent |
| **Task Lists** | `- [ ]`, `- [x]`, `- [X]` | `- [ ]`, `- [x]` | Checkbox preserved |
| **Fenced Code** | Triple backticks, tildes (`~~~`) | ```` ```lang ``` ```` | Triple backticks standard |
| **Fenced w/ Nested Backticks** | Any containing ``` | Outer uses 4+ backticks | Auto-promotes for nesting |
| **Indented Code** | 4-space indent | Fenced code block (```) | Converted to fence |
| **Blockquotes** | `>`, `>>` nesting | `> ` with blank line between paragraphs | Nesting preserved |
| **Tables** | Any pipe alignment (`|--|`, `|:--:|`, `\|--|`) | `\| -- \|`, `\| :--: \|`, `\| --: \|` | Separators normalized |
| **Horizontal Rules** | `---`, `***`, `___`, `----` | `________________________________________` (72 `_`) | All → long underscore line |
| **Links (Inline)** | `[text](url "title")` | Same | Preserved |
| **Links (Reference)** | `[text][ref]` + `[ref]: url` | Inlined to `[text](url)` | References eliminated |
| **Images** | `![alt](url)`, reference style | Inlined `![alt](url)` | References eliminated |
| **Emphasis** | `**`, `__`, `*`, `_`, `~~` | `**bold**`, `*italic*`, `~~strike~~` | Normalized markers |
| **Inline Code** | `` `code` ``, ```` `code` ```` | `` `code` `` | Backtick count minimized |
| **HTML Blocks** | Raw `<div>...</div>` | Preserved verbatim | Pass-through |
| **Front Matter (YAML)** | `---` / `+++` delimiters | `________________________________________` (hr) + content as heading-like | **⚠️ Loses structure** — see below |
| **Mermaid Diagrams** | ```` ```mermaid ... ``` ```` | Same triple-backtick form | **Unchanged** |
| **Math ($$...$$)** | Display `$$...$$` | Same | Preserved byte-for-byte |
| **Math ($...$)** | Inline `$...$` | Same | **⚠️ Escapes `\` inside** — see cedit limits |
| **Footnotes** | `[^1]`, `[^ref]`, definitions anywhere | Ref at use, defs at end | Definitions moved to bottom |
| **Definition Lists** | `Term: Def` (PHP Markdown Extra) | Same format | Preserved (mdformat-gfm) |
| **Escaped Chars** | `\*`, `\_`, `\[`, etc. | Same | Preserved |

---

## ⚠️ Known Transformations / Caveats

| Element | Behavior | Workaround |
|---------|----------|------------|
| **Front Matter** | Converted to horizontal rule + plain text | Use `mdformat-frontmatter` plugin if you need preservation; or keep front matter in a separate tracked file |
| **Reference Links/Images** | Inlined (definitions dropped) | Write as inline links; or accept inlining |
| **$...$ with `\`** | Escaped to `\\` inside GitHub math | Use `→` unicode, ```math fence, or code span `` `$\alpha$` `` |
| **Unused Reference Defs** | Silently dropped (warning on stderr) | Use all refs or convert to inline |
| **Setext Headings** | → ATX | No workaround needed; this is the canonical form |
| **Indented Code** | → Fenced | No workaround needed |

---

## Quick Test Commands

```bash
# Test one file
cedit md canonicalize path/to/file.md

# Test all MD files (dry-run check only)
find . -name '*.md' -exec cedit md canonicalize --check {} \;

# Canonicalize all in-place
find . -name '*.md' -print0 | xargs -0 -n1 cedit md canonicalize -i
```

---

**Mermaid diagrams are completely safe** — they remain as triple-backtick fenced blocks with `mermaid` info string, byte-for-byte identical to input.