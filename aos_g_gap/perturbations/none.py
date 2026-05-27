"""Baseline — no perturbation."""
from .base import Perturbation


class NoPerturbation(Perturbation):
    name = "baseline"
    target_organs = ()

    def apply_pre_update(self, beat_no, organs):
        return None
