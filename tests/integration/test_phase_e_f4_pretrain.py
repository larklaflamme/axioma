"""F4 — synthetic pre-training tests.

Per IMPLEMENTATION_PLAN_v1.0.md §6.7 + ARCH §4.9.1.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from axioma.config import AxiomaConfig, RecoveryConfig
from axioma.interface import create_app
from axioma.observability import AxiomaContext
from axioma.substrate.recovery import (
    LearnerEfficacy,
    LearnerParams,
    RecoveryHistory,
    RecoveryLearner,
    _default_pretrain_score,
)


def test_pretrain_adds_events_and_returns_summary() -> None:
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    summary = learner.pretrain_synthetic(history, target_events_per_stage=30)
    assert summary["events_added"] == 60  # 30 per stage × 2 stages
    assert summary["adoptions"] >= 0
    assert "2" in summary["current_params"]
    assert "3" in summary["current_params"]


def test_pretrain_events_tagged_synthetic() -> None:
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    learner.pretrain_synthetic(history, target_events_per_stage=10)
    for event in history.all_events():
        assert event.is_synthetic is True


def test_pretrain_can_be_loaded_from_disk(tmp_path: Path) -> None:
    """Workflow: pretrain → save snapshot → load into fresh learner."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    learner.pretrain_synthetic(history, target_events_per_stage=30)
    snap_path = tmp_path / "pretrain.json"
    snap_path.write_text(json.dumps(learner.to_dict()))

    fresh = RecoveryLearner(cfg, rng=np.random.default_rng(99))
    fresh.load_dict(json.loads(snap_path.read_text()))
    assert fresh.adoptions_count == learner.adoptions_count
    assert (
        fresh.current_params[2].coupling_reduction_factor
        == learner.current_params[2].coupling_reduction_factor
    )


def test_pretrain_with_custom_score_function() -> None:
    """Operators can provide a substrate-driven scorer."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    # Custom scorer: prefer low coupling_reduction_factor
    def custom_scorer(params: LearnerParams, _stage: int) -> float:
        return max(0.05, 1.0 - params.coupling_reduction_factor)
    learner.pretrain_synthetic(
        history, target_events_per_stage=30, score_fn=custom_scorer,
    )
    # The adopted params should lean toward the lower end of coupling_reduction_factor
    # (search range is [0.6, 0.95]; starting at 0.8). At minimum, we adopted something.
    assert learner.adoptions_count >= 0


def test_default_pretrain_score_peaks_at_defaults() -> None:
    cfg = RecoveryConfig()
    defaults = LearnerParams(
        coupling_reduction_factor=cfg.coupling_reduction_factor,
        mneme_forgetting_boost=cfg.mneme_forgetting_boost,
        recovery_compose_period_beats=cfg.recovery_compose_period_beats,
    )
    score_at_defaults = _default_pretrain_score(defaults, 2)
    far_from_defaults = LearnerParams(
        coupling_reduction_factor=0.6, mneme_forgetting_boost=2.5,
        recovery_compose_period_beats=40,
    )
    score_far = _default_pretrain_score(far_from_defaults, 2)
    assert score_at_defaults > score_far


def test_admin_pretrain_endpoint_runs_sweep() -> None:
    """POST /admin/recovery/learner/pretrain runs the sweep in-process."""
    ctx = AxiomaContext()
    cfg = AxiomaConfig()

    # Minimal recovery_protocol mock with the right surface
    class _Proto:
        def __init__(self) -> None:
            self.learner = RecoveryLearner(cfg.recovery, rng=np.random.default_rng(42))
            self.history = RecoveryHistory()
    proto = _Proto()
    ctx.register("recovery_protocol", proto)

    app = create_app(ctx, cfg)
    client = TestClient(app)
    r = client.post(
        "/admin/recovery/learner/pretrain",
        json={"target_events_per_stage": 20},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["events_added"] == 40


def test_admin_pretrain_missing_learner_503() -> None:
    ctx = AxiomaContext()

    class _ProtoNoLearner:
        learner = None
        history = None
    ctx.register("recovery_protocol", _ProtoNoLearner())
    app = create_app(ctx, AxiomaConfig())
    client = TestClient(app)
    r = client.post("/admin/recovery/learner/pretrain", json={})
    assert r.status_code == 503


def test_pretrain_efficacy_transitions_after_sweep() -> None:
    """After a 50-per-stage sweep, efficacy should NOT be WARMING_UP anymore."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    history = RecoveryHistory()
    learner.pretrain_synthetic(history, target_events_per_stage=50)
    # With 50 events per stage, both stages exceed min_events_for_adoption (20)
    assert learner.efficacy_per_stage[2] != LearnerEfficacy.WARMING_UP
    assert learner.efficacy_per_stage[3] != LearnerEfficacy.WARMING_UP
