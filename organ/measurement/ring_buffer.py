"""Fixed-size ring buffer of organ states.

Preallocated NumPy arrays per organ; O(1) push; constant-time window access.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..config import RING_BUFFER_SIZE
from ..schemas import ORGAN_DIMS, ORGAN_ORDER


class RingBuffer:
    def __init__(self, capacity: int = RING_BUFFER_SIZE) -> None:
        self.capacity = int(capacity)
        self.size = 0
        self._next = 0
        self.beat_no = np.zeros(self.capacity, dtype=np.int64)
        self.timestamp = np.zeros(self.capacity, dtype=np.float64)
        self.states: dict[str, np.ndarray] = {
            name: np.zeros((self.capacity, ORGAN_DIMS[name]), dtype=np.float32)
            for name in ORGAN_ORDER
        }

    def push(
        self,
        beat_no: int,
        timestamp: float,
        state_arrays: dict[str, np.ndarray],
    ) -> None:
        i = self._next
        self.beat_no[i] = beat_no
        self.timestamp[i] = timestamp
        for name in ORGAN_ORDER:
            self.states[name][i] = state_arrays[name]
        self._next = (i + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def window(self, n: Optional[int] = None) -> dict[str, np.ndarray]:
        """Return the last `n` entries (chronological order), or all available."""
        if n is None:
            n = self.size
        n = min(n, self.size)
        if n == 0:
            return {name: np.zeros((0, ORGAN_DIMS[name]), dtype=np.float32) for name in ORGAN_ORDER}
        end = self._next
        if self.size < self.capacity:
            start = end - n
            sl = np.arange(start, end)
        else:
            sl = (np.arange(end - n, end) % self.capacity)
        return {name: self.states[name][sl] for name in ORGAN_ORDER}

    def window_beats(self, n: Optional[int] = None) -> np.ndarray:
        if n is None:
            n = self.size
        n = min(n, self.size)
        if n == 0:
            return np.zeros(0, dtype=np.int64)
        end = self._next
        if self.size < self.capacity:
            return self.beat_no[end - n:end].copy()
        return self.beat_no[(np.arange(end - n, end) % self.capacity)].copy()
