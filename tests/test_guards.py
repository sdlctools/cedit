"""The source-guard aggregator — one call runs every guard, once per site."""

from io import StringIO

from cedit import guards
from cedit.linkguard import warn_link_refs
from cedit.mathguard import warn_fragile_math
from cedit.rowguard import warn_row_overflow


def test_source_guards_is_every_warn_function():
    """A fourth guard is added to this tuple and nowhere else."""
    assert set(guards.SOURCE_GUARDS) == {
        warn_fragile_math, warn_row_overflow, warn_link_refs
    }


def test_warn_all_invokes_each_guard(monkeypatch):
    seen = []
    monkeypatch.setattr(guards, "SOURCE_GUARDS",
                        tuple(lambda s, l, _n=name: seen.append(_n)
                              for name in ("a", "b", "c")))
    guards.warn_all("src", "label")
    assert seen == ["a", "b", "c"]


def test_warn_all_routes_a_finding_to_stderr(capsys):
    """A guard finding reaches stderr through the aggregator, exit code untouched."""
    guards.warn_all("[unused]: https://example.com\n", "doc.md")
    err = capsys.readouterr().err
    assert "doc.md: warning:" in err
    assert "link reference definition" in err


def test_warn_all_is_silent_on_a_clean_document(capsys):
    guards.warn_all("# Title\n\nPlain prose.\n", "doc.md")
    assert capsys.readouterr().err == ""
