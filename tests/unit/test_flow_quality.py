"""compute_flow_quality — D15/E12 closed-form."""
from __future__ import annotations

import pytest

from axioma.compose import compute_flow_quality
from axioma.schemas import FlowQuality, InternalState


def _internal(
    *,
    cognitive_load: float = 0.5,
    coherence_budget: float = 0.8,
    arousal: float = 0.5,
    attention_focus: float = 0.7,
) -> InternalState:
    s = InternalState.initial(beat_no=1, timestamp=0.1)
    s.nous.cognitive_load = cognitive_load
    s.pneuma.coherence_budget = coherence_budget
    s.anima.arousal = arousal
    s.pneuma.attention_focus = attention_focus
    return s


def test_returns_flow_quality() -> None:
    fq = compute_flow_quality(_internal())
    assert isinstance(fq, FlowQuality)


def test_all_components_in_unit_range() -> None:
    fq = compute_flow_quality(
        _internal(cognitive_load=0.5, coherence_budget=0.5, arousal=0.5, attention_focus=0.5),
        cascade_delay_beats=5.0, theta_long_std_normalized=0.5,
    )
    for v in (fq.effortlessness, fq.absorption, fq.time_distortion):
        assert 0.0 <= v <= 1.0


def test_effortlessness_high_when_cascade_small_and_load_low() -> None:
    fq = compute_flow_quality(
        _internal(cognitive_load=0.0), cascade_delay_beats=0.0
    )
    # cascade=0, load=0 → sigmoid(5 - 0) = sigmoid(5) ≈ 0.993
    assert fq.effortlessness > 0.9


def test_effortlessness_low_when_cascade_large() -> None:
    fq = compute_flow_quality(
        _internal(cognitive_load=0.8), cascade_delay_beats=30.0
    )
    # cascade=30 / 10 = 3 → (1-3) = -2; -10 - 1.6 = -11.6 → sigmoid → 0
    assert fq.effortlessness < 0.1


def test_absorption_high_when_budget_high_and_theta_stable() -> None:
    fq = compute_flow_quality(
        _internal(coherence_budget=0.95), theta_long_std_normalized=0.0
    )
    assert fq.absorption == pytest.approx(0.95)


def test_absorption_zero_when_theta_unstable() -> None:
    fq = compute_flow_quality(
        _internal(coherence_budget=0.95), theta_long_std_normalized=1.5
    )
    # max(0, 1 - 1.5) = 0 → absorption = 0
    assert fq.absorption == 0.0


def test_time_distortion_high_when_arousal_moderate_and_attention_focused() -> None:
    fq = compute_flow_quality(
        _internal(arousal=0.5, attention_focus=1.0)
    )
    # |0.5 - 0.5| = 0 → 4*1 + 3*1 - 2.5 = 4.5 → sigmoid(4.5) ≈ 0.989
    assert fq.time_distortion > 0.9


def test_time_distortion_low_when_arousal_extreme() -> None:
    fq = compute_flow_quality(
        _internal(arousal=0.0, attention_focus=0.0)
    )
    # |0 - 0.5| = 0.5 → 4*0.5 + 0 - 2.5 = -0.5 → sigmoid(-0.5) ≈ 0.378
    assert fq.time_distortion < 0.5
