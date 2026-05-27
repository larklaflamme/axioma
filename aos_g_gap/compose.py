"""Compose function per design §2.

For each organ i at time t:
    f_i(t) = PNEUMA.integration_level × EIDOLON.self_coherence × w_i
    compose_i(t) = f_i × internal_i + (1 − f_i) × (μ_i + ε)

ε ~ N(0, σ²) where σ = noise_factor × rolling-std(internal_i over last 1000 beats).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import NOISE_FACTOR, ORGAN_WEIGHTS, MEAN_WINDOW, STD_WINDOW
from .running_mean import RollingMeanStd

from organ.schemas import ORGAN_DIMS, ORGAN_ORDER


@dataclass
class ComposeOutput:
    external_arrays: dict[str, np.ndarray]   # per-organ composed state (D_i,)
    fidelity_factors: dict[str, float]
    integration_level: float
    self_coherence: float


class ComposeFunction:
    def __init__(
        self,
        weights: dict[str, float] | None = None,
        noise_factor: float = NOISE_FACTOR,
        seed: int | None = None,
    ) -> None:
        self.weights = dict(weights) if weights is not None else dict(ORGAN_WEIGHTS)
        for o in ORGAN_ORDER:
            if o not in self.weights:
                raise ValueError(f"Missing weight for {o}")
        self.noise_factor = float(noise_factor)
        self.rng = np.random.default_rng(seed)
        self.rolling: dict[str, RollingMeanStd] = {
            o: RollingMeanStd(ORGAN_DIMS[o], MEAN_WINDOW, STD_WINDOW) for o in ORGAN_ORDER
        }

    def update_rolling(self, internal_arrays: dict[str, np.ndarray]) -> None:
        for o in ORGAN_ORDER:
            self.rolling[o].push(internal_arrays[o])

    def fidelity_factor(self, organ: str, integration_level: float, self_coherence: float) -> float:
        return float(integration_level * self_coherence * self.weights[organ])

    def compose(
        self,
        internal_arrays: dict[str, np.ndarray],
        integration_level: float,
        self_coherence: float,
    ) -> ComposeOutput:
        external: dict[str, np.ndarray] = {}
        fidelity: dict[str, float] = {}
        for o in ORGAN_ORDER:
            internal = internal_arrays[o].astype(np.float32)
            mu = self.rolling[o].mean
            sigma = self.rolling[o].std
            f = self.fidelity_factor(o, integration_level, self_coherence)
            eps = self.noise_factor * sigma * self.rng.standard_normal(internal.shape[0]).astype(np.float32)
            external[o] = (f * internal + (1.0 - f) * (mu + eps)).astype(np.float32)
            fidelity[o] = f
        return ComposeOutput(
            external_arrays=external,
            fidelity_factors=fidelity,
            integration_level=float(integration_level),
            self_coherence=float(self_coherence),
        )

    def concat(self, arrays: dict[str, np.ndarray]) -> np.ndarray:
        """Concatenate per-organ arrays in ORGAN_ORDER into a (27,) vector."""
        return np.concatenate([arrays[o] for o in ORGAN_ORDER]).astype(np.float32)
