"""The source-text guards, and the one place their wiring lives.

`mathguard`, `rowguard` and `linkguard` each scan a Markdown *source* for
something the mdformat round-trip would otherwise lose without a trace, and
report it on **stderr, leaving the exit code alone** (AGENTS.md invariant 4).
Two of the three do more than report: `mathguard` and `rowguard` sit on the
hashing path and *prevent* the loss (`protect` / `restore`), so their
`warn_*` is a fallback alarm for the cases protection cannot reach.
`linkguard` only warns — an unused link reference definition is genuinely
dropped and there is nothing byte-exact to put back.

Every path that hands a source to the parser runs all three, so they are
wired here as one tuple and one call rather than a three-line block repeated
at each site. A fourth guard is added to `SOURCE_GUARDS` and nowhere else.
"""

from __future__ import annotations

from .linkguard import warn_link_refs
from .mathguard import warn_fragile_math
from .rowguard import warn_row_overflow

# `mathguard` and `rowguard` — the two that also protect — first, `linkguard`
# — warn-only — last. Order is cosmetic: each guard writes an independent
# stderr block and none touches the exit code.
SOURCE_GUARDS = (warn_fragile_math, warn_row_overflow, warn_link_refs)


def warn_all(src: str, label: str) -> None:
    """Run every source-text guard's stderr warning over `src`."""
    for guard in SOURCE_GUARDS:
        guard(src, label)
