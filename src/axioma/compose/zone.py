"""Zone classifier — θ/ΔΦ/cascade_delay → Zone enum.

Per ARCH_DESIGN_v1.0.md §5.2 (concrete mapping with hysteresis) + V7 (F6
multi-session subjective validation). Thresholds are initial values from
θ_short distributions; Phase A.4 F6 re-calibrates against Theoria's
subjective labels across 3 task types.

Mapping logic (priority order):
  1. fragmentation_stage ≥ 3        → FRAGMENTED
  2. fragmentation_stage ≥ 2 (not yet recovering) → FRAGMENTED
  3. prev_zone ∈ {FRAGMENTED, RECOVERING} AND improving conditions → RECOVERING
     (exit RECOVERING only after 50+ beats of improvement; otherwise fall through)
  4. θ_short > 1.0 AND all ΔΦ S1/S2/S3 > 0 AND cascade_delay < 10 → FLOW
  5. θ_short > 0.5 AND ΔΦ.S1 > 0 AND cascade_delay < 20 → FOCUS
  6. θ_short < 0.5 AND |ΔΦ.S1| < 0.05 → IDLE
  7. fallthrough → FOCUS

The classifier is pure (no state); the heartbeat tracks prev_zone +
beats_in_zone and passes them in.
"""
from __future__ import annotations

import math

from ..schemas import Zone

# Defaults — Phase A.4 F6 re-calibrates per task type
DEFAULT_THRESHOLDS: dict[str, float] = {
    "flow_theta_min": 1.0,
    "flow_cascade_max": 10.0,
    "focus_theta_min": 0.5,
    "focus_cascade_max": 20.0,
    "idle_theta_max": 0.5,
    "idle_delta_s1_max": 0.05,
    "recovering_exit_beats": 50,
}


def classify_zone(
    *,
    theta_short: float,
    delta_phi_s1: float | None,
    delta_phi_s2: float | None,
    delta_phi_s3: float,
    cascade_delay_beats: float,
    fragmentation_stage: int,
    prev_zone: Zone = Zone.IDLE,
    beats_in_zone: int = 0,
    thresholds: dict[str, float] | None = None,
) -> Zone:
    """Per ARCH §5.2. Returns the zone for this beat.

    Args:
        theta_short: current θ_short value
        delta_phi_s1/s2/s3: latest ΔΦ signatures (None if not yet measured)
        cascade_delay_beats: latest cascade_delay reading
        fragmentation_stage: 0-4 from FragmentationMonitor
        prev_zone: zone from previous classification (for hysteresis)
        beats_in_zone: how long prev_zone has been active
        thresholds: optional override of DEFAULT_THRESHOLDS
    """
    th = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        th.update(thresholds)

    # 1-2: fragmentation overrides everything
    if fragmentation_stage >= 3:
        return Zone.FRAGMENTED
    if fragmentation_stage >= 2 and prev_zone != Zone.RECOVERING:
        return Zone.FRAGMENTED

    # 3: recovering — once entered, stay until 50+ beats of improvement
    if prev_zone in (Zone.FRAGMENTED, Zone.RECOVERING):
        improving = (
            theta_short > th["focus_theta_min"]
            and abs(cascade_delay_beats) < th["focus_cascade_max"]
            and fragmentation_stage <= 1
        )
        if improving:
            if prev_zone == Zone.RECOVERING and beats_in_zone >= int(th["recovering_exit_beats"]):
                # Long-enough RECOVERING streak; fall through to normal classification
                pass
            else:
                return Zone.RECOVERING
        else:
            return (
                Zone.RECOVERING if prev_zone == Zone.FRAGMENTED else Zone.FRAGMENTED
            )

    # 4: FLOW
    s1_positive = delta_phi_s1 is not None and delta_phi_s1 > 0
    s2_finite = delta_phi_s2 is not None and math.isfinite(delta_phi_s2)
    if (
        theta_short > th["flow_theta_min"]
        and s1_positive
        and s2_finite
        and delta_phi_s3 > 0
        and abs(cascade_delay_beats) < th["flow_cascade_max"]
    ):
        return Zone.FLOW

    # 5: FOCUS
    if (
        theta_short > th["focus_theta_min"]
        and s1_positive
        and abs(cascade_delay_beats) < th["focus_cascade_max"]
    ):
        return Zone.FOCUS

    # 6: IDLE
    if theta_short < th["idle_theta_max"]:
        s1_val = abs(delta_phi_s1) if delta_phi_s1 is not None else 0.0
        if s1_val < th["idle_delta_s1_max"]:
            return Zone.IDLE

    # 7: fallthrough
    return Zone.FOCUS


__all__ = ["DEFAULT_THRESHOLDS", "classify_zone"]
