"""InternalStateRingBuffer — bounded FIFO of InternalStates for measurement engines.

Owned by Heartbeat (registered as `state_buffer` in AxiomaContext). Pushed
on every beat after substrate.tick() returns. Engines read windows from it
in their compute() method.

Why a single shared buffer (not per-engine):
  - All engines read the same per-beat InternalStates; duplicating is wasteful.
  - Capacity = max(theta_long_window, raw_mi_long_window, ...) — covers all
    engines' needs in one allocation.
  - Engines call window(n) for their cadence-appropriate slice.

Per-organ state is stored as preallocated NumPy arrays (one (capacity, state_dim)
array per organ), so window() is a constant-time slice view.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import (
    ORGAN_ORDER,
    ORGAN_STATE_DIMS,
    InternalState,
)


class InternalStateRingBuffer:
    """Bounded FIFO of per-beat organ states.

    Each push records the per-organ state arrays + beat_no + timestamp.
    window(n) returns the last n entries in chronological order as a
    dict {organ: (n, D_organ) float32}.
    """

    name = "state_buffer"
    schema_version = 1

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self.capacity = int(capacity)
        self.size = 0
        self._next = 0
        self.beat_no = np.zeros(self.capacity, dtype=np.int64)
        self.timestamp = np.zeros(self.capacity, dtype=np.float64)
        self.states: dict[str, np.ndarray] = {
            name: np.zeros((self.capacity, ORGAN_STATE_DIMS[name]), dtype=np.float32)
            for name in ORGAN_ORDER
        }

    def push(self, internal: InternalState) -> None:
        i = self._next
        self.beat_no[i] = internal.beat_no
        self.timestamp[i] = internal.timestamp
        for name in ORGAN_ORDER:
            self.states[name][i] = internal.get_organ(name).to_array()
        self._next = (i + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def __len__(self) -> int:
        return self.size

    def is_full(self) -> bool:
        return self.size == self.capacity

    def window(self, n: int | None = None) -> dict[str, np.ndarray]:
        """Return the last n entries in chronological order.

        Returns dict {organ: (n_actual, D_organ) float32}. n_actual = min(n, size).
        """
        if n is None:
            n = self.size
        n = min(n, self.size)
        if n == 0:
            return {
                name: np.zeros((0, ORGAN_STATE_DIMS[name]), dtype=np.float32)
                for name in ORGAN_ORDER
            }
        end = self._next
        if self.size < self.capacity:
            # Buffer not yet wrapped — contiguous slice
            return {name: self.states[name][end - n : end].copy() for name in ORGAN_ORDER}
        # Wrapped — gather via modular indices
        idx = (np.arange(end - n, end) % self.capacity)
        return {name: self.states[name][idx].copy() for name in ORGAN_ORDER}

    def window_beats(self, n: int | None = None) -> np.ndarray:
        if n is None:
            n = self.size
        n = min(n, self.size)
        if n == 0:
            return np.zeros(0, dtype=np.int64)
        end = self._next
        if self.size < self.capacity:
            return self.beat_no[end - n : end].copy()
        return self.beat_no[(np.arange(end - n, end) % self.capacity)].copy()

    def window_timestamps(self, n: int | None = None) -> np.ndarray:
        if n is None:
            n = self.size
        n = min(n, self.size)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        end = self._next
        if self.size < self.capacity:
            return self.timestamp[end - n : end].copy()
        return self.timestamp[(np.arange(end - n, end) % self.capacity)].copy()

    def latest(self) -> dict[str, np.ndarray] | None:
        """The most recently pushed per-organ state, or None if empty."""
        if self.size == 0:
            return None
        idx = (self._next - 1) % self.capacity
        return {name: self.states[name][idx].copy() for name in ORGAN_ORDER}

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "capacity": self.capacity,
            "size": self.size,
            "next": self._next,
            "beat_no": self.beat_no.tolist(),
            "timestamp": self.timestamp.tolist(),
            "states": {name: arr.tolist() for name, arr in self.states.items()},
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        # capacity is immutable post-construction; if mismatch, cold-start
        if int(snapshot.get("capacity", self.capacity)) != self.capacity:
            return
        self.size = int(snapshot["size"])
        self._next = int(snapshot["next"])
        self.beat_no = np.asarray(snapshot["beat_no"], dtype=np.int64)
        self.timestamp = np.asarray(snapshot["timestamp"], dtype=np.float64)
        for name in ORGAN_ORDER:
            if name in snapshot["states"]:
                self.states[name] = np.asarray(
                    snapshot["states"][name], dtype=np.float32
                )
