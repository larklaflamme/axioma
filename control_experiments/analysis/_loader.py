"""Shared loader for control_experiments results."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def load_summaries(out_root: Path) -> list[dict]:
    with open(out_root / "all_summaries.json") as f:
        return json.load(f)


def load_trajectories(trial_dir: Path) -> dict[str, np.ndarray]:
    npz = np.load(trial_dir / "trajectories.npz")
    return {k: npz[k] for k in npz.files}


def filter_summaries(
    summaries: list[dict],
    *,
    mode: str | None = None,
    perturbation_type: str | None = None,
    magnitude: float | None = None,
    seed: int | None = None,
) -> list[dict]:
    out = summaries
    if mode is not None:
        out = [s for s in out if s["mode"] == mode]
    if perturbation_type is not None:
        out = [s for s in out if s["perturbation_type"] == perturbation_type]
    if magnitude is not None:
        out = [s for s in out if abs(s["magnitude"] - magnitude) < 1e-6]
    if seed is not None:
        out = [s for s in out if s["seed"] == seed]
    return out
