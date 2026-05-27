"""axioma.schemas — typed state contracts (organ states + InternalState + ExternalState).

InternalState is substrate-private — never crosses the WS boundary.
ExternalState is the peer-visible projection — built ONLY by ComposeFunction.

The C12 ImportError test (Phase C) verifies that axioma.interface.* modules
cannot import InternalState, making the privacy structural.
"""
from __future__ import annotations

from .external_state import (
    ComposeCadence,
    ExternalDeltaPhi,
    ExternalState,
    FlowQuality,
    Zone,
)
from .external_state import PerturbationContext as ExternalPerturbationContext
from .internal_state import InternalState, PerturbationContext
from .organ_state import (
    ORGAN_ORDER,
    ORGAN_STATE_CLS,
    ORGAN_STATE_DIMS,
    TOTAL_STATE_DIMS,
    AnimaState,
    EidolonState,
    MnemeState,
    NousState,
    OrganState,
    PneumaState,
    organ_ranges,
    validate_state,
)

__all__ = [
    "ORGAN_ORDER",
    "ORGAN_STATE_CLS",
    "ORGAN_STATE_DIMS",
    "TOTAL_STATE_DIMS",
    "AnimaState",
    "ComposeCadence",
    "EidolonState",
    "ExternalDeltaPhi",
    "ExternalPerturbationContext",
    "ExternalState",
    "FlowQuality",
    "InternalState",
    "MnemeState",
    "NousState",
    "OrganState",
    "PerturbationContext",
    "PneumaState",
    "Zone",
    "organ_ranges",
    "validate_state",
]
