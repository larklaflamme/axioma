"""Gzipped JSON Lines writer. Append-only, one object per line, per-session file."""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


class JsonlWriter:
    def __init__(self, session_id: str, root: str | Path = "data") -> None:
        self.session_id = session_id
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.path = self.root / f"organ_states_{ts}_session_{session_id}.jsonl.gz"
        self._fh = gzip.open(self.path, "at", encoding="utf-8")
        self._n = 0

    def write(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, default=_json_default)
        self._fh.write(line)
        self._fh.write("\n")
        self._n += 1

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None and not self._fh.closed:
            self._fh.close()

    @property
    def n_written(self) -> int:
        return self._n

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _json_default(o: Any):
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
