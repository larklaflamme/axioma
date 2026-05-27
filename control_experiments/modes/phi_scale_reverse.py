"""φ-scaling with REVERSE organ ordering (NOUS-first instead of PNEUMA-first).

Tests whether ANIMA's Δθ dominance is order-dependent.
If ANIMA still dominates when added at k=4 (instead of k=2), dominance is intrinsic.
If ANIMA's contribution shrinks, dominance was an order artifact.
"""
from __future__ import annotations

import numpy as np

from aos_g_gap.compose import ComposeFunction
from organ.substrate import CoupledLatentDynamics, Heartbeat

from .base import ControlMode, register


# REVERSE order: NOUS first, PNEUMA last.
PHI_SCALE_REVERSE_ORDER = ("nous", "mneme", "eidolon", "anima", "pneuma")

DISABLED_ORGANS: dict[int, tuple[str, ...]] = {
    1: ("mneme", "eidolon", "anima", "pneuma"),
    2: ("eidolon", "anima", "pneuma"),
    3: ("anima", "pneuma"),
    4: ("pneuma",),
    5: (),
}


@register
class PhiScaleReverseMode(ControlMode):
    name = "phi_scale_reverse"

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
