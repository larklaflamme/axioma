"""Random perturbation — non-specific noise into every organ's latent."""
from __future__ import annotations

import numpy as np

from .base import Perturbation


class RandomAll(Perturbation):
    name = "random_perturbation"
    target_organs = ("anima", "eidolon", "mneme", "nous", "pneuma")

    NOISE_SCALE = 0.6  # moderate; the design predicts a "minimal" gap increase

    def apply_pre_update(self, beat_no, organs):
        if not self.is_active(beat_no):
            return
        for o in self.target_organs:
            organ = organs[o]
            noise = self.NOISE_SCALE * self.rng.standard_normal(organ.latent.shape[0]).astype(np.float32)
            organ.latent = (organ.latent + noise).astype(np.float32)
