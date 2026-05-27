"""Common loader for trial data."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from organ.schemas import ORGAN_ORDER


def load_summaries(out_root: Path) -> list[dict]:
    with open(out_root / "all_summaries.json") as f:
        return json.load(f)


def load_events(trial_dir: Path) -> list[dict]:
    path = trial_dir / "compose_events.jsonl"
    return [json.loads(line) for line in open(path)]


def load_trajectories(trial_dir: Path) -> dict[str, np.ndarray]:
    npz = np.load(trial_dir / "trajectories.npz")
    return {k: npz[k] for k in npz.files}


def all_events(summaries: list[dict]) -> list[dict]:
    """Return all compose events across all trials, with trial metadata."""
    events = []
    for s in summaries:
        td = Path(s["trial_dir"])
        for ev in load_events(td):
            ev["_seed"] = s["seed"]
            events.append(ev)
    return events


def trials_by_condition(summaries: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for s in summaries:
        out.setdefault(s["condition"], []).append(s)
    return out
