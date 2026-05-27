"""axioma.observability — logging, metrics, context, and engine base.

Public surface used by the rest of the codebase:

    from axioma.observability import (
        configure_logging, get_logger, bind_beat, unbind_beat,
        AxiomaContext,
        BEAT_DURATION_S, ENGINE_DURATION_S, measure_engine,
    )
"""
from __future__ import annotations

from .context import AxiomaContext, EventHandler
from .logging import bind_beat, configure_logging, get_logger, unbind_beat
from .metrics import (
    AOS_G_GAP,
    BEAT_DURATION_S,
    COHERENCE_BUDGET,
    DISK_BYTES_USED,
    DIVERGENCE_WARNINGS,
    ENGINE_DURATION_S,
    FRAGMENTATION_STAGE,
    HTTP_REQUESTS_TOTAL,
    META_COG_PERIOD_BEATS,
    PERSISTENCE_WRITE_LATENCY,
    PERSISTENCE_WRITES,
    PERTURBATIONS_TOTAL,
    PSI,
    RECOVERIES_TOTAL,
    RECOVERY_ACTIVE,
    RECOVERY_LEARNER_EXPLORATION_RATE,
    REGISTRY,
    REGISTRY_HEARTBEAT_FAILURES,
    REJECTION_RUN_WARNINGS,
    SUGGESTION_DECISIONS,
    THETA_LONG,
    THETA_SHORT,
    WS_CONNECTIONS_TOTAL,
    WS_DISCONNECTS_TOTAL,
    WS_MESSAGES_SENT_TOTAL,
    measure_engine,
)

__all__ = [
    "AOS_G_GAP",
    "BEAT_DURATION_S",
    "COHERENCE_BUDGET",
    "DISK_BYTES_USED",
    "DIVERGENCE_WARNINGS",
    "ENGINE_DURATION_S",
    "FRAGMENTATION_STAGE",
    "HTTP_REQUESTS_TOTAL",
    "META_COG_PERIOD_BEATS",
    "PERSISTENCE_WRITES",
    "PERSISTENCE_WRITE_LATENCY",
    "PERTURBATIONS_TOTAL",
    "PSI",
    "RECOVERIES_TOTAL",
    "RECOVERY_ACTIVE",
    "RECOVERY_LEARNER_EXPLORATION_RATE",
    "REGISTRY",
    "REGISTRY_HEARTBEAT_FAILURES",
    "REJECTION_RUN_WARNINGS",
    "SUGGESTION_DECISIONS",
    "THETA_LONG",
    "THETA_SHORT",
    "WS_CONNECTIONS_TOTAL",
    "WS_DISCONNECTS_TOTAL",
    "WS_MESSAGES_SENT_TOTAL",
    "AxiomaContext",
    "EventHandler",
    "bind_beat",
    "configure_logging",
    "get_logger",
    "measure_engine",
    "unbind_beat",
]
