"""EIDOLON (self-model), 6 dims per §2.2.

`integration_feeling` is a subjective sense of coherence — distinct from the
computed θ value. We synthesize it from local self-coherence + a slow
contribution that drifts on top of the shared latent drive.
"""
from __future__ import annotations

import numpy as np

from ..schemas import EidolonState
from .base import Organ
from .dynamics import CoupledLatentDynamics, make_projection


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


class Eidolon(Organ):
    name = "eidolon"
    DIM = 6

    def __init__(self, dynamics: CoupledLatentDynamics, seed: int | None = None) -> None:
        self.dyn = dynamics
        rng = np.random.default_rng(seed)
        self.W = make_projection(self.DIM, rng)
        self.latent = rng.standard_normal(self.DIM).astype(np.float32) * 0.1
        self._state = EidolonState()

    def update(self, beat_no: int, drive: np.ndarray, time_scale: float = 1.0) -> None:
        push = drive @ self.W + self.dyn.organ_noise(self.DIM)
        self.latent = (0.9 ** time_scale) * self.latent + push * time_scale
        l = self.latent
        self._state = EidolonState(
            self_coherence=float(_sig(l[0])),
            confidence=float(_sig(l[1])),
            narrative_continuity=float(_sig(l[2])),
            identity_stability=float(_sig(l[3])),
            meta_uncertainty=float(_sig(l[4])),
            # subjective feeling: blends coherence + smoothed latent
            integration_feeling=float(_sig(0.5 * l[0] + 0.5 * l[5])),
        )

    def get_state(self) -> EidolonState:
        return self._state
