"""PlasticityBuffer — per-organ slow buffer + (mean_drift, var_ratio) summary."""
from __future__ import annotations

import numpy as np
import pytest

from axioma.substrate.plasticity import PlasticityBuffer, PlasticitySummary


def test_construct() -> None:
    b = PlasticityBuffer(organ_name="anima", latent_dim=8)
    assert b.name == "anima_plasticity"
    assert b.organ_name == "anima"
    assert b.latent_dim == 8
    assert b.update_period == 100
    assert b.alpha_p == 0.05
    assert b.buffer.shape == (8,)
    assert np.allclose(b.buffer, 0.0)
    assert b.updates == 0


def test_alpha_p_validation() -> None:
    with pytest.raises(ValueError):
        PlasticityBuffer(organ_name="x", latent_dim=4, alpha_p=0.0)
    with pytest.raises(ValueError):
        PlasticityBuffer(organ_name="x", latent_dim=4, alpha_p=1.5)


def test_record_beat_validates_shape() -> None:
    b = PlasticityBuffer(organ_name="anima", latent_dim=8)
    with pytest.raises(ValueError):
        b.record_beat(np.zeros(5, dtype=np.float32))


def test_maybe_update_no_op_below_period() -> None:
    b = PlasticityBuffer(organ_name="anima", latent_dim=4, update_period=10)
    for i in range(9):
        b.record_beat(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
        assert b.maybe_update(beat_no=i + 1) is None
    # Beat 10: triggers
    b.record_beat(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
    summary = b.maybe_update(beat_no=10)
    assert summary is not None


def test_maybe_update_at_beat_zero_is_noop() -> None:
    b = PlasticityBuffer(organ_name="anima", latent_dim=4, update_period=10)
    b.record_beat(np.zeros(4, dtype=np.float32))
    assert b.maybe_update(beat_no=0) is None


def test_summary_returned_at_update() -> None:
    b = PlasticityBuffer(organ_name="anima", latent_dim=4, update_period=10)
    rng = np.random.default_rng(0)
    for _ in range(10):
        b.record_beat(rng.standard_normal(4).astype(np.float32))
    summary = b.maybe_update(beat_no=10)
    assert isinstance(summary, PlasticitySummary)
    assert summary.mean_drift.shape == (4,)
    assert summary.var_ratio.shape == (4,)


def test_first_update_initializes_rolling_stats() -> None:
    """The first update sets rolling_mean / rolling_var to the current window's stats;
    mean_drift is exactly zero (window vs itself)."""
    b = PlasticityBuffer(organ_name="x", latent_dim=4, update_period=10)
    rng = np.random.default_rng(0)
    for _ in range(10):
        b.record_beat(rng.standard_normal(4).astype(np.float32))
    summary = b.maybe_update(beat_no=10)
    assert summary is not None
    # On first update, mean_drift = window.mean - rolling_mean = 0
    assert np.allclose(summary.mean_drift, 0.0)
    # var_ratio ≈ 1 (current var ≈ rolling var which was just initialized to it)
    assert np.allclose(summary.var_ratio, 1.0)


def test_subsequent_update_drift_nonzero_when_input_changes() -> None:
    """When the input distribution shifts, mean_drift picks it up."""
    b = PlasticityBuffer(organ_name="x", latent_dim=2, update_period=10, alpha_p=0.5)
    # Window 1: low-magnitude latents
    for _ in range(10):
        b.record_beat(np.array([0.1, 0.0], dtype=np.float32))
    _ = b.maybe_update(beat_no=10)
    # Window 2: dim-0 latents shifted to +2.0
    for _ in range(10):
        b.record_beat(np.array([2.0, 0.0], dtype=np.float32))
    s2 = b.maybe_update(beat_no=20)
    assert s2 is not None
    # Dim 0 should show positive drift (current_mean=2.0, rolling_mean previously ~0.1+0.05*1.9=0.195)
    assert s2.mean_drift[0] > 0.5
    # Dim 1 stayed at zero → near zero drift
    assert abs(s2.mean_drift[1]) < 0.1


def test_buffer_advances_with_updates() -> None:
    """Persistent buffer accumulates the mean_drift signal across updates."""
    b = PlasticityBuffer(organ_name="x", latent_dim=2, update_period=10, alpha_p=0.5)
    # First window: zero
    for _ in range(10):
        b.record_beat(np.zeros(2, dtype=np.float32))
    b.maybe_update(beat_no=10)
    assert b.updates == 1
    # Second window: positive
    for _ in range(10):
        b.record_beat(np.array([1.0, 0.0], dtype=np.float32))
    b.maybe_update(beat_no=20)
    assert b.updates == 2
    # Buffer should reflect the +ve drift in dim 0
    assert b.buffer[0] > 0


def test_current_drift_returns_copy() -> None:
    b = PlasticityBuffer(organ_name="x", latent_dim=2)
    drift = b.current_drift()
    assert drift.shape == (2,)
    drift[0] = 999.0
    # Mutating the copy must not affect the buffer
    assert b.buffer[0] == 0.0


def test_save_load_roundtrip() -> None:
    b = PlasticityBuffer(organ_name="x", latent_dim=3, update_period=5, alpha_p=0.3)
    rng = np.random.default_rng(0)
    for i in range(5):
        b.record_beat(rng.standard_normal(3).astype(np.float32))
    b.maybe_update(beat_no=5)
    # Record a few more (partial window not yet flushed)
    b.record_beat(np.array([1.0, 2.0, 3.0], dtype=np.float32))

    snap = b.save_state()
    # Wreck state
    b.buffer[:] = 999.0
    b._window.clear()
    b._rolling_initialized = False
    # Restore
    b.load_state(snap)
    assert b.updates == 1
    assert b._rolling_initialized
    assert len(b._window) == 1
    assert not np.allclose(b.buffer, 999.0)


# ── v1.6.0 (Checkpoint HH) — shape validation + bounded window ───────────


def test_v1_6_0_load_state_rejects_wrong_buffer_shape() -> None:
    """Loading a snapshot with mismatched latent_dim raises rather than
    silently overwriting `self.buffer` with the wrong shape."""
    b_small = PlasticityBuffer(organ_name="anima", latent_dim=8)
    b_small.record_beat(np.ones(8, dtype=np.float32))
    b_small.maybe_update(beat_no=100)
    snap = b_small.save_state()

    b_big = PlasticityBuffer(organ_name="anima", latent_dim=16)
    with pytest.raises(ValueError, match="plasticity snapshot shape mismatch"):
        b_big.load_state(snap)


def test_v1_6_0_load_state_rejects_wrong_window_entry_shape() -> None:
    """Snapshot window entries with the wrong latent_dim raise on load."""
    b = PlasticityBuffer(organ_name="anima", latent_dim=8)
    snap = b.save_state()
    # Inject a window entry of wrong shape
    snap["window"] = [np.ones(16, dtype=np.float32).tolist()]
    with pytest.raises(ValueError, match="window entry has shape"):
        b.load_state(snap)


def test_v1_6_0_load_state_accepts_matching_shape() -> None:
    """Sanity: load_state still works when shapes match (no regression)."""
    b1 = PlasticityBuffer(organ_name="anima", latent_dim=8)
    for i in range(50):
        b1.record_beat(np.full(8, float(i), dtype=np.float32))
    b1.maybe_update(beat_no=100)
    snap = b1.save_state()

    b2 = PlasticityBuffer(organ_name="anima", latent_dim=8)
    b2.load_state(snap)
    assert np.allclose(b2.buffer, b1.buffer)
    assert b2.updates == b1.updates


def test_v1_6_0_window_is_bounded_deque() -> None:
    """The window is now a deque with maxlen=2*update_period; appending
    beyond that bound silently drops oldest entries rather than growing
    unboundedly. Steady-state size is exactly update_period after each
    maybe_update."""
    from collections import deque

    b = PlasticityBuffer(organ_name="anima", latent_dim=4, update_period=10)
    assert isinstance(b._window, deque)
    assert b._window.maxlen == 20
    # Record more than maxlen without ever calling maybe_update
    for _ in range(50):
        b.record_beat(np.ones(4, dtype=np.float32))
    # Window stayed at maxlen rather than growing
    assert len(b._window) == 20
