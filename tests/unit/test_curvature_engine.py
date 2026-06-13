"""Unit tests for CurvatureMeasurementEngine and its pure-math helpers.

Tests cover:
  1. Effective rank — discrete + fractional (participation ratio)
  2. Sectional curvature — sign convention (always ≤ 0 for SPD(n))
  3. Scalar curvature R(n) = -n(n-1)(n+2)/8 — spot-checked n=2..6
  4. n_eff_inferred from scalar curvature inversion
  5. CurvatureMeasurementEngine reads from a real InternalStateRingBuffer
  6. Engine produces CurvatureResult after warm-up
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from numpy.linalg import eigh

from axioma.measurement.curvature_engine import (
    CurvatureMeasurementEngine,
    CurvatureResult,
    _identity_area_sq,
    _identity_metric,
    _inner_product,
    _map_to_identity,
    _regularise,
    effective_rank,
    effective_rank_fractional,
    geodesic_curvature,
    infer_dimension_from_scalar_R,
    scalar_curvature_spd,
    sectional_curvature,
)
from axioma.measurement.ring_buffer import InternalStateRingBuffer
from axioma.observability import AxiomaContext
from axioma.schemas import (
    ORGAN_ORDER,
    ORGAN_STATE_CLS,
    ORGAN_STATE_DIMS,
    InternalState,
)


# ════════════════════════════════════════════════════════════════════════════
#  HELPER
# ════════════════════════════════════════════════════════════════════════════

def _push_random_states(buf: InternalStateRingBuffer, n: int,
                         seed: int = 0) -> None:
    """Push n random InternalStates into the buffer using concrete subclasses."""
    rng = np.random.default_rng(seed)
    for i in range(n):
        organs = {}
        for name in ORGAN_ORDER:
            cls = ORGAN_STATE_CLS[name]
            fields = cls.ORDER
            kwargs: dict[str, Any] = {}
            for fname in fields:
                if name == "mneme" and fname == "wm_load":
                    kwargs[fname] = int(rng.integers(0, 7))
                elif name == "nous" and fname in ("inference_depth", "active_hypotheses"):
                    kwargs[fname] = int(rng.integers(0, 10))
                elif name == "pneuma" and fname == "buffer_depth":
                    kwargs[fname] = int(rng.integers(0, 10))
                else:
                    kwargs[fname] = float(rng.uniform(-0.5, 0.5))
            organs[name] = cls(**kwargs)
        buf.push(InternalState(
            beat_no=i,
            timestamp=float(i),
            anima=organs['anima'],
            eidolon=organs['eidolon'],
            mneme=organs['mneme'],
            nous=organs['nous'],
            pneuma=organs['pneuma'],
        ))


# ════════════════════════════════════════════════════════════════════════════
#  1. EFFECTIVE RANK
# ════════════════════════════════════════════════════════════════════════════

class TestEffectiveRank:
    def test_full_rank_identity(self) -> None:
        for d in (3, 5, 10):
            assert effective_rank(np.eye(d)) == d

    def test_degenerate_one_signal_dim(self) -> None:
        Sigma = np.zeros((10, 10))
        Sigma[0, 0] = 1.0
        assert effective_rank(Sigma) == 1

    def test_degenerate_all_zero(self) -> None:
        assert effective_rank(np.zeros((5, 5))) == 0

    def test_fractional_full_rank(self) -> None:
        d = 10
        fr = effective_rank_fractional(np.eye(d))
        assert abs(fr - d) < 1e-6

    def test_fractional_rank_1(self) -> None:
        Sigma = np.zeros((10, 10))
        Sigma[0, 0] = 1.0
        fr = effective_rank_fractional(Sigma)
        assert abs(fr - 1.0) < 1e-6

    def test_fractional_between(self) -> None:
        evals = np.array([5.0, 3.0, 0.2, 0.1, 0.02])
        Sigma = np.diag(evals)
        fr = effective_rank_fractional(Sigma)
        assert 1.0 < fr < 5.0
        expected = (8.32 ** 2) / 34.0504
        assert abs(fr - expected) < 1e-6

    def test_empty_spectrum_returns_zero(self) -> None:
        assert effective_rank_fractional(np.eye(3) * 1e-12) == 0.0


# ════════════════════════════════════════════════════════════════════════════
#  2. RIEMANNIAN METRIC HELPERS
# ════════════════════════════════════════════════════════════════════════════

class TestMetricHelpers:
    def test_regularise_makes_positive_definite(self) -> None:
        M = np.array([[1.0, 1.0], [1.0, 1.0]])
        R = _regularise(M)
        evals = eigh(R)[0]
        assert all(ev > 0 for ev in evals)

    def test_inner_product_positive_definite(self) -> None:
        P = np.eye(3)
        X = np.array([[1, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=float)
        assert _inner_product(P, X, X) > 0

    def test_identity_metric_symmetric(self) -> None:
        A = np.array([[1, 2], [2, 0]], dtype=float)
        B = np.array([[0, -1], [-1, 3]], dtype=float)
        assert abs(_identity_metric(A, B) - _identity_metric(B, A)) < 1e-15

    def test_identity_area_sq_nonnegative(self) -> None:
        A = np.array([[1, 0], [0, 0]], dtype=float)
        B = np.array([[0, 0], [0, 1]], dtype=float)
        assert _identity_area_sq(A, B) > 0
        assert _identity_area_sq(A, 3 * A) < 1e-30

    def test_map_to_identity_preserves_product(self) -> None:
        P = np.array([[2, 0.5], [0.5, 3]], dtype=float)
        X = np.array([[1, 0.2], [0.2, -1]], dtype=float)
        Y = np.array([[0, 0.7], [0.7, 1]], dtype=float)
        lhs = _inner_product(P, X, Y)
        rhs = _identity_metric(_map_to_identity(P, X), _map_to_identity(P, Y))
        assert abs(lhs - rhs) < 1e-10


# ════════════════════════════════════════════════════════════════════════════
#  3. SECTIONAL CURVATURE
# ════════════════════════════════════════════════════════════════════════════

class TestSectionalCurvature:
    def test_spd_curvature_nonpositive_2d(self) -> None:
        rng = np.random.default_rng(42)
        for _ in range(10):
            A = rng.normal(size=(2, 2))
            P = _regularise(A.T @ A + np.eye(2))
            X = np.array([[1, 0], [0, 0]], dtype=float)
            Y = np.array([[0, 0], [0, 1]], dtype=float)
            K = sectional_curvature(P, X, Y)
            assert K <= 1e-10, f"K={K} should be ≤ 0"

    def test_spd_curvature_nonpositive_3d(self) -> None:
        rng = np.random.default_rng(99)
        P = _regularise(rng.normal(size=(3, 3)))
        P = P.T @ P
        K = sectional_curvature(P, np.diag([1, 0, 0]), np.diag([0, 1, 0]))
        assert K <= 1e-10

    def test_identically_zero_for_dependent_planes(self) -> None:
        P = np.eye(3)
        X = np.diag([1, 0, 0])
        assert abs(sectional_curvature(P, X, 3 * X)) < 1e-30


# ════════════════════════════════════════════════════════════════════════════
#  4. SCALAR CURVATURE
# ════════════════════════════════════════════════════════════════════════════

class TestScalarCurvature:
    @pytest.mark.parametrize("n, expected", [
        (2, -1.0),   (3, -3.75),  (4, -9.0),
        (5, -17.5),  (6, -30.0),  (7, -47.25),
    ])
    def test_scalar_curvature_values(self, n: int, expected: float) -> None:
        actual = -n * (n - 1) * (n + 2) / 8.0
        assert abs(scalar_curvature_spd(n) - actual) < 1e-12

    def test_scalar_curvature_negative_for_all_n(self) -> None:
        for n in range(2, 20):
            assert scalar_curvature_spd(n) < 0

    def test_n_eff_inferred_round_trip(self) -> None:
        for n in [2, 3, 4, 5, 6, 7, 8]:
            R = scalar_curvature_spd(n)
            inferred = infer_dimension_from_scalar_R(R)
            assert abs(inferred - n) < 0.5


# ════════════════════════════════════════════════════════════════════════════
#  5. GEODESIC CURVATURE
# ════════════════════════════════════════════════════════════════════════════

class TestGeodesicCurvature:
    def test_linear_path_is_geodesic(self) -> None:
        from scipy.linalg import expm
        M = np.array([[0.1, 0, 0], [0, -0.05, 0], [0, 0, 0.02]], dtype=float)
        P = np.eye(3)
        S1 = expm(0.0 * M) @ P @ expm(0.0 * M).T
        S2 = expm(0.5 * M) @ P @ expm(0.5 * M).T
        S3 = expm(1.0 * M) @ P @ expm(1.0 * M).T
        assert geodesic_curvature(S1, S2, S3) < 0.01

    def test_bent_path_has_positive_curvature(self) -> None:
        S1 = _regularise(np.eye(2))
        S2 = _regularise(np.array([[1.5, 0.3], [0.3, 0.7]]))
        S3 = _regularise(np.array([[2.0, 0.0], [0.0, 0.5]]))
        assert geodesic_curvature(S1, S2, S3) > 0


# ════════════════════════════════════════════════════════════════════════════
#  6. ENGINE — integration with ring buffer
# ════════════════════════════════════════════════════════════════════════════

class TestCurvatureEngine:
    def test_engine_returns_none_until_warm(self) -> None:
        ctx = AxiomaContext()
        buf = InternalStateRingBuffer(capacity=60)
        ctx.register("state_buffer", buf)
        engine = CurvatureMeasurementEngine(ctx, window_size=30)
        engine.compute()
        assert engine.current_value() is None

    def test_engine_returns_curvature_result_after_warmup(self) -> None:
        ctx = AxiomaContext()
        buf = InternalStateRingBuffer(capacity=60)
        _push_random_states(buf, 35, seed=42)
        ctx.register("state_buffer", buf)
        engine = CurvatureMeasurementEngine(ctx, window_size=30)
        engine.compute()
        result = engine.current_value()
        assert result is not None
        assert isinstance(result, CurvatureResult)
        assert result.valid
        assert result.n_eff > 0
        assert result.fractional_rank > 0
        assert result.scalar_R_at_n_eff < 0
        assert result.beat_no >= 0

    def test_engine_organ_pair_curvatures_after_multiple_ticks(self) -> None:
        ctx = AxiomaContext()
        buf = InternalStateRingBuffer(capacity=60)
        _push_random_states(buf, 35, seed=99)
        ctx.register("state_buffer", buf)
        engine = CurvatureMeasurementEngine(ctx, window_size=30)
        engine.compute()  # tick 1: no velocity
        _push_random_states(buf, 1, seed=100)
        engine.compute()  # tick 2: velocity V exists
        r2 = engine.current_value()
        assert r2 is not None
        assert isinstance(r2.organ_pair_curvatures, dict)
        _push_random_states(buf, 1, seed=101)
        engine.compute()  # tick 3: geodesic curvature possible
        r3 = engine.current_value()
        assert r3 is not None

    def test_engine_save_load_round_trip(self) -> None:
        ctx = AxiomaContext()
        buf = InternalStateRingBuffer(capacity=60)
        _push_random_states(buf, 35, seed=42)
        ctx.register("state_buffer", buf)
        engine = CurvatureMeasurementEngine(ctx, window_size=30)
        engine.compute()
        saved = engine.save_state()
        assert saved["current"] is not None
        assert saved["current"]["n_eff"] > 0
        engine2 = CurvatureMeasurementEngine(ctx, window_size=30)
        engine2.load_state(saved)
        r2 = engine2.current_value()
        assert r2 is not None
        assert r2.n_eff == saved["current"]["n_eff"]

    def test_engine_handles_empty_buffer_gracefully(self) -> None:
        ctx = AxiomaContext()
        buf = InternalStateRingBuffer(capacity=60)
        ctx.register("state_buffer", buf)
        engine = CurvatureMeasurementEngine(ctx, window_size=30)
        engine.compute()
        assert engine.current_value() is None
        _push_random_states(buf, 1, seed=0)
        engine.compute()
        assert engine.current_value() is None

    def test_engine_defaults_to_19dim_summary(self) -> None:
        ctx = AxiomaContext()
        buf = InternalStateRingBuffer(capacity=60)
        _push_random_states(buf, 35, seed=42)
        ctx.register("state_buffer", buf)
        engine = CurvatureMeasurementEngine(ctx, window_size=30)
        engine.compute()
        result = engine.current_value()
        assert result is not None
        assert result.total_dim == 19
        assert result.details["use_summary_dims"] is True

    def test_engine_can_use_full_28dim(self) -> None:
        ctx = AxiomaContext()
        buf = InternalStateRingBuffer(capacity=60)
        _push_random_states(buf, 35, seed=42)
        ctx.register("state_buffer", buf)
        engine = CurvatureMeasurementEngine(ctx, window_size=30,
                                             use_summary_dims=False)
        engine.compute()
        result = engine.current_value()
        assert result is not None
        assert result.total_dim == 28
        assert result.details["use_summary_dims"] is False
