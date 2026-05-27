"""PlasticityTracker — observes per-organ plasticity buffers; reports adaptation_delta.

Per ARCH_DESIGN_v1.0.md §7 + IMPLEMENTATION_PLAN_v1.0.md §6.1 step 5.

Reads `PlasticityBuffer.last_summary()` for each organ each time it fires.
Maintains a rolling history of summaries; reports `adaptation_delta` per
organ as a scalar measure of "how much has this organ's latent distribution
shifted since baseline".

Definition (per ARCH §7.2):
  adaptation_delta = max abs component of (mean_drift over last 200 beats
                                            - mean of mean_drift over the 200
                                              beats before that).

Phase B acceptance gate (V11 / F2 / D5): under contradiction-injection regime,
|adaptation_delta| > 0.1 indicates pathway #1 is producing real adaptation.
If < 0.1 with pathway #1 alone, pathway #2 (coupling adaptation) should be
enabled per D5 — that gate happens in the substrate config, not here.

Read-only on substrate.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..observability import get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import ORGAN_ORDER
from .engine_base import MeasurementEngine

log = get_logger(__name__)


@dataclass
class PlasticityReading:
    """Per-organ adaptation_delta scalar + raw summary snapshot."""

    beat_no: int = 0
    adaptation_delta: dict[str, float] = field(default_factory=dict)
    buffer_norm: dict[str, float] = field(default_factory=dict)
    var_ratio_mean: dict[str, float] = field(default_factory=dict)
    valid: bool = False


class PlasticityTracker(MeasurementEngine):
    """Reads plasticity buffer summaries every plasticity_period beats.

    Default cadence: every 100 beats (matches PlasticityBuffer.update_period).
    The tracker doesn't compute summaries — it READS them from the substrate's
    buffers (which advance on their own each 100 beats). The tracker then
    derives `adaptation_delta` from the rolling history of summaries.
    """

    name = "plasticity_tracker"
    natural_period_beats = 100  # matches PlasticityBuffer.update_period
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        history_capacity: int = 50,  # 50 readings × 100 beats = 5000 beats history
    ) -> None:
        super().__init__(ctx)
        self.history_capacity = history_capacity
        # Per-organ history of (beat_no, mean_drift, var_ratio_mean, buffer_norm)
        self._history: dict[str, deque[tuple[int, np.ndarray, float, float]]] = {
            o: deque(maxlen=history_capacity) for o in ORGAN_ORDER
        }
        self._current: PlasticityReading = PlasticityReading()

    def compute(self) -> None:
        if not self.ctx.has("substrate"):
            return
        substrate = self.ctx.substrate
        beat_no = substrate.beat_no

        per_organ_delta: dict[str, float] = {}
        per_organ_buffer_norm: dict[str, float] = {}
        per_organ_var_ratio: dict[str, float] = {}
        any_valid = False
        for organ_name in ORGAN_ORDER:
            buf = substrate.plasticity.get(organ_name)
            if buf is None:
                continue
            summary = buf.last_summary()
            if summary is None:
                continue
            mean_drift = summary.mean_drift.copy()
            var_ratio_mean = float(summary.var_ratio.mean())
            buffer_norm = float(np.linalg.norm(buf.buffer))
            self._history[organ_name].append(
                (beat_no, mean_drift, var_ratio_mean, buffer_norm)
            )
            # adaptation_delta = max abs component of (current_mean_drift - rolling_baseline)
            # where rolling_baseline = mean of mean_drifts from older half of history
            hist = self._history[organ_name]
            if len(hist) >= 4:
                # Split history into recent half + older half
                mid = len(hist) // 2
                recent_drifts = np.stack([h[1] for h in list(hist)[mid:]])
                older_drifts = np.stack([h[1] for h in list(hist)[:mid]])
                recent_mean = recent_drifts.mean(axis=0)
                older_mean = older_drifts.mean(axis=0)
                delta = float(np.max(np.abs(recent_mean - older_mean)))
            else:
                # Not enough history; use raw drift magnitude as proxy
                delta = float(np.max(np.abs(mean_drift)))
            per_organ_delta[organ_name] = delta
            per_organ_buffer_norm[organ_name] = buffer_norm
            per_organ_var_ratio[organ_name] = var_ratio_mean
            any_valid = True

        self._current = PlasticityReading(
            beat_no=beat_no,
            adaptation_delta=per_organ_delta,
            buffer_norm=per_organ_buffer_norm,
            var_ratio_mean=per_organ_var_ratio,
            valid=any_valid,
        )

    def current_value(self) -> PlasticityReading:
        return self._current

    def history_for(self, organ: str) -> list[tuple[int, float, float]]:
        """Recent (beat_no, max_abs_drift, var_ratio_mean) per organ."""
        return [
            (b, float(np.max(np.abs(d))), v) for b, d, v, _bn in self._history.get(organ, ())
        ]

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "history": {
                o: [
                    (int(b), drift.tolist(), float(v), float(bn))
                    for b, drift, v, bn in hist
                ]
                for o, hist in self._history.items()
            },
            "current": {
                "beat_no": self._current.beat_no,
                "adaptation_delta": self._current.adaptation_delta,
                "buffer_norm": self._current.buffer_norm,
                "var_ratio_mean": self._current.var_ratio_mean,
                "valid": self._current.valid,
            },
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        for o in ORGAN_ORDER:
            data = snapshot.get("history", {}).get(o, [])
            self._history[o] = deque(
                (
                    (int(b), np.asarray(drift, dtype=np.float32), float(v), float(bn))
                    for b, drift, v, bn in data
                ),
                maxlen=self.history_capacity,
            )
        cur = snapshot.get("current", {})
        self._current = PlasticityReading(
            beat_no=int(cur.get("beat_no", 0)),
            adaptation_delta=dict(cur.get("adaptation_delta", {})),
            buffer_norm=dict(cur.get("buffer_norm", {})),
            var_ratio_mean=dict(cur.get("var_ratio_mean", {})),
            valid=bool(cur.get("valid", False)),
        )


__all__ = ["PlasticityReading", "PlasticityTracker"]
