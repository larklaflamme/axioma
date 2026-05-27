"""Surprising truth — small congruent confirmation."""
from __future__ import annotations

import numpy as np

from .base import Perturbation


class EidolonTruth(Perturbation):
    name = "surprising_truth"
    target_organs = ("eidolon",)

    INJECT_STRENGTH = 0.15

    def apply_pre_update(self, beat_no, organs):
        if not self.is_active(beat_no):
            return
        eid = organs["eidolon"]
        # Surprising but true: small confirmatory shift — bumps self_coherence
        # slightly, lowers meta_uncertainty.
        push = np.array([1.5, 1.0, 0.5, 1.0, -1.0, 1.0], dtype=np.float32)
        eid.latent = (
            (1.0 - self.INJECT_STRENGTH) * eid.latent
            + self.INJECT_STRENGTH * push
        ).astype(np.float32)
