"""ExternalState schema — round-trip + serialization."""
from __future__ import annotations

import numpy as np
import pytest

from axioma.schemas import (
    ORGAN_ORDER,
    ORGAN_STATE_DIMS,
    ComposeCadence,
    ExternalDeltaPhi,
    ExternalState,
    FlowQuality,
    InternalState,
    Zone,
)
from axioma.schemas.external_state import PerturbationContext as ExtPert


def _make_external(beat_no: int = 1, timestamp: float = 0.1) -> ExternalState:
    return ExternalState(
        anima=np.zeros(ORGAN_STATE_DIMS["anima"], dtype=np.float32),
        eidolon=np.zeros(ORGAN_STATE_DIMS["eidolon"], dtype=np.float32),
        mneme=np.zeros(ORGAN_STATE_DIMS["mneme"], dtype=np.float32),
        nous=np.zeros(ORGAN_STATE_DIMS["nous"], dtype=np.float32),
        pneuma=np.zeros(ORGAN_STATE_DIMS["pneuma"], dtype=np.float32),
        beat_no=beat_no,
        timestamp=timestamp,
    )


def test_external_state_defaults() -> None:
    ext = _make_external()
    assert ext.beat_no == 1
    assert ext.theta_short == 0.0
    assert ext.zone == Zone.IDLE
    assert ext.cadence == ComposeCadence.BASELINE
    assert ext.flow_quality is None


def test_get_organ_array() -> None:
    ext = _make_external()
    for name in ORGAN_ORDER:
        arr = ext.get_organ_array(name)
        assert arr.shape == (ORGAN_STATE_DIMS[name],)


def test_get_organ_array_unknown_raises() -> None:
    ext = _make_external()
    with pytest.raises(KeyError):
        ext.get_organ_array("nope")


def test_get_concatenated_dims() -> None:
    """28-dim concatenated state matches InternalState's shape."""
    ext = _make_external()
    arr = ext.get_concatenated()
    assert arr.shape == (28,)
    assert arr.dtype.name == "float32"


def test_concatenated_matches_internal_shape() -> None:
    """ExternalState.get_concatenated() and InternalState.get_concatenated()
    produce arrays of the same shape (the privacy is on the *type*, not
    the dimensionality)."""
    ext = _make_external()
    internal = InternalState.initial(beat_no=1, timestamp=0.1)
    assert ext.get_concatenated().shape == internal.get_concatenated().shape


def test_to_dict_serializable() -> None:
    """to_dict produces a JSON-serializable representation."""
    import json
    ext = _make_external()
    ext.theta_short = 1.2
    ext.psi = 0.85
    ext.fragmentation_stage = 2
    ext.fidelity_factors = {"anima": 0.5}
    ext.flow_quality = FlowQuality(effortlessness=0.8, absorption=0.7, time_distortion=0.6)
    d = ext.to_dict()
    # Should be JSON-serializable
    s = json.dumps(d)
    assert s
    # Spot-check fields
    assert d["theta_short"] == 1.2
    assert d["psi"] == 0.85
    assert d["fragmentation_stage"] == 2
    assert d["zone"] == "idle"
    assert d["cadence"] == "baseline"
    assert d["flow_quality"]["effortlessness"] == 0.8


def test_to_dict_optional_fields_none() -> None:
    ext = _make_external()
    d = ext.to_dict()
    assert d["flow_quality"] is None
    assert d["perturbation_context"] is None


def test_to_dict_with_perturbation_context() -> None:
    ext = _make_external()
    ext.perturbation_context = ExtPert(
        event_id="evt1", kind="contradiction", target="eidolon",
        magnitude=0.3, started_at_beat=100, duration_beats=1,
    )
    d = ext.to_dict()
    assert d["perturbation_context"]["event_id"] == "evt1"
    assert d["perturbation_context"]["kind"] == "contradiction"


def test_delta_phi_subfields() -> None:
    ext = _make_external()
    ext.delta_phi = ExternalDeltaPhi(
        s1_peak_delta_theta=0.5, s2_recovery_beats=10.0,
        s3_context_variance=0.04, cascade_delay_beats=7.0,
        event_kind="step", in_perturbation_window=True,
    )
    d = ext.to_dict()
    assert d["delta_phi"]["S1"] == 0.5
    assert d["delta_phi"]["S2"] == 10.0
    assert d["delta_phi"]["S3"] == 0.04
    assert d["delta_phi"]["cascade_delay"] == 7.0
    assert d["delta_phi"]["in_window"] is True
