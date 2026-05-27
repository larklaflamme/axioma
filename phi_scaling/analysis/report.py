"""Combine analyses into one report."""
from __future__ import annotations

import json
from pathlib import Path

from . import per_organ_contribution, scaling_fits


def run_all(out_root: Path) -> dict:
    return {
        "scaling_fits": scaling_fits.run(out_root),
        "per_organ_contribution": per_organ_contribution.run(out_root),
    }


def save_report(report: dict, out_root: Path) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "analysis_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
