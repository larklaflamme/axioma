"""Typed organ state schemas — ranges, serialization round-trip."""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from axioma.schemas import (
    ORGAN_ORDER,
    ORGAN_STATE_CLS,
    ORGAN_STATE_DIMS,
    TOTAL_STATE_DIMS,
    AnimaState,
    EidolonState,
    MnemeState,
    NousState,
    OrganState,
    PneumaState,
    organ_ranges,
    validate_state,
)


def test_total_state_dims_consistent() -> None:
    assert TOTAL_STATE_DIMS == 28  # v1.0: +1 for PNEUMA.coherence_budget
    assert sum(ORGAN_STATE_DIMS.values()) == TOTAL_STATE_DIMS


def test_organ_order_matches_state_cls_keys() -> None:
    assert ORGAN_ORDER == tuple(ORGAN_STATE_CLS.keys())


def test_anima_default_in_range() -> None:
    validate_state("anima", AnimaState())


def test_eidolon_default_in_range() -> None:
    validate_state("eidolon", EidolonState())


def test_mneme_default_in_range() -> None:
    validate_state("mneme", MnemeState())


def test_nous_default_in_range() -> None:
    validate_state("nous", NousState())


def test_pneuma_default_in_range() -> None:
    validate_state("pneuma", PneumaState())


def test_pneuma_has_coherence_budget_field() -> None:
    """v1.0: PneumaState has 7 dims, including the new coherence_budget."""
    s = PneumaState()
    assert hasattr(s, "coherence_budget")
    assert s.coherence_budget == 1.0  # default is idle/full budget
    assert len(s.ORDER) == 7
    assert s.ORDER[-1] == "coherence_budget"


def test_validate_state_rejects_out_of_range() -> None:
    bad = AnimaState(valence=2.0)  # > 1
    with pytest.raises(ValueError, match=r"valence=2\.0 outside"):
        validate_state("anima", bad)


def test_validate_state_accepts_at_rails() -> None:
    """Validation is inclusive of the rails."""
    at_low = AnimaState(valence=-1.0, arousal=0.0)
    at_high = AnimaState(valence=1.0, arousal=1.0, dominance=1.0, mood=1.0)
    validate_state("anima", at_low)
    validate_state("anima", at_high)


def test_to_array_canonical_order() -> None:
    s = AnimaState(valence=0.1, arousal=0.2, dominance=0.3, mood=0.4)
    arr = s.to_array()
    assert arr.shape == (4,)
    assert arr.dtype == np.float32
    np.testing.assert_allclose(arr, [0.1, 0.2, 0.3, 0.4], rtol=1e-6)


def test_to_array_integer_casts_to_float() -> None:
    s = MnemeState(wm_load=5, retrieval_rate=0.7)
    arr = s.to_array()
    assert arr[0] == 5.0  # int cast to float
    assert arr.dtype == np.float32


def test_from_array_roundtrip_anima() -> None:
    """Float32 round-trip preserves values within ~1e-6 (not bit-exact for
    arbitrary doubles like 0.1)."""
    orig = AnimaState(valence=0.1, arousal=0.2, dominance=0.3, mood=0.4)
    arr = orig.to_array()
    back = AnimaState.from_array(arr)
    for field_name in AnimaState.ORDER:
        assert abs(getattr(back, field_name) - getattr(orig, field_name)) < 1e-6


def test_from_array_preserves_int_type() -> None:
    orig = MnemeState(wm_load=3, retrieval_rate=0.5)
    arr = orig.to_array()
    back = MnemeState.from_array(arr)
    assert back.wm_load == 3
    assert isinstance(back.wm_load, int)


def test_from_array_wrong_shape_raises() -> None:
    with pytest.raises(ValueError, match="shape"):
        AnimaState.from_array(np.array([0.1, 0.2]))


def test_organ_ranges_returns_dict() -> None:
    r = organ_ranges("pneuma")
    assert "coherence_budget" in r
    assert r["coherence_budget"] == (0.0, 1.0)


# ── Property tests ──────────────────────────────────────────────────────────


@given(
    valence=st.floats(min_value=-1.0, max_value=1.0),
    arousal=st.floats(min_value=0.0, max_value=1.0),
    dominance=st.floats(min_value=0.0, max_value=1.0),
    mood=st.floats(min_value=-1.0, max_value=1.0),
)
def test_anima_in_range_always_validates(
    valence: float, arousal: float, dominance: float, mood: float
) -> None:
    """Property: any AnimaState built with in-range values passes validation."""
    state = AnimaState(
        valence=valence, arousal=arousal, dominance=dominance, mood=mood
    )
    validate_state("anima", state)


@given(
    valence=st.floats(min_value=-1.0, max_value=1.0),
    arousal=st.floats(min_value=0.0, max_value=1.0),
)
def test_anima_roundtrip_property(valence: float, arousal: float) -> None:
    orig = AnimaState(valence=valence, arousal=arousal, dominance=0.5, mood=0.0)
    arr = orig.to_array()
    back = AnimaState.from_array(arr)
    # float32 round-trip — small tolerance
    assert abs(back.valence - orig.valence) < 1e-5
    assert abs(back.arousal - orig.arousal) < 1e-5


def test_organ_state_is_abstract_marker_only() -> None:
    """OrganState is a base class; concrete subclasses define ORDER."""
    assert OrganState.ORDER == ()
    # All concrete subclasses have non-empty ORDER
    for cls in ORGAN_STATE_CLS.values():
        assert len(cls.ORDER) > 0
