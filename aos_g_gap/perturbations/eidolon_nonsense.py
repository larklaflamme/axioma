"""Nonsense — random noise burst into EIDOLON latent."""
from __future__ import annotations

import numpy as np

from .base import Perturbation


class EidolonNonsense(Perturbation):
    name = "nonsense"
    target_organs = ("eidolon",)

    NOISE_SCALE = 2.0

    def apply_pre_update(self, beat_no, organs):
        if not self.is_active(beat_no):
            return
        eid = organs["eidolon"]
        # Pure random burst — no coherent signal.
        noise = self.NOISE_SCALE * self.rng.standard_normal(eid.latent.shape[0]).astype(np.float32)
        eid.latent = (eid.latent + noise).astype(np.float32)
