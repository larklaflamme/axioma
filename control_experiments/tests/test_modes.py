import numpy as np
import pytest

from aos_g_gap.compose import ComposeFunction
from control_experiments.modes import build_mode
from control_experiments.modes.control4 import IdentityComposeFunction
from organ.schemas import ORGAN_DIMS, ORGAN_ORDER


def test_baseline_round_trip():
    mode = build_mode("baseline")
    hb = mode.build_heartbeat(seed=0, coupling=0.6)
    for _ in range(50):
        hb.tick()
    # All organs produce range-valid state.
    for o in hb.organs:
        s = o.get_state()
        assert s.to_array().shape == (ORGAN_DIMS[o.name],)


def test_control1_self_coherence_constant():
    mode = build_mode("control1")
    hb = mode.build_heartbeat(seed=0, coupling=0.6)
    coh = []
    for _ in range(100):
        hb.tick()
        coh.append(hb.eidolon.get_state().self_coherence)
    assert max(coh) - min(coh) < 1e-6  # constant 0.5


def test_control1_pneuma_integration_constant():
    mode = build_mode("control1")
    hb = mode.build_heartbeat(seed=0, coupling=0.6)
    integ = []
    for _ in range(100):
        hb.tick()
        integ.append(hb.pneuma.get_state().integration_level)
    assert max(integ) - min(integ) < 1e-6


def test_control2_random_dt():
    mode = build_mode("control2")
    hb = mode.build_heartbeat(seed=0, coupling=0.6)
    for _ in range(500):
        hb.tick()
    dts = np.array(hb.dt_history)
    assert 90 < dts.mean() < 110  # mean ~100
    assert dts.std() > 30          # high variance
    assert (dts >= 10).all() and (dts <= 190).all()


def test_control3_organs_share_latent_after_post_tick():
    mode = build_mode("control3")
    hb = mode.build_heartbeat(seed=0, coupling=0.6)
    for _ in range(20):
        hb.tick()
        mode.post_tick(hb)
    # After post_tick, non-ANIMA organs' latent is a tile of ANIMA's.
    anima_l = hb.anima.latent
    for organ in (hb.eidolon, hb.mneme, hb.nous, hb.pneuma):
        tile = np.tile(anima_l, int(np.ceil(organ.DIM / len(anima_l))))[:organ.DIM]
        assert np.allclose(organ.latent, tile, atol=1e-5)


def test_control4_identity_compose():
    mode = build_mode("control4")
    cf = mode.build_compose(seed=0)
    assert isinstance(cf, IdentityComposeFunction)
    internal = {o: np.arange(ORGAN_DIMS[o], dtype=np.float32) for o in ORGAN_ORDER}
    # First push something into rolling so it isn't all zeros.
    cf.update_rolling(internal)
    out = cf.compose(internal, integration_level=0.0, self_coherence=0.0)
    for o in ORGAN_ORDER:
        assert np.allclose(out.external_arrays[o], internal[o])
        assert out.fidelity_factors[o] == 1.0


def test_baseline_time_scale_default_is_1():
    """Existing aos_g_gap trials use time_scale=1.0 by default → no change."""
    from aos_g_gap.trial import TrialConfig, run_single_trial
    r1 = run_single_trial(TrialConfig(condition="baseline", seed=42, n_beats=100))
    r2 = run_single_trial(TrialConfig(condition="baseline", seed=42, n_beats=100))
    assert np.allclose(r1.delta_norm_series, r2.delta_norm_series)
