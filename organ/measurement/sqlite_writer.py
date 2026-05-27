"""SQLite secondary store for queryable history.

WAL mode, indexed on (session_id, beat_no, mode), atomic per-row writes.
The full entry (states + summaries + theta) is JSON-encoded in `payload`.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


_DDL = """
CREATE TABLE IF NOT EXISTS organ_log (
    session_id TEXT NOT NULL,
    beat_no    INTEGER NOT NULL,
    timestamp  REAL NOT NULL,
    mode       TEXT NOT NULL,
    theta      REAL,
    theta_p_value REAL,
    theta_significant INTEGER,
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_session_beat ON organ_log(session_id, beat_no);
CREATE INDEX IF NOT EXISTS ix_session_mode ON organ_log(session_id, mode);
"""


class SqliteWriter:
    def __init__(self, path: str | Path = "data/organ.sqlite3") -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(path, isolation_level=None)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                self._con.execute(s)
        self._n = 0

    def write(self, entry: dict[str, Any]) -> None:
        theta = entry.get("theta")
        p = entry.get("theta_p_value")
        sig = entry.get("theta_significant")
        payload = json.dumps(entry, default=_default)
        self._con.execute(
            "INSERT INTO organ_log (session_id, beat_no, timestamp, mode, theta, theta_p_value, theta_significant, payload) VALUES (?,?,?,?,?,?,?,?)",
            (
                entry["session_id"],
                int(entry["beat_no"]),
                float(entry["timestamp"]),
                entry["mode"],
                None if theta is None else float(theta),
                None if p is None else float(p),
                None if sig is None else int(bool(sig)),
                payload,
            ),
        )
        self._n += 1

    def close(self) -> None:
        if self._con is not None:
            self._con.close()

    @property
    def n_written(self) -> int:
        return self._n

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _default(o: Any):
    try:
        import numpy as np

        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    raise TypeError(f"Unserializable: {type(o)}")
