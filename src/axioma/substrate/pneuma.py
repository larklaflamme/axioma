"""PNEUMA — integration peer (7-dim state).

Per ARCH_DESIGN_v1.0.md §4.3 + §4.7 (peer, not hub) + §4.8 (coherence_budget):
  latent_dim = 12, state_dim = 7 (+1 for coherence_budget), ρ = 0.92, V_scale = 1.0

★ PEER, NOT HUB. PNEUMA has the SAME interface as every other organ. No
`integrate()` method (that would re-introduce the hub confound from v0.2).

The compose function (Phase C) uses θ_global from the measurement layer,
NOT PneumaState.integration_level. PNEUMA's `integration_level` is its
own rendered observation of integration, computed from its own latent.

`coherence_budget` is new in v1.0 (ARCH §4.8). It's a load signal computed
from substrate-wide load contributors:
  load = α · NOUS.cognitive_load
       + β · MNEME.wm_load / 7
       + γ · (1 − PNEUMA.global_coherence)
       + δ · [cascade_delay > 20]   (if available)

  coherence_budget = clip(1 − load, 0, 1)

The cascade_delay term is set externally by the measurement layer; PNEUMA
caches the latest value (default 0 = no cascade_delay reading yet).

Rendered fields:
  integration_level   ∈ [0, 1]
  global_coherence    ∈ [0, 1]
  fragmentation       ∈ [0, 1]
  awareness_level     ∈ [0, 1]
  attention_focus     ∈ [0, 1]
  buffer_depth        ∈ [0, ∞)  integer
  coherence_budget    ∈ [0, 1]
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..schemas import PneumaState
from .base import Organ
from .render import to_unit

_MODULATION = 0.1

# Default coherence-budget weights — per ARCH §4.8
_BUDGET_WEIGHTS = {"nous_load": 0.3, "mneme_wm": 0.3, "pneuma_incoh": 0.3, "cascade": 0.1}

# v1.6.0 (Checkpoint II): extracted magic numbers from _compute_coherence_budget.
# `_WM_LOAD_CAPACITY` normalizes the integer working-memory load into [0,1] via
# Miller's 7±2 (ARCH §4.8); MNEME's wm_load saturates at 7 (per substrate render
# bounds), so dividing by 7 gives ~1.0 at saturation. `_CASCADE_DELAY_THRESHOLD`
# is the beat-count above which cascade-delay contributes to the budget penalty
# (ARCH §4.8 — cascade > 20 beats == sustained downstream backpressure).
_WM_LOAD_CAPACITY = 7.0
_CASCADE_DELAY_THRESHOLD = 20.0


class Pneuma(Organ):
    name = "pneuma"

    def __init__(
        self,
        *,
        drive_dim: int,
        latent_dim: int = 12,
        rho: float = 0.92,
        v_scale: float = 1.0,
        noise_scale: float = 0.1,
        latent_hard_clip: float = 30.0,
        seed: int | None = None,
    ) -> None:
        super().__init__(
            drive_dim=drive_dim,
            latent_dim=latent_dim,
            state_dim=7,  # +1 for coherence_budget
            rho=rho,
            v_scale=v_scale,
            noise_scale=noise_scale,
            latent_hard_clip=latent_hard_clip,
            seed=seed,
        )
        # Compose-buffer counter — bumped by ComposeFunction (Phase C); shown in state
        self._buffer_depth = 0
        # Load inputs that PNEUMA reads from siblings + measurement layer
        # (set by SubstrateApp / MeasurementLayer; default 0 until first beat)
        self._nous_cognitive_load = 0.0
        self._mneme_wm_load = 0
        self._cascade_delay_beats = 0.0

    # ── Compose-buffer bookkeeping ────────────────────────────────────────

    def push_compose(self) -> None:
        """ComposeFunction calls this when a compose event fires."""
        self._buffer_depth += 1

    def drain_compose(self) -> None:
        """ComposeFunction calls this after publishing the ExternalState."""
        self._buffer_depth = 0

    # ── Inputs for coherence_budget computation ──────────────────────────

    def set_load_signals(
        self,
        *,
        nous_cognitive_load: float | None = None,
        mneme_wm_load: int | None = None,
        cascade_delay_beats: float | None = None,
    ) -> None:
        """Update the inputs to coherence_budget. Called by SubstrateApp wiring
        each beat from the relevant organ states + measurement output."""
        if nous_cognitive_load is not None:
            self._nous_cognitive_load = float(nous_cognitive_load)
        if mneme_wm_load is not None:
            self._mneme_wm_load = int(mneme_wm_load)
        if cascade_delay_beats is not None:
            self._cascade_delay_beats = float(cascade_delay_beats)

    def _compute_coherence_budget(self, global_coherence: float) -> float:
        w = _BUDGET_WEIGHTS
        load = (
            w["nous_load"] * self._nous_cognitive_load
            + w["mneme_wm"] * (self._mneme_wm_load / _WM_LOAD_CAPACITY)
            + w["pneuma_incoh"] * (1.0 - global_coherence)
            + w["cascade"] * (
                1.0 if self._cascade_delay_beats > _CASCADE_DELAY_THRESHOLD else 0.0
            )
        )
        return float(np.clip(1.0 - load, 0.0, 1.0))

    # ── Render ────────────────────────────────────────────────────────────

    def render(self, plasticity_drift: np.ndarray | None = None) -> PneumaState:
        z = self.latent
        drift = (
            _MODULATION * plasticity_drift
            if plasticity_drift is not None
            else np.zeros(self.latent_dim, dtype=np.float32)
        )
        integration = to_unit(float(z[0] + drift[0]))
        global_coh = to_unit(float(z[1] + drift[1]))
        fragmentation = to_unit(float(z[2] + drift[2]))
        awareness = to_unit(float(z[3] + drift[3]))
        attention = to_unit(float(z[4] + drift[4]))
        # coherence_budget is derived, NOT a free latent dim
        budget = self._compute_coherence_budget(global_coh)
        return PneumaState(
            integration_level=integration,
            global_coherence=global_coh,
            fragmentation=fragmentation,
            awareness_level=awareness,
            attention_focus=attention,
            buffer_depth=self._buffer_depth,
            coherence_budget=budget,
        )

    def save_state(self) -> dict[str, Any]:
        snap = super().save_state()
        snap["buffer_depth"] = self._buffer_depth
        snap["nous_cognitive_load"] = self._nous_cognitive_load
        snap["mneme_wm_load"] = self._mneme_wm_load
        snap["cascade_delay_beats"] = self._cascade_delay_beats
        return snap

    def load_state(self, snapshot: dict[str, Any]) -> None:
        super().load_state(snapshot)
        self._buffer_depth = int(snapshot.get("buffer_depth", 0))
        self._nous_cognitive_load = float(snapshot.get("nous_cognitive_load", 0.0))
        self._mneme_wm_load = int(snapshot.get("mneme_wm_load", 0))
        self._cascade_delay_beats = float(snapshot.get("cascade_delay_beats", 0.0))
