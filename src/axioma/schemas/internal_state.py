"""InternalState — the substrate's private, typed snapshot.

Per ARCH_DESIGN_v1.0.md §5 (typed compose/send boundary).

InternalState is NEVER serialized across the WS boundary. The Phase C
ImportError test verifies that axioma.interface.* modules cannot import
InternalState. ExternalState (Phase C) is the only thing peers see.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .organ_state import (
    ORGAN_ORDER,
    AnimaState,
    EidolonState,
    MnemeState,
    NousState,
    OrganState,
    PneumaState,
)


@dataclass(slots=True)
class InternalState:
    """Substrate-private snapshot of all 5 organ states + bookkeeping.

    Held by the heartbeat in memory; passed to ComposeFunction at compose
    time; never crosses the WS boundary.
    """

    anima: AnimaState
    eidolon: EidolonState
    mneme: MnemeState
    nous: NousState
    pneuma: PneumaState
    beat_no: int
    timestamp: float

    @classmethod
    def initial(cls, beat_no: int = 0, timestamp: float = 0.0) -> InternalState:
        """Build an InternalState with default organ states."""
        return cls(
            anima=AnimaState(),
            eidolon=EidolonState(),
            mneme=MnemeState(),
            nous=NousState(),
            pneuma=PneumaState(),
            beat_no=beat_no,
            timestamp=timestamp,
        )

    def get_organ(self, name: str) -> OrganState:
        if name == "anima":
            return self.anima
        if name == "eidolon":
            return self.eidolon
        if name == "mneme":
            return self.mneme
        if name == "nous":
            return self.nous
        if name == "pneuma":
            return self.pneuma
        raise KeyError(f"unknown organ: {name}")

    def organ_dict(self) -> dict[str, OrganState]:
        return {
            "anima": self.anima,
            "eidolon": self.eidolon,
            "mneme": self.mneme,
            "nous": self.nous,
            "pneuma": self.pneuma,
        }

    def get_concatenated(self) -> np.ndarray:
        """Concatenated state vector for measurement (28-dim float32).

        Order: anima(4) + eidolon(6) + mneme(5) + nous(6) + pneuma(7).
        Integer fields cast to float.
        """
        return np.concatenate(
            [self.get_organ(o).to_array() for o in ORGAN_ORDER]
        ).astype(np.float32)


@dataclass(slots=True)
class PerturbationContext:
    """Optional context attached to InternalState during a perturbation window.

    Set by PerturbationScheduler when an event fires; consumed by DeltaPhiEngine
    to tag perturbation-relative measurements.
    """

    event_id: str
    kind: str
    target: str | None
    magnitude: float
    started_at_beat: int
    duration_beats: int
    tag: str | None = None
    extra: dict[str, object] = field(default_factory=dict)
