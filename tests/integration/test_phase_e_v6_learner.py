"""V6 — F2 recovery learner monitoring window test.

Per IMPLEMENTATION_PLAN_v1.0.md §9.2 V6 + ARCH §4.9.1.

Synthetic regime that produces no improvement after 20 events:
  - Learner stays in MONITORING through event 60
  - Then transitions to INEFFECTIVE
  - Reverts to defaults
  - Gathers 100-event clean baseline (no exploration)
  - Re-engages

Constructs RecoveryEvents directly rather than driving the heartbeat —
quality scores are computed from θ which is stochastic; for the F2 monitoring
behavior we want deterministic event scores.
"""
from __future__ import annotations

import uuid

import numpy as np

from axioma.config import RecoveryConfig
from axioma.substrate.recovery import (
    LearnerEfficacy,
    RecoveryEvent,
    RecoveryHistory,
    RecoveryLearner,
    RecoveryQuality,
)


def _make_event(
    stage: int,
    composite_score: float,
    *,
    is_default: bool,
    cfg: RecoveryConfig,
    beat_no: int,
) -> RecoveryEvent:
    """Build a finalized event with the requested score and default/explore tag."""
    if is_default:
        actions_used = {
            "coupling_reduction_factor": cfg.coupling_reduction_factor,
            "mneme_forgetting_boost": cfg.mneme_forgetting_boost,
            "recovery_compose_period_beats": cfg.recovery_compose_period_beats,
            "stage_overlay_3": stage >= 3,
            "stage_overlay_4": stage >= 4,
        }
    else:
        # Slightly perturbed params (within PARAM_RANGES)
        actions_used = {
            "coupling_reduction_factor": cfg.coupling_reduction_factor * 0.9,
            "mneme_forgetting_boost": cfg.mneme_forgetting_boost * 1.1,
            "recovery_compose_period_beats": cfg.recovery_compose_period_beats,
            "stage_overlay_3": stage >= 3,
            "stage_overlay_4": stage >= 4,
        }
    return RecoveryEvent(
        event_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        stage=stage,
        started_at_beat=beat_no,
        ended_at_beat=beat_no + 100,
        actions_used=actions_used,
        quality=RecoveryQuality(
            smoothness=composite_score, completeness=composite_score,
            durability=1.0, composite_score=composite_score,
        ),
        quality_finalized=True,
    )


def _stuff_history(history: RecoveryHistory, events: list[RecoveryEvent]) -> None:
    for e in events:
        history.append(e)


def test_warming_up_below_20_events() -> None:
    """First 19 events: efficacy is WARMING_UP (n < 20)."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    for i in range(19):
        e = _make_event(2, 0.5, is_default=True, cfg=cfg, beat_no=i * 100)
        history.append(e)
        learner.update(history)
    assert learner.efficacy_per_stage[2] == LearnerEfficacy.WARMING_UP


def test_monitoring_between_20_and_60_events_no_improvement() -> None:
    """Events 20-59: stuck-at-baseline regime → MONITORING (extension active)."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    # 30 events at the same composite_score → no improvement vs baseline
    for i in range(30):
        e = _make_event(2, 0.5, is_default=True, cfg=cfg, beat_no=i * 100)
        history.append(e)
        learner.update(history)
    # n=30 → below extension threshold (60) → MONITORING
    assert learner.efficacy_per_stage[2] == LearnerEfficacy.MONITORING


def test_ineffective_after_60_events_no_improvement_triggers_revert() -> None:
    """Events ≥ 60 with no improvement → INEFFECTIVE fires + revert + clean baseline."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    # Adopt a non-default learned param manually to verify revert
    from axioma.substrate.recovery import LearnerParams
    learner.current_params[2] = LearnerParams(
        coupling_reduction_factor=0.7,  # ≠ default 0.8
        mneme_forgetting_boost=2.0,
        recovery_compose_period_beats=80,
    )
    history = RecoveryHistory()
    # Stop at exactly the 60th event to verify the INEFFECTIVE → revert transition.
    for i in range(60):
        e = _make_event(2, 0.4, is_default=True, cfg=cfg, beat_no=i * 100)
        history.append(e)
        learner.update(history)
    assert learner.efficacy_per_stage[2] == LearnerEfficacy.INEFFECTIVE
    assert learner.reversions_count >= 1
    # Reverted to defaults
    assert learner.current_params[2].coupling_reduction_factor == cfg.coupling_reduction_factor
    # Clean-baseline window armed
    assert learner._clean_baseline_remaining[2] == cfg.learner_clean_baseline_events
    # One more event ticks the clean-baseline counter
    history.append(_make_event(2, 0.5, is_default=True, cfg=cfg, beat_no=60 * 100))
    learner.update(history)
    assert learner.efficacy_per_stage[2] == LearnerEfficacy.WARMING_UP
    assert learner._clean_baseline_remaining[2] == cfg.learner_clean_baseline_events - 1
    # Only one reversion across the whole window (no double-fire)
    assert learner.reversions_count == 1


def test_clean_baseline_window_disables_exploration() -> None:
    """During clean-baseline window, select_params always returns defaults."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(0))
    learner._clean_baseline_remaining[2] = 50  # arm the window
    history = RecoveryHistory()
    # Stuff enough finalized events so exploration WOULD normally fire
    for i in range(30):
        e = _make_event(2, 0.5, is_default=True, cfg=cfg, beat_no=i * 100)
        history.append(e)
    # 20 calls to select_params; all must return defaults despite exploration_rate
    for _ in range(20):
        params = learner.select_params(2, history)
        assert params.coupling_reduction_factor == cfg.coupling_reduction_factor
        assert params.mneme_forgetting_boost == cfg.mneme_forgetting_boost


