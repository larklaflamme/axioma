"""MNEME disruption — collapse working memory and retrieval rate."""
from __future__ import annotations

import numpy as np

from .base import Perturbation


class MnemeDisruption(Perturbation):
    name = "mneme_disruption"
    target_organs = ("mneme",)

    INJECT_STRENGTH = 0.8

    def apply_pre_update(self, beat_no, organs):
        if not self.is_active(beat_no):
            return
        mn = organs["mneme"]
        # MNEME latent ORDER:
        #   0 wm_load(latent), 1 retrieval_rate, 2 decay_rate,
        #   3 episodic_freshness, 4 semantic_coherence
        # Force wm_load latent low (sigmoid→~0 → wm_load=0),
        # retrieval_rate low, decay_rate high, episodic_freshness low.
        push = np.array([-5.0, -5.0, 4.0, -4.0, -2.0], dtype=np.float32)
        mn.latent = (
            (1.0 - self.INJECT_STRENGTH) * mn.latent
            + self.INJECT_STRENGTH * push
        ).astype(np.float32)
