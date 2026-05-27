"""Direct contradiction — strong negative push on EIDOLON's self_coherence latent."""
from __future__ import annotations

import numpy as np

from .base import Perturbation


class EidolonContradiction(Perturbation):
    name = "direct_contradiction"
    target_organs = ("eidolon",)

    # EIDOLON latent ORDER:
    #   0 self_coherence, 1 confidence, 2 narrative_continuity,
    #   3 identity_stability, 4 meta_uncertainty, 5 integration_feeling
    LATENT_TARGETS = np.array([-6.0, -4.0, -5.0, -4.0, 6.0, -6.0], dtype=np.float32)
    # Drive self_coherence latent strongly negative → sigmoid ≈ 0.05 (collapse)
    # and meta_uncertainty up (sigmoid ≈ 0.95).
    INJECT_STRENGTH = 0.9  # fraction of latent we overwrite each tick

    def apply_pre_update(self, beat_no, organs):
        if not self.is_active(beat_no):
            return
        eid = organs["eidolon"]
        # Strong push toward LATENT_TARGETS.
        eid.latent = (
            (1.0 - self.INJECT_STRENGTH) * eid.latent
            + self.INJECT_STRENGTH * self.LATENT_TARGETS
        ).astype(np.float32)
