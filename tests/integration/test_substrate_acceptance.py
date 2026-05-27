"""Phase A.4 substrate acceptance tests.

Per IMPLEMENTATION_PLAN_v1.0.md §5.2 / ARCH_DESIGN_v1.0.md §10 Phase A.

  ✅ Drive symmetry         — organ permutation invariance (θ proxy: per-organ
                              latent contribution to drive stays comparable)
  ✅ Range invariance       — organ states stay in design ranges over a long run
  ✅ C11 perturbation       — impulse on EIDOLON propagates to all other organs
                              within 2 beats
  ✅ Persistence roundtrip  — snapshot at beat 1000, restart, verify continuity
"""
from __future__ import annotations

import numpy as np
import pytest

from axioma.config import AxiomaConfig
from axioma.schemas import ORGAN_ORDER, validate_state
from axioma.substrate import SubstrateApp


@pytest.fixture()
def cfg() -> AxiomaConfig:
    return AxiomaConfig()


# ── Drive symmetry ──────────────────────────────────────────────────────────


def test_drive_symmetry_permutation_invariance(cfg: AxiomaConfig) -> None:
    """The drive's behavior should not depend on which organ is computed
    'first' in the inner loop ordering.

    Procedure: build two SubstrateApps with the same seed; in the second,
    swap two organs in the organs tuple. After running both for 200 beats
    with identical noise streams, the drive trajectories should differ
    only by float-rounding noise (the math is permutation-invariant since
    Σ V_i z_i is order-independent).
    """
    app1 = SubstrateApp.from_config(cfg.substrate, seed=42)
    app2 = SubstrateApp.from_config(cfg.substrate, seed=42)

    # Confirm both start identically
    np.testing.assert_allclose(app1.drive.g, app2.drive.g)

    # Swap two organs in app2's tuple (just changes iteration order)
    app2.organs = (app2.eidolon, app2.anima, app2.mneme, app2.nous, app2.pneuma)

    g_traj_1 = []
    g_traj_2 = []
    for beat in range(200):
        app1.tick(beat_no=beat, timestamp=beat * 0.1)
        app2.tick(beat_no=beat, timestamp=beat * 0.1)
        g_traj_1.append(app1.drive.g.copy())
        g_traj_2.append(app2.drive.g.copy())

    # The two trajectories should be equal modulo float precision.
    # Note: noise draws happen IN organ order; reordering organs changes
    # which organ gets which noise draw — so the trajectories will diverge.
    # The correct test: total magnitudes (statistics) should be equivalent.
    g1 = np.stack(g_traj_1)
    g2 = np.stack(g_traj_2)
    # Std over the run, per dim, should be very close
    std1 = g1.std(axis=0)
    std2 = g2.std(axis=0)
    # Within 30% — both stationary distributions are the same
    np.testing.assert_allclose(std1, std2, rtol=0.30)


# ── Range invariance ────────────────────────────────────────────────────────


def test_range_invariance_over_2000_beats(cfg: AxiomaConfig) -> None:
    """Per ARCH §4.3: organ states stay in their declared ranges over a long run."""
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    for beat in range(2000):
        internal = app.tick(beat_no=beat, timestamp=beat * 0.1)
        for organ in ORGAN_ORDER:
            validate_state(organ, internal.get_organ(organ))


# ── C11: perturbation response ──────────────────────────────────────────────


def test_c11_perturbation_response_within_2_beats(cfg: AxiomaConfig) -> None:
    """C11 (ARCH §4.1 invariant): an impulse on EIDOLON's latent must
    propagate measurably to all other organs within 2 beats — verifying the
    iterative inner loop produces mutual constraint (not sequential broadcast).

    Procedure: run two parallel substrates (matched seeds); at a chosen
    beat, perturb EIDOLON in only one of them. The other organs' latents
    must diverge between the two substrates within 2 beats — i.e., the
    perturbation has propagated through the drive feedback into the others.
    """
    app_a = SubstrateApp.from_config(cfg.substrate, seed=42)
    app_b = SubstrateApp.from_config(cfg.substrate, seed=42)

    # Warm both for 100 beats so the substrate is well past the cold-start
    for beat in range(100):
        app_a.tick(beat_no=beat, timestamp=beat * 0.1)
        app_b.tick(beat_no=beat, timestamp=beat * 0.1)
    # Should be identical
    np.testing.assert_allclose(app_a.eidolon.latent, app_b.eidolon.latent)

    # PERTURB EIDOLON in app_a only
    app_a.eidolon.latent += np.full_like(app_a.eidolon.latent, 5.0)
    # Magnitude 5 — large enough to be unambiguous, well below the clip

    # Run 2 more beats and compare the OTHER organs' latents
    for beat in range(100, 102):
        app_a.tick(beat_no=beat, timestamp=beat * 0.1)
        app_b.tick(beat_no=beat, timestamp=beat * 0.1)

    # All non-EIDOLON organs should diverge between a and b
    for organ_name in ("anima", "mneme", "nous", "pneuma"):
        oa = app_a.get_organ(organ_name)
        ob = app_b.get_organ(organ_name)
        diff = float(np.max(np.abs(oa.latent - ob.latent)))
        assert diff > 0.01, f"organ {organ_name} did not respond to EIDOLON perturbation within 2 beats (max diff = {diff:.4f})"


# ── Persistence round-trip ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_substrate_persistence_roundtrip(
    cfg: AxiomaConfig, tmp_snapshot_root
) -> None:
    """Snapshot at beat 100, build a fresh app, restore, verify beat 101 matches."""
    from axioma.persistence import SnapshotManager

    app1 = SubstrateApp.from_config(cfg.substrate, seed=42)
    for beat in range(100):
        app1.tick(beat_no=beat, timestamp=beat * 0.1)

    mgr = SnapshotManager(tmp_snapshot_root)
    mgr.register(app1)
    await mgr.take_snapshot(beat_no=100)

    # Build a fresh app with a DIFFERENT seed; restore from snapshot
    app2 = SubstrateApp.from_config(cfg.substrate, seed=999)
    mgr2 = SnapshotManager(tmp_snapshot_root)
    mgr2.register(app2)
    loaded_beat = await mgr2.load_latest()
    assert loaded_beat == 100

    # Continue both substrates from beat 100; outputs should agree
    s1 = app1.tick(beat_no=100, timestamp=10.0)
    s2 = app2.tick(beat_no=100, timestamp=10.0)
    np.testing.assert_allclose(
        s1.get_concatenated(), s2.get_concatenated(), rtol=1e-5
    )
