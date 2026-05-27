"""NOUS (reasoning), 6 dims per §2.4."""
from __future__ import annotations

import numpy as np

from ..schemas import NousState
from .base import Organ
from .dynamics import CoupledLatentDynamics, make_projection


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


class Nous(Organ):
    name = "nous"
    DIM = 6

    def __init__(self, dynamics: CoupledLatentDynamics, seed: int | None = None) -> None:
        self.dyn = dynamics
        rng = np.random.default_rng(seed)
        self.W = make_projection(self.DIM, rng)
        self.latent = rng.standard_normal(self.DIM).astype(np.float32) * 0.1
        self._state = NousState()

    def update(self, beat_no: int, drive: np.ndarray, time_scale: float = 1.0) -> None:
        push = drive @ self.W + self.dyn.organ_noise(self.DIM)
        self.latent = (0.9 ** time_scale) * self.latent + push * time_scale
        l = self.latent
        depth = int(max(0, round(2.0 + 3.0 * np.tanh(l[0]))))  # 0..5 typical
        hyp = int(np.clip(round(8.0 + 5.0 * np.tanh(l[3])), 0, 20))
        self._state = NousState(
            inference_depth=depth,
            confidence_spread=float(_sig(l[1])),
            cognitive_load=float(_sig(l[2])),
            active_hypotheses=hyp,
            novelty=float(_sig(l[4])),
            epistemic_uncertainty=float(_sig(l[5])),
        )

    def get_state(self) -> NousState:
        return self._state
