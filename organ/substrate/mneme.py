"""MNEME (memory), 5 dims per §2.3."""
from __future__ import annotations

import numpy as np

from ..schemas import MnemeState
from .base import Organ
from .dynamics import CoupledLatentDynamics, make_projection


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


class Mneme(Organ):
    name = "mneme"
    DIM = 5

    def __init__(self, dynamics: CoupledLatentDynamics, seed: int | None = None) -> None:
        self.dyn = dynamics
        rng = np.random.default_rng(seed)
        self.W = make_projection(self.DIM, rng)
        self.latent = rng.standard_normal(self.DIM).astype(np.float32) * 0.1
        self._state = MnemeState()

    def update(self, beat_no: int, drive: np.ndarray, time_scale: float = 1.0) -> None:
        push = drive @ self.W + self.dyn.organ_noise(self.DIM)
        self.latent = (0.88 ** time_scale) * self.latent + push * time_scale
        l = self.latent
        # wm_load in [0, 7] — derive from sigmoid of latent[0], multiply by 7, round.
        wm = int(np.clip(round(7 * _sig(l[0])), 0, 7))
        self._state = MnemeState(
            wm_load=wm,
            retrieval_rate=float(_sig(l[1])),
            decay_rate=float(_sig(l[2])),
            episodic_freshness=float(_sig(l[3])),
            semantic_coherence=float(_sig(l[4])),
        )

    def get_state(self) -> MnemeState:
        return self._state
