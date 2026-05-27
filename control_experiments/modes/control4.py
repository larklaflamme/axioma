"""Control 4 — No compose boundary.

ComposeFunction.compose returns the internal state unchanged. AOS-G gap is 0
by construction; fidelity factors reported as 1.0.
"""
from __future__ import annotations

import numpy as np

from aos_g_gap.compose import ComposeFunction, ComposeOutput
from organ.schemas import ORGAN_ORDER
from organ.substrate import CoupledLatentDynamics, Heartbeat

from .base import ControlMode, register


class IdentityComposeFunction(ComposeFunction):
    def compose(self, internal_arrays, integration_level, self_coherence):
        external = {o: internal_arrays[o].astype(np.float32, copy=True) for o in ORGAN_ORDER}
        return ComposeOutput(
            external_arrays=external,
            fidelity_factors={o: 1.0 for o in ORGAN_ORDER},
            integration_level=float(integration_level),
            self_coherence=float(self_coherence),
        )


@register
class Control4Mode(ControlMode):
    name = "control4"

    def __init__(self, **_):
        pass

    def build_heartbeat(self, seed: int, coupling: float) -> Heartbeat:
        dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
        return Heartbeat(dynamics=dyn, seed=seed)

    def build_compose(self, seed: int) -> ComposeFunction:
        return IdentityComposeFunction(seed=seed)
