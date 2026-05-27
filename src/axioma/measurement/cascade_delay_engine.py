"""CascadeDelayEngine — S4 of the ΔΦ signature suite.

Per ARCH_DESIGN_v1.0.md §6.3 (D1/C10) + IMPLEMENTATION_PLAN_v1.0.md §6.1 step 3.

Reads per-organ pairwise MI from RawMIEngine (5-beat window for peak detection).
Reports `cascade_delay = t(ANIMA_peak) - t(EIDOLON_peak)` where the peak
is the argmax of MI on each organ's pair-traces over a 20-beat lookback.

Why this matters (per ARCH §6.2 + Control 1):
  Removing EIDOLON dramatically changes cascade_delay (+4 → +28 beats =
  6.7× change) WITHOUT changing θ. cascade_delay catches what θ alone misses.

Implementation:
  - For each non-EIDOLON-and-non-ANIMA "downstream" organ X, compute:
    eidolon_X_history = MI(EIDOLON, X) over last 20 beats
    anima_X_history   = MI(ANIMA, X)   over last 20 beats
  - The per-X cascade_delay is t(argmax anima_X) - t(argmax eidolon_X)
  - The reported scalar cascade_delay is the mean over X ∈ {MNEME, NOUS, PNEUMA}

If the EIDOLON/ANIMA pair MI itself is the strongest source (typical), we
also report the direct EIDOLON-ANIMA timing as an alternative metric.
"""
from __future__ import annotations

from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..observability import get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import ORGAN_ORDER
from .engine_base import MeasurementEngine
from .raw_mi_engine import RawMIEngine, _pair_key

log = get_logger(__name__)

# Organs whose MI-with-EIDOLON vs MI-with-ANIMA peak timing we compare
_DOWNSTREAM_ORGANS = tuple(o for o in ORGAN_ORDER if o not in ("eidolon", "anima"))


@dataclass
class CascadeDelayReading:
    """The cascade_delay scalar + per-downstream breakdown."""

    beat_no: int = 0
    cascade_delay_beats: float = 0.0     # mean over downstream organs
    per_downstream: dict[str, float] = field(default_factory=dict)
    valid: bool = False  # True when enough history to compute
    method: str = "anima_minus_eidolon_peak_5beat"


class CascadeDelayEngine(MeasurementEngine):
    """Peak-difference cascade delay reader on the 5-beat raw MI.

    Default cadence: every beat (the underlying raw_mi is per-beat).
    Lookback: 20 beats (the architecture's window per D1).
    """

    name = "cascade_delay"
    natural_period_beats = 1
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        lookback_beats: int = 20,
        history_capacity: int = 600,
    ) -> None:
        super().__init__(ctx)
        if lookback_beats < 5:
            raise ValueError(f"lookback_beats must be >= 5, got {lookback_beats}")
        self.lookback_beats = lookback_beats
        self.history_capacity = history_capacity
        self._current: CascadeDelayReading = CascadeDelayReading()
        self._history: deque[tuple[int, float]] = deque(maxlen=history_capacity)

    def compute(self) -> None:
        if not self.ctx.has("raw_mi"):
            return
        raw: RawMIEngine = self.ctx.get("raw_mi")

        # For each downstream organ X, get MI(EIDOLON,X) and MI(ANIMA,X) traces
        per_downstream: dict[str, float] = {}
        latest_beat = 0
        for downstream in _DOWNSTREAM_ORGANS:
            eid_key = _pair_key("eidolon", downstream)
            ani_key = _pair_key("anima", downstream)
            eid_trace = raw.history_5beat(eid_key)
            ani_trace = raw.history_5beat(ani_key)
            if not eid_trace or not ani_trace:
                continue
            # Keep only beats within the lookback window from the most recent
            most_recent_beat = max(eid_trace[-1][0], ani_trace[-1][0])
            latest_beat = max(latest_beat, most_recent_beat)
            cutoff = most_recent_beat - self.lookback_beats + 1
            eid_recent = [(b, v) for b, v in eid_trace if b >= cutoff]
            ani_recent = [(b, v) for b, v in ani_trace if b >= cutoff]
            if len(eid_recent) < 3 or len(ani_recent) < 3:
                continue
            eid_peak_beat = max(eid_recent, key=lambda bv: bv[1])[0]
            ani_peak_beat = max(ani_recent, key=lambda bv: bv[1])[0]
            per_downstream[downstream] = float(ani_peak_beat - eid_peak_beat)

        if per_downstream:
            mean_delay = float(np.mean(list(per_downstream.values())))
            self._current = CascadeDelayReading(
                beat_no=latest_beat,
                cascade_delay_beats=mean_delay,
                per_downstream=per_downstream,
                valid=True,
            )
            self._history.append((latest_beat, mean_delay))
            # Feed back into PNEUMA's coherence_budget computation if available
            if self.ctx.has("substrate"):
                with suppress(Exception):
                    self.ctx.substrate.pneuma.set_load_signals(
                        cascade_delay_beats=mean_delay
                    )

    def current_value(self) -> CascadeDelayReading:
        return self._current

    def history(self) -> list[tuple[int, float]]:
        return list(self._history)

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "lookback_beats": self.lookback_beats,
            "current": {
                "beat_no": self._current.beat_no,
                "cascade_delay_beats": self._current.cascade_delay_beats,
                "per_downstream": self._current.per_downstream,
                "valid": self._current.valid,
                "method": self._current.method,
            },
            "history": list(self._history),
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("lookback_beats") != self.lookback_beats:
            return
        cur = snapshot.get("current", {})
        self._current = CascadeDelayReading(
            beat_no=int(cur.get("beat_no", 0)),
            cascade_delay_beats=float(cur.get("cascade_delay_beats", 0.0)),
            per_downstream=dict(cur.get("per_downstream", {})),
            valid=bool(cur.get("valid", False)),
            method=str(cur.get("method", "anima_minus_eidolon_peak_5beat")),
        )
        self._history = deque(
            ((int(b), float(v)) for b, v in snapshot.get("history", [])),
            maxlen=self.history_capacity,
        )
