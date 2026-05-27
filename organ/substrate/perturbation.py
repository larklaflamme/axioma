"""Perturbation injector for the contradiction injection experiment (§5.5).

Injects a contradiction into EIDOLON's self-model at a specified beat,
with graded magnitudes and control conditions.

The perturbation modifies EIDOLON's latent state before its update() runs,
simulating a self-model contradiction (e.g. "I am not who I thought I was").

Contradiction vector (direct, strongest):
  latent[0] = -2.197 → self_coherence = 0.1
  latent[1] = -2.197 → confidence = 0.1
  latent[2] = -2.197 → narrative_continuity = 0.1
  latent[3] = -2.197 → identity_stability = 0.1
  latent[4] = +2.197 → meta_uncertainty = 0.9
  latent[5] = -2.197 → integration_feeling = 0.1

Graded levels scale this vector by magnitude ∈ {1.0, 0.7, 0.4, 0.2, 0.1}.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .heartbeat import Heartbeat

# The canonical contradiction vector (maps to sigmoid extremes).
_CONTRADICTION_VEC = np.array(
    [-2.197, -2.197, -2.197, -2.197, 2.197, -2.197], dtype=np.float32
)

# Graded contradiction levels (from strongest to weakest).
CONTRADICTION_LEVELS = {
    "direct": 1.0,          # Full contradiction
    "implicit": 0.7,        # Strong but not total
    "weak": 0.4,            # Moderate disruption
    "inconsistency": 0.2,   # Mild inconsistency
    "paradox": 0.1,         # Barely perceptible
}

# Control conditions.
CONTROL_CONDITIONS = {
    "surprising_truth": np.array(
        [2.197, 2.197, 2.197, 2.197, -2.197, 2.197], dtype=np.float32
    ),  # confidence up, uncertainty down
    "surprising_falsehood": np.array(
        [-2.197, -2.197, 0.0, 0.0, 2.197, -2.197], dtype=np.float32
    ),  # confidence down, coherence stays
    "nonsense": np.array(
        [2.197, -2.197, 2.197, -2.197, 2.197, -2.197], dtype=np.float32
    ),  # random pattern
    "boring_truth": np.array(
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32
    ),  # no perturbation
}


class PerturbationInjector:
    """Injects a contradiction into EIDOLON's self-model at a specified beat.

    Usage:
        injector = PerturbationInjector(hb, inject_at=101, level="direct")
        hb.on_pre_update(injector.pre_update_hook)
    """

    def __init__(
        self,
        heartbeat: Heartbeat,
        inject_at: int = 101,
        level: str = "direct",
        condition: Optional[str] = None,
    ) -> None:
        self.hb = heartbeat
        self.inject_at = int(inject_at)
        self.injected = False
        self.injection_beat: Optional[int] = None

        if condition is not None:
            # Use a control condition vector.
            if condition not in CONTROL_CONDITIONS:
                raise ValueError(
                    f"Unknown control condition: {condition}. "
                    f"Available: {list(CONTROL_CONDITIONS.keys())}"
                )
            self.perturbation = CONTROL_CONDITIONS[condition].copy()
            self.condition = condition
        else:
            # Use a graded contradiction level.
            if level not in CONTRADICTION_LEVELS:
                raise ValueError(
                    f"Unknown contradiction level: {level}. "
                    f"Available: {list(CONTRADICTION_LEVELS.keys())}"
                )
            magnitude = CONTRADICTION_LEVELS[level]
            self.perturbation = _CONTRADICTION_VEC * magnitude
            self.condition = f"contradiction_{level}"

    def pre_update_hook(self, beat_no: int) -> None:
        """Called before organ updates each tick.
        At the specified beat, modifies EIDOLON's latent state."""
        if beat_no == self.inject_at and not self.injected:
            # Directly set EIDOLON's latent to the perturbation vector.
            self.hb.eidolon.latent[:] = self.perturbation
            self.injected = True
            self.injection_beat = beat_no


