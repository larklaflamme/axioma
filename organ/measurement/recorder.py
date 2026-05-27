"""Recorder: wires heartbeat hooks to ring buffer + JSONL + SQLite + θ pipeline."""
from __future__ import annotations

import time
import uuid
from typing import Callable, Optional

import numpy as np

from ..config import WINDOW_SIZE, UPDATE_FREQUENCY
from ..schemas import ORGAN_ORDER
from .ring_buffer import RingBuffer
from .jsonl_writer import JsonlWriter
from .sqlite_writer import SqliteWriter


ThetaFn = Callable[[dict[str, np.ndarray]], dict]


class Recorder:
    def __init__(
        self,
        heartbeat,
        session_id: Optional[str] = None,
        data_root: str = "data",
        sqlite_path: Optional[str] = None,
        theta_fn: Optional[ThetaFn] = None,
        theta_window: int = WINDOW_SIZE,
        theta_every: int = UPDATE_FREQUENCY,
        enable_jsonl: bool = True,
        enable_sqlite: bool = True,
    ) -> None:
        self.hb = heartbeat
        self.session_id = session_id or uuid.uuid4().hex[:10]
        self.ring = RingBuffer()
        self.jsonl: Optional[JsonlWriter] = (
            JsonlWriter(self.session_id, root=data_root) if enable_jsonl else None
        )
        self.sqlite: Optional[SqliteWriter] = (
            SqliteWriter(sqlite_path or f"{data_root}/organ.sqlite3")
            if enable_sqlite
            else None
        )
        self.theta_fn = theta_fn
        self.theta_window = int(theta_window)
        self.theta_every = int(theta_every)
        self.theta_history: list[dict] = []
        self.last_theta: Optional[dict] = None
        self._theta_counter = 0

        heartbeat.on_beat(self._on_beat)

    def _capture_states(self) -> tuple[dict[str, dict], dict[str, np.ndarray]]:
        states_dict: dict[str, dict] = {}
        arrays: dict[str, np.ndarray] = {}
        for organ in self.hb.organs:
            s = organ.get_state()
            states_dict[organ.name] = s.to_dict()
            arrays[organ.name] = organ.get_state_array()
        return states_dict, arrays

    def _on_beat(self, beat_no: int, mode: str) -> None:
        states_dict, arrays = self._capture_states()
        ts = time.time()
        self.ring.push(beat_no, ts, arrays)

        entry = {
            "beat_no": int(beat_no),
            "timestamp": ts,
            "session_id": self.session_id,
            "mode": mode,
            "states": states_dict,
        }

        # Theta: compute every theta_every beats once we have a full window.
        if (
            self.theta_fn is not None
            and self.ring.size >= self.theta_window
            and (self._theta_counter % self.theta_every == 0)
        ):
            window = self.ring.window(self.theta_window)
            result = self.theta_fn(window)
            entry["theta"] = float(result["theta"])
            entry["theta_p_value"] = float(result["p_value"])
            entry["theta_significant"] = bool(result["significant"])
            entry["pairwise_mi"] = {
                f"{a}-{b}": float(v) for (a, b), v in result["pairwise_mi"].items()
            }
            self.last_theta = result
            self.theta_history.append(
                {
                    "beat_no": int(beat_no),
                    "timestamp": ts,
                    "theta": float(result["theta"]),
                    "p_value": float(result["p_value"]),
                    "significant": bool(result["significant"]),
                }
            )
        self._theta_counter += 1

        if self.jsonl is not None:
            self.jsonl.write(entry)
        if self.sqlite is not None:
            self.sqlite.write(entry)

    def close(self) -> None:
        if self.jsonl is not None:
            self.jsonl.close()
        if self.sqlite is not None:
            self.sqlite.close()
