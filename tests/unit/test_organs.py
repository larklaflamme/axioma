"""5 concrete organs — basic construction + render contract."""
from __future__ import annotations

import numpy as np
import pytest

from axioma.schemas import (
    AnimaState,
    EidolonState,
    MnemeState,
    NousState,
    PneumaState,
    validate_state,
)
from axioma.substrate import Anima, Eidolon, Mneme, Nous, Pneuma, SharedLatentDrive


def test_anima_specs() -> None:
    o = Anima(drive_dim=16)
    assert o.name == "anima"
    assert o.latent_dim == 8  # v1.0 widened
    assert o.state_dim == 4
    assert o.rho == 0.85


def test_eidolon_v1_specs() -> None:
    """C1: EIDOLON ρ=0.92, V_scale=1.3, latent_dim=12 — fastest, strongest."""
    o = Eidolon(drive_dim=16)
    assert o.name == "eidolon"
    assert o.latent_dim == 12
    assert o.rho == 0.92
    assert o.v_scale == 1.3


def test_mneme_v1_specs() -> None:
    """MNEME stage-1 compensation: V_scale = α_M = 1.4."""
    o = Mneme(drive_dim=16)
    assert o.name == "mneme"
    assert o.latent_dim == 12
    assert o.rho == 0.88
    assert o.v_scale == 1.4
    assert not o.stage2_enabled
    assert not o.stage3_enabled


def test_nous_specs() -> None:
    o = Nous(drive_dim=16)
    assert o.name == "nous"
    assert o.latent_dim == 10
    assert o.rho == 0.90
    assert o.v_scale == 1.0


def test_pneuma_specs() -> None:
    """PNEUMA peer interface: same as other organs, state_dim=7 with coherence_budget."""
    o = Pneuma(drive_dim=16)
    assert o.name == "pneuma"
    assert o.latent_dim == 12
    assert o.state_dim == 7  # +1 for coherence_budget
    # PNEUMA has NO integrate() method — that's the architectural fix
    assert not hasattr(o, "integrate")


def test_anima_render_returns_animastate_in_range() -> None:
    o = Anima(drive_dim=16, seed=0)
    s = o.render()
    assert isinstance(s, AnimaState)
    validate_state("anima", s)


def test_eidolon_render_returns_eidolonstate_in_range() -> None:
    o = Eidolon(drive_dim=16, seed=0)
    s = o.render()
    assert isinstance(s, EidolonState)
    validate_state("eidolon", s)


def test_mneme_render_returns_mnemestate_in_range() -> None:
    o = Mneme(drive_dim=16, seed=0)
    s = o.render()
    assert isinstance(s, MnemeState)
    validate_state("mneme", s)


def test_nous_render_returns_nousstate_in_range() -> None:
    o = Nous(drive_dim=16, seed=0)
    s = o.render()
    assert isinstance(s, NousState)
    validate_state("nous", s)


def test_pneuma_render_returns_pneumastate_in_range() -> None:
    o = Pneuma(drive_dim=16, seed=0)
    s = o.render()
    assert isinstance(s, PneumaState)
    validate_state("pneuma", s)


def test_render_in_range_after_500_beats() -> None:
    """All organ states stay in declared ranges over a 500-beat run.

    This is the Phase A.4 'range invariance' acceptance test, unit-scoped
    (no full SubstrateApp; just drive + organs)."""
    d = SharedLatentDrive(drive_dim=16, seed=42)
    organs = (
        Anima(drive_dim=16, seed=1),
        Eidolon(drive_dim=16, seed=2),
        Mneme(drive_dim=16, seed=3),
        Nous(drive_dim=16, seed=4),
        Pneuma(drive_dim=16, seed=5),
    )
    for beat in range(500):
        d.step(list(organs))
        # Render each organ; validate
        for o in organs:
            s = o.render()
            validate_state(o.name, s)


