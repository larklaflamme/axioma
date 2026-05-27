"""θ engines — short window (per ARCH §6.5) + long window.

Per ARCH_DESIGN_v1.0.md §6 + IMPLEMENTATION_PLAN_v1.0.md §6.1 step 1 + Q2.

  ThetaShortEngine  — 30-beat window, every beat, CPU (small matrix; kernel
                      launch overhead dominates GPU)
  ThetaLongEngine   — 500-beat window, every 10 beats, GPU (perm null with
                      100 shuffles benefits from GPU batching)

Both ship `bias_diagnostic()` per Q2 — compares θ_short trajectory against
θ_long over a recent window; if p95 |bias| > 0.20, recommends widening
the short window.

The engines read InternalState windows from `ctx.state_buffer` (the
heartbeat's InternalStateRingBuffer registered under name "state_buffer").
Compute is read-only on substrate per ARCH §6.8.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..observability import THETA_LONG, THETA_SHORT, get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from .engine_base import MeasurementEngine
from .theta_core import compute_theta_from_summary, concat_summary_window

log = get_logger(__name__)


@dataclass
class ThetaResult:
    """Latest θ measurement (msgspec-serializable for snapshots + WS push)."""

    theta: float
    p_value: float
    significant: bool
    null_95th: float
    method: str
    pairwise_mi: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    beat_no: int = 0


@dataclass
class BiasDiagnostic:
    """Output of ThetaShortEngine.bias_diagnostic() — Q2.

    p50, p95 are quantiles of |θ_short - θ_long| / max(θ_long, ε)
    across the recent paired-readings window. Recommendation is None
    or a string from {'widen_window_to_50'}.
    """

    p50: float = 0.0
    p95: float = 0.0
    n_pairs: int = 0
    recommendation: str | None = None
    insufficient_data: bool = False


class _ThetaEngineBase(MeasurementEngine):
    """Shared θ-engine logic. Subclasses set window_size, natural_period, name."""

    schema_version = 1
    backend: str = "auto"

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        window_size: int,
        n_permutations: int = 100,
        significance_threshold: float = 0.05,
        force_normalize: str | None = None,
        gauge=None,  # prometheus Gauge to update on each compute
    ) -> None:
        super().__init__(ctx)
        if window_size < 3:
            raise ValueError(f"window_size must be >= 3, got {window_size}")
        self.window_size = window_size
        self.n_permutations = n_permutations
        self.significance_threshold = significance_threshold
        self.force_normalize = force_normalize
        self._gauge = gauge
        self._current: ThetaResult | None = None
        # Rolling history of recent θ values (for bias_diagnostic)
        # Bounded so memory stays small: ~600 readings (~1 min @ 10 Hz for short)
        self._history: deque[tuple[int, float]] = deque(maxlen=600)

    def compute(self) -> None:
        """Run the θ pipeline on the current window. Read-only on substrate."""
        if not self.ctx.has("state_buffer"):
            log.warning("theta_engine_no_state_buffer", engine=self.name)
            return
        buf = self.ctx.get("state_buffer")
        if len(buf) < self.window_size:
            return  # not yet warm

        window = buf.window(self.window_size)
        summary = concat_summary_window(window)
        try:
            result = compute_theta_from_summary(
                summary,
                n_permutations=self.n_permutations,
                significance_threshold=self.significance_threshold,
                force_normalize=self.force_normalize,
                backend=self.backend,
            )
        except Exception:
            log.exception("theta_compute_failed", engine=self.name)
            return

        beat_no = int(buf.window_beats(1)[0]) if len(buf) > 0 else 0
        self._current = ThetaResult(
            theta=float(result["theta"]),
            p_value=float(result["p_value"]),
            significant=bool(result["significant"]),
            null_95th=float(result["null_95th"]),
            method=str(result["method"]),
            pairwise_mi=dict(result["pairwise_mi"]),
            details=dict(result["details"]),
            beat_no=beat_no,
        )
        self._history.append((beat_no, self._current.theta))
        if self._gauge is not None:
            self._gauge.set(self._current.theta)

    def current_value(self) -> ThetaResult | None:
        return self._current

    def history(self) -> list[tuple[int, float]]:
        """Recent (beat_no, theta) pairs, oldest → newest. Up to ~600 entries."""
        return list(self._history)

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "window_size": self.window_size,
            "n_permutations": self.n_permutations,
            "current": (
                {
                    "theta": self._current.theta,
                    "p_value": self._current.p_value,
                    "significant": self._current.significant,
                    "null_95th": self._current.null_95th,
                    "method": self._current.method,
                    "pairwise_mi": self._current.pairwise_mi,
                    "details": self._current.details,
                    "beat_no": self._current.beat_no,
                }
                if self._current is not None
                else None
            ),
            "history": list(self._history),
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("window_size") != self.window_size:
            return  # cold-start on config change
        cur = snapshot.get("current")
        if cur is not None:
            self._current = ThetaResult(
                theta=cur["theta"], p_value=cur["p_value"],
                significant=cur["significant"], null_95th=cur["null_95th"],
                method=cur["method"], pairwise_mi=cur.get("pairwise_mi", {}),
                details=cur.get("details", {}), beat_no=cur.get("beat_no", 0),
            )
        self._history = deque(
            ((int(b), float(t)) for b, t in snapshot.get("history", [])),
            maxlen=self._history.maxlen,
        )


class ThetaShortEngine(_ThetaEngineBase):
    """30-beat θ window, every beat. Used by:
      - ComposeFunction (fidelity factor — Phase C)
      - Zone classifier
      - FragmentationMonitor

    CPU backend — for n=30, kernel-launch overhead dominates GPU compute.
    """

    name = "theta_short"
    natural_period_beats = 1
    backend = "cpu"

    def __init__(self, ctx: AxiomaContext, *, window_size: int = 30, **kw: Any) -> None:
        super().__init__(ctx, window_size=window_size, gauge=THETA_SHORT, **kw)

    # ── Q2: bias diagnostic ───────────────────────────────────────────────

    def bias_diagnostic(self, *, vs_engine_name: str = "theta_long") -> BiasDiagnostic:
        """Compare θ_short trajectory against the long-window engine's history.

        Pairs by closest beat_no. If p95 |bias|/|θ_long| > 0.20, recommends
        widening the short window to 50 beats.

        Returns BiasDiagnostic with p50, p95, n_pairs, recommendation.
        """
        if not self.ctx.has(vs_engine_name):
            return BiasDiagnostic(insufficient_data=True)
        other = self.ctx.get(vs_engine_name)
        short_h = self.history()
        long_h = other.history()
        if len(short_h) < 50 or len(long_h) < 50:
            return BiasDiagnostic(insufficient_data=True)

        # Pair short readings with the nearest long reading at-or-before
        long_beats = np.array([b for b, _ in long_h])
        long_thetas = np.array([t for _, t in long_h])
        diffs: list[float] = []
        for sb, st in short_h:
            idx = int(np.searchsorted(long_beats, sb, side="right") - 1)
            if idx < 0:
                continue
            lt = float(long_thetas[idx])
            diffs.append(abs(st - lt) / max(abs(lt), 1e-6))
        if len(diffs) < 50:
            return BiasDiagnostic(insufficient_data=True)
        arr = np.array(diffs)
        p50 = float(np.percentile(arr, 50))
        p95 = float(np.percentile(arr, 95))
        recommendation = "widen_window_to_50" if p95 > 0.20 else None
        if recommendation is not None:
            log.warning(
                "theta_short_bias_exceeds_threshold",
                p95=p95,
                p50=p50,
                n_pairs=len(diffs),
                recommendation=recommendation,
            )
        return BiasDiagnostic(p50=p50, p95=p95, n_pairs=len(diffs),
                              recommendation=recommendation)


class ThetaLongEngine(_ThetaEngineBase):
    """500-beat θ window, every 10 beats. Used for:
      - Reporting (ground-truth θ, low bias)
      - ΔΦ engine baseline (Phase B)
      - Coupling-matrix recalibration controller (deferred)

    GPU backend (default) — perm null with 100 shuffles is the heavy operation
    (~50-80 ms on H100 per ARCH §6.4).
    """

    name = "theta_long"
    natural_period_beats = 10
    backend = "auto"  # gpu if available, else cpu

    def __init__(self, ctx: AxiomaContext, *, window_size: int = 500, **kw: Any) -> None:
        super().__init__(ctx, window_size=window_size, gauge=THETA_LONG, **kw)


# ── Convenience for engine wiring ──────────────────────────────────────────


def build_theta_engines(
    ctx: AxiomaContext,
    *,
    short_window: int = 30,
    long_window: int = 500,
    n_permutations: int = 100,
) -> tuple[ThetaShortEngine, ThetaLongEngine]:
    """Build both θ engines and register them under their canonical names."""
    short = ThetaShortEngine(
        ctx, window_size=short_window, n_permutations=n_permutations
    )
    long = ThetaLongEngine(
        ctx, window_size=long_window, n_permutations=n_permutations
    )
    ctx.register("theta_short", short)
    ctx.register("theta_long", long)
    return short, long
