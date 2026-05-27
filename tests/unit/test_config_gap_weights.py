"""v1.2-prep — `ComposeConfig.aos_g_gap_weights` deployment override."""
from __future__ import annotations

import pytest

from axioma.config import AxiomaConfig, ComposeConfig
from axioma.measurement.aos_g_engine import (
    EIDOLON_WEIGHTED_GAP_WEIGHTS,
    PNEUMA_WEIGHTED_GAP_WEIGHTS,
    UNIFORM_GAP_WEIGHTS,
)


def test_default_gap_weights_is_pneuma_weighted_v1_3() -> None:
    """v1.3 default-flip per Checkpoint P: ships with PNEUMA-weighted defaults.

    The empirical justification (Checkpoint L) is +81% recovery-learner adoptions
    across 3 seeds × 50K beats, ALL V11/V13 ship-gates PASS. v1.0/v1.1 operators
    wanting uniform behavior load configs/v1_0_backwards_compat.yaml."""
    cfg = ComposeConfig()
    assert cfg.aos_g_gap_weights == PNEUMA_WEIGHTED_GAP_WEIGHTS


def test_axioma_config_inherits_compose_default() -> None:
    cfg = AxiomaConfig()
    assert cfg.compose.aos_g_gap_weights == PNEUMA_WEIGHTED_GAP_WEIGHTS


def test_default_alert_threshold_is_recalibrated_for_pneuma() -> None:
    """v1.3 default-flip: aos_g_alert_threshold scales to match the PNEUMA-weighted
    gap baseline (1.52× larger than uniform). Threshold 0.152 preserves the same
    'fire when gap < 1.4% of typical magnitude' sensitivity as v1.0's 0.10."""
    cfg = ComposeConfig()
    assert cfg.aos_g_alert_threshold == 0.152


def test_pneuma_weighted_preset_assignable_to_config() -> None:
    cfg = ComposeConfig(aos_g_gap_weights=PNEUMA_WEIGHTED_GAP_WEIGHTS)
    assert cfg.aos_g_gap_weights == PNEUMA_WEIGHTED_GAP_WEIGHTS
    # The preset itself follows the documented PNEUMA-weighted shape
    assert cfg.aos_g_gap_weights["pneuma"] == 2.5
    assert cfg.aos_g_gap_weights["eidolon"] == 0.75


def test_eidolon_weighted_preset_assignable_to_config() -> None:
    cfg = ComposeConfig(aos_g_gap_weights=EIDOLON_WEIGHTED_GAP_WEIGHTS)
    assert cfg.aos_g_gap_weights["eidolon"] == 2.5
    assert cfg.aos_g_gap_weights["pneuma"] == 0.5


def test_arbitrary_custom_weights_assignable() -> None:
    custom = {"anima": 0.1, "eidolon": 5.0, "mneme": 1.0, "nous": 1.0, "pneuma": 0.1}
    cfg = ComposeConfig(aos_g_gap_weights=custom)
    assert cfg.aos_g_gap_weights == custom


def test_compose_config_frozen_after_construction() -> None:
    cfg = ComposeConfig()
    # frozen=True invariant per ComposeConfig model_config
    with pytest.raises(Exception):  # pydantic ValidationError
        cfg.aos_g_gap_weights = PNEUMA_WEIGHTED_GAP_WEIGHTS  # type: ignore[misc]


def test_harness_resolution_uses_config_when_unspecified() -> None:
    """When build_phase_e_stack is called without an explicit gap_weights param,
    the stack's AOSGEngine should pick up cfg.compose.aos_g_gap_weights."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from integration.phase_e_harness import build_phase_e_stack

    cfg = AxiomaConfig()
    object.__setattr__(
        cfg.compose, "aos_g_gap_weights", PNEUMA_WEIGHTED_GAP_WEIGHTS,
    )
    stack = build_phase_e_stack(cfg=cfg, n_permutations=3)
    assert stack.aos_g.gap_weights == PNEUMA_WEIGHTED_GAP_WEIGHTS


def test_harness_explicit_param_overrides_config() -> None:
    """Explicit gap_weights argument wins over config."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from integration.phase_e_harness import build_phase_e_stack

    cfg = AxiomaConfig()
    object.__setattr__(
        cfg.compose, "aos_g_gap_weights", PNEUMA_WEIGHTED_GAP_WEIGHTS,
    )
    # explicit eidolon override should win
    stack = build_phase_e_stack(
        cfg=cfg, gap_weights=EIDOLON_WEIGHTED_GAP_WEIGHTS, n_permutations=3,
    )
    assert stack.aos_g.gap_weights == EIDOLON_WEIGHTED_GAP_WEIGHTS


def test_harness_default_config_uses_pneuma_weighted_v1_3() -> None:
    """v1.3 default-flip (Checkpoint P): default config now ships PNEUMA-weighted.

    v1.0/v1.1/v1.2 operators that relied on this defaulting to uniform must
    explicitly opt back via configs/v1_0_backwards_compat.yaml."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from integration.phase_e_harness import build_phase_e_stack

    stack = build_phase_e_stack(n_permutations=3)
    assert stack.aos_g.gap_weights == PNEUMA_WEIGHTED_GAP_WEIGHTS


def test_explicit_uniform_override_still_works() -> None:
    """Operators can still explicitly use uniform if they want v1.0 behavior."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from integration.phase_e_harness import build_phase_e_stack

    stack = build_phase_e_stack(gap_weights=UNIFORM_GAP_WEIGHTS, n_permutations=3)
    assert stack.aos_g.gap_weights == UNIFORM_GAP_WEIGHTS
