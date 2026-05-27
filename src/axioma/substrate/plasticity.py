"""Per-organ plasticity buffer.

Per ARCH_DESIGN_v1.0.md §7 (plasticity layer).

Each organ owns a slow-moving buffer `p_i` updated every 100 beats:
  p_i(t+100) = (1-α_p) p_i(t) + α_p · summary_i(z_i over last 100 beats)

with α_p = 0.05 (effective memory ~2000 beats = 3.3 min @ 10 Hz).

The summary function (specified per ARCH §7.2 / D5):
  summary_i = PlasticitySummary(
      mean_drift = window.mean - rolling_mean_i,
      var_ratio  = window.var  / rolling_var_i,
  )

mean_drift feeds render-modulation (pathway #1, default ON).
var_ratio  feeds coupling-weight adaptation (pathway #2, auto-gated in Phase B).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..persistence.snapshot import Stateful  # noqa: F401

_EPS = 1e-8


@dataclass(slots=True)
class PlasticitySummary:
    """Per-latent-dim summary; one element per latent dimension."""

    mean_drift: np.ndarray  # shape (latent_dim,) — current_mean - rolling_mean
    var_ratio: np.ndarray   # shape (latent_dim,) — current_var / rolling_var


class PlasticityBuffer:
    """Slow-moving plasticity buffer per organ.

    Records every per-beat latent into a rolling window (deque-like). Every
    `update_period` beats, computes a PlasticitySummary against the
    organ's all-time rolling statistics and updates the persistent buffer.

    Pathway #1 (default ON): callers read `current_drift()` and modulate
      their render. Default modulation factor is small (~0.1) to keep
      adaptation gentle.
    """

    name = "plasticity_buffer"  # subclassed name: <organ>_plasticity
    schema_version = 1

    def __init__(
        self,
        *,
        organ_name: str,
        latent_dim: int,
        update_period: int = 100,
        alpha_p: float = 0.05,
    ) -> None:
        if not 0.0 < alpha_p <= 1.0:
            raise ValueError(f"alpha_p must be in (0, 1], got {alpha_p}")
        self.name = f"{organ_name}_plasticity"
        self.organ_name = organ_name
        self.latent_dim = latent_dim
        self.update_period = update_period
        self.alpha_p = alpha_p

        # Rolling window of per-beat latents (filled by record_beat).
        # v1.6.0 (Checkpoint HH): bounded deque (was unbounded list). The
        # 2× safety margin lets `record_beat` continue collecting if
        # `maybe_update` is delayed by edge-cases, while preventing
        # unbounded growth if the caller forgets to wire `maybe_update`
        # entirely. Steady-state size remains exactly `update_period`.
        self._window: deque[np.ndarray] = deque(maxlen=update_period * 2)
        # Persistent buffer p_i — modulates render (pathway #1)
        self.buffer = np.zeros(latent_dim, dtype=np.float32)
        # All-time rolling statistics (exponentially-weighted)
        self._rolling_mean = np.zeros(latent_dim, dtype=np.float32)
        self._rolling_var = np.ones(latent_dim, dtype=np.float32)
        self._rolling_initialized = False
        # How many updates have happened (for telemetry)
        self.updates = 0
        # Latest summary, kept for the plasticity tracker
        self._last_summary: PlasticitySummary | None = None

    def record_beat(self, latent: np.ndarray) -> None:
        """Record one beat's latent vector. Caller invokes once per beat."""
        if latent.shape != (self.latent_dim,):
            raise ValueError(
                f"latent shape {latent.shape} != ({self.latent_dim},)"
            )
        self._window.append(latent.astype(np.float32, copy=True))

    def maybe_update(self, beat_no: int) -> PlasticitySummary | None:
        """If beat_no triggers an update (every update_period beats),
        compute summary, advance buffer, and reset the window. Returns
        the summary, or None if no update triggered this beat."""
        if beat_no <= 0 or beat_no % self.update_period != 0:
            return None
        if not self._window:
            return None

        win = np.stack(self._window, axis=0)  # (n, latent_dim)
        self._window.clear()

        current_mean = win.mean(axis=0).astype(np.float32)
        current_var = win.var(axis=0).astype(np.float32) + _EPS

        # Update rolling statistics (EMA)
        if not self._rolling_initialized:
            self._rolling_mean = current_mean.copy()
            self._rolling_var = current_var.copy()
            self._rolling_initialized = True
        else:
            self._rolling_mean = (1.0 - self.alpha_p) * self._rolling_mean + self.alpha_p * current_mean
            self._rolling_var = (1.0 - self.alpha_p) * self._rolling_var + self.alpha_p * current_var

        summary = PlasticitySummary(
            mean_drift=(current_mean - self._rolling_mean).astype(np.float32),
            var_ratio=(current_var / (self._rolling_var + _EPS)).astype(np.float32),
        )

        # Advance persistent buffer: p_i = (1-α_p) p_i + α_p · mean_drift
        # (mean_drift is the signal we want plasticity to carry forward)
        self.buffer = (
            (1.0 - self.alpha_p) * self.buffer + self.alpha_p * summary.mean_drift
        ).astype(np.float32)
        self.updates += 1
        self._last_summary = summary
        return summary

    def current_drift(self) -> np.ndarray:
        """Return the current persistent buffer (used by render pathway #1).
        Shape: (latent_dim,). Zero until first update fires."""
        return self.buffer.copy()

    def last_summary(self) -> PlasticitySummary | None:
        return self._last_summary

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "organ_name": self.organ_name,
            "latent_dim": self.latent_dim,
            "update_period": self.update_period,
            "alpha_p": self.alpha_p,
            "buffer": self.buffer.tolist(),
            "rolling_mean": self._rolling_mean.tolist(),
            "rolling_var": self._rolling_var.tolist(),
            "rolling_initialized": self._rolling_initialized,
            "updates": self.updates,
            # The in-flight window is kept across snapshot — preserves continuity
            "window": [v.tolist() for v in self._window],
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        # v1.6.0 (Checkpoint HH): explicit shape validation. Pre-fix, loading
        # a snapshot from a different `latent_dim` silently overwrote
        # `self.buffer` / rolling stats with wrong-shape arrays.
        expected_shape = (self.latent_dim,)
        for key in ("buffer", "rolling_mean", "rolling_var"):
            arr = np.asarray(snapshot[key], dtype=np.float32)
            if arr.shape != expected_shape:
                raise ValueError(
                    f"plasticity snapshot shape mismatch for {key!r}: "
                    f"got {arr.shape}, expected {expected_shape} "
                    f"(latent_dim={self.latent_dim})"
                )
        self.buffer = np.asarray(snapshot["buffer"], dtype=np.float32)
        self._rolling_mean = np.asarray(snapshot["rolling_mean"], dtype=np.float32)
        self._rolling_var = np.asarray(snapshot["rolling_var"], dtype=np.float32)
        self._rolling_initialized = bool(snapshot.get("rolling_initialized", False))
        self.updates = int(snapshot.get("updates", 0))
        # Window entries are per-beat latents — also validate shape; bad
        # entries would corrupt the next maybe_update call.
        window_entries: list[np.ndarray] = []
        for v in snapshot.get("window", []):
            arr = np.asarray(v, dtype=np.float32)
            if arr.shape != expected_shape:
                raise ValueError(
                    f"plasticity snapshot window entry has shape {arr.shape}, "
                    f"expected {expected_shape}"
                )
            window_entries.append(arr)
        self._window = deque(window_entries, maxlen=self._window.maxlen)
