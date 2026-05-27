"""Common loader for φ-scaling results."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def load_summaries(out_root: Path) -> list[dict]:
    with open(out_root / "all_summaries.json") as f:
        return json.load(f)


def theta_by_k_seed(summaries: list[dict]) -> dict[int, dict[int, float]]:
    """{organ_count: {seed: theta_baseline}}"""
    out: dict[int, dict[int, float]] = {}
    for s in summaries:
        k = int(s["organ_count"])
        seed = int(s["seed"])
        out.setdefault(k, {})[seed] = float(s["theta_baseline"])
    return out


def theta_array(summaries: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Return paired arrays (k, theta) — one row per trial."""
    ks = np.array([s["organ_count"] for s in summaries], dtype=np.float64)
    ts = np.array([s["theta_baseline"] for s in summaries], dtype=np.float64)
    return ks, ts
