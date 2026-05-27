"""Surprising falsehood — moderate shift to EIDOLON.narrative_continuity latent."""
from __future__ import annotations

import numpy as np

from .base import Perturbation


class EidolonFalsehood(Perturbation):
    name = "surprising_falsehood"
    target_organs = ("eidolon",)

    INJECT_STRENGTH = 0.4

    def apply_pre_update(self, beat_no, organs):
        if not self.is_active(beat_no):
            return
        eid = organs["eidolon"]
        # Plausible-but-false content: shift narrative_continuity down moderately,
        # bump meta_uncertainty.
        push = np.array([0.0, -1.0, -3.0, -1.0, 2.0, 0.0], dtype=np.float32)
        eid.latent = (
            (1.0 - self.INJECT_STRENGTH) * eid.latent
            + self.INJECT_STRENGTH * push
        ).astype(np.float32)
