"""SubstrateApp + Heartbeat — wiring together the substrate critical path."""
from __future__ import annotations

import numpy as np
import pytest

from axioma.config import AxiomaConfig
from axioma.observability import AxiomaContext
from axioma.runtime import Heartbeat
from axioma.schemas import ORGAN_ORDER, InternalState, validate_state
from axioma.substrate import SubstrateApp


def test_from_config_builds_substrate() -> None:
    cfg = AxiomaConfig()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    assert app.drive.n_iter == 3
    assert app.anima.latent_dim == 8
    assert app.eidolon.latent_dim == 12
    assert app.eidolon.rho == 0.92  # C1
    assert app.eidolon.v_scale == 1.3  # C1
    assert app.mneme.v_scale == 1.4  # MNEME α_M
    assert app.pneuma.state_dim == 7  # +1 for coherence_budget


def test_substrate_organs_in_canonical_order() -> None:
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=0)
    assert tuple(o.name for o in app.organs) == ORGAN_ORDER


def test_tick_returns_internal_state() -> None:
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=42)
    internal = app.tick(beat_no=1, timestamp=0.1)
    assert isinstance(internal, InternalState)
    assert internal.beat_no == 1
    assert internal.timestamp == 0.1


def test_tick_advances_substrate_state() -> None:
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=42)
    initial_g = app.drive.g.copy()
    initial_latents = [o.latent.copy() for o in app.organs]
    app.tick(beat_no=1, timestamp=0.1)
    assert not np.allclose(app.drive.g, initial_g)
    for o, init in zip(app.organs, initial_latents, strict=True):
        assert not np.allclose(o.latent, init)


def test_render_all_requires_tick_first() -> None:
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=42)
    with pytest.raises(RuntimeError, match=r"tick.*has not been called"):
        app.render_all()


def test_substrate_app_invariants_500_beats() -> None:
    """A.4 acceptance: range invariance over a long run."""
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=42)
    internal = None
    for beat in range(500):
        internal = app.tick(beat_no=beat, timestamp=beat * 0.1)
        for organ in ORGAN_ORDER:
            validate_state(organ, internal.get_organ(organ))
    assert internal is not None
    assert internal.beat_no == 499


def test_save_load_roundtrip() -> None:
    app1 = SubstrateApp.from_config(AxiomaConfig().substrate, seed=42)
    for beat in range(100):
        app1.tick(beat_no=beat, timestamp=beat * 0.1)
    snap = app1.save_state()

    # Build a fresh app with same config; restore
    app2 = SubstrateApp.from_config(AxiomaConfig().substrate, seed=99)  # different seed
    app2.load_state(snap)
    # Next tick from both should match
    state1 = app1.tick(beat_no=100, timestamp=10.0)
    state2 = app2.tick(beat_no=100, timestamp=10.0)
    # Deterministic continuation: bit-equal for the same beat_no
    assert state1.beat_no == state2.beat_no
    np.testing.assert_allclose(
        state1.get_concatenated(), state2.get_concatenated(), rtol=1e-5
    )


def test_get_organ_by_name() -> None:
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=0)
    assert app.get_organ("anima") is app.anima
    assert app.get_organ("pneuma") is app.pneuma
    with pytest.raises(KeyError):
        app.get_organ("nope")


def test_plasticity_disabled() -> None:
    app = SubstrateApp.from_config(
        AxiomaConfig().substrate, seed=42, plasticity_enabled=False
    )
    for beat in range(150):
        app.tick(beat_no=beat, timestamp=beat * 0.1)
    # All plasticity buffers should still be at zero (no updates triggered)
    for buf in app.plasticity.values():
        assert buf.updates == 0
        assert np.allclose(buf.buffer, 0.0)


def test_plasticity_enabled_triggers_updates() -> None:
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=42)
    # Drive 150 beats to trigger at least one plasticity update at beat 100
    for beat in range(150):
        app.tick(beat_no=beat, timestamp=beat * 0.1)
    # All plasticity buffers should have at least one update
    for buf in app.plasticity.values():
        assert buf.updates >= 1


