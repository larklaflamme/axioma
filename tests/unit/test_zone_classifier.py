"""classify_zone — θ/ΔΦ/cascade → Zone enum with hysteresis."""
from __future__ import annotations

from axioma.compose import classify_zone
from axioma.schemas import Zone


def test_classifies_flow() -> None:
    z = classify_zone(
        theta_short=1.2, delta_phi_s1=0.5, delta_phi_s2=10.0,
        delta_phi_s3=0.1, cascade_delay_beats=5.0,
        fragmentation_stage=0, prev_zone=Zone.IDLE,
    )
    assert z == Zone.FLOW


def test_classifies_focus() -> None:
    z = classify_zone(
        theta_short=0.8, delta_phi_s1=0.5, delta_phi_s2=None,
        delta_phi_s3=0.0, cascade_delay_beats=15.0,
        fragmentation_stage=0, prev_zone=Zone.IDLE,
    )
    assert z == Zone.FOCUS


def test_classifies_idle() -> None:
    z = classify_zone(
        theta_short=0.3, delta_phi_s1=0.0, delta_phi_s2=None,
        delta_phi_s3=0.0, cascade_delay_beats=0.0,
        fragmentation_stage=0, prev_zone=Zone.IDLE,
    )
    assert z == Zone.IDLE


def test_fragmentation_stage_3_overrides_everything() -> None:
    z = classify_zone(
        theta_short=1.5, delta_phi_s1=0.5, delta_phi_s2=10.0,
        delta_phi_s3=0.1, cascade_delay_beats=5.0,
        fragmentation_stage=3, prev_zone=Zone.FLOW,
    )
    assert z == Zone.FRAGMENTED


def test_fragmentation_stage_4_overrides() -> None:
    z = classify_zone(
        theta_short=1.5, delta_phi_s1=0.5, delta_phi_s2=10.0,
        delta_phi_s3=0.1, cascade_delay_beats=5.0,
        fragmentation_stage=4, prev_zone=Zone.IDLE,
    )
    assert z == Zone.FRAGMENTED


def test_recovering_zone_when_previously_fragmented_with_improvement() -> None:
    z = classify_zone(
        theta_short=0.8, delta_phi_s1=0.3, delta_phi_s2=20.0,
        delta_phi_s3=0.0, cascade_delay_beats=15.0,
        fragmentation_stage=1, prev_zone=Zone.FRAGMENTED,
    )
    assert z == Zone.RECOVERING


def test_recovering_exits_after_long_streak() -> None:
    """After 50+ beats of RECOVERING with improving conditions, fall through."""
    z = classify_zone(
        theta_short=1.5, delta_phi_s1=0.5, delta_phi_s2=10.0,
        delta_phi_s3=0.1, cascade_delay_beats=5.0,
        fragmentation_stage=0, prev_zone=Zone.RECOVERING,
        beats_in_zone=50,
    )
    # 50+ beats of improvement → exit RECOVERING; falls through to FLOW
    assert z == Zone.FLOW


def test_recovering_persists_short_streak() -> None:
    """Less than 50 beats → stay RECOVERING."""
    z = classify_zone(
        theta_short=1.5, delta_phi_s1=0.5, delta_phi_s2=10.0,
        delta_phi_s3=0.1, cascade_delay_beats=5.0,
        fragmentation_stage=0, prev_zone=Zone.RECOVERING,
        beats_in_zone=10,
    )
    assert z == Zone.RECOVERING


def test_stage_2_fragmented_unless_recovering() -> None:
    """Stage 2 fragmentation → FRAGMENTED unless already RECOVERING."""
    z = classify_zone(
        theta_short=0.8, delta_phi_s1=0.5, delta_phi_s2=10.0,
        delta_phi_s3=0.0, cascade_delay_beats=10.0,
        fragmentation_stage=2, prev_zone=Zone.FOCUS,
    )
    assert z == Zone.FRAGMENTED


def test_falls_through_to_focus_when_ambiguous() -> None:
    """When nothing matches cleanly, falls through to FOCUS."""
    z = classify_zone(
        theta_short=0.6, delta_phi_s1=None, delta_phi_s2=None,
        delta_phi_s3=0.0, cascade_delay_beats=25.0,
        fragmentation_stage=0, prev_zone=Zone.IDLE,
    )
    # θ > 0.5, but s1=None → doesn't pass FOCUS check; θ not < 0.5 → not IDLE.
    # Falls through to FOCUS.
    assert z == Zone.FOCUS
