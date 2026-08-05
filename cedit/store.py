"""Durable-write primitives: every state file is written via a temp file in
the target directory plus `rename(2)`, so a reader never observes a
half-written file and a crash leaves the previous good version in place.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile


def utc_now() -> str:
    """ISO 8601 UTC, second precision, `Z` suffix."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def atomic_write_text(path: str, text: str) -> None:
    """Write via a temp file in the *same directory* plus `rename(2)`.

    Same directory matters: `rename` is only atomic within one filesystem.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-cedit-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
