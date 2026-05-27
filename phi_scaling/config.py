"""Constants for the φ-scaling experiment per design §4.1."""
from __future__ import annotations

PHI_SCALE_COUNTS: tuple[int, ...] = (1, 2, 3, 4, 5)
PHI_SCALE_SEEDS: tuple[int, ...] = (42, 43, 44, 45, 46)
PHI_SCALE_BEATS: int = 600
PHI_SCALE_FREEZE_AT_BEAT: int = 100
PHI_SCALE_N_PERM: int = 100

PHI_SCALE_ORDER = ("pneuma", "anima", "eidolon", "mneme", "nous")
