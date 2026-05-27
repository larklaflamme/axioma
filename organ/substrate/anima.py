"""ANIMA (emotional core), 4 dims per §2.1."""
from __future__ import annotations

import numpy as np

from ..schemas import AnimaState
from .base import Organ
from .dynamics import CoupledLatentDynamics, make_projection


def _sig(x: float | np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class Anima(Organ):
    name = "anima"
    DIM = 4

    def __init__(self, dynamics: CoupledLatentDynamics, seed: int | None = None) -> None:
        self.dyn = dynamics
        rng = np.random.default_rng(seed)
        self.W = make_projection(self.DIM, rng)
        self.latent = rng.standard_normal(self.DIM).astype(np.float32) * 0.1
        self.mood_latent = float(rng.standard_normal() * 0.1)
        self._state = AnimaState()

    def update(self, beat_no: int, drive: np.ndarray, time_scale: float = 1.0) -> None:
        push = drive @ self.W + self.dyn.organ_noise(self.DIM)
        self.latent = (0.85 ** time_scale) * self.latent + push * time_scale
        # Mood drifts slowly toward mean of valence latent.
        self.mood_latent = 0.99 * self.mood_latent + 0.01 * float(self.latent[0])
        self._state = AnimaState(
            valence=float(np.tanh(self.latent[0])),
            arousal=float(_sig(self.latent[1])),
            dominance=float(_sig(self.latent[2])),
            mood=float(np.tanh(self.mood_latent)),
        )

    def get_state(self) -> AnimaState:
        return self._state