# ── Heartbeat integration ───────────────────────────────────────────────────


def test_heartbeat_tick_advances_beat_no() -> None:
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    ctx.register("substrate", app)
    hb = Heartbeat(ctx=ctx, substrate=app, hz=10)
    hb.tick()
    assert hb.beat_no == 1
    hb.tick()
    assert hb.beat_no == 2


def test_heartbeat_tick_returns_internal() -> None:
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=0)
    hb = Heartbeat(ctx=ctx, substrate=app, hz=10)
    internal = hb.tick()
    assert isinstance(internal, InternalState)


def test_heartbeat_invalid_hz_raises() -> None:
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=0)
    with pytest.raises(ValueError, match="hz must be positive"):
        Heartbeat(ctx=ctx, substrate=app, hz=0)


def test_heartbeat_run_requires_one_of_seconds_or_beats() -> None:
    import asyncio

    ctx = AxiomaContext()
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=0)
    hb = Heartbeat(ctx=ctx, substrate=app, hz=10)
    with pytest.raises(ValueError, match="Provide exactly one"):
        asyncio.run(hb.run())
    with pytest.raises(ValueError, match="Provide exactly one"):
        asyncio.run(hb.run(seconds=1, beats=1))


async def test_heartbeat_run_for_n_beats() -> None:
    cfg = AxiomaConfig()
    ctx = AxiomaContext()
    app = SubstrateApp.from_config(cfg.substrate, seed=0)
    # Use higher hz so the test is fast
    hb = Heartbeat(ctx=ctx, substrate=app, hz=1000)
    await hb.run(beats=20)
    assert hb.beat_no == 20


# ── v1.6.0 (Checkpoint II) — GG-7 substrate load-skip tracking ───────────


def test_v1_6_0_last_load_skipped_default_empty() -> None:
    """At construction, no load has happened — both skip lists are empty."""
    app = SubstrateApp.from_config(AxiomaConfig().substrate, seed=42)
    assert app.last_load_skipped_organs == []
    assert app.last_load_skipped_plasticity == []


def test_v1_6_0_load_state_full_snapshot_yields_empty_skip_lists() -> None:
    """A complete snapshot round-trips with no skips."""
    cfg = AxiomaConfig()
    app1 = SubstrateApp.from_config(cfg.substrate, seed=42)
    app1.tick(beat_no=0, timestamp=0.0)
    snap = app1.save_state()

    app2 = SubstrateApp.from_config(cfg.substrate, seed=99)
    app2.load_state(snap)
    assert app2.last_load_skipped_organs == []
    assert app2.last_load_skipped_plasticity == []


def test_v1_6_0_load_state_records_missing_organs() -> None:
    """If the snapshot is missing some organs, they show up in
    last_load_skipped_organs instead of silently no-op'ing."""
    cfg = AxiomaConfig()
    app1 = SubstrateApp.from_config(cfg.substrate, seed=42)
    app1.tick(beat_no=0, timestamp=0.0)
    snap = app1.save_state()
    # Strip eidolon + nous from the snapshot
    del snap["organs"]["eidolon"]
    del snap["organs"]["nous"]

    app2 = SubstrateApp.from_config(cfg.substrate, seed=99)
    app2.load_state(snap)
    assert sorted(app2.last_load_skipped_organs) == ["eidolon", "nous"]
    assert app2.last_load_skipped_plasticity == []


def test_v1_6_0_load_state_records_missing_plasticity() -> None:
    """Same coverage for missing plasticity buffers."""
    cfg = AxiomaConfig()
    app1 = SubstrateApp.from_config(cfg.substrate, seed=42)
    app1.tick(beat_no=0, timestamp=0.0)
    snap = app1.save_state()
    del snap["plasticity"]["mneme"]

    app2 = SubstrateApp.from_config(cfg.substrate, seed=99)
    app2.load_state(snap)
    assert app2.last_load_skipped_plasticity == ["mneme"]
    assert app2.last_load_skipped_organs == []


