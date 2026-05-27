"""Control 1 — No self-model.

EIDOLON does a random walk (no drive coupling); PNEUMA is pass-through with
integration_level held at a constant 0.5. Compose still runs but its fidelity
factor collapses because EIDOLON.self_coherence is no longer a coherent signal.
"""
from __future__ import annotations

import numpy as np

from aos_g_gap.compose import ComposeFunction
from organ.schemas import EidolonState, PneumaState
from organ.substrate import CoupledLatentDynamics, Heartbeat
from organ.substrate.eidolon import Eidolon
from organ.substrate.pneuma import Pneuma

from .base import ControlMode, register


class _RandomWalkEidolon(Eidolon):
    """Pure Gaussian random walk; no drive, no coupling."""

    def __init__(self, dynamics: CoupledLatentDynamics, seed: int | None = None) -> None:
        super().__init__(dynamics, seed=seed)
        self._rng = np.random.default_rng(
            None if seed is None else seed * 9973 + 1
        )

    def update(self, beat_no: int, drive: np.ndarray, time_scale: float = 1.0) -> None:
        # Random walk: latent += N(0, 0.1) per beat. No drive contribution.
        self.latent = (self.latent + 0.1 * np.sqrt(time_scale) *
                       self._rng.standard_normal(self.DIM).astype(np.float32))
        # Render state — but force self_coherence to a constant so the compose
        # fidelity formula no longer reflects coherence dynamics.
        from organ.substrate.eidolon import _sig

        l = self.latent
        self._state = EidolonState(
            self_coherence=0.5,           # constant — no self-model
            confidence=float(_sig(l[1])),
            narrative_continuity=float(_sig(l[2])),
            identity_stability=float(_sig(l[3])),
            meta_uncertainty=float(_sig(l[4])),
            integration_feeling=float(_sig(0.5 * l[0] + 0.5 * l[5])),
        )


class _PassThroughPneuma(Pneuma):
    """Pass-through: PNEUMA's reported state is fixed; no compose-relevant
    integration signal."""

    def integrate(self, other_organs):
        self._state = PneumaState(
            integration_level=0.5,        # constant — no integration
            global_coherence=0.5,
            fragmentation=0.5,
            awareness_level=0.5,
            attention_focus=0.5,
            buffer_depth=self._buffer,
        )


@register
class Control1Mode(ControlMode):
    name = "control1"

    def __init__(self, **_):
        pass

    def build_heartbeat(self, seed: int, coupling: float) -> Heartbeat:
        dyn = CoupledLatentDynamics(coupling=coupling, seed=seed)
        hb = Heartbeat(dynamics=dyn, seed=seed)
        # Swap in the modified organs.
        hb.eidolon = _RandomWalkEidolon(dyn, seed=None if seed is None else seed + 2)
        hb.pneuma = _PassThroughPneuma(dyn, seed=None if seed is None else seed + 5)
        hb.organs = (hb.anima, hb.eidolon, hb.mneme, hb.nous, hb.pneuma)
        return hb

    def build_compose(self, seed: int) -> ComposeFunction:
        return ComposeFunction(seed=seed)
