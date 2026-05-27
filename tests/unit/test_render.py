"""Non-saturating render helpers — linear rescale + clip."""
from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from axioma.substrate.render import (
    to_int_nonneg,
    to_int_range,
    to_range,
    to_unit,
    to_unit_centered,
)


def test_to_unit_centered_at_origin() -> None:
    assert to_unit_centered(0.0) == 0.0


def test_to_unit_centered_at_scale_hits_rail() -> None:
    """latent == scale should hit +1; -scale should hit -1."""
    assert to_unit_centered(10.0, scale=10.0) == 1.0
    assert to_unit_centered(-10.0, scale=10.0) == -1.0


def test_to_unit_centered_clips_beyond_scale() -> None:
    assert to_unit_centered(100.0, scale=10.0) == 1.0
    assert to_unit_centered(-100.0, scale=10.0) == -1.0


def test_to_unit_centered_linear_inside_scale() -> None:
    """In [-scale, scale], should be linear."""
    for v in (-5.0, -1.0, 0.0, 3.0, 7.5):
        assert to_unit_centered(v, scale=10.0) == pytest.approx(v / 10.0)


def test_to_unit_at_origin_is_half() -> None:
    assert to_unit(0.0) == 0.5


def test_to_unit_linear_in_range() -> None:
    assert to_unit(5.0, scale=10.0) == pytest.approx(0.75)
    assert to_unit(-5.0, scale=10.0) == pytest.approx(0.25)


def test_to_range() -> None:
    assert to_range(0.0, lo=0.0, hi=7.0, scale=10.0) == pytest.approx(3.5)
    assert to_range(10.0, lo=0.0, hi=7.0, scale=10.0) == pytest.approx(7.0)
    assert to_range(-10.0, lo=0.0, hi=7.0, scale=10.0) == pytest.approx(0.0)


def test_to_int_range() -> None:
    assert to_int_range(0.0, lo=0, hi=7) == 4  # 0.5 of [0,7] = 3.5 → 4
    assert to_int_range(10.0, lo=0, hi=7) == 7
    assert to_int_range(-10.0, lo=0, hi=7) == 0


def test_to_int_nonneg_zero_for_negative() -> None:
    assert to_int_nonneg(-5.0) == 0


def test_to_int_nonneg_positive() -> None:
    assert to_int_nonneg(2.0, scale_per_unit=5.0) == 10


# ── Property tests ──────────────────────────────────────────────────────────


@given(v=st.floats(allow_nan=False, allow_infinity=False), scale=st.floats(min_value=0.5, max_value=100.0))
def test_to_unit_centered_always_in_minus1_1(v: float, scale: float) -> None:
    """Property: output always in [-1, 1] regardless of input."""
    out = to_unit_centered(v, scale=scale)
    assert -1.0 <= out <= 1.0


@given(v=st.floats(allow_nan=False, allow_infinity=False), scale=st.floats(min_value=0.5, max_value=100.0))
def test_to_unit_always_in_0_1(v: float, scale: float) -> None:
    out = to_unit(v, scale=scale)
    assert 0.0 <= out <= 1.0


@given(
    v=st.floats(min_value=-1e6, max_value=1e6),
    lo=st.integers(min_value=-100, max_value=10),
    hi_extra=st.integers(min_value=1, max_value=100),
)
def test_to_int_range_always_in_bounds(v: float, lo: int, hi_extra: int) -> None:
    hi = lo + hi_extra
    out = to_int_range(v, lo=lo, hi=hi)
    assert lo <= out <= hi


def test_render_no_nan_on_finite_input() -> None:
    """Critical: render functions must never produce NaN on finite input
    (this was the bug we hit during initial substrate stability tests)."""
    for v in (-1e10, -100, -3, 0, 3, 100, 1e10):
        assert math.isfinite(to_unit_centered(v))
        assert math.isfinite(to_unit(v))
        assert math.isfinite(to_range(v, lo=0, hi=7))
        assert isinstance(to_int_range(v, lo=0, hi=20), int)
