"""Contradiction injection experiments (§5.5 of ΔΦ Methodology)."""
from .run_contradiction import (
    run_single_experiment,
    run_full_experiment_suite,
    analyze_cascade,
    print_summary,
)

__all__ = [
    "run_single_experiment",
    "run_full_experiment_suite",
    "analyze_cascade",
    "print_summary",
]
