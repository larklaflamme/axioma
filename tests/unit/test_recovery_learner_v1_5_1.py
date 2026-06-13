"""v1.5.1 (Checkpoint BB) — RecoveryLearner correctness patches.

Three targeted fixes:

1. `_is_default` + `_matches_params` now consider `recovery_compose_period_beats`
   (previously ignored, causing events with non-default periods to be wrongly
   classified as default/matching).

2. `baseline_score` is now per-stage (`baseline_score_per_stage`). The single
   global scalar was overwritten by whichever stage's loop ran last, so the
   per-stage improvement comparison used the wrong baseline.

3. AxiomaApp + phase_e_harness now seed the learner's exploration RNG from
   the substrate seed, making adoption decisions reproducible across runs.
"""
from __future__ import annotations

import numpy as np
import pytest

from axioma.config import RecoveryConfig
from axioma.substrate.recovery import (
    LearnerParams,
    RecoveryLearner,
)


def _stage2_default_actions(cfg: RecoveryConfig) -> dict[str, float]:
    return {
        "coupling_reduction_factor": cfg.coupling_reduction_factor,
        "mneme_forgetting_boost": cfg.mneme_forgetting_boost,
        "recovery_compose_period_beats": cfg.recovery_compose_period_beats,
        "stage_overlay_3": False,
        "stage_overlay_4": False,
    }


# ── Fix #1: _is_default + _matches_params include compose_period ─────────


def test_v1_5_1_is_default_now_considers_compose_period() -> None:
    """An event with default coupling+forgetting but a non-default compose_period
    is NO LONGER classified as default."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    actions = _stage2_default_actions(cfg)
    assert learner._is_default(actions) is True  # all 3 default
    actions["recovery_compose_period_beats"] = cfg.recovery_compose_period_beats + 20
    assert learner._is_default(actions) is False  # period diverges → not default


def test_v1_5_1_matches_params_now_considers_compose_period() -> None:
    """An event with matching coupling+forgetting but different compose_period
    is NO LONGER reported as matching."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    current = LearnerParams(
        coupling_reduction_factor=0.75,
        mneme_forgetting_boost=1.8,
        recovery_compose_period_beats=70,
    )
    actions_match = {
        "coupling_reduction_factor": 0.75,
        "mneme_forgetting_boost": 1.8,
        "recovery_compose_period_beats": 70,
    }
    assert learner._matches_params(actions_match, current) is True
    actions_diff = {**actions_match, "recovery_compose_period_beats": 90}
    assert learner._matches_params(actions_diff, current) is False


# ── Fix #2: per-stage baseline_score ─────────────────────────────────────


def test_v1_5_1_baseline_score_per_stage_attribute_exists() -> None:
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    assert hasattr(learner, "baseline_score_per_stage")
    assert learner.baseline_score_per_stage == {2: 0.0, 3: 0.0}
    assert not hasattr(learner, "baseline_score"), (
        "v1.5.1 removed the global baseline_score scalar; only per-stage exists now"
    )


def test_v1_5_1_baseline_score_per_stage_independent() -> None:
    """Setting stage 2's baseline does not affect stage 3's, and vice versa."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    learner.baseline_score_per_stage[2] = 0.4
    learner.baseline_score_per_stage[3] = 0.7
    assert learner.baseline_score_per_stage[2] == 0.4
    assert learner.baseline_score_per_stage[3] == 0.7


def test_v1_5_1_load_dict_accepts_legacy_baseline_score() -> None:
    """Snapshots saved under v1.5.0 used `baseline_score` (scalar). v1.5.1
    load_dict must accept legacy snapshots without crashing."""
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    legacy_snap = {
        "current_params": {},
        "baseline_score": 0.55,  # legacy single scalar
        "adoptions_count": 3,
        "reversions_count": 0,
        "efficacy_per_stage": {},
        "clean_baseline_remaining": {},
    }
    learner.load_dict(legacy_snap)
    # Legacy scalar should be spread to both stages
    assert learner.baseline_score_per_stage == {2: 0.55, 3: 0.55}
    assert learner.adoptions_count == 3


def test_v1_5_1_load_dict_round_trips_per_stage_baseline() -> None:
    cfg = RecoveryConfig()
    learner = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    learner.baseline_score_per_stage = {2: 0.3, 3: 0.6}
    snap = learner.to_dict()
    assert "baseline_score_per_stage" in snap
    learner2 = RecoveryLearner(cfg, rng=np.random.default_rng(42))
    learner2.load_dict(snap)
    assert learner2.baseline_score_per_stage == {2: 0.3, 3: 0.6}


# ── Fix #3: seeded learner RNG produces reproducible exploration ─────────


def test_v1_5_1_seeded_rng_makes_exploration_reproducible() -> None:
    """Two learners with the same RNG seed explore the same sequence of params."""
    cfg = RecoveryConfig()
    rng1 = np.random.default_rng(123)
    rng2 = np.random.default_rng(123)
    learner1 = RecoveryLearner(cfg, rng=rng1)
    learner2 = RecoveryLearner(cfg, rng=rng2)
    base = LearnerParams(
        coupling_reduction_factor=0.8,
        mneme_forgetting_boost=1.5,
        recovery_compose_period_beats=60,
    )
    explored1 = [learner1._explore_around(base) for _ in range(10)]
    explored2 = [learner2._explore_around(base) for _ in range(10)]
    for e1, e2 in zip(explored1, explored2, strict=True):
        assert e1.coupling_reduction_factor == e2.coupling_reduction_factor
        assert e1.mneme_forgetting_boost == e2.mneme_forgetting_boost
        assert e1.recovery_compose_period_beats == e2.recovery_compose_period_beats


async def _build_and_explore(seed: int) -> list[tuple[float, float, int]]:
    from axioma.config import AxiomaConfig
    from axioma.runtime.app import AxiomaApp

    cfg = AxiomaConfig()
    app = AxiomaApp(
        cfg, seed=seed,
        with_agora=False, with_registry=False, with_http_api=False,
    )
    await app.setup()
    try:
        recovery = app.ctx.get("recovery_protocol")  # type: ignore[union-attr]
        base = LearnerParams(
            coupling_reduction_factor=0.8,
            mneme_forgetting_boost=1.5,
            recovery_compose_period_beats=60,
        )
        return [
            (e.coupling_reduction_factor, e.mneme_forgetting_boost,
             e.recovery_compose_period_beats)
            for e in [recovery.learner._explore_around(base) for _ in range(5)]
        ]
    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_v1_5_1_axioma_app_seeds_recovery_rng() -> None:
    """AxiomaApp threads its seed into RecoveryProtocol/RecoveryLearner so the
    learner's exploration is deterministic for the same substrate seed."""
    # Same seed → same exploration sequence
    seq_a = await _build_and_explore(42)
    seq_b = await _build_and_explore(42)
    assert seq_a == seq_b

    # Different seed → different exploration sequence
    seq_c = await _build_and_explore(7)
    assert seq_a != seq_c
