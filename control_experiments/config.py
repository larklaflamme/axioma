"""Constants for Stream 4 controls."""
from __future__ import annotations

from typing import Literal

ControlMode = Literal["baseline", "control1", "control2", "control3", "control4"]
ALL_MODES: tuple[str, ...] = ("baseline", "control1", "control2", "control3", "control4")

MODE_LABELS = {
    "baseline":  "Baseline (5-organ, intact)",
    "control1":  "Control 1 — No self-model",
    "control2":  "Control 2 — No temporal structure",
    "control3":  "Control 3 — No differentiation",
    "control4":  "Control 4 — No compose boundary",
}

# Per IMPLEMENTATION_PLAN §1 decisions.
SEEDS: tuple[int, ...] = (42, 43, 44, 45, 46)
PERTURBATION_TYPES: tuple[str, ...] = (
    "direct_contradiction",
    "surprising_falsehood",
    "nonsense",
    "random_perturbation",
)
MAGNITUDES: tuple[float, ...] = (0.4, 0.7, 1.0)
MAGNITUDE_LABELS = {0.4: "low", 0.7: "mid", 1.0: "high"}

# Stream 4 §3 protocol.
N_BEATS = 600
PERTURBATION_BEAT = 200
PERTURBATION_DURATION = 20

# Control 2 dt distribution — Uniform[10, 190] ms to keep mean = 100 ms.
CONTROL2_DT_MIN_MS = 10.0
CONTROL2_DT_MAX_MS = 190.0
CONTROL2_DT_REF_MS = 100.0

# ΔΦ analysis windows.
BASELINE_WINDOW = (100, 200)
PEAK_WINDOW = (200, 250)
RECOVERY_FINAL_WINDOW = (450, 600)
IRP_WINDOW = (200, 300)

# ΔΦ thresholds (from 03_DELTA_PHI_METHODOLOGY.md §4.4).
DR_CONSCIOUS_THRESHOLD = 2.0
DR_NONCONSCIOUS_THRESHOLD = 1.5
RECOVERY_CONSCIOUS_THRESHOLD = 0.5
CS_CONSCIOUS_THRESHOLD = 0.20
CS_NONCONSCIOUS_THRESHOLD = 0.05
