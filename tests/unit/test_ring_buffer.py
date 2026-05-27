"""InternalStateRingBuffer — FIFO of per-beat states."""
from __future__ import annotations

import numpy as np
import pytest

from axioma.measurement import InternalStateRingBuffer
from axioma.schemas import ORGAN_ORDER, ORGAN_STATE_DIMS, InternalState


def _fake_internal(beat: int, value: float = 0.0) -> InternalState:
    s = InternalState.initial(beat_no=beat, timestamp=beat * 0.1)
    s.anima.valence = value
    return s


def test_construct() -> None:
    buf = InternalStateRingBuffer(capacity=10)
    assert buf.capacity == 10
    assert buf.size == 0
    assert len(buf) == 0
    assert buf.latest() is None


def test_capacity_validation() -> None:
    with pytest.raises(ValueError):
        InternalStateRingBuffer(capacity=0)


def test_push_grows_size() -> None:
    buf = InternalStateRingBuffer(capacity=5)
    for i in range(3):
        buf.push(_fake_internal(i))
    assert buf.size == 3
    assert len(buf) == 3
    assert not buf.is_full()


def test_push_caps_at_capacity() -> None:
    buf = InternalStateRingBuffer(capacity=3)
    for i in range(10):
        buf.push(_fake_internal(i))
    assert buf.size == 3
    assert buf.is_full()


def test_window_returns_chronological() -> None:
    buf = InternalStateRingBuffer(capacity=10)
    for i in range(5):
        buf.push(_fake_internal(i, value=float(i) / 10.0))
    w = buf.window(3)
    # Last 3 entries (beats 2, 3, 4)
    for organ in ORGAN_ORDER:
        assert w[organ].shape == (3, ORGAN_STATE_DIMS[organ])
    # ANIMA valence should be 0.2, 0.3, 0.4
    np.testing.assert_allclose(w["anima"][:, 0], [0.2, 0.3, 0.4], rtol=1e-5)


def test_window_handles_wrap() -> None:
    buf = InternalStateRingBuffer(capacity=3)
    # Push 5 → wraps; last 3 = beats 2,3,4
    for i in range(5):
        buf.push(_fake_internal(i, value=float(i)))
    w = buf.window(3)
    np.testing.assert_allclose(w["anima"][:, 0], [2.0, 3.0, 4.0])


def test_window_n_larger_than_size() -> None:
    buf = InternalStateRingBuffer(capacity=10)
    for i in range(3):
        buf.push(_fake_internal(i))
    w = buf.window(100)  # asks for more than we have
    for organ in ORGAN_ORDER:
        assert w[organ].shape[0] == 3


def test_window_zero_returns_empty() -> None:
    buf = InternalStateRingBuffer(capacity=10)
    w = buf.window(5)
    for organ in ORGAN_ORDER:
        assert w[organ].shape[0] == 0


def test_window_beats() -> None:
    buf = InternalStateRingBuffer(capacity=10)
    for i in (100, 101, 102, 103):
        buf.push(_fake_internal(i))
    beats = buf.window_beats(3)
    np.testing.assert_array_equal(beats, [101, 102, 103])


def test_latest() -> None:
    buf = InternalStateRingBuffer(capacity=10)
    buf.push(_fake_internal(1, value=0.42))
    latest = buf.latest()
    assert latest is not None
    assert latest["anima"][0] == pytest.approx(0.42)


def test_save_load_roundtrip() -> None:
    buf1 = InternalStateRingBuffer(capacity=10)
    for i in range(7):
        buf1.push(_fake_internal(i, value=float(i) / 10))
    snap = buf1.save_state()
    buf2 = InternalStateRingBuffer(capacity=10)
    buf2.load_state(snap)
    assert buf2.size == 7
    w1 = buf1.window(7)
    w2 = buf2.window(7)
    for organ in ORGAN_ORDER:
        np.testing.assert_array_equal(w1[organ], w2[organ])


def test_load_capacity_mismatch_is_cold_start() -> None:
    """Loading a snapshot with a different capacity should silently cold-start."""
    buf1 = InternalStateRingBuffer(capacity=20)
    for i in range(5):
        buf1.push(_fake_internal(i))
    snap = buf1.save_state()
    buf2 = InternalStateRingBuffer(capacity=10)  # different capacity
    buf2.load_state(snap)
    # Cold-start: size stays at 0
    assert buf2.size == 0
