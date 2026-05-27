"""Baseline mode: intact 5-organ substrate."""
from __future__ import annotations

from aos_g_gap.compose import ComposeFunction
from organ.substrate import CoupledLatentDynamics, Heartbeat

from .base import ControlMode, register


@register
class BaselineMode(ControlMode):
    name = "baseline"

    def __init__(self, **_):
        pass

    def build_heartbeat(self, seed: int, coupling: float) -> Heartbeat:
        dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
        return Heartbeat(dynamics=dyn, seed=seed)

    def build_compose(self, seed: int) -> ComposeFunction:
        return ComposeFunction(seed=seed)
