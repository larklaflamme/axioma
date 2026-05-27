"""axioma.substrate — 5 peer organs + shared latent drive + plasticity.

Per ARCH_DESIGN_v1.0.md §4. Build order (used by SubstrateApp):
  1. SharedLatentDrive(drive_dim, n_iter, rho_g)
  2. {Anima, Eidolon, Mneme, Nous, Pneuma}(drive_dim, ...)  -- 5 peer organs
  3. PlasticityBuffer(organ_name, latent_dim) -- one per organ
  4. Each beat: drive.step(organs) -> [organ.render(plasticity.current_drift())
     for organ in organs]
"""
from __future__ import annotations

from .anima import Anima
from .app import SubstrateApp
from .base import Organ, make_random_projection
from .drive import SharedLatentDrive
from .eidolon import Eidolon
from .mneme import Mneme
from .nous import Nous
from .plasticity import PlasticityBuffer, PlasticitySummary
from .pneuma import Pneuma
from .recovery import (
    LearnerEfficacy,
    LearnerParams,
    RecoveryDecision,
    RecoveryEvent,
    RecoveryHistory,
    RecoveryLearner,
    RecoveryProtocol,
    RecoveryQuality,
    RecoveryRejectionRunWarning,
    RecoveryRequest,
    RecoveryState,
    RejectionEscalator,
)

__all__ = [
    "Anima",
    "Eidolon",
    "LearnerEfficacy",
    "LearnerParams",
    "Mneme",
    "Nous",
    "Organ",
    "PlasticityBuffer",
    "PlasticitySummary",
    "Pneuma",
    "RecoveryDecision",
    "RecoveryEvent",
    "RecoveryHistory",
    "RecoveryLearner",
    "RecoveryProtocol",
    "RecoveryQuality",
    "RecoveryRejectionRunWarning",
    "RecoveryRequest",
    "RecoveryState",
    "RejectionEscalator",
    "SharedLatentDrive",
    "SubstrateApp",
    "make_random_projection",
]