def test_v1_6_0_load_state_resets_skip_lists_on_each_call() -> None:
    """Skip lists reflect the most recent load, not cumulative across loads."""
    cfg = AxiomaConfig()
    app1 = SubstrateApp.from_config(cfg.substrate, seed=42)
    app1.tick(beat_no=0, timestamp=0.0)
    snap_partial = app1.save_state()
    del snap_partial["organs"]["pneuma"]
    snap_full = app1.save_state()

    app2 = SubstrateApp.from_config(cfg.substrate, seed=99)
    app2.load_state(snap_partial)
    assert app2.last_load_skipped_organs == ["pneuma"]
    # Subsequent full load → skip list cleared
    app2.load_state(snap_full)
    assert app2.last_load_skipped_organs == []


# ── v1.6.2 (Checkpoint KK / GG-2) — MNEME stage-2/3 wiring ───────────────


def test_v1_6_2_stage2_off_means_no_wiring_invoked() -> None:
    """When stage2_enabled is explicitly OFF (v1.6 backwards-compat), SubstrateApp.tick
    must NOT initialize the cross-organ matrix M or set neighbor states.

    v1.7 default-flip (Checkpoint MM) flipped the default to True. Operators
    wanting the v1.6 substrate behavior load configs/v1_6_backwards_compat.yaml."""
    cfg = AxiomaConfig()
    object.__setattr__(cfg.substrate, "mneme_compensation_2_enabled", False)
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    app.tick(beat_no=0, timestamp=0.0)
    assert app.mneme._M is None
    assert app.mneme._neighbor_states_concat is None


def test_v1_7_mneme_compensations_default_on() -> None:
    """v1.7 default-flip (Checkpoint MM): both MNEME compensations default ON.
    Empirical justification in RELEASE_v1.7.md (Checkpoint LL sweep —
    +0.30/+0.36 recovery quality, 92%/96% fragmentation reduction on 2/3 seeds)."""
    cfg = AxiomaConfig()
    assert cfg.substrate.mneme_compensation_2_enabled is True
    assert cfg.substrate.mneme_compensation_3_enabled is True
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    app.tick(beat_no=0, timestamp=0.0)
    assert app.mneme._neighbor_states_concat is not None  # stage-2 wired
    assert app.plasticity["mneme"].alpha_p == 0.10  # stage-3 boosted


def test_v1_7_backwards_compat_yaml_restores_v1_6_behavior() -> None:
    """configs/v1_6_backwards_compat.yaml MUST restore the v1.6 substrate
    (both MNEME compensations OFF)."""
    import os

    from axioma.config import load_config
    prev = os.environ.get("AXIOMA_CONFIG")
    os.environ["AXIOMA_CONFIG"] = "configs/v1_6_backwards_compat.yaml"
    try:
        cfg = load_config()
        assert cfg.substrate.mneme_compensation_2_enabled is False
        assert cfg.substrate.mneme_compensation_3_enabled is False
    finally:
        if prev is None:
            del os.environ["AXIOMA_CONFIG"]
        else:
            os.environ["AXIOMA_CONFIG"] = prev


def test_v1_6_2_stage2_enabled_wires_neighbor_states_after_first_tick() -> None:
    """When stage2_enabled=True, the first tick calls ensure_stage2 + sets
    neighbor_states. cross_coupling becomes nonzero on the SECOND tick (after
    which both _M and _neighbor_states_concat are populated)."""
    cfg = AxiomaConfig()
    object.__setattr__(cfg.substrate, "mneme_compensation_2_enabled", True)
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    # First tick: cross_coupling fires with no neighbor states yet → zero
    app.tick(beat_no=0, timestamp=0.0)
    # After first tick, M and neighbor states should be set up
    assert app.mneme._M is not None
    assert app.mneme._neighbor_states_concat is not None
    # Neighbor concat should match the sum of state_dims for anima(4) + eidolon(6) + nous(6) + pneuma(7) = 23
    assert app.mneme._neighbor_states_concat.shape == (23,)
    # cross_coupling on this beat (called BEFORE wiring fires) returned zero;
    # the next tick's cross_coupling will use the now-set states.
    cc = app.mneme.cross_coupling()
    assert not np.allclose(cc, 0.0)


