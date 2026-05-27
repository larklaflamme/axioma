"""φ-scaling mode: variable organ count per ideas/05_PHI_SCALING_EXPERIMENT.md.

Strategy:
  - PNEUMA-first selection order (PNEUMA always active).
  - Organs beyond `organ_count` are "disabled":
      * Warm up normally for `freeze_at_beat` (100) beats.
      * At beat 100, snapshot each soon-to-be-disabled organ's full state.
      * From beat 100 onward, zero the latent every tick AND pin the state
        fields to the frozen snapshot.
  - Disabled organs have zero variance in their summary columns, so
    `drop_constant_dims` in compute_theta removes them cleanly.
  - For k=1 (PNEUMA only), the standard cross-organ θ pipeline yields
    fewer than 2 blocks → θ = 0. The runner overrides that case using
    `phi_scaling.intra_theta.compute_intra_organ_theta`.
"""
from __future__ import annotations

import numpy as np

from aos_g_gap.compose import ComposeFunction
from organ.substrate import CoupledLatentDynamics, Heartbeat

from .base import ControlMode, register


# Order in which organs are added when k grows from 1 → 5.
PHI_SCALE_ORDER = ("pneuma", "anima", "eidolon", "mneme", "nous")

DISABLED_ORGANS: dict[int, tuple[str, ...]] = {
    1: ("anima", "eidolon", "mneme", "nous"),
    2: ("eidolon", "mneme", "nous"),
    3: ("mneme", "nous"),
    4: ("nous",),
    5: (),
}


@register
class PhiScaleMode(ControlMode):
    name = "phi_scale"

    def __init__(self, organ_count: int = 5, freeze_at_beat: int = 100, **_) -> None:
        if int(organ_count) not in range(1, 6):
            raise ValueError(f"organ_count must be 1..5, got {organ_count}")
        self.organ_count = int(organ_count)
        self.freeze_at_beat = int(freeze_at_beat)
        self._disabled: tuple[str, ...] = DISABLED_ORGANS[self.organ_count]
        self._frozen_states: dict[str, dict[str, float]] = {}

    def build_heartbeat(self, seed: int, coupling: float) -> Heartbeat:
        dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
        return Heartbeat(dynamics=dyn, seed=seed)

    def build_compose(self, seed: int) -> ComposeFunction:
        return ComposeFunction(seed=seed)

    def post_tick(self, hb: Heartbeat) -> None:
        # Step 1: at the freeze beat, snapshot each disabled organ's state.
        if hb.beat_no == self.freeze_at_beat and not self._frozen_states:
            for name in self._disabled:
                organ = getattr(hb, name)
                state = organ.get_state()
                self._frozen_states[name] = {
                    field: float(getattr(state, field)) for field in state.ORDER
                }

        # Step 2: after the freeze beat, zero disabled latents and pin state.
        if hb.beat_no >= self.freeze_at_beat:
            for name in self._disabled:
                organ = getattr(hb, name)
                organ.latent[:] = 0.0
                snap = self._frozen_states.get(name)
                if snap is not None:
                    state = organ.get_state()
                    for field, value in snap.items():
                        setattr(state, field, value)
