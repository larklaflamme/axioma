"""axioma.persistence — Stateful protocol + SnapshotManager."""
from __future__ import annotations

from .snapshot import (
    CURRENT_SYMLINK,
    SNAPSHOT_MANIFEST,
    LoadResult,
    SnapshotManager,
    Stateful,
)

__all__ = ["CURRENT_SYMLINK", "SNAPSHOT_MANIFEST", "LoadResult", "SnapshotManager", "Stateful"]
