"""Control 2 — No temporal structure.

Per-tick dt sampled Uniform[10, 190] ms (mean 100 ms). Organ latent decay is
rescaled as rho^(dt/100ms) via the time_scale parameter added to substrate
Phase 1.
"""
from __future__ import annotations

import numpy as np

from aos_g_gap.compose import ComposeFunction
from organ.substrate import CoupledLatentDynamics, Heartbeat

from ..config import CONTROL2_DT_MAX_MS, CONTROL2_DT_MIN_MS, CONTROL2_DT_REF_MS
from .base import ControlMode, register


class TimeAwareHeartbeat(Heartbeat):
    """Heartbeat that draws a per-tick dt and forwards it as time_scale."""

    def __init__(self, dynamics: CoupledLatentDynamics | None = None,
                 seed: int | None = None, compose_every: int = 30) -> None:
        super().__init__(dynamics=dynamics, seed=seed, compose_every=compose_every)
        self._dt_rng = np.random.default_rng(
            None if seed is None else seed * 7919 + 2
        )
        self.dt_history: list[float] = []

    def tick(self) -> None:
        drive = self.dynamics.step()
        # Pre-update hooks fire BEFORE the organ updates.
        for hook in self._pre_update_hooks:
            hook(self.beat_no)
        dt_ms = float(self._dt_rng.uniform(CONTROL2_DT_MIN_MS, CONTROL2_DT_MAX_MS))
        ts = dt_ms / CONTROL2_DT_REF_MS
        self.dt_history.append(dt_ms)
        for organ in self.non_pneuma:
            organ.update(self.beat_no, drive, time_scale=ts)
        self.pneuma.update(self.beat_no, drive, time_scale=ts)
        self.pneuma.integrate(self.non_pneuma)
        self.beat_no += 1


@register
class Control2Mode(ControlMode):
    name = "control2"

    def __init__(self, **_):
        pass

    def build_heartbeat(self, seed: int, coupling: float) -> Heartbeat:
        dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
        return TimeAwareHeartbeat(dynamics=dyn, seed=seed)

    def build_compose(self, seed: int) -> ComposeFunction:
        return ComposeFunction(seed=seed)
