"""Hypothesis-testing modules for AOS-G gap experiment.

Each module exports a `run(...)` function returning a structured result dict.
"""
from . import h1_correlation, h2_contradiction, h3_cascade, h4_recovery, h5_specificity

__all__ = ["h1_correlation", "h2_contradiction", "h3_cascade", "h4_recovery", "h5_specificity"]
