"""
Plateau Detector — multi-signal stagnation detector for Parelia v2.

Monitors the Φ(t) stream and detects when it plateaus — the system's signal
that it has reached the current capacity of its lattice. A sustained plateau
is the trigger condition for self-expansion.

Zero-dependency (stdlib only). Reads from the same JSONL file the writer
produces, so it can warm-start by replaying history.

Design spec: PLATEAU_DETECTOR.md
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Events ────────────────────────────────────────────────────────────────

@dataclass
class PlateauEvent:
    """Fired when a plateau is detected."""

    window_size: int
    max_delta: float
    phi_mean: float
    phi_std: float
    beat: int
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "event": "PLATEAU_DETECTED",
            "window_size": self.window_size,
            "max_delta": round(self.max_delta, 6),
            "phi_mean": round(self.phi_mean, 6),
            "phi_std": round(self.phi_std, 6),
            "beat": self.beat,
            "timestamp": self.timestamp,
        }


@dataclass
class PlateauConfig:
    """Tunable parameters for plateau detection."""

    window: int = 50
    threshold: float = 0.01
    cooldown: int = 100


class PlateauDetector:
    """Monitor Φ(t) and detect stagnation."""

    def __init__(
        self,
        config: PlateauConfig | None = None,
        telemetry_path: str | Path | None = None,
        field: str = "phi",
    ) -> None:
        self.config = config or PlateauConfig()
        self.field = field
        self._phi_history: deque[float] = deque(maxlen=self.config.window)
        self._last_trigger_beat: int = -self.config.cooldown
        self._last_event: PlateauEvent | None = None
        self._total_beats_seen: int = 0
        if telemetry_path is not None:
            self._warm_from_telemetry(Path(telemetry_path))
        logger.info("plateau_detector_init", window=self.config.window,
                     threshold=self.config.threshold, cooldown=self.config.cooldown)

    def update(self, beat: int, phi: float) -> PlateauEvent | None:
        if phi is None:
            return None
        self._phi_history.append(phi)
        self._total_beats_seen += 1
        if len(self._phi_history) < self.config.window:
            return None
        if (self._total_beats_seen - self._last_trigger_beat) < self.config.cooldown:
            return None
        window = list(self._phi_history)
        max_delta = max(window) - min(window)
        if max_delta < self.config.threshold:
            phi_mean = statistics.mean(window)
            phi_std = statistics.stdev(window) if len(window) > 1 else 0.0
            self._last_event = PlateauEvent(
                window_size=self.config.window, max_delta=max_delta,
                phi_mean=phi_mean, phi_std=phi_std,
                beat=beat, timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._last_trigger_beat = self._total_beats_seen
            return self._last_event
        return None

    def update_from_record(self, record: dict) -> PlateauEvent | None:
        beat = record.get("beat", self._total_beats_seen + 1)
        phi = record.get(self.field) or record.get("phi_raw") or record.get("phi_smoothed")
        return self.update(beat, phi)

    @property
    def last_event(self) -> PlateauEvent | None:
        return self._last_event

    @property
    def fired(self) -> bool:
        return self._last_event is not None

    @property
    def beats_seen(self) -> int:
        return self._total_beats_seen

    def reset(self) -> None:
        self._phi_history.clear()
        self._last_trigger_beat = -self.config.cooldown
        self._last_event = None
        self._total_beats_seen = 0

    def _warm_from_telemetry(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            with open(path) as f:
                lines = f.readlines()
            if not lines:
                return
            for line in lines[-min(len(lines), self.config.window * 2):]:
                line = line.strip()
                if line:
                    try:
                        self.update_from_record(json.loads(line))
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except OSError as e:
            logger.warning("plateau_warm_fail: %s", e)


@dataclass
class MultiSignalConfig:
    theta_threshold: float = 0.1
    aos_gap_threshold: float = 0.05
    zone_variety_max: int = 2
    window: int = 50
    cooldown: int = 200


class MultiSignalDetector:
    def __init__(self, config: MultiSignalConfig | None = None) -> None:
        self.config = config or MultiSignalConfig()
        self._theta_history: deque[float] = deque(maxlen=self.config.window)
        self._aos_gap_history: deque[float] = deque(maxlen=self.config.window)
        self._zone_history: deque[str] = deque(maxlen=self.config.window)
        self._psi_history: deque[float] = deque(maxlen=self.config.window)
        self._last_trigger_beat: int = -self.config.cooldown
        self._total_beats: int = 0
        self._last_event: dict | None = None

    def update(self, beat: int, theta: float, aos_g_gap: float,
               zone: str, psi: float) -> dict | None:
        self._theta_history.append(theta)
        self._aos_gap_history.append(aos_g_gap)
        self._zone_history.append(zone)
        self._psi_history.append(psi)
        self._total_beats += 1
        if len(self._theta_history) < self.config.window:
            return None
        if (self._total_beats - self._last_trigger_beat) < self.config.cooldown:
            return None
        tr = max(self._theta_history) - min(self._theta_history)
        gr = max(self._aos_gap_history) - min(self._aos_gap_history)
        zv = len(set(self._zone_history))
        if tr < self.config.theta_threshold and gr < self.config.aos_gap_threshold and zv <= self.config.zone_variety_max:
            self._last_event = {
                "event": "GROWTH_READY", "beat": beat,
                "theta_range": round(tr, 4), "aos_gap_range": round(gr, 4),
                "zone_variety": zv,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "detector": "multi_signal",
            }
            self._last_trigger_beat = self._total_beats
            return self._last_event
        return None


__all__ = [
    "PlateauConfig", "PlateauEvent", "PlateauDetector",
    "MultiSignalConfig", "MultiSignalDetector",
]