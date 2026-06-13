"""axioma.measurement — read-only measurement engines (θ, raw MI, ΔΦ, …).

Per ARCH_DESIGN_v1.0.md §6. All engines:
  - inherit from MeasurementEngine (engine_base.py)
  - implement `should_run(beat_no, coherence_budget)` and `compute()`
  - read from `ctx.state_buffer` (InternalStateRingBuffer)
  - NEVER mutate substrate state

Phase B.1 (Session 3): theta_engine, raw_mi_engine, cascade_delay_engine
Phase B.2: delta_phi_engine, plasticity_tracker, aos_g_engine,
           fragmentation_monitor, perturbation_scheduler
Phase B.3: meta_cognition_loop, coherence_scheduler
"""
from __future__ import annotations

from .aos_g_engine import (
    AOSGEngine,
    AOSGReading,
    ComposeFunctionLike,
    IdentityCompose,
)
from .cascade_delay_engine import CascadeDelayEngine, CascadeDelayReading
from .delta_phi_engine import DeltaPhiEngine, DeltaPhiReading
from .engine_base import MeasurementEngine
from .fragmentation_monitor import (
    DEFAULT_THRESHOLDS as FRAGMENTATION_THRESHOLDS,
)
from .fragmentation_monitor import (
    FragmentationMonitor,
    FragmentationReading,
    FragmentationStageChange,
    RecoveryRequestPayload,
)
from .meta_cognition_loop import (
    BoundaryHealthTrend,
    IntegrationTrend,
    MetaCognition,
    MetaCognitionDivergenceWarning,
    MetaCognitionLoop,
    MetaCognitionSuggestion,
    ObserverMode,
    OverallAssessment,
    SuggestionTracker,
    SuggestionType,
)
from .perturbation_scheduler import (
    DEFAULT_BATTERY,
    PERTURBATION_SPECS,
    PerturbationEvent,
    PerturbationKind,
    PerturbationScheduler,
    PerturbationSpec,
    apply_perturbation,
)
from .plasticity_tracker import PlasticityReading, PlasticityTracker
from .raw_mi_engine import ORGAN_PAIRS, RawMIEngine, _pair_key
from .ring_buffer import InternalStateRingBuffer
from .theta_core import (
    SUMMARY_DIMS,
    SUMMARY_INDICES,
    TOTAL_SUMMARY_DIMS,
    compute_theta_from_summary,
    concat_summary_window,
    select_summary_columns,
)
from .curvature_engine import (
    CurvatureMeasurementEngine,
    CurvatureResult,
)
from .theta_engine import (
    BiasDiagnostic,
    ThetaLongEngine,
    ThetaResult,
    ThetaShortEngine,
    build_theta_engines,
)

__all__ = [
    "DEFAULT_BATTERY",
    "FRAGMENTATION_THRESHOLDS",
    "ORGAN_PAIRS",
    "PERTURBATION_SPECS",
    "SUMMARY_DIMS",
    "SUMMARY_INDICES",
    "TOTAL_SUMMARY_DIMS",
    "AOSGEngine",
    "AOSGReading",
    "BiasDiagnostic",
    "BoundaryHealthTrend",
    "CascadeDelayEngine",
    "CascadeDelayReading",
    "ComposeFunctionLike",
    "DeltaPhiEngine",
    "DeltaPhiReading",
    "FragmentationMonitor",
    "FragmentationReading",
    "FragmentationStageChange",
    "IdentityCompose",
    "IntegrationTrend",
    "InternalStateRingBuffer",
    "MeasurementEngine",
    "MetaCognition",
    "MetaCognitionDivergenceWarning",
    "MetaCognitionLoop",
    "MetaCognitionSuggestion",
    "ObserverMode",
    "OverallAssessment",
    "PerturbationEvent",
    "PerturbationKind",
    "PerturbationScheduler",
    "PerturbationSpec",
    "PlasticityReading",
    "PlasticityTracker",
    "RawMIEngine",
    "RecoveryRequestPayload",
    "SuggestionTracker",
    "SuggestionType",
    "CurvatureMeasurementEngine",
    "CurvatureResult",
    "ThetaLongEngine",
    "ThetaResult",
    "ThetaShortEngine",
    "_pair_key",
    "apply_perturbation",
    "build_theta_engines",
    "compute_theta_from_summary",
    "concat_summary_window",
    "select_summary_columns",
]
