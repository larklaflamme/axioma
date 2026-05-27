"""Rolling-window mean (100-beat) and std (1000-beat) per organ.

Updates in O(1) per push for the mean (running sum); std recomputed from the
larger window's NumPy view since it's still cheap (1000 floats × organ dim).
"""
from __future__ import annotations

import numpy as np


class RollingMeanStd:
    """Maintain rolling mean over `mean_window` and std over `std_window`."""

    def __init__(self, dim: int, mean_window: int = 100, std_window: int = 1000) -> None:
        self.dim = int(dim)
        self.mean_window = int(mean_window)
        self.std_window = int(std_window)
        self._buf = np.zeros((self.std_window, self.dim), dtype=np.float32)
        self._next = 0
        self._size = 0
        self._mean_sum = np.zeros(self.dim, dtype=np.float64)

    def push(self, x: np.ndarray) -> None:
        x = np.asarray(x, dtype=np.float32).reshape(self.dim)
        # Maintain mean_sum over the last mean_window entries.
        if self._size >= self.mean_window:
            # Subtract the entry that's about to drop out of the mean window.
            old_idx = (self._next - self.mean_window) % self.std_window
            self._mean_sum -= self._buf[old_idx]
        self._mean_sum += x
        self._buf[self._next] = x
        self._next = (self._next + 1) % self.std_window
        self._size = min(self._size + 1, self.std_window)

    @property
    def n(self) -> int:
        return self._size

    @property
    def mean(self) -> np.ndarray:
        """Mean of the last min(size, mean_window) entries."""
        n = min(self._size, self.mean_window)
        if n == 0:
            return np.zeros(self.dim, dtype=np.float32)
        return (self._mean_sum / n).astype(np.float32)

    @property
    def std(self) -> np.ndarray:
        """Std of the last min(size, std_window) entries (population std)."""
        if self._size < 2:
            return np.ones(self.dim, dtype=np.float32)
        if self._size < self.std_window:
            view = self._buf[: self._size]
        else:
            # Wrap-around: reconstruct chronological order.
            view = np.concatenate(
                [self._buf[self._next :], self._buf[: self._next]], axis=0
            )
        return view.std(axis=0).astype(np.float32)
