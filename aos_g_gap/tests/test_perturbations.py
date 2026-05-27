import numpy as np

from aos_g_gap.perturbations import build, REGISTRY
from organ.substrate import Heartbeat


def _new_hb(seed):
    return Heartbeat(seed=seed)


def test_no_perturbation_is_noop():
    pert = build("baseline", trigger_beat=10, duration=5, seed=0)
    hb = _new_hb(0)
    eid_latent_before = hb.eidolon.latent.copy()
    pert.apply_pre_update(15, {o.name: o for o in hb.organs})
    assert np.array_equal(hb.eidolon.latent, eid_latent_before)


def test_contradiction_collapses_self_coherence():
    pert = build("direct_contradiction", trigger_beat=10, duration=10, seed=0)
    hb = _new_hb(0)
    # Run a few baseline beats to let latent settle.
    for _ in range(10):
        hb.tick()
    # Apply perturbation for its full duration via direct calls.
    for b in range(10, 20):
        pert.apply_pre_update(b, {o.name: o for o in hb.organs})
        # Run organ update on the perturbed latent.
        drive = hb.dynamics.step()
        hb.eidolon.update(b, drive)
    assert hb.eidolon.get_state().self_coherence < 0.2


def test_mneme_disruption_kills_wm_load():
    pert = build("mneme_disruption", trigger_beat=0, duration=20, seed=0)
    hb = _new_hb(0)
    for b in range(20):
        pert.apply_pre_update(b, {o.name: o for o in hb.organs})
        drive = hb.dynamics.step()
        hb.mneme.update(b, drive)
    s = hb.mneme.get_state()
    assert s.wm_load <= 1
    assert s.retrieval_rate < 0.2


def test_inactive_outside_window():
    pert = build("direct_contradiction", trigger_beat=100, duration=20, seed=0)
    assert not pert.is_active(50)
    assert pert.is_active(100)
    assert pert.is_active(119)
    assert not pert.is_active(120)


def test_registry_complete():
    for cond in [
        "baseline",
        "direct_contradiction",
        "surprising_falsehood",
        "surprising_truth",
        "nonsense",
        "mneme_disruption",
        "random_perturbation",
    ]:
        assert cond in REGISTRY
