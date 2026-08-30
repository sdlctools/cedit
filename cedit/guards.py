"""The source-text guards, wired as one list and one call.

`mathguard`, `rowguard` and `linkguard` each scan a Markdown *source* for
something the mdformat round-trip would lose and warn about it on **stderr,
leaving the exit code alone** (AGENTS.md invariant 4). Every path that hands
a source to the parser runs all three — so `warn_all` iterates `SOURCE_GUARDS`
rather than the three-line block being repeated at each site. A fourth guard
is added to `SOURCE_GUARDS` and nowhere else.
"""

from __future__ import annotations

from .linkguard import warn_link_refs
from .mathguard import warn_fragile_math
from .rowguard import warn_row_overflow

SOURCE_GUARDS = (warn_fragile_math, warn_row_overflow, warn_link_refs)


def warn_all(src: str, label: str) -> None:
    """Run every source-text guard's stderr warning over `src`."""
    for guard in SOURCE_GUARDS:
        guard(src, label)
