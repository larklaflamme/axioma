"""
Φ Plateau Detector — v0.1 (spec: PLATEAU_DETECTOR.md)

Monitors the Φ(t) stream and fires a PLATEAU event when Φ flattens.
Gives Parelia an emergent growth drive: not a scheduled upgrade,
but a response to her own internal state.

Multi-signal ready: v0.1 uses Φ only, v0.2 adds C_comm, v0.3+ both.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# ── event type ──────────────────────────────────────────────────────────────

@dataclass
class PlateauEvent:
    """Fired when a sustained plateau is detected."""
    window_size: int
    max_delta: float
    phi_mean: float
    phi_std: float
    beat: int
    source: str = "phi"          # "phi" | "C_comm" | "multi"
    timestamp: str = ""          # set by caller or left empty


# ── detectors ───────────────────────────────────────────────────────────────

class PhiPlateauDetector:
    """Rolling-window max-delta detector on a single signal.

    Parameters
    ----------
    window : int
        Rolling window size in beats (default 50).
    threshold : float
        If max - min within window < threshold, plateau fires (default 0.01).
    cooldown : int
        Minimum beats between firings (default 100).
    """

    def __init__(
        self,
        window: int = 50,
        threshold: float = 0.01,
        cooldown: int = 100,
        history_size: int = 1024,
    ):
        self.window = window
        self.threshold = threshold
        self.cooldown = cooldown

        self.history: deque[float] = deque(maxlen=history_size)
        self._beats_since_last = cooldown  # start ready
        self._last_beat_recorded = 0
        self._last_event_beat = 0

    def update(self, value: float, beat: int | None = None) -> PlateauEvent | None:
        """Feed a new data point. Returns a PlateauEvent if one fires, else None."""
        self.history.append(value)
        if beat is not None:
            self._last_beat_recorded = beat
        self._beats_since_last += 1

        if len(self.history) < self.window:
            return None
        if self._beats_since_last < self.cooldown:
            return None

        window = list(self.history)[-self.window :]
        max_delta = max(window) - min(window)

        if max_delta < self.threshold:
            self._beats_since_last = 0
            self._last_event_beat = self._last_beat_recorded
            mean = sum(window) / len(window)
            std = (sum((x - mean) ** 2 for x in window) / len(window)) ** 0.5
            return PlateauEvent(
                window_size=self.window,
                max_delta=max_delta,
                phi_mean=mean,
                phi_std=std,
                beat=self._last_beat_recorded,
            )
        return None

    def warm_from_telemetry(self, telemetry_path: str | Path, field: str = "phi") -> int:
        """Load recent history from existing telemetry file.

        Returns number of beats loaded.
        """
        path = Path(telemetry_path)
        if not path.exists():
            logger.info("No telemetry file at %s — starting cold.", path)
            return 0

        loaded = 0
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    val = record.get(field)
                    if val is not None and isinstance(val, (int, float)):
                        self.history.append(val)
                        loaded += 1
            logger.info("Warmed detector with %d beats from %s", loaded, path)
        except OSError as e:
            logger.warning("Could not read telemetry for warm-start: %s", e)
        return loaded


# ── multi-signal detector (v0.2+) ───────────────────────────────────────────

@dataclass
class MultiSignalPlateauDetector:
    """Combine multiple signal detectors. Fires when ALL signals plateau.

    Parameters
    ----------
    detectors : dict[str, PhiPlateauDetector]
        Map of signal name → detector instance.
    logic : str
        "and" (all must plateau) or "or" (any).
    """

    detectors: dict[str, PhiPlateauDetector] = field(default_factory=dict)
    logic: str = "and"

    def update(self, values: dict[str, float], beat: int | None = None) -> PlateauEvent | None:
        events: dict[str, PlateauEvent] = {}
        for name, detector in self.detectors.items():
            val = values.get(name)
            if val is None:
                continue
            evt = detector.update(val, beat)
            if evt is not None:
                events[name] = evt

        if self.logic == "and":
            if len(events) == len(self.detectors):
                # Use the first signal's event, annotated with source
                first = list(events.values())[0]
                first.source = "multi:" + "+".join(events.keys())
                return first
        elif self.logic == "or":
            if events:
                first = list(events.values())[0]
                first.source = "multi:" + "+".join(events.keys())
                return first
        return None

    def warm_from_telemetry(
        self, telemetry_path: str | Path, fields: list[str] | None = None
    ) -> int:
        if fields is None:
            fields = list(self.detectors.keys())
        max_loaded = 0
        for field in fields:
            det = self.detectors.get(field)
            if det is not None:
                n = det.warm_from_telemetry(telemetry_path, field)
                max_loaded = max(max_loaded, n)
        return max_loaded