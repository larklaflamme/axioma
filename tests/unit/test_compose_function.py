"""ComposeFunction — integration-weighted compression."""
from __future__ import annotations

import numpy as np

from axioma.compose import ComposeFunction
from axioma.schemas import ORGAN_ORDER, ComposeCadence, ExternalState, InternalState, Zone


def _internal_with_eidolon_coh(eidolon_coh: float) -> InternalState:
    s = InternalState.initial(beat_no=10, timestamp=1.0)
    s.eidolon.self_coherence = eidolon_coh
    s.anima.valence = 0.5
    s.pneuma.coherence_budget = 0.8
    return s


def test_construct_defaults() -> None:
    c = ComposeFunction()
    assert c.name == "compose_function"
    assert c.composes_total == 0
    assert c.latest_external is None


def test_compose_returns_external_state() -> None:
    c = ComposeFunction(rng_seed=42)
    internal = _internal_with_eidolon_coh(0.5)
    ext = c.compose(internal, theta_short=1.0)
    assert isinstance(ext, ExternalState)
    assert ext.beat_no == 10
    assert ext.theta_short == 1.0
    assert ext.cadence == ComposeCadence.BASELINE
    assert ext.zone == Zone.IDLE  # caller overrides


def test_compose_extracts_eidolon_coh_live_p13() -> None:
    """P13: eidolon_coh extracted live from internal.eidolon.self_coherence
    when not explicitly passed."""
    c = ComposeFunction(rng_seed=42, noise_factor=0.0)
    internal = _internal_with_eidolon_coh(0.7)
    ext_a = c.compose(internal, theta_short=0.5)
    # explicit eidolon_coh = same value should give the same fidelity
    c2 = ComposeFunction(rng_seed=42, noise_factor=0.0)
    ext_b = c2.compose(internal, theta_short=0.5, eidolon_coh=0.7)
    # Same θ, same eidolon_coh, same seed → fidelity factors match
    assert ext_a.fidelity_factors == ext_b.fidelity_factors


def test_fidelity_factor_formula() -> None:
    """f_i = clip(θ_short × eidolon_coh × weight, 0, 1)."""
    c = ComposeFunction(rng_seed=42, weights={"anima": 1.0, "eidolon": 0.5,
                                              "mneme": 1.0, "nous": 1.0,
                                              "pneuma": 1.0})
    internal = _internal_with_eidolon_coh(0.6)
    ext = c.compose(internal, theta_short=0.8)
    # anima: 0.8 × 0.6 × 1.0 = 0.48
    assert abs(ext.fidelity_factors["anima"] - 0.48) < 1e-6
    # eidolon: 0.8 × 0.6 × 0.5 = 0.24
    assert abs(ext.fidelity_factors["eidolon"] - 0.24) < 1e-6


def test_fidelity_factor_clipped_at_one() -> None:
    c = ComposeFunction(rng_seed=42)
    internal = _internal_with_eidolon_coh(1.0)
    ext = c.compose(internal, theta_short=2.0)  # 2.0 × 1.0 × 1.0 = 2.0 → clip to 1.0
    for v in ext.fidelity_factors.values():
        assert v == 1.0


def test_fidelity_factor_clipped_at_zero() -> None:
    c = ComposeFunction(rng_seed=42)
    internal = _internal_with_eidolon_coh(0.5)
    ext = c.compose(internal, theta_short=-1.0)  # negative input → clip to 0
    for v in ext.fidelity_factors.values():
        assert v == 0.0


def test_high_fidelity_external_close_to_internal() -> None:
    """At f=1.0, external_arr ≈ internal_arr (high fidelity)."""
    c = ComposeFunction(rng_seed=42, noise_factor=0.0)
    internal = _internal_with_eidolon_coh(1.0)
    ext = c.compose(internal, theta_short=2.0)  # f_i = 1.0
    # External should equal internal (modulo noise=0)
    for organ in ORGAN_ORDER:
        np.testing.assert_allclose(
            ext.get_organ_array(organ),
            internal.get_organ(organ).to_array(),
        )


def test_zero_fidelity_external_is_rolling_mean() -> None:
    """At f=0.0, external_arr = rolling_mean + noise."""
    c = ComposeFunction(rng_seed=42, noise_factor=0.0)
    internal = _internal_with_eidolon_coh(0.5)
    # First compose populates the rolling mean
    c.compose(internal, theta_short=0.0)  # f=0
    # Second compose: f=0 again; external should be the rolling mean
    ext = c.compose(internal, theta_short=0.0)
    for organ in ORGAN_ORDER:
        np.testing.assert_allclose(
            ext.get_organ_array(organ),
            c.rolling_mean(organ),
        )


def test_compose_memoizes_latest_external() -> None:
    c = ComposeFunction(rng_seed=42)
    internal = _internal_with_eidolon_coh(0.5)
    ext = c.compose(internal, theta_short=1.0)
    assert c.latest_external is ext
    assert c.latest_internal is internal


def test_compose_advances_count() -> None:
    c = ComposeFunction(rng_seed=42)
    internal = _internal_with_eidolon_coh(0.5)
    for _ in range(5):
        c.compose(internal, theta_short=1.0)
    assert c.composes_total == 5


def test_coherence_budget_propagates_to_external() -> None:
    c = ComposeFunction(rng_seed=42)
    internal = _internal_with_eidolon_coh(0.5)
    internal.pneuma.coherence_budget = 0.42
    ext = c.compose(internal, theta_short=1.0)
    assert ext.coherence_budget == 0.42


def test_save_load_roundtrip() -> None:
    c = ComposeFunction(rng_seed=42)
    internal = _internal_with_eidolon_coh(0.5)
    for _ in range(5):
        c.compose(internal, theta_short=1.0)
    snap = c.save_state()
    c2 = ComposeFunction(rng_seed=99)  # different seed
    c2.load_state(snap)
    assert c2.composes_total == c.composes_total
    for organ in ORGAN_ORDER:
        np.testing.assert_allclose(c2.rolling_mean(organ), c.rolling_mean(organ))
