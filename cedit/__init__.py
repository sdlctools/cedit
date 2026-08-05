"""cedit — continuous editing of vendored Markdown.

A persistent block-level overlay of local adaptations, re-applied by 3-way
structural merge on every upstream update. See SPEC.md.
"""

from importlib.metadata import PackageNotFoundError, version as _version

# Read from the installed distribution's metadata rather than hard-coded
# here. The release workflows stamp only pyproject.toml's `version` line, so
# a literal in this file is a second source of truth that silently drifts —
# it already had, sitting at 0.1.0.dev0 while pyproject said 0.1.2.
try:
    __version__ = _version("cedit")
except PackageNotFoundError:
    # A source checkout that was never installed (the test suite runs this
    # way — conftest.py puts the repo root on sys.path instead).
    __version__ = "0.0.0+source"
