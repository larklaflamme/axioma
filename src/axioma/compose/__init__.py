"""axioma.compose — typed compose/send boundary.

Per ARCH_DESIGN_v1.0.md §5. ComposeFunction is the ONLY producer of
ExternalState. The Phase C ImportError test (C12) verifies that
axioma.interface.* modules cannot import InternalState — privacy is
structural.

Components:
  - ComposeFunction (function.py)        : InternalState × θ × eidolon_coh → ExternalState
  - CadenceController (cadence.py)       : adaptive 5/30/60-beat schedule (D2)
  - compute_flow_quality (flow_quality.py): D15/E12 closed-form
  - classify_zone (zone.py)              : θ/ΔΦ/cascade → Zone enum
"""
from __future__ import annotations

from .cadence import CadenceController
from .flow_quality import compute_flow_quality
from .function import DEFAULT_WEIGHTS, ComposeFunction
from .zone import DEFAULT_THRESHOLDS as ZONE_THRESHOLDS
from .zone import classify_zone

__all__ = [
    "DEFAULT_WEIGHTS",
    "ZONE_THRESHOLDS",
    "CadenceController",
    "ComposeFunction",
    "classify_zone",
    "compute_flow_quality",
]