def test_contribution_to_drive_shape() -> None:
    """V_i z_i has shape (drive_dim,)."""
    for cls in (Anima, Eidolon, Mneme, Nous, Pneuma):
        o = cls(drive_dim=16, seed=0)
        c = o.contribution_to_drive()
        assert c.shape == (16,)


def test_default_cross_coupling_is_zero() -> None:
    for cls in (Anima, Eidolon, Nous, Pneuma):
        o = cls(drive_dim=16, seed=0)
        c = o.cross_coupling()
        assert c.shape == (o.latent_dim,)
        assert np.allclose(c, 0.0)


def test_mneme_stage1_cross_coupling_is_zero() -> None:
    """With stage-1 (default) only, MNEME cross_coupling is zero too."""
    o = Mneme(drive_dim=16, seed=0)
    assert np.allclose(o.cross_coupling(), 0.0)


def test_mneme_stage2_requires_setup() -> None:
    """If stage2 enabled but neighbor states not set, cross_coupling stays zero."""
    o = Mneme(drive_dim=16, stage2_enabled=True, seed=0)
    assert np.allclose(o.cross_coupling(), 0.0)
    # After setup + neighbor states, should be nonzero
    o.ensure_stage2(neighbor_dim=20)
    o.set_neighbor_states(np.ones(20, dtype=np.float32))
    c = o.cross_coupling()
    assert not np.allclose(c, 0.0)


def test_pneuma_coherence_budget_depends_on_load() -> None:
    """Higher load → lower budget."""
    o = Pneuma(drive_dim=16, seed=0)
    # Default load = 0 → max budget
    o.set_load_signals(nous_cognitive_load=0.0, mneme_wm_load=0)
    s_low = o.render()
    # Pile on load
    o.set_load_signals(nous_cognitive_load=1.0, mneme_wm_load=7)
    s_high = o.render()
    assert s_high.coherence_budget < s_low.coherence_budget


def test_pneuma_cascade_delay_affects_budget() -> None:
    o = Pneuma(drive_dim=16, seed=0)
    o.set_load_signals(nous_cognitive_load=0.0, mneme_wm_load=0, cascade_delay_beats=0.0)
    s_no_cascade = o.render()
    o.set_load_signals(cascade_delay_beats=25.0)  # > 20 threshold
    s_with_cascade = o.render()
    assert s_with_cascade.coherence_budget < s_no_cascade.coherence_budget


def test_pneuma_buffer_push_drain() -> None:
    o = Pneuma(drive_dim=16, seed=0)
    o.push_compose()
    o.push_compose()
    assert o.render().buffer_depth == 2
    o.drain_compose()
    assert o.render().buffer_depth == 0


def test_organ_save_load_roundtrip() -> None:
    o1 = Anima(drive_dim=16, seed=42)
    d = SharedLatentDrive(drive_dim=16, seed=42)
    for _ in range(10):
        d.step([o1])
    snap = o1.save_state()
    # Wreck state
    o1.latent[:] = 0.0
    o1._mood_latent = 999.0
    # Load
    o1.load_state(snap)
    assert o1._mood_latent != 999.0  # restored


def test_organ_subclass_must_set_name() -> None:
    """Constructor sanity: a subclass without a name attribute should fail loudly."""
    from axioma.substrate.base import Organ

    class NamelessOrgan(Organ):
        # missing name attribute set to nonempty
        def render(self):  # type: ignore[no-untyped-def, override]
            return None

    with pytest.raises(NotImplementedError):
        NamelessOrgan(
            drive_dim=16,
            latent_dim=8,
            state_dim=4,
            rho=0.9,
            v_scale=1.0,
            seed=0,
        )


# ── v1.6.0 (Checkpoint HH) — shape-validation on Organ.load_state ────────


def test_v1_6_0_organ_load_state_rejects_wrong_latent_shape() -> None:
    """An organ snapshot whose latent doesn't match the current latent_dim
    raises rather than silently overwriting the latent."""
    o_small = Anima(drive_dim=16, latent_dim=8, seed=42)
    snap = o_small.save_state()
    o_big = Anima(drive_dim=16, latent_dim=12, seed=42)
    with pytest.raises(ValueError, match=r"latent\.shape="):
        o_big.load_state(snap)


