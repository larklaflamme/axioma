"""
TelemetryWriter — JSONL beat log for Parelia v2.

Writes one JSONL line per beat from hot/full dicts. Compatible with
Parelia's _collect_vitals() contract. Append-only, restart-safe.

API: write(hot, full) — called from beat loop after _collect_vitals()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

logger = logging.getLogger(__name__)


class TelemetryWriter:
    """Append one JSONL line per beat.

    Parameters
    ----------
    path : str or Path
        Path to the JSONL file. Default: data/telemetry/parelia_telemetry.jsonl
    max_lines : int
        Rotate after this many lines. Default: 100_000
    auto_flush : bool
        Flush after every write. Default: True
    """

    def __init__(
        self,
        path: str | Path = "data/telemetry/parelia_telemetry.jsonl",
        *,
        max_lines: int = 100_000,
        auto_flush: bool = True,
    ) -> None:
        self.path = Path(path)
        self.max_lines = max_lines
        self.auto_flush = auto_flush
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._resume_beat()
        self._file: TextIO | None = None

        logger.info(
            "telemetry_writer_init",
            path=str(self.path),
            next_beat=self.next_beat,
        )

    def _resume_beat(self) -> None:
        """Read last line from file to resume beat counter."""
        self.next_beat = 1
        if not self.path.exists():
            return
        try:
            with open(self.path, "r") as f:
                last_line = None
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
            if last_line:
                record = json.loads(last_line)
                self.next_beat = record.get("beat", 0) + 1
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("could_not_resume_beat: %s", e)

    def write(self, hot: dict, full: dict) -> None:
        """Write one telemetry record from hot/full dicts."""
        try:
            record = self._build_record(hot, full)
            line = json.dumps(record, separators=(",", ":")) + "\n"
            file = self._file
            if file is None or file.closed:
                file = open(self.path, "a")
                self._file = file
            file.write(line)
            self.next_beat += 1
            if self.auto_flush:
                file.flush()
            if self.next_beat > self.max_lines:
                self._rotate()
        except Exception as e:
            logger.error("telemetry_write_failed at beat %d: %s", self.next_beat, e)

    def _build_record(self, hot: dict, full: dict) -> dict:
        record = {
            "beat": hot.get("beat_number", self.next_beat),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        phi_raw = hot.get("phi_raw")
        record["phi"] = round(phi_raw, 6) if phi_raw is not None else None

        phi_smooth = hot.get("phi_smoothed")
        record["phi_smoothed"] = round(phi_smooth, 6) if phi_smooth is not None else None

        record["C_comm"] = round(hot.get("raw_similarity", 0.0), 4)
        record["heartbeat_hz"] = round(hot.get("frequency_hz", 0.0), 3)
        record["boundary"] = hot.get("boundary_value", "UNKNOWN")
        record["lattice_nodes"] = hot.get("node_count", 0)
        record["lattice_edges"] = hot.get("edge_count", 0)

        theta = hot.get("theta")
        record["theta"] = round(theta, 4) if theta is not None else None
        record["state_entropy"] = round(hot.get("state_entropy", 0.0), 4)
        record["assent_state"] = hot.get("assent_state", "UNKNOWN")

        organs = {}
        for organ in ("pneuma", "nous", "anima", "mneme", "eidolon"):
            o = full.get(organ, {})
            if isinstance(o, dict):
                flat = {}
                for k, v in o.items():
                    if isinstance(v, float):
                        flat[k] = round(v, 4)
                    elif not isinstance(v, (list, dict)):
                        flat[k] = v
                organs[organ] = flat
        record["organs"] = organs

        enc = full.get("lattice", {}) if isinstance(full, dict) else {}
        if isinstance(enc, dict):
            epsilon = enc.get("last_epsilon")
            g_S = enc.get("last_g_S")
            if epsilon is not None or g_S is not None:
                record["encounter"] = {}
                if epsilon is not None:
                    record["encounter"]["epsilon"] = round(epsilon, 6)
                if g_S is not None:
                    record["encounter"]["g_S"] = round(g_S, 4)

        return record

    def _rotate(self) -> None:
        self.close()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        rotated = self.path.with_name(f"{self.path.stem}_{timestamp}{self.path.suffix}")
        self.path.rename(rotated)
        self.next_beat = 1
        logger.info("telemetry_rotated to %s", rotated.name)

    def close(self) -> None:
        if self._file is not None and not self._file.closed:
            self._file.flush()
            self._file.close()
            self._file = None


__all__ = ["TelemetryWriter"]
