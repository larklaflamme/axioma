"""NOUS — reasoning (6-dim state).

Per ARCH_DESIGN_v1.0.md §4.3:
  latent_dim = 10, state_dim = 6, ρ = 0.90, V_scale = 1.0

Rendered fields:
  inference_depth        ∈ [0, ∞)  integer
  confidence_spread      ∈ [0, 1]
  cognitive_load         ∈ [0, 1]
  active_hypotheses      ∈ [0, 20] integer
  novelty                ∈ [0, 1]
  epistemic_uncertainty  ∈ [0, 1]
"""
from __future__ import annotations

import numpy as np

from ..schemas import NousState
from .base import Organ
from .render import to_int_nonneg, to_int_range, to_unit

_MODULATION = 0.1


class Nous(Organ):
    name = "nous"

    def __init__(
        self,
        *,
        drive_dim: int,
        latent_dim: int = 10,
        rho: float = 0.90,
        v_scale: float = 1.0,
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

    def render(self, plasticity_drift: np.ndarray | None = None) -> NousState:
        z = self.latent
        drift = (
            _MODULATION * plasticity_drift
            if plasticity_drift is not None
            else np.zeros(self.latent_dim, dtype=np.float32)
        )
        return NousState(
            inference_depth=to_int_nonneg(float(z[0] + drift[0])),
            confidence_spread=to_unit(float(z[1] + drift[1])),
            cognitive_load=to_unit(float(z[2] + drift[2])),
            active_hypotheses=to_int_range(float(z[3] + drift[3]), lo=0, hi=20),
            novelty=to_unit(float(z[4] + drift[4])),
            epistemic_uncertainty=to_unit(float(z[5] + drift[5])),
        )