def test_v1_6_2_stage2_changes_substrate_dynamics_when_enabled() -> None:
    """Enabling stage-2 produces a different substrate trajectory than off.
    Concrete behavioral check: MNEME's latent after N beats differs between
    stage2=off and stage2=on (same seed). This confirms the wiring isn't
    a no-op."""
    cfg_off = AxiomaConfig()
    object.__setattr__(cfg_off.substrate, "mneme_compensation_2_enabled", False)
    object.__setattr__(cfg_off.substrate, "mneme_compensation_3_enabled", False)
    cfg_on = AxiomaConfig()
    object.__setattr__(cfg_on.substrate, "mneme_compensation_2_enabled", True)
    object.__setattr__(cfg_on.substrate, "mneme_compensation_3_enabled", False)

    app_off = SubstrateApp.from_config(cfg_off.substrate, seed=42)
    app_on = SubstrateApp.from_config(cfg_on.substrate, seed=42)
    # Run both for several beats so cross-coupling has time to affect MNEME's latent
    for beat in range(20):
        app_off.tick(beat_no=beat, timestamp=float(beat) * 0.1)
        app_on.tick(beat_no=beat, timestamp=float(beat) * 0.1)
    # MNEME's latent should diverge between the two regimes
    assert not np.allclose(app_off.mneme.latent, app_on.mneme.latent, atol=1e-6)


def test_v1_6_2_stage3_off_means_baseline_alpha_p() -> None:
    """When stage3_enabled is explicitly OFF (v1.6 backwards-compat), MNEME's
    plasticity buffer uses the baseline alpha_p=0.05.

    v1.7 default-flip (Checkpoint MM) flipped this default to True; this test
    asserts the off path still works for back-compat YAML loads."""
    cfg = AxiomaConfig()
    object.__setattr__(cfg.substrate, "mneme_compensation_3_enabled", False)
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    assert app.plasticity["mneme"].alpha_p == 0.05
    # Sanity: non-mneme organs also at baseline 0.05
    assert app.plasticity["anima"].alpha_p == 0.05


def test_v1_6_2_stage3_enabled_boosts_mneme_alpha_p_only() -> None:
    """When stage3_enabled=True, MNEME's plasticity gets alpha_p=0.10 (2×
    baseline); other organs stay at 0.05. Selective per-organ boost."""
    cfg = AxiomaConfig()
    object.__setattr__(cfg.substrate, "mneme_compensation_3_enabled", True)
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    assert app.plasticity["mneme"].alpha_p == 0.10
    # Non-mneme organs unaffected
    for organ_name in ("anima", "eidolon", "nous", "pneuma"):
        assert app.plasticity[organ_name].alpha_p == 0.05


def test_v1_6_2_stage2_and_stage3_can_be_enabled_independently() -> None:
    """The two compensations are independent toggles."""
    cfg = AxiomaConfig()
    # Explicitly set: stage2 ON, stage3 OFF (overriding v1.7's both-default-ON)
    object.__setattr__(cfg.substrate, "mneme_compensation_2_enabled", True)
    object.__setattr__(cfg.substrate, "mneme_compensation_3_enabled", False)
    app = SubstrateApp.from_config(cfg.substrate, seed=42)
    app.tick(beat_no=0, timestamp=0.0)
    assert app.mneme.stage2_enabled is True
    assert app.mneme.stage3_enabled is False
    assert app.plasticity["mneme"].alpha_p == 0.05  # baseline (stage3 off)
    assert app.mneme._neighbor_states_concat is not None  # stage2 wired
