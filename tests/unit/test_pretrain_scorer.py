"""Substrate-driven F4 scorer — v1.1.3."""
from __future__ import annotations

import numpy as np

from axioma.config import RecoveryConfig
from axioma.substrate.pretrain_scorer import substrate_score_fn
from axioma.substrate.recovery import LearnerParams, RecoveryHistory, RecoveryLearner


def test_scorer_returns_score_in_valid_range() -> None:
    params = LearnerParams(
        coupling_reduction_factor=0.8,
        mneme_forgetting_boost=1.5,
        recovery_compose_period_beats=60,
    )
    score = substrate_score_fn(params, stage=2, seed=42)
    assert 0.05 <= score <= 1.0


def test_scorer_deterministic_with_seed() -> None:
    params = LearnerParams(
        coupling_reduction_factor=0.7,
        mneme_forgetting_boost=1.8,
        recovery_compose_period_beats=80,
    )
    s1 = substrate_score_fn(params, stage=2, seed=42)
    s2 = substrate_score_fn(params, stage=2, seed=42)
    assert s1 == s2


def test_scorer_distinguishes_different_params() -> None:
    """Different parameter points produce different scores (the scorer
    isn't a constant function — gives the learner real gradient signal)."""
    p1 = LearnerParams(
        coupling_reduction_factor=0.6,
        mneme_forgetting_boost=1.2,
        recovery_compose_period_beats=40,
    )
    p2 = LearnerParams(
        coupling_reduction_factor=0.95,
        mneme_forgetting_boost=2.5,
        recovery_compose_period_beats=100,
    )
    s1 = substrate_score_fn(p1, stage=2, seed=42)
    s2 = substrate_score_fn(p2, stage=2, seed=42)
    assert s1 != s2


def test_scorer_stage_3_with_drive_noise_overlay() -> None:
    """Stage 3 applies the drive_noise × 0.5 overlay; scores should differ
    from stage 2 with the same params."""
    params = LearnerParams(
        coupling_reduction_factor=0.8,
        mneme_forgetting_boost=1.5,
        recovery_compose_period_beats=60,
    )
    s2 = substrate_score_fn(params, stage=2, seed=42)
    s3 = substrate_score_fn(params, stage=3, seed=42)
    # The Stage-3 overlay changes the substrate's response → different score
    assert s2 != s3


def test_scorer_with_pretrain_synthetic_integration() -> None:
    """RecoveryLearner.pretrain_synthetic accepts the substrate scorer."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    summary = learner.pretrain_synthetic(
        history,
        target_events_per_stage=15,
        score_fn=substrate_score_fn,
    )
    assert summary["events_added"] == 30
    # All scores should be in valid range
    for event in history.all_events():
        assert 0.05 <= event.quality.composite_score <= 1.0
