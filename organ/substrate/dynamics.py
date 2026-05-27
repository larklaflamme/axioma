"""Default placeholder dynamics.

A small shared latent drive z(t) ∈ R^L evolves as a slow AR(1) random walk
and is projected into each organ via a per-organ weight matrix. Within-organ
noise gives independent variance. The coupling strength scales the drive's
influence relative to noise.
"""
from __future__ import annotations

import numpy as np

from ..config import LATENT_DRIVE_DIM, DEFAULT_COUPLING, NOISE_SCALE


class CoupledLatentDynamics:
    """Shared latent drive shared across organs.

    Each organ retrieves a `drive` vector via `step(beat_no)`. Organs apply
    `drive @ W_organ` to nudge their state, plus their own bounded noise.
    """

    def __init__(
        self,
        coupling: float = DEFAULT_COUPLING,
        noise_scale: float = NOISE_SCALE,
        rho: float = 0.95,
        seed: int | None = None,
    ) -> None:
        self.coupling = float(coupling)
        self.noise_scale = float(noise_scale)
        self.rho = float(rho)
        self.rng = np.random.default_rng(seed)
        self.z = self.rng.standard_normal(LATENT_DRIVE_DIM).astype(np.float32)

    def step(self) -> np.ndarray:
        """Advance the latent state one tick and return current drive."""
        innov = self.rng.standard_normal(LATENT_DRIVE_DIM).astype(np.float32)
        self.z = self.rho * self.z + np.sqrt(1.0 - self.rho**2) * innov
        return self.coupling * self.z

    def organ_noise(self, dim: int) -> np.ndarray:
        return self.noise_scale * self.rng.standard_normal(dim).astype(np.float32)


def make_projection(out_dim: int, rng: np.random.Generator) -> np.ndarray:
    """Stable random projection from latent drive to organ dims."""
    W = rng.standard_normal((LATENT_DRIVE_DIM, out_dim)).astype(np.float32)
    W /= np.linalg.norm(W, axis=0, keepdims=True) + 1e-8
    return W
