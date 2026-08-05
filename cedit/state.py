"""`.cedit/` — the state directory in the consumer repository.

| Path                        | Contents                              | Committed |
| `.cedit/base/<doc>`         | canonical base snapshot (B)           | yes       |
| `.cedit/manifest.json`      | per-doc ledger + unresolved conflicts | yes       |
| `.cedit/overlay.json`       | derived local-edit overlay            | yes (like a lockfile — reviewable, always recomputable from B + the working copy) |

Base snapshots are stored as files rather than git blob refs because B comes
from a *different* repository — there is no local blob to point at. Doc keys are normalized relative paths; JSON is
UTF-8, `ensure_ascii=False`, docs serialized sorted so diffs stay local.
"""

from __future__ import annotations

import os

from .merge3 import Conflict, LocalEdit
from .store import atomic_write_text, dumps, load_json, read_text, utc_now

MANIFEST_SCHEMA = "cedit-manifest/v1"
OVERLAY_SCHEMA = "cedit-overlay/v1"
DEFAULT_STATE_DIR = ".cedit"


class StateError(RuntimeError):
    pass


def norm_doc(doc: str) -> str:
    path = os.path.normpath(doc)
    if os.path.isabs(path) or path.split(os.sep, 1)[0] == os.pardir:
        raise StateError(
            f"{doc}: tracked documents are addressed by a path relative to "
            f"the repository root (run cedit from the root)"
        )
    return path


class State:
    """Loads lazily, saves atomically; docs keys always sorted."""

    def __init__(self, root: str = ".", state_dir: str | None = None):
        self.root = os.path.abspath(root)
        self.dir = os.path.join(self.root, state_dir or DEFAULT_STATE_DIR)
        self.manifest_path = os.path.join(self.dir, "manifest.json")
        self.overlay_path = os.path.join(self.dir, "overlay.json")
        self.manifest = (load_json(self.manifest_path)
                         if os.path.exists(self.manifest_path)
                         else {"schema": MANIFEST_SCHEMA, "docs": {}})
        self.overlay = (load_json(self.overlay_path)
                        if os.path.exists(self.overlay_path)
                        else {"schema": OVERLAY_SCHEMA, "docs": {}})

    # -- paths ------------------------------------------------------------

    def doc_path(self, doc: str) -> str:
        return os.path.join(self.root, doc)

    def base_path(self, doc: str) -> str:
        return os.path.join(self.dir, "base", doc)

    # -- manifest ---------------------------------------------------------

    def tracked(self) -> list[str]:
        return sorted(self.manifest["docs"])

    def entry(self, doc: str) -> dict:
        try:
            return self.manifest["docs"][doc]
        except KeyError:
            raise StateError(f"{doc}: not tracked — run `cedit snapshot` first")

    def is_tracked(self, doc: str) -> bool:
        return doc in self.manifest["docs"]

    def set_entry(self, doc: str, *, upstream: str, base_doc_hash: str,
                  conflicts: dict | None = None) -> dict:
        entry = self.manifest["docs"].setdefault(doc, {})
        entry.update({
            "upstream": upstream,
            "base_doc_hash": base_doc_hash,
            "synced_at": utc_now(),
        })
        if conflicts is not None:
            entry["conflicts"] = conflicts
        entry.setdefault("conflicts", {})
        return entry

    def conflicts(self, doc: str) -> dict[str, Conflict]:
        raw = self.entry(doc).get("conflicts", {})
        return {key: Conflict.from_dict(key, data) for key, data in raw.items()}

    def save_manifest(self) -> None:
        out = dict(self.manifest)
        out["docs"] = {k: self.manifest["docs"][k]
                       for k in sorted(self.manifest["docs"])}
        atomic_write_text(self.manifest_path, dumps(out))

    # -- overlay ----------------------------------------------------------

    def set_overlay(self, doc: str, edits: list[LocalEdit]) -> None:
        self.overlay["docs"][doc] = {
            "derived_at": utc_now(),
            "edits": [edit.as_dict() for edit in edits],
        }

    def save_overlay(self) -> None:
        out = dict(self.overlay)
        out["docs"] = {k: self.overlay["docs"][k]
                       for k in sorted(self.overlay["docs"])}
        atomic_write_text(self.overlay_path, dumps(out))

    # -- base snapshots ---------------------------------------------------

    def read_base(self, doc: str) -> str:
        path = self.base_path(doc)
        if not os.path.exists(path):
            raise StateError(f"{doc}: base snapshot missing ({path}) — "
                             f"was `.cedit/base/` committed?")
        return read_text(path)

    def write_base(self, doc: str, canonical_md: str) -> None:
        atomic_write_text(self.base_path(doc), canonical_md)
