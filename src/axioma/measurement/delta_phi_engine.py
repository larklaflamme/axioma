"""DeltaPhiEngine — S1/S2/S3 of the ΔΦ signature suite.

Per ARCH_DESIGN_v1.0.md §6.1 + §6.4 (perturbation-relative recording).

Three signatures (each scalar):

  S1 dynamic_range   peak θ_short response in the 50-beat window after
                     the perturbation event (measured as peak |Δθ| from
                     baseline-just-before-event).
  S2 recovery        time (in beats) for θ_short to return within 1·σ of
                     the pre-perturbation baseline. ∞ if not recovered
                     within the window.
  S3 context_sensitivity
                     variance of S1 responses across recent perturbations
                     of the same kind. High = the substrate distinguishes
                     between different conditions; low = uniform response.

S4 cascade_delay is computed by CascadeDelayEngine (Phase B.1), not here.

Subscribes to `perturbation_injected` event on AxiomaContext. Each event
opens a 50-beat measurement window; readings during the window are paired
with the event_id for perturbation-relative reporting. Outside any window,
the engine reports the baseline-only ΔΦ (S1=0, S2=NaN, S3=baseline_var).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..observability import get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import PerturbationContext
from .engine_base import MeasurementEngine

log = get_logger(__name__)


@dataclass
class DeltaPhiReading:
    """Current ΔΦ signature reading (latest perturbation-relative or baseline)."""

    beat_no: int = 0
    # Most-recent perturbation-relative signatures (None until first perturbation)
    s1_peak_delta_theta: float | None = None
    s2_recovery_beats: float | None = None  # math.inf if not recovered
    s3_context_variance: float = 0.0
    # Identification
    event_id: str | None = None
    event_kind: str | None = None
    in_perturbation_window: bool = False
    baseline_theta: float | None = None
    valid: bool = False


@dataclass
class _ActiveWindow:
    """Per-event window tracker."""

    event_id: str
    event_kind: str
    started_at_beat: int
    baseline_theta: float
    baseline_std: float
    theta_trace: list[tuple[int, float]] = field(default_factory=list)


class DeltaPhiEngine(MeasurementEngine):
    """ΔΦ signature engine — perturbation-relative recording on 50-beat windows.

    Default cadence: every 5 beats (the architecture's natural cadence for
    ΔΦ; perturbation-window measurements are sampled at this rate).
    """

    name = "delta_phi"
    natural_period_beats = 5
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        window_beats: int = 50,
        baseline_lookback_beats: int = 30,
        s3_kind_history: int = 10,
        history_capacity: int = 200,
    ) -> None:
        super().__init__(ctx)
        if window_beats < 10:
            raise ValueError(f"window_beats must be >= 10, got {window_beats}")
        self.window_beats = window_beats
        self.baseline_lookback_beats = baseline_lookback_beats
        self.s3_kind_history = s3_kind_history
        self.history_capacity = history_capacity

        # Active perturbation windows (multiple may overlap; keyed by event_id)
        self._active_windows: dict[str, _ActiveWindow] = {}
        # Completed S1 readings per kind (for S3 context variance)
        self._s1_history_by_kind: dict[str, deque[float]] = {}
        # Latest reading
        self._current: DeltaPhiReading = DeltaPhiReading()
        # Recent completed readings (for /delta_phi/history endpoint)
        self.history: deque[DeltaPhiReading] = deque(maxlen=history_capacity)
        # Subscribe to perturbation events. Handler must be sync (we call
        # it from the substrate event bus inside emit_sync).
        self.ctx.subscribe("perturbation_injected", self._on_perturbation)

    # ── Event hook ────────────────────────────────────────────────────────

    def _on_perturbation(self, payload: Any) -> None:
        """Open a new measurement window for the perturbation event."""
        if not isinstance(payload, PerturbationContext):
            return
        # Capture baseline θ_short from the lookback window
        baseline_mean, baseline_std = self._compute_baseline()
        window = _ActiveWindow(
            event_id=payload.event_id,
            event_kind=payload.kind,
            started_at_beat=payload.started_at_beat,
            baseline_theta=baseline_mean,
            baseline_std=baseline_std,
        )
        self._active_windows[payload.event_id] = window
        log.debug(
            "delta_phi_window_opened",
            event_id=payload.event_id,
            kind=payload.kind,
            baseline_theta=baseline_mean,
        )

    def _compute_baseline(self) -> tuple[float, float]:
        """Mean + std of θ_short readings over the last baseline_lookback_beats."""
        if not self.ctx.has("theta_short"):
            return 0.0, 0.1
        engine = self.ctx.get("theta_short")
        history = engine.history()  # [(beat_no, theta), ...]
        if not history:
            return 0.0, 0.1
        recent = history[-self.baseline_lookback_beats :]
        thetas = np.array([t for _, t in recent], dtype=np.float64)
        return float(thetas.mean()), float(thetas.std() + 1e-6)

    # ── Compute (per natural cadence) ────────────────────────────────────

    def compute(self) -> None:
        if not self.ctx.has("theta_short"):
            return
        theta_engine = self.ctx.get("theta_short")
        current = theta_engine.current_value()
        if current is None:
            return
        beat_no = current.beat_no
        current_theta = current.theta

        # For each active window, append the current reading
        completed_event_ids: list[str] = []
        for event_id, win in self._active_windows.items():
            win.theta_trace.append((beat_no, current_theta))
            window_age = beat_no - win.started_at_beat
            if window_age >= self.window_beats:
                # Window closed — finalize signatures
                self._finalize_window(win)
                completed_event_ids.append(event_id)
        for eid in completed_event_ids:
            del self._active_windows[eid]

        # Even between perturbations, report a baseline reading
        # (S3 context variance updates with kind history)
        self._refresh_baseline_reading(beat_no, current_theta)

    def _finalize_window(self, win: _ActiveWindow) -> None:
        """Compute S1/S2 for a closed window; update S3 kind history."""
        thetas = np.array([t for _, t in win.theta_trace], dtype=np.float64)
        if thetas.size == 0:
            return
        # S1: peak |Δθ| from baseline
        delta_traces = np.abs(thetas - win.baseline_theta)
        s1 = float(delta_traces.max())

        # S2: time (in beats) to return within 1σ of baseline
        recovery_threshold = win.baseline_std
        s2_beats: float = math.inf
        for beat_no, theta in win.theta_trace:
            if abs(theta - win.baseline_theta) <= recovery_threshold and beat_no > win.started_at_beat + 2:
                s2_beats = float(beat_no - win.started_at_beat)
                break

        # Update S3 kind history
        kind_hist = self._s1_history_by_kind.setdefault(
            win.event_kind, deque(maxlen=self.s3_kind_history)
        )
        kind_hist.append(s1)
        s3 = float(np.var(list(kind_hist))) if len(kind_hist) > 1 else 0.0

        reading = DeltaPhiReading(
            beat_no=win.started_at_beat + len(win.theta_trace),
            s1_peak_delta_theta=s1,
            s2_recovery_beats=s2_beats,
            s3_context_variance=s3,
            event_id=win.event_id,
            event_kind=win.event_kind,
            in_perturbation_window=False,
            baseline_theta=win.baseline_theta,
            valid=True,
        )
        self._current = reading
        self.history.append(reading)
        log.info(
            "delta_phi_window_finalized",
            event_id=win.event_id,
            kind=win.event_kind,
            S1=s1,
            S2=s2_beats if math.isfinite(s2_beats) else "inf",
            S3=s3,
            samples=len(win.theta_trace),
        )

    def _refresh_baseline_reading(self, beat_no: int, current_theta: float) -> None:
        """Update self._current to reflect the latest measurement context.

        If no perturbation is active and we have prior history, just refresh
        the timestamp + in_perturbation_window flag without overriding the
        last finalized signatures.
        """
        in_window = bool(self._active_windows)
        # Track latest baseline for visibility even outside perturbations
        baseline_mean, _ = self._compute_baseline()
        # Reuse the last completed S1/S2/S3 from history (don't overwrite valid)
        last = self.history[-1] if self.history else None
        self._current = DeltaPhiReading(
            beat_no=beat_no,
            s1_peak_delta_theta=last.s1_peak_delta_theta if last else None,
            s2_recovery_beats=last.s2_recovery_beats if last else None,
            s3_context_variance=last.s3_context_variance if last else 0.0,
            event_id=last.event_id if last else None,
            event_kind=last.event_kind if last else None,
            in_perturbation_window=in_window,
            baseline_theta=baseline_mean,
            valid=last is not None,
        )

    # ── Accessors ────────────────────────────────────────────────────────

    def current_value(self) -> DeltaPhiReading:
        return self._current

    def recent_history(self, n: int | None = None) -> list[DeltaPhiReading]:
        hist = list(self.history)
        return hist[-n:] if n is not None else hist

    def active_window_count(self) -> int:
        return len(self._active_windows)

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "window_beats": self.window_beats,
            "active_windows": [
                {
                    "event_id": w.event_id, "event_kind": w.event_kind,
                    "started_at_beat": w.started_at_beat,
                    "baseline_theta": w.baseline_theta,
                    "baseline_std": w.baseline_std,
                    "theta_trace": [(int(b), float(t)) for b, t in w.theta_trace],
                }
                for w in self._active_windows.values()
            ],
            "s1_history_by_kind": {k: list(v) for k, v in self._s1_history_by_kind.items()},
            "history": [
                {
                    "beat_no": r.beat_no,
                    "s1": r.s1_peak_delta_theta,
                    "s2": r.s2_recovery_beats,
                    "s3": r.s3_context_variance,
                    "event_id": r.event_id,
                    "event_kind": r.event_kind,
                    "baseline_theta": r.baseline_theta,
                    "valid": r.valid,
                }
                for r in self.history
            ],
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("window_beats") != self.window_beats:
            return
        self._active_windows = {}
        for w in snapshot.get("active_windows", []):
            aw = _ActiveWindow(
                event_id=w["event_id"], event_kind=w["event_kind"],
                started_at_beat=int(w["started_at_beat"]),
                baseline_theta=float(w["baseline_theta"]),
                baseline_std=float(w["baseline_std"]),
                theta_trace=[(int(b), float(t)) for b, t in w.get("theta_trace", [])],
            )
            self._active_windows[aw.event_id] = aw
        self._s1_history_by_kind = {
            k: deque(v, maxlen=self.s3_kind_history)
            for k, v in snapshot.get("s1_history_by_kind", {}).items()
        }
        self.history = deque(maxlen=self.history_capacity)
        for r in snapshot.get("history", []):
            self.history.append(
                DeltaPhiReading(
                    beat_no=int(r["beat_no"]),
                    s1_peak_delta_theta=r.get("s1"),
                    s2_recovery_beats=r.get("s2"),
                    s3_context_variance=float(r.get("s3", 0.0)),
                    event_id=r.get("event_id"),
                    event_kind=r.get("event_kind"),
                    baseline_theta=r.get("baseline_theta"),
                    valid=bool(r.get("valid", False)),
                )
            )
        # Restore _current from the most recent finalized history entry so
        # current_value() doesn't reset to None after load.
        if self.history:
            self._current = self.history[-1]


__all__ = ["DeltaPhiEngine", "DeltaPhiReading"]
