"""Shared harness for Phase F follow-up experiments.

Each Phase F script:
  1. Builds a substrate stack (reuses Phase E harness)
  2. Runs an experiment (specific to the script)
  3. Writes a JSON result to results/phase_f/<name>.json

The aggregator (`aggregator.py`) rolls these up into `phase_f_summary.md`.
Per IMPLEMENTATION_PLAN_v1.0.md §10.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

# Wire test harness into sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from integration.phase_e_harness import (
    PhaseEStack,
    build_phase_e_stack,
    run_for_beats,
)

RESULTS_ROOT = Path(__file__).resolve().parents[2] / "results" / "phase_f"


def write_result(name: str, data: dict[str, Any]) -> Path:
    """Write a Phase F result JSON to results/phase_f/<name>.json."""
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    path = RESULTS_ROOT / f"{name}.json"
    body = {
        "name": name,
        "timestamp": time.time(),
        **data,
    }
    path.write_text(json.dumps(body, indent=2, default=str))
    return path


__all__ = [
    "RESULTS_ROOT",
    "PhaseEStack",
    "build_phase_e_stack",
    "run_for_beats",
    "write_result",
]
