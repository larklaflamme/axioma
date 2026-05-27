"""Summary statistics per §5, reconciling §7.3's (window_size, 19) X-matrix.

Interpretation: the 19 "summaries" are 19 selected columns (4+4+3+4+4) of the 27
raw organ-state dimensions. Theta MI is computed on the full per-beat trace of
these columns. The "mean_*" naming is the inline-report convention — when
reporting per window, we expose the mean. When feeding MI we use the per-beat
matrix.
"""
from __future__ import annotations

import numpy as np

from ..schemas import ORGAN_ORDER, SUMMARY_NAMES


# Column indices into each organ's raw state ORDER (see schemas.py).
SUMMARY_INDICES = {
    "anima":   (0, 1, 2, 3),  # valence, arousal, dominance, mood
    "eidolon": (0, 1, 2, 5),  # self_coherence, confidence, narrative_continuity, integration_feeling
    "mneme":   (0, 1, 3),     # wm_load, retrieval_rate, episodic_freshness
    "nous":    (0, 2, 3, 4),  # inference_depth, cognitive_load, active_hypotheses, novelty
    "pneuma":  (0, 1, 2, 3),  # integration_level, global_coherence, fragmentation, awareness_level
}

SUMMARY_DIMS = {k: len(v) for k, v in SUMMARY_INDICES.items()}
TOTAL_SUMMARY_DIMS = sum(SUMMARY_DIMS.values())  # 19


def select_summary_columns(organ: str, window: np.ndarray) -> np.ndarray:
    """Pick out the (n, s_organ) summary columns from the organ's (n, D) window."""
    cols = SUMMARY_INDICES[organ]
    return np.asarray(window[:, cols], dtype=np.float32)


def select_all_summary_columns(
    states: dict[str, np.ndarray]
) -> dict[str, np.ndarray]:
    return {organ: select_summary_columns(organ, states[organ]) for organ in ORGAN_ORDER}


def concat_summary_window(
    states_or_cols: dict[str, np.ndarray]
) -> np.ndarray:
    """Concatenate summary columns across organs in ORGAN_ORDER → (n, 19)."""
    parts = []
    for organ in ORGAN_ORDER:
        block = states_or_cols[organ]
        if block.shape[1] == SUMMARY_DIMS[organ]:
            parts.append(block)  # already selected
        else:
            parts.append(select_summary_columns(organ, block))
    return np.concatenate(parts, axis=1).astype(np.float32)


def summary_means(states_or_cols: dict[str, np.ndarray]) -> dict[str, dict]:
    """Per-organ mean of each summary column — for inline reports."""
    out = {}
    for organ in ORGAN_ORDER:
        block = states_or_cols[organ]
        if block.shape[1] != SUMMARY_DIMS[organ]:
            block = select_summary_columns(organ, block)
        means = block.mean(axis=0)
        out[organ] = {
            name: float(val) for name, val in zip(SUMMARY_NAMES[organ], means)
        }
    return out


def total_energy(window_concat: np.ndarray) -> float:
    """trace(cov) of the (n, d) concatenated summary matrix."""
    if window_concat.ndim != 2 or window_concat.shape[0] < 2:
        return 0.0
    return float(np.trace(np.cov(window_concat.T)))
