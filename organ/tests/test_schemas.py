import numpy as np

from organ.schemas import (
    ORGAN_DIMS,
    ORGAN_ORDER,
    SUMMARY_NAMES,
    TOTAL_DIMS,
    TOTAL_SUMMARIES,
    AnimaState,
    EidolonState,
    MnemeState,
    NousState,
    PneumaState,
    validate_ranges,
)


def test_totals():
    assert sum(ORGAN_DIMS.values()) == TOTAL_DIMS == 27
    assert TOTAL_SUMMARIES == 19
    assert ORGAN_ORDER == ("anima", "eidolon", "mneme", "nous", "pneuma")


def test_to_array_shapes():
    states = [
        ("anima", AnimaState()),
        ("eidolon", EidolonState()),
        ("mneme", MnemeState()),
        ("nous", NousState()),
        ("pneuma", PneumaState()),
    ]
    for name, s in states:
        a = s.to_array()
        assert a.shape == (ORGAN_DIMS[name],)
        assert a.dtype == np.float32


def test_validate_ranges_default_states_ok():
    for name, cls in [
        ("anima", AnimaState()),
        ("eidolon", EidolonState()),
        ("mneme", MnemeState()),
        ("nous", NousState()),
        ("pneuma", PneumaState()),
    ]:
        validate_ranges(name, cls)


def test_validate_ranges_rejects_out_of_range():
    import pytest
    bad = AnimaState(valence=2.0)  # > 1.0
    with pytest.raises(ValueError):
        validate_ranges("anima", bad)


def test_summary_names_count():
    counts = {k: len(v) for k, v in SUMMARY_NAMES.items()}
    assert counts == {"anima": 4, "eidolon": 4, "mneme": 3, "nous": 4, "pneuma": 4}
