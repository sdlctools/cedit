"""Packaging metadata — the parts that can silently rot.

Not a substitute for building the wheel (that happens in release.yml), but
these things drift without anyone noticing: `__version__` now comes from
distribution metadata rather than a literal, pyproject's dependency pins
have to stay byte-identical to requirements.txt or invariant 2 quietly stops
holding for pip-installed consumers, and README.md doubles as the package's
PyPI long description, where a relative link is a 404 nobody sees from a
GitHub preview.
"""

import importlib
import importlib.metadata
import pathlib
import re

import pytest

import cedit

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_version_is_a_non_empty_string():
    assert isinstance(cedit.__version__, str)
    assert cedit.__version__


def test_version_falls_back_in_an_uninstalled_checkout(monkeypatch):
    """A source checkout that was never installed must still import."""
    def _raise(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _raise)
    try:
        assert importlib.reload(cedit).__version__ == "0.0.0+source"
    finally:
        monkeypatch.undo()
        importlib.reload(cedit)


def test_pyproject_pins_match_requirements_txt():
    """Invariant 2: one parser configuration, however cedit was installed.

    requirements.txt is what a source checkout gets; pyproject's
    `dependencies` is what `pip install cedit` gets. If they disagree, a
    consumer's parser differs from the one the tests ran against and every
    hash in their `.cedit/` state can move.
    """
    tomllib = pytest.importorskip("tomllib")

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    declared = pyproject["project"]["dependencies"]

    pinned = []
    for line in (ROOT / "requirements.txt").read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            # pytest and friends — test-only, and deliberately not a runtime
            # dependency of the published package.
            continue
        pinned.append(line)

    assert declared == pinned, (
        "pyproject.toml [project] dependencies and requirements.txt have "
        "drifted apart — see invariant 2 in AGENTS.md"
    )
    # Every runtime dependency is pinned with ==, never loosened.
    for dep in declared:
        assert re.fullmatch(r"[A-Za-z0-9._-]+==[0-9][^,;]*", dep), dep


# Every inline link and image target: the `](` of `[text](target)`,
# `![alt](target)` and the badge form `[![alt](img)](target)` alike. Matching
# on the closing bracket rather than on a whole `[...]` label is what catches
# that last one — a nested `]` inside the label defeats any `\[[^\]]*\]` form,
# silently exempting exactly the badges at the top of the file.
_MD_LINK = re.compile(r"\]\(([^)\s]+)")


def test_readme_links_are_absolute():
    """README.md is the PyPI long description, and PyPI does not rewrite links.

    `readme = "README.md"` in pyproject.toml means every link in this file is
    resolved against pypi.org/project/cedit/, not against the repository. A
    relative target renders fine on GitHub and 404s on the page most new users
    see first — so relative links are a packaging bug, not a style choice.
    """
    readme = (ROOT / "README.md").read_text("utf-8")

    relative = [
        target
        for target in _MD_LINK.findall(readme)
        if not target.startswith(("https://", "http://", "#"))
    ]

    assert not relative, (
        "README.md is the PyPI long description; these targets are relative "
        f"and will 404 on pypi.org: {relative}"
    )
