"""Perturbation ABC."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Perturbation(ABC):
    name: str = "perturbation"
    target_organs: tuple[str, ...] = ()

    def __init__(self, *, trigger_beat: int, duration: int, seed: int) -> None:
        self.trigger_beat = int(trigger_beat)
        self.duration = int(duration)
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)

    def is_active(self, beat_no: int) -> bool:
        return self.trigger_beat <= beat_no < (self.trigger_beat + self.duration)

    @abstractmethod
    def apply_pre_update(self, beat_no: int, organs: dict[str, object]) -> None:
        """Mutate organ-internal latent state before the organ's update() call.

        `organs` is a dict keyed by organ name; values are the actual Organ
        instances (with a `.latent` numpy array, etc.).
        """
