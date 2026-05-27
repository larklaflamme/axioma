"""Adaptive compose-frequency controller per design §4.1.

Phases:
  - baseline [0, pert_window[0]): compose every BASELINE_INTERVAL beats
  - perturbation [pert_window[0], pert_window[1]): compose every PERT_INTERVAL beats
  - recovery [pert_window[1], end): compose every BASELINE_INTERVAL beats

Auto-trigger: if current_delta exceeds AUTO_TRIGGER_MULTIPLIER × baseline_mean,
switch to PERT_INTERVAL for AUTO_TRIGGER_DURATION beats.
"""
from __future__ import annotations

from .config import (
    AUTO_TRIGGER_DURATION,
    AUTO_TRIGGER_MULTIPLIER,
    BASELINE_INTERVAL,
    PERT_INTERVAL,
    PERT_WINDOW,
)


class AdaptiveComposeController:
    def __init__(
        self,
        baseline_interval: int = BASELINE_INTERVAL,
        pert_interval: int = PERT_INTERVAL,
        pert_window: tuple[int, int] = PERT_WINDOW,
        auto_trigger_multiplier: float = AUTO_TRIGGER_MULTIPLIER,
        auto_trigger_duration: int = AUTO_TRIGGER_DURATION,
    ) -> None:
        self.baseline_interval = int(baseline_interval)
        self.pert_interval = int(pert_interval)
        self.pert_start, self.pert_end = pert_window
        self.auto_trigger_multiplier = float(auto_trigger_multiplier)
        self.auto_trigger_duration = int(auto_trigger_duration)
        self._auto_until = -1  # beat_no until which auto-trigger is active

    def desired_interval(self, beat_no: int, current_delta: float, baseline_mean: float) -> int:
        if self.pert_start <= beat_no < self.pert_end:
            return self.pert_interval
        # Outside the perturbation phase: check auto-trigger.
        if baseline_mean > 1e-9 and current_delta > self.auto_trigger_multiplier * baseline_mean:
            self._auto_until = beat_no + self.auto_trigger_duration
        if beat_no < self._auto_until:
            return self.pert_interval
        return self.baseline_interval

    def phase(self, beat_no: int) -> str:
        if beat_no < self.pert_start:
            return "baseline"
        if beat_no < self.pert_end:
            return "perturbation"
        return "recovery"

    def is_auto_triggered(self, beat_no: int) -> bool:
        return beat_no < self._auto_until
