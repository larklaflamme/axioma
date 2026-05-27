"""InternalState — substrate-private snapshot container."""
from __future__ import annotations

import pytest

from axioma.schemas import (
    ORGAN_ORDER,
    AnimaState,
    EidolonState,
    InternalState,
    MnemeState,
    NousState,
    PerturbationContext,
    PneumaState,
)


def test_initial_factory() -> None:
    s = InternalState.initial()
    assert s.beat_no == 0
    assert s.timestamp == 0.0
    assert isinstance(s.anima, AnimaState)
    assert isinstance(s.eidolon, EidolonState)
    assert isinstance(s.mneme, MnemeState)
    assert isinstance(s.nous, NousState)
    assert isinstance(s.pneuma, PneumaState)


def test_get_organ() -> None:
    s = InternalState.initial(beat_no=5, timestamp=0.5)
    assert s.get_organ("anima") is s.anima
    assert s.get_organ("pneuma") is s.pneuma
    with pytest.raises(KeyError):
        s.get_organ("nope")


def test_organ_dict_in_canonical_order() -> None:
    s = InternalState.initial()
    d = s.organ_dict()
    assert tuple(d.keys()) == ORGAN_ORDER


def test_get_concatenated_dimensions() -> None:
    s = InternalState.initial(beat_no=1, timestamp=0.1)
    arr = s.get_concatenated()
    assert arr.shape == (28,)  # 4+6+5+6+7
    assert arr.dtype.name == "float32"


def test_perturbation_context_defaults() -> None:
    ctx = PerturbationContext(
        event_id="evt1",
        kind="contradiction",
        target="eidolon",
        magnitude=0.3,
        started_at_beat=100,
        duration_beats=1,
    )
    assert ctx.tag is None
    assert ctx.extra == {}
