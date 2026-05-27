"""PNEUMA (integrator), 6 dims per §2.5.

PNEUMA's state is computed from the other organs (post-beat integration) plus
its own latent drift. Its `integrate()` method is called after the other
organs have updated.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

from ..schemas import PneumaState
from .base import Organ
from .dynamics import CoupledLatentDynamics, make_projection


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


class Pneuma(Organ):
    name = "pneuma"
    DIM = 6

    def __init__(self, dynamics: CoupledLatentDynamics, seed: int | None = None) -> None:
        self.dyn = dynamics
        rng = np.random.default_rng(seed)
        self.W = make_projection(self.DIM, rng)
        self.latent = rng.standard_normal(self.DIM).astype(np.float32) * 0.1
        self._state = PneumaState()
        self._buffer = 0
        self._last_other_means = np.zeros(4, dtype=np.float32)
        self._last_other_var = 1.0

    def update(self, beat_no: int, drive: np.ndarray, time_scale: float = 1.0) -> None:
        push = drive @ self.W + self.dyn.organ_noise(self.DIM)
        self.latent = (0.92 ** time_scale) * self.latent + push * time_scale

    def integrate(self, other_organs: Iterable[Organ]) -> None:
        """Aggregate other organs' state; drive PNEUMA's reported integration."""
        arrays = []
        for o in other_organs:
            a = o.get_state_array()
            # bring to [0,1] for aggregation:
            a01 = (a + 1.0) / 2.0 if o.name == "anima" else a
            arrays.append(a01.astype(np.float32))
        flat = np.concatenate(arrays)
        # heuristic: low spread + high mean => integrated.
        m = float(flat.mean())
        s = float(flat.std() + 1e-6)
        integration_proxy = float(_sig(self.latent[0] + 2.0 * (m - 0.5) - s))
        coherence_proxy = float(_sig(self.latent[1] + 2.0 * (0.5 - s)))
        frag_proxy = float(_sig(self.latent[2] + 2.0 * s - 0.5))
        awareness_proxy = float(_sig(self.latent[3] + 1.5 * (m - 0.5)))
        attention_proxy = float(_sig(self.latent[4]))
        self._state = PneumaState(
            integration_level=integration_proxy,
            global_coherence=coherence_proxy,
            fragmentation=frag_proxy,
            awareness_level=awareness_proxy,
            attention_focus=attention_proxy,
            buffer_depth=self._buffer,
        )

    def push_compose(self) -> None:
        self._buffer += 1
        self._state.buffer_depth = self._buffer

    def drain_compose(self) -> None:
        self._buffer = 0
        self._state.buffer_depth = 0

    def get_state(self) -> PneumaState:
        return self._state