def test_clean_baseline_window_suppresses_revert() -> None:
    """During the clean-baseline window, no additional reverts can fire even
    if events keep coming with no improvement."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    # Phase 1: 60 stuck-at-0.4 events → INEFFECTIVE at event 60 → revert
    for i in range(60):
        history.append(_make_event(2, 0.4, is_default=True, cfg=cfg, beat_no=i * 100))
        learner.update(history)
    assert learner.efficacy_per_stage[2] == LearnerEfficacy.INEFFECTIVE
    assert learner.reversions_count == 1
    # Phase 2: send events WITHIN the clean-baseline window (100 events). Even if
    # they show no improvement, the revert path is suppressed.
    for i in range(cfg.learner_clean_baseline_events - 10):
        history.append(_make_event(2, 0.4, is_default=True, cfg=cfg, beat_no=(60 + i) * 100))
        learner.update(history)
    # Still 1 reversion (no double-fire while clean-baseline armed)
    assert learner.reversions_count == 1
    # Still ticking
    assert 0 < learner._clean_baseline_remaining[2] < cfg.learner_clean_baseline_events


def test_effective_when_improvement_observed() -> None:
    """Last-10 median improvement >= 0.10 over baseline → EFFECTIVE.

    Setup: 20 *default* events at 0.4 (baseline = 0.4), then 10 *explored*
    events at 0.7 (so the baseline refresh at n=30 doesn't include them and
    stays at 0.4 → improvement = 0.3 → EFFECTIVE).
    """
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    # 20 default events at score 0.4 (establishes baseline = 0.4)
    for i in range(20):
        history.append(_make_event(2, 0.4, is_default=True, cfg=cfg, beat_no=i * 100))
        learner.update(history)
    # Then 10 EXPLORED events at 0.7 — baseline refresh at n=30 finds zero
    # defaults in last 10, baseline stays at 0.4; recent-10 median = 0.7;
    # improvement = 0.3 → EFFECTIVE
    for i in range(20, 30):
        history.append(_make_event(2, 0.7, is_default=False, cfg=cfg, beat_no=i * 100))
        learner.update(history)
    assert learner.efficacy_per_stage[2] == LearnerEfficacy.EFFECTIVE


def test_reset_clears_state() -> None:
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    # v1.5.1 (Checkpoint BB): baseline_score is now per-stage
    learner.baseline_score_per_stage[2] = 0.5
    learner.baseline_score_per_stage[3] = 0.7
    learner.adoptions_count = 7
    from axioma.substrate.recovery import LearnerParams
    learner.current_params[2] = LearnerParams(
        coupling_reduction_factor=0.7,
        mneme_forgetting_boost=2.0,
        recovery_compose_period_beats=80,
    )
    learner._clean_baseline_remaining[2] = 50
    learner.efficacy_per_stage[2] = LearnerEfficacy.EFFECTIVE
    learner.reset()
    assert learner.baseline_score_per_stage == {2: 0.0, 3: 0.0}
    assert learner.current_params[2].coupling_reduction_factor == cfg.coupling_reduction_factor
    assert learner.efficacy_per_stage[2] == LearnerEfficacy.WARMING_UP
    assert learner._clean_baseline_remaining[2] == 0


def test_to_dict_includes_new_fields() -> None:
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg)
    learner.efficacy_per_stage[2] = LearnerEfficacy.MONITORING
    learner._clean_baseline_remaining[3] = 42
    d = learner.to_dict()
    assert d["efficacy_per_stage"]["2"] == "monitoring"
    assert d["clean_baseline_remaining"]["3"] == 42


def test_load_dict_restores_new_fields() -> None:
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg)
    learner.efficacy_per_stage[2] = LearnerEfficacy.EFFECTIVE
    learner._clean_baseline_remaining[2] = 13
    d = learner.to_dict()
    fresh = RecoveryLearner(cfg)
    fresh.load_dict(d)
    assert fresh.efficacy_per_stage[2] == LearnerEfficacy.EFFECTIVE
    assert fresh._clean_baseline_remaining[2] == 13