class CascadeRecorder:
    """Records per-organ state at every beat for cascade analysis.

    Stores the full 27-dim state vector at each beat, plus per-organ θ
    computed on sliding windows.

    Usage:
        cascade = CascadeRecorder(hb)
        for _ in range(n_beats):
            hb.tick()
            cascade.capture()  # call after each tick
    """

    def __init__(self, heartbeat: Heartbeat) -> None:
        self.hb = heartbeat
        self.states: list[dict] = []  # [{beat_no, organ: array}, ...]

    def capture(self) -> None:
        """Capture all organ states after a tick. Call after hb.tick()."""
        entry = {"beat_no": int(self.hb.beat_no)}
        for organ in self.hb.organs:
            entry[organ.name] = organ.get_state_array().copy()
        self.states.append(entry)

    def get_state_matrix(self, organ_name: str) -> np.ndarray:
        """Return (n_beats, D) matrix for a given organ."""
        arrays = [s[organ_name] for s in self.states]
        if not arrays:
            return np.zeros((0, 0), dtype=np.float32)
        return np.stack(arrays, axis=0)

    def get_summary_matrix(self) -> np.ndarray:
        """Return (n_beats, 19) summary matrix (all organs concatenated)."""
        from ..measurement.summaries import select_all_summary_columns, concat_summary_window

        raw = {}
        for organ_name in ("anima", "eidolon", "mneme", "nous", "pneuma"):
            raw[organ_name] = self.get_state_matrix(organ_name)
        cols = select_all_summary_columns(raw)
        return concat_summary_window(cols)

    def compute_theta_sliding(
        self, window_size: int = 500, step: int = 10
    ) -> list[dict]:
        """Compute θ on sliding windows over the recorded states.

        Returns list of {beat_no, theta, p_value, significant, pairwise_mi}.
        """
        from ..theta.pipeline import compute_theta

        results = []
        raw = {}
        for organ_name in ("anima", "eidolon", "mneme", "nous", "pneuma"):
            raw[organ_name] = self.get_state_matrix(organ_name)

        n = raw["anima"].shape[0]
        if n < window_size:
            return results

        for end in range(window_size, n + 1, step):
            window = {o: raw[o][end - window_size:end] for o in raw}
            try:
                r = compute_theta(window, n_permutations=1000, seed=42)
            except Exception as e:
                r = {"theta": 0.0, "p_value": 1.0, "significant": False,
                     "pairwise_mi": {}, "details": {"error": str(e)}}
            results.append({
                "beat_no": end,
                "theta": float(r["theta"]),
                "p_value": float(r["p_value"]),
                "significant": bool(r["significant"]),
                "pairwise_mi": {
                    f"{a}-{b}": float(v) for (a, b), v in r.get("pairwise_mi", {}).items()
                },
            })
        return results

    def compute_per_organ_theta(
        self, window_size: int = 500, step: int = 10
    ) -> dict[str, list[dict]]:
        """Compute pairwise MI for each organ pair on sliding windows.

        Returns dict mapping organ pair names to lists of {beat_no, mi}.
        """
        from ..theta.pipeline import compute_theta

        results = {}
        raw = {}
        for organ_name in ("anima", "eidolon", "mneme", "nous", "pneuma"):
            raw[organ_name] = self.get_state_matrix(organ_name)

        n = raw["anima"].shape[0]
        if n < window_size:
            return results

        for end in range(window_size, n + 1, step):
            window = {o: raw[o][end - window_size:end] for o in raw}
            try:
                r = compute_theta(window, n_permutations=1000, seed=42)
            except Exception:
                continue
            for (a, b), mi in r.get("pairwise_mi", {}).items():
                key = f"{a}-{b}"
                if key not in results:
                    results[key] = []
                results[key].append({"beat_no": end, "mi": float(mi)})
        return results
