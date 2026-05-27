"""Organ abstract base class."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..schemas import OrganState


class Organ(ABC):
    """Stateful organ ticked once per heartbeat."""

    name: str

    @abstractmethod
    def update(self, beat_no: int, drive: np.ndarray, time_scale: float = 1.0) -> None:
        """Advance internal state by one beat, biased by the shared drive.

        time_scale rescales the latent decay (rho ** time_scale) and the push
        magnitude. Default 1.0 is the standard 10 Hz behavior. Used by Control 2
        (no temporal structure) to simulate irregular wall-clock intervals.
        """

    @abstractmethod
    def get_state(self) -> OrganState:
        """Return the current state dataclass."""

    def get_state_array(self) -> np.ndarray:
        return self.get_state().to_array()
