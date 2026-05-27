"""Combine H1-H5 into one report."""
from __future__ import annotations

import json
from pathlib import Path

from . import h1_correlation, h2_contradiction, h3_cascade, h4_recovery, h5_specificity


def run_all(out_root: Path) -> dict:
    return {
        "H1": h1_correlation.run(out_root),
        "H2": h2_contradiction.run(out_root),
        "H3": h3_cascade.run(out_root),
        "H4": h4_recovery.run(out_root),
        "H5": h5_specificity.run(out_root),
    }


def save_report(report: dict, out_root: Path) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    with open(out_root / "analysis_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
