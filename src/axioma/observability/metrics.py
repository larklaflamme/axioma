"""Prometheus metrics registry.

Per IMPLEMENTATION_PLAN_v1.0.md §3.2.

Exposed at HTTP :8821/metrics (Phase D). Metrics are pull-based; nothing
pushes anywhere by default.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

# ── Per-beat timing ──────────────────────────────────────────────────────────

BEAT_DURATION_S = Histogram(
    "axioma_beat_duration_seconds",
    "Wall-clock time per heartbeat tick (10 Hz target = 0.1 s)",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.5, 1.0),
    registry=REGISTRY,
)

ENGINE_DURATION_S = Histogram(
    "axioma_engine_duration_seconds",
    "Per-engine compute time",
    ["engine"],
    buckets=(0.0001, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
    registry=REGISTRY,
)

# ── State gauges (current values; one per subsystem) ─────────────────────────

THETA_SHORT = Gauge("axioma_theta_short", "θ over short window (30 beats)", registry=REGISTRY)
THETA_LONG = Gauge("axioma_theta_long", "θ over long window (500 beats)", registry=REGISTRY)
AOS_G_GAP = Gauge("axioma_aos_g_gap", "Compose AOS-G gap", registry=REGISTRY)
PSI = Gauge("axioma_psi", "Boundary integrity field [0,1]", registry=REGISTRY)
COHERENCE_BUDGET = Gauge(
    "axioma_coherence_budget", "PNEUMA coherence budget [0,1]", registry=REGISTRY
)
FRAGMENTATION_STAGE = Gauge(
    "axioma_fragmentation_stage", "Current fragmentation stage (0-4)", registry=REGISTRY
)
RECOVERY_ACTIVE = Gauge(
    "axioma_recovery_active", "1 if in active recovery, else 0", registry=REGISTRY
)
META_COG_PERIOD_BEATS = Gauge(
    "axioma_meta_cognition_period_beats",
    "Current meta-cog cadence (100 default; raised on Q7 fallback)",
    registry=REGISTRY,
)
RECOVERY_LEARNER_EXPLORATION_RATE = Gauge(
    "axioma_recovery_learner_exploration_rate", "Current learner exploration rate", registry=REGISTRY
)

# ── Counters ─────────────────────────────────────────────────────────────────

PERTURBATIONS_TOTAL = Counter(
    "axioma_perturbations_total", "Perturbations injected", ["source", "kind"], registry=REGISTRY
)
RECOVERIES_TOTAL = Counter(
    "axioma_recoveries_total", "Recovery events", ["stage", "decision"], registry=REGISTRY
)
SUGGESTION_DECISIONS = Counter(
    "axioma_meta_suggestions_total",
    "Meta-cog suggestions handled",
    ["decision"],
    registry=REGISTRY,
)
DIVERGENCE_WARNINGS = Counter(
    "axioma_divergence_warnings_total",
    "F5 meta-cog divergence warnings emitted",
    registry=REGISTRY,
)
REJECTION_RUN_WARNINGS = Counter(
    "axioma_rejection_run_warnings_total",
    "Q1 recovery rejection-run warnings emitted",
    registry=REGISTRY,
)
PERSISTENCE_WRITES = Counter(
    "axioma_persistence_writes_total", "Snapshot/JSONL writes", ["target"], registry=REGISTRY
)
PERSISTENCE_WRITE_LATENCY = Histogram(
    "axioma_persistence_write_seconds",
    "Persistence write latency",
    ["target"],
    buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0),
    registry=REGISTRY,
)
DISK_BYTES_USED = Gauge(
    "axioma_disk_bytes_used", "Total disk bytes used by data/ subtree", registry=REGISTRY
)

# ── External interface (Phase D) ────────────────────────────────────────────

WS_CONNECTIONS_TOTAL = Counter(
    "axioma_ws_connections_total", "Inbound WebSocket connections opened", registry=REGISTRY
)
WS_DISCONNECTS_TOTAL = Counter(
    "axioma_ws_disconnects_total", "Inbound WebSocket connections closed", registry=REGISTRY
)
WS_MESSAGES_SENT_TOTAL = Counter(
    "axioma_ws_messages_sent_total", "Outbound WS messages sent across all subscribers", registry=REGISTRY
)
HTTP_REQUESTS_TOTAL = Counter(
    "axioma_http_requests_total", "HTTP API requests", ["method", "path", "status"], registry=REGISTRY
)
REGISTRY_HEARTBEAT_FAILURES = Counter(
    "axioma_registry_heartbeat_failures_total",
    "Registry heartbeat failures (degraded mode increments this)",
    registry=REGISTRY,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


@contextmanager
def measure_engine(name: str) -> Iterator[None]:
    """Wrap an engine's compute() call to record its duration.

    Usage:
        with measure_engine("theta_short"):
            self._compute()
    """
    with ENGINE_DURATION_S.labels(engine=name).time():
        yield
