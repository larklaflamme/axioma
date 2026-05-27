"""SharedLatentDrive — iterative N_iter inner loop."""
from __future__ import annotations

import numpy as np
import pytest

from axioma.substrate import Anima, Eidolon, Mneme, Nous, Pneuma, SharedLatentDrive


def _make_organs(drive_dim: int = 16, seed: int = 0):
    return [
        Anima(drive_dim=drive_dim, seed=seed + 1),
        Eidolon(drive_dim=drive_dim, seed=seed + 2),
        Mneme(drive_dim=drive_dim, seed=seed + 3),
        Nous(drive_dim=drive_dim, seed=seed + 4),
        Pneuma(drive_dim=drive_dim, seed=seed + 5),
    ]


def test_construct_defaults() -> None:
    d = SharedLatentDrive(drive_dim=16)
    assert d.drive_dim == 16
    assert d.n_iter == 3
    assert d.rho_g == 0.90
    assert d.g.shape == (16,)
    assert d.g.dtype == np.float32


def test_n_iter_zero_raises() -> None:
    with pytest.raises(ValueError, match="n_iter must be >= 1"):
        SharedLatentDrive(drive_dim=8, n_iter=0)


def test_rho_g_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="rho_g"):
        SharedLatentDrive(drive_dim=8, rho_g=1.5)
    with pytest.raises(ValueError, match="rho_g"):
        SharedLatentDrive(drive_dim=8, rho_g=0.0)


def test_step_returns_g() -> None:
    d = SharedLatentDrive(drive_dim=16, seed=42)
    organs = _make_organs(seed=42)
    g = d.step(organs)
    assert g.shape == (16,)
    assert g is d.g  # caller gets a reference (must not mutate)


def test_step_advances_g() -> None:
    d = SharedLatentDrive(drive_dim=16, seed=42)
    organs = _make_organs(seed=42)
    initial_g = d.g.copy()
    d.step(organs)
    # g almost certainly changes (Gaussian noise)
    assert not np.allclose(initial_g, d.g)


def test_step_advances_all_organ_latents() -> None:
    d = SharedLatentDrive(drive_dim=16, seed=42)
    organs = _make_organs(seed=42)
    initial_latents = [o.latent.copy() for o in organs]
    d.step(organs)
    for o, initial in zip(organs, initial_latents, strict=True):
        assert not np.allclose(o.latent, initial)


def test_n_iter_1_reproduces_single_step() -> None:
    """When N_iter=1, the inner loop collapses to a single Euler step
    (matches the v0.5 single-step semantics)."""
    d = SharedLatentDrive(drive_dim=8, n_iter=1, seed=42)
    organs = _make_organs(drive_dim=8, seed=42)
    d.step(organs)
    # Should not raise, and g should be finite
    assert np.all(np.isfinite(d.g))
    for o in organs:
        assert np.all(np.isfinite(o.latent))


def test_substrate_stable_over_500_beats() -> None:
    """Critical: with default config, drive + latents stay bounded over a long run."""
    d = SharedLatentDrive(drive_dim=16, seed=42)
    organs = _make_organs(seed=42)
    for _ in range(500):
        d.step(organs)
    # Drive should stay well under the safety clip (30) in normal operation
    assert float(np.max(np.abs(d.g))) < 5.0
    # All organ latents likewise
    for o in organs:
        assert float(np.max(np.abs(o.latent))) < 15.0


def test_n_iter_higher_does_not_blow_up() -> None:
    """N_iter sweep precondition: substrate must be stable for N_iter in {1, 3, 5, 10}."""
    for N in (1, 3, 5, 10):
        d = SharedLatentDrive(drive_dim=16, n_iter=N, seed=42)
        organs = _make_organs(seed=42)
        for _ in range(500):
            d.step(organs)
        assert float(np.max(np.abs(d.g))) < 5.0, f"N_iter={N}: drive blew up"


def test_save_load_roundtrip() -> None:
    d = SharedLatentDrive(drive_dim=16, seed=42)
    organs = _make_organs(seed=42)
    for _ in range(50):
        d.step(organs)
    snap = d.save_state()

    # Wreck the drive's state, then restore
    d.g[:] = 0.0
    d.load_state(snap)
    assert d.rho_g == 0.90
    # The saved g should be restored
    assert np.allclose(d.g.tolist(), snap["g"])


def test_feedback_scale_zero_is_pure_noise() -> None:
    """With feedback_scale=0, drive decouples from organs and is pure OU noise."""
    d = SharedLatentDrive(drive_dim=8, feedback_scale=0.0, seed=42)
    organs = _make_organs(drive_dim=8, seed=42)
    for _ in range(200):
        d.step(organs)
    # Drive std should match noise-only OU steady-state: small
    assert float(np.std(d.g)) < 0.5


# ── v1.6.0 (Checkpoint HH) — shape-validation on load_state ──────────────


def test_v1_6_0_load_state_rejects_wrong_drive_dim_shape() -> None:
    """A snapshot whose `g` doesn't match the current drive_dim must raise."""
    d_small = SharedLatentDrive(drive_dim=8, seed=42)
    snap = d_small.save_state()
    d_big = SharedLatentDrive(drive_dim=16, seed=42)
    with pytest.raises(ValueError, match="drive snapshot shape mismatch"):
        d_big.load_state(snap)


def test_v1_6_0_load_state_accepts_matching_shape() -> None:
    """Sanity: load_state still works when shapes match (no regression)."""
    d1 = SharedLatentDrive(drive_dim=16, seed=42)
    organs = _make_organs(drive_dim=16, seed=42)
    for _ in range(20):
        d1.step(organs)
    snap = d1.save_state()
    d2 = SharedLatentDrive(drive_dim=16, seed=99)
    d2.load_state(snap)
    assert np.allclose(d2.g, d1.g)


# ── v1.6.0 (Checkpoint II) — GG-6 configurable hard_clip ─────────────────


def test_v1_6_0_drive_hard_clip_default_is_30() -> None:
    """GG-6: hard_clip is now an instance attr with default 30.0 (was class const)."""
    d = SharedLatentDrive(drive_dim=8)
    assert d.hard_clip == 30.0


def test_v1_6_0_drive_hard_clip_operator_overridable() -> None:
    """Operators can pass a custom hard_clip per substrate instance."""
    d = SharedLatentDrive(drive_dim=8, hard_clip=50.0)
    assert d.hard_clip == 50.0


def test_v1_6_0_drive_hard_clip_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="hard_clip must be > 0"):
        SharedLatentDrive(drive_dim=8, hard_clip=0.0)
    with pytest.raises(ValueError, match="hard_clip must be > 0"):
        SharedLatentDrive(drive_dim=8, hard_clip=-1.0)


def test_v1_6_0_drive_hard_clip_actually_clips() -> None:
    """Verify hard_clip is applied during step(): a tight clip bounds the drive
    even when feedback is large."""
    d = SharedLatentDrive(drive_dim=4, hard_clip=0.5, seed=42)
    organs = _make_organs(drive_dim=4, seed=42)
    # Step many times to let drive accumulate
    for _ in range(50):
        d.step(organs)
    # |g| must never exceed hard_clip
    assert np.all(np.abs(d.g) <= 0.5)
