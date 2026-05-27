"""EIDOLON — self-model (6-dim state).

Per ARCH_DESIGN_v1.0.md §4.3 (v1.0 deltas C1):
  latent_dim = 12, state_dim = 6, ρ = 0.92, V_scale = 1.3

  ★ Strongest average coupling, fastest ρ — tuned for rapid cascade
  propagation per Control 1's 6.7× cascade_delay change finding.

All rendered fields ∈ [0, 1].

`integration_feeling` is the subjective sense of integration; distinct from
the computed θ. Synthesized from self_coherence + a smoothed contribution.
"""
from __future__ import annotations

import numpy as np

from ..schemas import EidolonState
from .base import Organ
from .render import to_unit

_MODULATION = 0.1


class Eidolon(Organ):
    name = "eidolon"

    def __init__(
        self,
        *,
        drive_dim: int,
        latent_dim: int = 12,
        rho: float = 0.92,        # C1: faster ρ
        v_scale: float = 1.3,     # C1: stronger feedback
        noise_scale: float = 0.1,
        latent_hard_clip: float = 30.0,
        seed: int | None = None,
    ) -> None:
        super().__init__(
            drive_dim=drive_dim,
            latent_dim=latent_dim,
            state_dim=6,
            rho=rho,
            v_scale=v_scale,
            noise_scale=noise_scale,
            latent_hard_clip=latent_hard_clip,
            seed=seed,
        )

    def render(self, plasticity_drift: np.ndarray | None = None) -> EidolonState:
        z = self.latent
        drift = (
            _MODULATION * plasticity_drift
            if plasticity_drift is not None
            else np.zeros(self.latent_dim, dtype=np.float32)
        )
        l0 = float(z[0] + drift[0])
        l1 = float(z[1] + drift[1])
        l2 = float(z[2] + drift[2])
        l3 = float(z[3] + drift[3])
        l4 = float(z[4] + drift[4])
        l5 = float(z[5] + drift[5])
        return EidolonState(
            self_coherence=to_unit(l0),
            confidence=to_unit(l1),
            narrative_continuity=to_unit(l2),
            identity_stability=to_unit(l3),
            meta_uncertainty=to_unit(l4),
            # Blend self-coherence with a smoothed contribution
            integration_feeling=to_unit(0.5 * l0 + 0.5 * l5),
        )
