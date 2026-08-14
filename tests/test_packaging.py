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

try:
    import tomllib
except ModuleNotFoundError:  # 3.10 — tomllib is stdlib only from 3.11
    # requirements.txt installs tomli there. The earlier
    # `pytest.importorskip("tomllib")` was worse than it looked: the two
    # tests below are the guards against metadata drift, and on the oldest
    # supported leg — the one most likely to actually drift — they skipped
    # silently while still reporting green.
    import tomli as tomllib

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


def test_supported_pythons_are_the_tested_pythons():
    """The classifiers, requires-python and the CI matrix are one list.

    A `Programming Language :: Python :: X.Y` classifier is a claim that cedit
    runs on X.Y, and `requires-python` is what pip enforces before installing.
    Adding either without adding the matching leg to
    `.github/workflows/tests.yml` puts the package back where CED-12 found it:
    asserting support that nothing verifies. The 3.15-style advisory legs are
    deliberately excluded — they carry `advisory: true`, are not in the
    metadata, and cannot fail the job.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))

    classified = {
        c.rsplit(" ", 1)[-1]
        for c in pyproject["project"]["classifiers"]
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
    }

    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text("utf-8")
    matrix = re.search(r"^\s*python-version: \[(.+)\]\s*$", workflow, re.MULTILINE)
    assert matrix, (
        "could not find the python-version matrix in .github/workflows/tests.yml "
        "— if the workflow was reformatted, update this test with it rather "
        "than deleting it"
    )
    tested = set(re.findall(r'"(3\.\d+)"', matrix.group(1)))

    assert classified == tested, (
        f"classifiers claim {sorted(classified)} but CI tests {sorted(tested)} "
        "— see the header comment in .github/workflows/tests.yml"
    )

    floor = pyproject["project"]["requires-python"]
    oldest = min(tested, key=lambda v: int(v.split(".")[1]))
    assert floor == f">={oldest}", (
        f"requires-python is {floor!r} but the oldest tested version is "
        f"{oldest} — pip would let an untested interpreter install cedit"
    )


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


def test_the_docs_site_stays_out_of_the_distribution():
    """`docs/` and `website/` are published, not shipped.

    CED-32 confirmed by building that neither appears in the sdist or the
    wheel. This test guards the *reasons* that held, because with setuptools
    there are exactly four ways either could get in and all four are visible
    here without running a build:

    * `[tool.setuptools] packages` — explicit, and every entry is a `cedit`
      package. Auto-discovery is what would sweep up a sibling directory.
    * a `MANIFEST.in` — `graft`/`include` directives are honoured by the
      sdist regardless of the package list. There is none.
    * `package-data` / `data-files` — the other route into the wheel.
    * `readme` — README.md is the one Markdown file that legitimately ships,
      as the PyPI long description.

    The point is not size. `website/node_modules` aside, a wheel that carries
    documentation invites it to be read from the install path, where it is
    whatever version the reader happened to install and cannot be corrected.
    The site is the correctable copy.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    setuptools_cfg = pyproject.get("tool", {}).get("setuptools", {})

    packages = setuptools_cfg.get("packages")
    assert isinstance(packages, list) and packages, (
        "[tool.setuptools] packages must stay an explicit list — under "
        "auto-discovery a flat-layout sibling like docs/ or website/ can be "
        "picked up as a package"
    )
    assert all(p == "cedit" or p.startswith("cedit.") for p in packages), packages

    assert not (ROOT / "MANIFEST.in").exists(), (
        "a MANIFEST.in can graft docs/ or website/ into the sdist "
        "independently of the package list — if one is added, assert its "
        "contents here"
    )

    for key in ("package-data", "data-files", "package_data", "data_files"):
        assert key not in setuptools_cfg, (
            f"[tool.setuptools] {key} is a route into the wheel that this "
            "test does not inspect — check it does not carry docs/ or "
            "website/, then teach this test about it"
        )

    assert pyproject["project"]["readme"] == "README.md"


_FENCE = re.compile(r"^\s*(```|~~~)")
_CODE_SPAN = re.compile(r"`[^`]*`")
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_REMOTE = re.compile(r"^(https?:|data:|pathname://|/)")


def _prose_images(md: str):
    """Every image URL in `md` that is prose, not an example inside code."""
    out, in_fence = [], False
    for line in md.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for url in _IMAGE.findall(_CODE_SPAN.sub("", line)):
            out.append(url.split()[0].strip("<>"))
    return out


def test_docs_images_resolve_from_inside_docs():
    """A relative image in `docs/` must point at a file inside `docs/`.

    This is the guard for the one way a docs page can be correct in the
    repository, correct on GitHub, correct in a site build, and still break
    the release — which is exactly what happened on v0.3.4.

    `docusaurus docs:version` snapshots `docs/` and nothing else. An image
    that lives outside it resolves only by accident of depth:
    `docs/userguide/index.md` reaching `../../assets/x.png` lands on the
    repository root, but the snapshot of that same file at
    `website/versioned_docs/version-X/userguide/index.md` lands on
    `website/versioned_docs/assets/x.png`, which does not exist. Images are
    resolved by webpack rather than by the link checker, so it is a hard
    build failure, and it appears in the release run — after review, after
    merge, with the broken snapshot already committed and unrepeatable.

    Both trees are scanned, because the snapshot is what actually broke and
    a hand-repaired one can drift from its source. Remote and site-absolute
    URLs are somebody else's problem; only local paths are checked, and only
    in prose — an `![alt](url)` written as an example inside a fence or a
    code span is documentation about Markdown, not a reference to a file.
    """
    roots = [ROOT / "docs"]
    versioned = ROOT / "website" / "versioned_docs"
    if versioned.is_dir():
        roots.append(versioned)

    checked = 0
    for root in roots:
        for page in sorted(root.rglob("*.md")):
            for url in _prose_images(page.read_text("utf-8")):
                if _REMOTE.match(url):
                    continue
                target = (page.parent / url.split("#")[0]).resolve()
                rel = page.relative_to(ROOT)
                assert target.is_file(), f"{rel}: image not found: {url}"
                assert target.is_relative_to(root.resolve()), (
                    f"{rel}: image {url} escapes {root.name}/ — it will not "
                    "survive `docusaurus docs:version`, which snapshots that "
                    "directory and nothing else"
                )
                checked += 1

    assert checked, "no local images found — has the scan stopped seeing them?"