def test_v1_6_0_organ_load_state_rejects_wrong_W_shape() -> None:
    """Wrong W shape (from a snapshot with different drive_dim) raises."""
    o1 = Anima(drive_dim=8, latent_dim=8, seed=42)
    snap = o1.save_state()
    o2 = Anima(drive_dim=16, latent_dim=8, seed=42)
    with pytest.raises(ValueError, match=r"W\.shape="):
        o2.load_state(snap)


def test_v1_6_0_organ_load_state_rejects_wrong_V_shape() -> None:
    """Wrong V shape is also caught (V is latent_dim × drive_dim)."""
    o1 = Anima(drive_dim=8, latent_dim=8, seed=42)
    snap = o1.save_state()
    # Manually inject a V of the wrong shape (different drive_dim)
    import numpy as np
    snap["V"] = np.zeros((8, 16), dtype=np.float32).tolist()
    o2 = Anima(drive_dim=8, latent_dim=8, seed=42)
    with pytest.raises(ValueError, match=r"V\.shape="):
        o2.load_state(snap)


def test_v1_6_0_organ_load_state_accepts_matching_shape() -> None:
    """Sanity: load_state still works when shapes match (no regression)."""
    o1 = Anima(drive_dim=16, latent_dim=8, seed=42)
    d = SharedLatentDrive(drive_dim=16, seed=42)
    for _ in range(10):
        d.step([o1])
    snap = o1.save_state()
    o2 = Anima(drive_dim=16, latent_dim=8, seed=99)
    o2.load_state(snap)
    import numpy as np
    assert np.allclose(o2.latent, o1.latent)


# ── v1.6.0 (Checkpoint II) — GG-4/GG-6 polish: configurable clips + named constants ──


def test_v1_6_0_organ_latent_hard_clip_is_instance_attr() -> None:
    """Operators can override the latent hard clip per-organ via __init__."""
    o_default = Anima(drive_dim=16, seed=42)
    assert o_default.latent_hard_clip == 30.0
    o_custom = Anima(drive_dim=16, seed=42, latent_hard_clip=50.0)
    assert o_custom.latent_hard_clip == 50.0


def test_v1_6_0_organ_latent_hard_clip_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="latent_hard_clip must be > 0"):
        Anima(drive_dim=16, seed=42, latent_hard_clip=0.0)
    with pytest.raises(ValueError, match="latent_hard_clip must be > 0"):
        Anima(drive_dim=16, seed=42, latent_hard_clip=-1.0)


def test_v1_6_0_pneuma_coherence_budget_constants_named() -> None:
    """GG-4: magic numbers from _compute_coherence_budget are now named
    module-level constants for operator inspection + future config wiring."""
    from axioma.substrate.pneuma import (
        _CASCADE_DELAY_THRESHOLD,
        _WM_LOAD_CAPACITY,
    )
    assert _WM_LOAD_CAPACITY == 7.0
    assert _CASCADE_DELAY_THRESHOLD == 20.0


def test_v1_6_0_pneuma_coherence_budget_uses_cascade_threshold_constant() -> None:
    """Verify the constant is actually used (not just declared): cascade delay
    just above vs just below _CASCADE_DELAY_THRESHOLD produces a budget step."""
    p = Pneuma(drive_dim=16, seed=42)
    # Just below threshold → cascade contributes 0
    p.set_load_signals(cascade_delay_beats=19.0)
    budget_below = p._compute_coherence_budget(global_coherence=0.9)
    # Just above threshold → cascade contributes _BUDGET_WEIGHTS["cascade"]=0.1
    p.set_load_signals(cascade_delay_beats=21.0)
    budget_above = p._compute_coherence_budget(global_coherence=0.9)
    # Budget should be lower above threshold (more load = less budget)
    assert budget_above < budget_below
    assert abs((budget_below - budget_above) - 0.1) < 1e-6
