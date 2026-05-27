"""Constants for the AOS-G gap experiment per design v0.1.0."""
from __future__ import annotations

# Compose function (design §2).
#
# Design v0.1.0 §2.2 specifies weights "sums to 1.0 across organs" with 0.20
# each. That formulation caps the fidelity factor at max(w_i) = 0.20, which
# contradicts the §2.5 phenomenology table that requires f ∈ [0, 1] (f≈1.0
# meaning "faithful copy"). The design is internally inconsistent on this
# point. To preserve the *intent* (equal weighting, full [0,1] dynamic range
# for f) we use w_i = 1.0 each. Documented in the findings report.
ORGAN_WEIGHTS = {
    "anima": 1.0,
    "eidolon": 1.0,
    "mneme": 1.0,
    "nous": 1.0,
    "pneuma": 1.0,
}
NOISE_FACTOR = 0.01  # σ = 0.01 × std(internal over last 1000 beats)
MEAN_WINDOW = 100    # 100-beat running mean per design §2.3
STD_WINDOW = 1000    # 1000-beat std per design §2.4

# Adaptive frequency controller (design §4.1)
BASELINE_INTERVAL = 30
PERT_INTERVAL = 5
PERT_WINDOW = (180, 300)        # [start, end) — phase 2 ("perturbation window")
AUTO_TRIGGER_MULTIPLIER = 2.0
AUTO_TRIGGER_DURATION = 50

# Experiment protocol (design §4.3)
N_BEATS = 600
PERTURBATION_BEAT = 200
PERTURBATION_DURATION = 20      # sustained injection across 20 beats per IMPLEMENTATION_PLAN §9

# Default trial conditions (design §4.2) and seeds (§4.4)
DEFAULT_CONDITIONS = (
    "direct_contradiction",
    "surprising_falsehood",
    "surprising_truth",
    "nonsense",
    "mneme_disruption",
    "random_perturbation",
    "baseline",
)
DEFAULT_SEEDS = (42, 43, 44)

# Substrate coupling for trials (matches the final-measurement default)
DEFAULT_COUPLING = 0.6

# Pre/post windows for H2 (design §3 H2)
H2_PRE_WINDOW = (170, 200)
H2_POST_WINDOW = (200, 230)

# Cross-correlation window for H4 (design §3 H4)
H4_WINDOW = (200, 600)

# Analysis pass/fail thresholds (mirrors IMPLEMENTATION_PLAN §6)
H1_R_THRESHOLD = -0.5
H2_RATIO_THRESHOLD = 1.2
H3_LAG_MIN = 1
H3_LAG_MAX = 5
H3_GRANGER_P = 0.05
H4_LAG_TOLERANCE = 2
H4_R_THRESHOLD = -0.5
H5_WITHIN_THRESHOLD = 0.8
H5_BETWEEN_THRESHOLD = 0.5
