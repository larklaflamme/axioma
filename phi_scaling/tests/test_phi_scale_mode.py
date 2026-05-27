import numpy as np
import pytest

from control_experiments.modes import build_mode
from control_experiments.trial import ControlTrialConfig, run_control_trial
from organ.schemas import ORGAN_DIMS, ORGAN_ORDER


def _organ_slice(name):
    start = 0
    for o in ORGAN_ORDER:
        if o == name:
            return slice(start, start + ORGAN_DIMS[o])
        start += ORGAN_DIMS[o]
    raise KeyError(name)


@pytest.mark.parametrize("k", [1, 2, 3, 4, 5])
def test_disabled_organs_have_zero_variance_after_freeze(k):
    cfg = ControlTrialConfig(
        mode="phi_scale", perturbation_type="baseline", magnitude=1.0,
        seed=42, n_beats=300, mode_kwargs={"organ_count": k},
    )
    result = run_control_trial(cfg)
    from control_experiments.modes.phi_scale import DISABLED_ORGANS
    for name in DISABLED_ORGANS[k]:
        sl = _organ_slice(name)
        # After the freeze beat (100) + a few beats of compose stabilization, the
        # internal trajectory for this organ should be constant ACROSS TIME.
        # (per-column variance, not across all flat values).
        segment = result.internal_trajectory[120:300, sl]
        col_var = np.var(segment, axis=0).max()
        assert col_var < 1e-6, (
            f"k={k}, organ={name}: per-column variance {col_var:.2e} not ≈ 0"
        )


def test_k5_no_organ_frozen():
    cfg = ControlTrialConfig(
        mode="phi_scale", perturbation_type="baseline", magnitude=1.0,
        seed=42, n_beats=300, mode_kwargs={"organ_count": 5},
    )
    result = run_control_trial(cfg)
    for name in ORGAN_ORDER:
        sl = _organ_slice(name)
        # Some columns may be quasi-constant (e.g. PNEUMA.buffer_depth=0) but at
        # least one column should vary across time.
        col_var = float(np.var(result.internal_trajectory[120:, sl], axis=0).max())
        assert col_var > 1e-6, f"k=5 organ {name} max-col variance {col_var} unexpectedly small"


def test_factory_kwargs():
    """build_mode accepts organ_count kwarg."""
    mode = build_mode("phi_scale", organ_count=3)
    assert mode.organ_count == 3
    assert "eidolon" not in mode._disabled
    assert "mneme" in mode._disabled


def test_pneuma_always_active():
    """PNEUMA should never be in the disabled set."""
    from control_experiments.modes.phi_scale import DISABLED_ORGANS
    for k, disabled in DISABLED_ORGANS.items():
        assert "pneuma" not in disabled, f"PNEUMA disabled at k={k}"
