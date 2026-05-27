"""ANIMA — emotional core (4-dim state).

Per ARCH_DESIGN_v1.0.md §4.3:
  latent_dim = 8, state_dim = 4, ρ = 0.85, V_scale = 1.0

Rendered fields (non-saturating linear rescale + clip per ARCH §4.3 / E15):
  valence    ∈ [-1, 1]
  arousal    ∈ [ 0, 1]
  dominance  ∈ [ 0, 1]
  mood       ∈ [-1, 1]  (slow drift)
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..schemas import AnimaState
from .base import Organ
from .render import to_unit, to_unit_centered

_MODULATION = 0.1  # pathway #1 default modulation factor


class Anima(Organ):
    name = "anima"

    def __init__(
        self,
        *,
        drive_dim: int,
        latent_dim: int = 8,
        rho: float = 0.85,
        v_scale: float = 1.0,
        noise_scale: float = 0.1,
        latent_hard_clip: float = 30.0,
        seed: int | None = None,
    ) -> None:
        super().__init__(
            drive_dim=drive_dim,
            latent_dim=latent_dim,
            state_dim=4,
            rho=rho,
            v_scale=v_scale,
            noise_scale=noise_scale,
            latent_hard_clip=latent_hard_clip,
            seed=seed,
        )
        # Slow mood drift — separate scalar latent that lags the valence latent.
        # Initialized small per cold-start convention.
        self._mood_latent = float(self.rng.standard_normal() * 0.1)

    def render(self, plasticity_drift: np.ndarray | None = None) -> AnimaState:
        z = self.latent
        drift = (
            _MODULATION * plasticity_drift
            if plasticity_drift is not None
            else np.zeros(self.latent_dim, dtype=np.float32)
        )
        # Use latent dims 0..3 for the four observable fields, plus mood drift
        valence_l = float(z[0] + drift[0])
        arousal_l = float(z[1] + drift[1])
        dominance_l = float(z[2] + drift[2])

        # Mood is a slow EMA of valence latent (smoothed over many beats)
        self._mood_latent = 0.99 * self._mood_latent + 0.01 * valence_l

        return AnimaState(
            valence=to_unit_centered(valence_l),
            arousal=to_unit(arousal_l),
            dominance=to_unit(dominance_l),
            mood=to_unit_centered(self._mood_latent),
        )

    def save_state(self) -> dict[str, Any]:
        snap = super().save_state()
        snap["mood_latent"] = self._mood_latent
        return snap

    def load_state(self, snapshot: dict[str, Any]) -> None:
        super().load_state(snapshot)
        self._mood_latent = float(snapshot.get("mood_latent", 0.0))
