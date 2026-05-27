"""ComposeFunction — the typed compose/send boundary.

Per ARCH_DESIGN_v1.0.md §5 + §4.7 + IMPLEMENTATION_PLAN_v1.0.md §7.2 (P13).

★ ARCHITECTURAL KEYSTONE: ComposeFunction is the ONLY producer of
  ExternalState. Subscribers (WebSocket peers, HTTP API, JSONL writer) deal
  exclusively with ExternalState — not InternalState. The Phase C ImportError
  test (C12) verifies that axioma.interface.* modules cannot import
  InternalState, making the privacy structural.

Integration-weighted compression per ARCH §5:
  external_i = f_i · internal_i + (1 - f_i) · (rolling_mean_i + ε)

where:
  f_i = clip(θ_short · eidolon_coh · weight_i, 0, 1)  -- fidelity factor
  rolling_mean_i = EMA of internal_i over recent compose events
  ε ~ N(0, noise_factor)

f_i is high when integration is strong AND EIDOLON's self_coherence is high
(self-model is coherent enough to faithfully report). When integration drops
or self-model fragments, f_i → 0 and external state collapses toward the
running mean + noise (the peer-visible state becomes a *summary* rather than
a faithful report).

P13 (eidolon_coh signal path): EIDOLON's self_coherence is extracted live
from internal.eidolon.self_coherence at compose time — read from the current
substrate state, not cached, not buffered.

Per ARCH §4.7: compose uses θ_short × eidolon_coh (NOT PneumaState.integration_level —
that would re-introduce the v0.2 hub confound).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..observability import get_logger
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import (
    ORGAN_ORDER,
    ComposeCadence,
    ExternalState,
    InternalState,
    Zone,
)

log = get_logger(__name__)


# Default per-organ weights for the fidelity factor formula.
# weight_i = 1.0 means full integration-fidelity gating; smaller weights
# make that organ's external view more faithful regardless of integration.
DEFAULT_WEIGHTS: dict[str, float] = {
    "anima": 1.0,
    "eidolon": 1.0,
    "mneme": 1.0,
    "nous": 1.0,
    "pneuma": 1.0,
}


@dataclass
class _RollingMean:
    """Per-organ EMA tracker."""

    alpha: float
    state: np.ndarray | None = None  # shape (state_dim,)

    def update(self, x: np.ndarray) -> np.ndarray:
        if self.state is None:
            self.state = x.astype(np.float32).copy()
        else:
            self.state = ((1.0 - self.alpha) * self.state + self.alpha * x).astype(np.float32)
        return self.state.copy()

    def current(self) -> np.ndarray:
        if self.state is None:
            return np.zeros(0, dtype=np.float32)
        return self.state.copy()


class ComposeFunction:
    """Build ExternalState from InternalState with integration-weighted compression.

    Stateful (rolling means per organ; weights are config-driven). Persistence
    via save_state/load_state.
    """

    name = "compose_function"
    schema_version = 1

    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        rolling_alpha: float = 0.05,
        noise_factor: float = 0.02,
        aos_g_alert_threshold: float = 0.1,
        psi_alert_threshold: float = 0.3,
        rng_seed: int | None = None,
    ) -> None:
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)
        self.rolling_alpha = float(rolling_alpha)
        self.noise_factor = float(noise_factor)
        self.aos_g_alert_threshold = float(aos_g_alert_threshold)
        self.psi_alert_threshold = float(psi_alert_threshold)
        self.rng = np.random.default_rng(rng_seed)
        # Per-organ rolling-mean trackers
        self._rolling: dict[str, _RollingMean] = {
            name: _RollingMean(alpha=self.rolling_alpha) for name in ORGAN_ORDER
        }
        # Bounded history of recent fidelity factors (for diagnostics)
        self._fidelity_history: deque[dict[str, float]] = deque(maxlen=200)
        # Compose-count for telemetry
        self.composes_total: int = 0
        # Memoized latest compose result — consumed by AOSGEngine + publishers.
        # Avoids re-running compose with different noise samples for the same beat.
        self.latest_internal: InternalState | None = None
        self.latest_external: ExternalState | None = None

    # ── Core compose ──────────────────────────────────────────────────────

    def compose(
        self,
        internal: InternalState,
        theta_short: float,
        eidolon_coh: float | None = None,
    ) -> ExternalState:
        """Build ExternalState. Caller passes theta_short (from ThetaShortEngine)
        and optionally eidolon_coh — if None, extracted live from
        internal.eidolon.self_coherence per P13.
        """
        if eidolon_coh is None:
            eidolon_coh = float(internal.eidolon.self_coherence)
        else:
            eidolon_coh = float(eidolon_coh)
        theta_short = float(theta_short)

        # Per-organ fidelity factor + compressed array
        fidelities: dict[str, float] = {}
        organ_arrays: dict[str, np.ndarray] = {}
        for organ_name in ORGAN_ORDER:
            internal_arr = internal.get_organ(organ_name).to_array()
            f = self._fidelity_factor(organ_name, theta_short, eidolon_coh)
            fidelities[organ_name] = f
            rolling_mean = self._rolling[organ_name].update(internal_arr)
            # ε ~ N(0, noise_factor) per dimension
            noise = self.rng.normal(0.0, self.noise_factor, size=internal_arr.shape).astype(
                np.float32
            )
            # Integration-weighted compression
            external_arr = (
                f * internal_arr + (1.0 - f) * (rolling_mean + noise)
            ).astype(np.float32)
            organ_arrays[organ_name] = external_arr

        self._fidelity_history.append(fidelities)
        self.composes_total += 1

        # PNEUMA's coherence_budget is exposed (per ARCH §5.1 + §4.8 — load
        # signal for peer agents). Read from the rendered PneumaState.
        pneuma_state = internal.pneuma
        coherence_budget = float(pneuma_state.coherence_budget)

        external = ExternalState(
            anima=organ_arrays["anima"],
            eidolon=organ_arrays["eidolon"],
            mneme=organ_arrays["mneme"],
            nous=organ_arrays["nous"],
            pneuma=organ_arrays["pneuma"],
            beat_no=internal.beat_no,
            timestamp=internal.timestamp,
            theta_short=theta_short,
            fidelity_factors=fidelities,
            coherence_budget=coherence_budget,
            cadence=ComposeCadence.BASELINE,  # caller may override
            zone=Zone.IDLE,  # zone classifier sets this; default IDLE
        )
        self.latest_internal = internal
        self.latest_external = external
        return external

    # ── Fidelity factor formula ───────────────────────────────────────────

    def _fidelity_factor(
        self, organ_name: str, theta_short: float, eidolon_coh: float
    ) -> float:
        """f_i = clip(θ_short · eidolon_coh · weights[organ], 0, 1).

        Per ARCH §4.7: high θ + high self_coherence ⇒ faithful report.
        Low θ or low self_coherence ⇒ compressed report (running mean + noise).
        """
        weight = self.weights.get(organ_name, 1.0)
        raw = theta_short * eidolon_coh * weight
        return float(np.clip(raw, 0.0, 1.0))

    # ── Diagnostics ───────────────────────────────────────────────────────

    def latest_fidelities(self) -> dict[str, float] | None:
        if not self._fidelity_history:
            return None
        return dict(self._fidelity_history[-1])

    def fidelity_history(self) -> list[dict[str, float]]:
        return list(self._fidelity_history)

    def rolling_mean(self, organ_name: str) -> np.ndarray:
        return self._rolling[organ_name].current()

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "weights": dict(self.weights),
            "rolling_alpha": self.rolling_alpha,
            "noise_factor": self.noise_factor,
            "rolling_state": {
                name: (rm.state.tolist() if rm.state is not None else None)
                for name, rm in self._rolling.items()
            },
            "composes_total": self.composes_total,
            "fidelity_history": [dict(h) for h in self._fidelity_history],
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        self.weights = dict(snap.get("weights", self.weights))
        self.rolling_alpha = float(snap.get("rolling_alpha", self.rolling_alpha))
        self.noise_factor = float(snap.get("noise_factor", self.noise_factor))
        self.composes_total = int(snap.get("composes_total", 0))
        for name, st in snap.get("rolling_state", {}).items():
            if st is not None and name in self._rolling:
                self._rolling[name].state = np.asarray(st, dtype=np.float32)
        self._fidelity_history.clear()
        for h in snap.get("fidelity_history", []):
            self._fidelity_history.append(dict(h))


__all__ = ["DEFAULT_WEIGHTS", "ComposeFunction"]
