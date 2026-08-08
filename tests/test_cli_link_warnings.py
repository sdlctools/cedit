"""CLI-level tests for link reference warnings.

Tests that the warning is emitted when running `cedit md canonicalize`
on a file with unused link reference definitions.
"""

import pytest

from cedit.cli import main
from cedit.mdcli import cmd_md_canonicalize
from types import SimpleNamespace


def test_canonicalize_warns_about_unused_link_refs(capsys):
    """Running canonicalize on a file with unused link refs emits a warning."""
    # Create a test file
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write('[unused]: https://example.com/unused\n')
        f.write('[used]: https://example.com/used\n')
        f.write('\n')
        f.write('Link to [used].\n')
        test_file = f.name

    try:
        # Run canonicalize
        args = SimpleNamespace(file=test_file, check=False, in_place=False)
        cmd_md_canonicalize(args)

        # Check that a warning was emitted
        captured = capsys.readouterr()
        assert 'warning' in captured.err
        assert 'unused' in captured.err
        assert '[unused]:' in captured.err

        # Check that the output is correct
        assert 'Link to [used](https://example.com/used).' in captured.out
        assert '[unused]:' not in captured.out

    finally:
        os.unlink(test_file)


def test_canonicalize_no_warning_when_all_refs_used(capsys):
    """Running canonicalize on a file with only used link refs emits no warning."""
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write('[used]: https://example.com/used\n')
        f.write('\n')
        f.write('Link to [used].\n')
        test_file = f.name

    try:
        args = SimpleNamespace(file=test_file, check=False, in_place=False)
        cmd_md_canonicalize(args)

        # Check that no warning was emitted
        captured = capsys.readouterr()
        assert captured.err == ''

        # Check that the output is correct
        assert 'Link to [used](https://example.com/used).' in captured.out

    finally:
        os.unlink(test_file)


def test_canonicalize_no_warning_when_no_refs(capsys):
    """Running canonicalize on a file with no link refs emits no warning."""
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write('Plain text with no references.\n')
        test_file = f.name

    try:
        args = SimpleNamespace(file=test_file, check=False, in_place=False)
        cmd_md_canonicalize(args)

        # Check that no warning was emitted
        captured = capsys.readouterr()
        assert captured.err == ''

    finally:
        os.unlink(test_file)
