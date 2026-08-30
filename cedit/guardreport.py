"""The stderr block every source guard prints, in one place.

Each guard's warning has the same shape — a `<label>: warning: <summary>`
line, one indented `line <n>: …` per finding, a short prose footer whose
last line is the user guide's *Limits* page. Only the wording is the guard's
own. A leaf module on purpose: it imports nothing from the guard family, so
`guards.py` can import the guards without a cycle.
"""

from __future__ import annotations

import sys
from typing import Callable, Sequence, TypeVar

USER_GUIDE_LIMITS = "https://sdlctools.github.io/cedit/docs/userguide/limits"

_F = TypeVar("_F")


def emit(label: str, findings: Sequence[_F], *, summary: str,
         detail: Callable[[_F], str], footer: str, stream=None) -> Sequence[_F]:
    """Print one guard's stderr block, or nothing when `findings` is empty.

    Every finding must carry a 1-based `.line`. Returns `findings` unchanged
    so a `warn_*` can `return emit(...)`. Never touches the exit code.
    """
    if not findings:
        return findings
    out = sys.stderr if stream is None else stream
    print(f"{label}: warning: {summary}", file=out)
    for finding in findings:
        print(f"    line {finding.line}: {detail(finding)}", file=out)
    print(footer, file=out)
    print(f"    {USER_GUIDE_LIMITS}", file=out)
    return findings
