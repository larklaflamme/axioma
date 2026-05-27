"""AxiomaConfig — pydantic config tree (single source of truth).

Per IMPLEMENTATION_PLAN_v1.0.md §12.

Loaded via axioma.config.loader.load_config(). Layered:
  1. configs/default.yaml (committed)
  2. configs/local.yaml (gitignored)
  3. AXIOMA_CONFIG=<path> env var
  4. AXIOMA_* env var overrides (per-field)

Config is FROZEN after load. Mutation requires the admin API.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

# ── Substrate ────────────────────────────────────────────────────────────────


class OrganSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    latent_dim: int = Field(gt=0)
    state_dim: int = Field(gt=0)
    rho: float = Field(ge=0.0, le=1.0)
    v_scale: float = Field(gt=0.0)


class SubstrateConfig(BaseModel):
    """Per ARCH_DESIGN_v1.0.md §4."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    n_iter: int = 3
    rho_g: float = 0.90
    drive_dim: int = 16  # L = dimension of shared latent drive g

    # Default per-organ specs from ARCH §4.3 + v1.0 deltas (EIDOLON ρ=0.92 V_E=1.3,
    # MNEME α_M=1.4, PNEUMA state_dim 7 for coherence_budget)
    organ_specs: dict[str, OrganSpec] = Field(
        default_factory=lambda: {
            "anima": OrganSpec(latent_dim=8, state_dim=4, rho=0.85, v_scale=1.0),
            "eidolon": OrganSpec(latent_dim=12, state_dim=6, rho=0.92, v_scale=1.3),
            "mneme": OrganSpec(latent_dim=12, state_dim=5, rho=0.88, v_scale=1.4),
            "nous": OrganSpec(latent_dim=10, state_dim=6, rho=0.90, v_scale=1.0),
            "pneuma": OrganSpec(latent_dim=12, state_dim=7, rho=0.92, v_scale=1.0),
        }
    )

    # v1.7 default-flip (Checkpoint MM): both MNEME compensations now default
    # ON. Empirical justification: 3 seeds × 50K beats sweep (Checkpoint LL)
    # showed substrate stabilization with quality jumps of +0.30 / +0.36 on
    # 2 of 3 seeds and fragmentation reduction of 92% / 96%. All 6 decision
    # criteria pass under the refined quality-conditional learner-productivity
    # rule (Δ adoptions ≥ 0 OR Δ quality ≥ 0.10 per seed), which backwards-
    # validates against v1.5's BB sweep.
    #
    # v1.6 operators wanting to restore the v1.6 substrate behavior (both
    # compensations OFF) should load configs/v1_6_backwards_compat.yaml.
    mneme_compensation_2_enabled: bool = True
    mneme_compensation_3_enabled: bool = True
    plasticity_pathway_2_enabled: bool = False
    seed: int | None = None


# ── Measurement ──────────────────────────────────────────────────────────────


class MeasurementConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    theta_short_window: int = 30
    theta_long_window: int = 500
    raw_mi_short_window: int = 5
    raw_mi_long_window: int = 20
    delta_phi_window: int = 50
    plasticity_period: int = 100
    fragmentation_check_period: int = 10
    meta_cognition_period: int = 100
    meta_cognition_trajectory_window: int = 1000  # E5
    theta_long_cadence: int = 10
    perturbation_default_magnitude: float = 0.3
    n_permutations: int = 100
    significance_threshold: float = 0.05


# ── Compose ──────────────────────────────────────────────────────────────────


class ComposeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    baseline_period_beats: int = 30
    perturbation_period_beats: int = 5
    recovery_period_beats: int = 60
    perturbation_window_beats: int = 50
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "anima": 1.0,
            "eidolon": 1.0,
            "mneme": 1.0,
            "nous": 1.0,
            "pneuma": 1.0,
        }
    )
    noise_factor: float = 0.05

    # v1.3 default-flip: aos_g_alert_threshold recalibrated for PNEUMA-weighted
    # gap baseline (1.52× larger than uniform). v1.0/v1.1 operators wanting the
    # uniform regime should also set aos_g_alert_threshold = 0.10 or load
    # configs/v1_0_backwards_compat.yaml.
    aos_g_alert_threshold: float = 0.152
    psi_alert_threshold: float = 0.3

    # v1.3 default-flip: PNEUMA-weighted AOS-G is now the default per
    # Checkpoint L's empirical finding (+81% recovery-learner adoptions
    # across 3 seeds × 50K beats, ALL V11/V13 ship-gates PASS).
    #
    # Operators wanting v1.0 uniform behavior:
    #   AXIOMA_CONFIG=configs/v1_0_backwards_compat.yaml python -m axioma
    #
    # Or programmatically:
    #   from axioma.measurement.aos_g_engine import UNIFORM_GAP_WEIGHTS
    #   object.__setattr__(cfg.compose, "aos_g_gap_weights", UNIFORM_GAP_WEIGHTS)
    #
    # Presets in axioma.measurement.aos_g_engine:
    #   UNIFORM_GAP_WEIGHTS          (= v1.0 plain L2; explicit opt-in for v1.3+)
    #   EIDOLON_WEIGHTED_GAP_WEIGHTS (biases gap toward EIDOLON contributions)
    #   PNEUMA_WEIGHTED_GAP_WEIGHTS  (v1.3 default; biases gap toward PNEUMA)
    aos_g_gap_weights: dict[str, float] | None = Field(
        default_factory=lambda: {
            "anima": 0.5,
            "eidolon": 0.75,
            "mneme": 0.75,
            "nous": 0.5,
            "pneuma": 2.5,
        }
    )

    # v1.4.2 — auto-tuned aos_g_alert_threshold.
    #
    # When enabled, AOSGEngine measures the observed gap distribution during
    # the warmup window (auto_tune_warmup_beats), then sets aos_g_alert_threshold
    # to `auto_tune_threshold_ratio × mean(observed_gap)`. Re-tunes every
    # `auto_tune_recompute_period_beats` beats so the threshold tracks drift.
    #
    # The static `aos_g_alert_threshold` above becomes the initial value used
    # before warmup completes. After auto-tune fires, that value is overridden.
    #
    # Operators on bespoke gap_weights (not uniform / not PNEUMA-weighted)
    # benefit most from this — no need to manually run alert_threshold_calibration.py.
    # v1.5 default-flip (Checkpoint Y): auto-tune now defaults ON. Combined
    # with the per-organ normalize default-flip below, this gives v1.5
    # deployments a self-calibrating alert surface that tracks substrate
    # drift without manual threshold tuning. v1.4 operators wanting to keep
    # static thresholds should load configs/v1_4_backwards_compat.yaml.
    aos_g_alert_threshold_auto_tune: bool = True
    aos_g_alert_threshold_auto_tune_ratio: float = 0.014  # 1.4% of typical magnitude
    # v1.4.4: bumped 600 → 3000 to coordinate with v1.4.1 normalization warmup
    # (default normalize_min_samples=60 × AOSGEngine.natural_period_beats=30 =
    # 1800 beats before normalization fully activates; 3000 adds ~67% safety
    # margin so the first auto-tune fires against a fully-normalized gap
    # distribution). Per Checkpoint W's empirical finding: at 600 beats the
    # first set landed at ~2× the converged value because normalization was
    # still in unnormalized fallback for most of the warmup window.
    # For operators NOT using normalize_per_organ, this means auto-tune fires
    # 2400 beats later (~4 min @ 10 Hz) — well within V12's cold-start envelope
    # and safer (longer baseline observation before threshold is committed).
    aos_g_alert_threshold_auto_tune_warmup_beats: int = 3000
    aos_g_alert_threshold_auto_tune_recompute_period_beats: int = 36000  # ~1h @ 10 Hz

    # v1.4.3 — per-component ψ alert thresholds. When None (default),
    # AOSGEngine uses the single `psi_alert_threshold` above for all components
    # (v1.0/v1.1/v1.2/v1.3 backwards-compat behavior). When set, alert fires
    # if ANY component drops below its own threshold. Lets operators tune
    # sensitivity per sub-signal:
    #   gap_variance_health: catches compose degeneration (looseable; varies
    #     naturally with substrate dynamics)
    #   structural_health:   catches architectural integrity violations
    #     (should be near 1.0 always; tight threshold catches regressions early)
    #   compose_probe_health: periodic probe vs current compose
    #     (mid-sensitivity; intermittent fires are expected during recovery)
    #
    # Missing keys fall back to `psi_alert_threshold`.
    psi_per_component_thresholds: dict[str, float] | None = None

    # v1.4.1 — opt-in per-organ gap normalization.
    #
    # Per Checkpoint I's measurement: under raw L2, per-organ gap is dominated
    # by the organs with the largest natural state magnitudes (PNEUMA ≈ 7.26,
    # ANIMA ≈ 0.036 — a 130× ratio). Weighting alone cannot rebalance this
    # because raw magnitudes overwhelm the multiplier (PNEUMA at weight 1.0
    # still contributes 97-99% of the gap signal).
    #
    # Normalization fixes this WITHOUT touching substrate dynamics: each organ's
    # gap is divided by its rolling-mean gap before the weighted sum. After
    # warmup, every organ contributes equally on its own scale; weights then
    # control the architectural bias cleanly.
    #
    # Math:
    #   raw_organ_gap_i = ||internal_i − external_i||
    #   scale_i         = rolling_mean(raw_organ_gap_i, window)
    #   normalized_i    = raw_organ_gap_i / scale_i
    #   gap = sqrt(Σ_organ w_organ × normalized_i²)
    #
    # During warmup (< min_samples observations) scale_i = 1.0, so behavior
    # exactly matches unnormalized (v1.0..v1.4.0).
    #
    # v1.5 default-flip (Checkpoint Y): per-organ normalization now defaults
    # ON. Empirical sweep (3 seeds × 50K beats × {off, on} with auto-tune on
    # in both branches) showed: V11/V13 6/6 PASS, recovery quality stable,
    # auto-tune converges (cross-seed CV=3.2% on the converged threshold;
    # first_set within 1.07-1.31× of converged). v1.4 operators wanting
    # unnormalized weighted L2 should load configs/v1_4_backwards_compat.yaml.
    aos_g_normalize_per_organ: bool = True
    aos_g_normalize_per_organ_window_beats: int = 600
    aos_g_normalize_per_organ_min_samples: int = 60


# ── Recovery + learner ───────────────────────────────────────────────────────


class RecoveryConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    min_recovery_stage: int = 2
    default_duration_beats: int = 100
    restore_beats: int = 20
    min_budget_to_accept: float = 0.20  # Q3 P3

    # Default action parameters (tuned by learner)
    coupling_reduction_factor: float = 0.8
    mneme_forgetting_boost: float = 1.5
    recovery_compose_period_beats: int = 60

    # Learner
    learner_exploration_rate: float = 0.15
    learner_adoption_threshold: float = 0.05
    learner_regression_threshold: float = 0.10
    learner_min_events_for_adoption: int = 20  # F2
    learner_monitoring_extension_events: int = 60  # F2
    learner_baseline_refresh_period_events: int = 10  # F2
    learner_clean_baseline_events: int = 100  # F2 post-INEFFECTIVE clean-baseline window

    # F4 pre-training
    pretrain_target_events: int = 50
    require_pretrain: bool = True

    # Q1 rejection escalation
    rejection_escalation_consecutive: int = 3
    rejection_warning_cooldown_beats: int = 600

    # P8 oscillation
    feedback_oscillation_period_threshold_beats: int = 100

    # Phase E durability finalization watchdog
    durability_watchdog_beats: int = 3000


# ── Meta-cognition ───────────────────────────────────────────────────────────


class MetaCognitionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool = True  # Q8 scope reduction toggle
    observer_mode: Literal["observer_only", "embedded"] = "observer_only"  # F7
    suggestion_confidence_threshold: float = 0.7
    divergence_warning_threshold: int = 5  # F5

    # Q7 auto-fallback
    budget_seconds: float = 0.010
    budget_overrun_consecutive_cycles: int = 3
    fallback_period_beats: int = 200
    fallback_simplified: bool = False  # auto-set

    # F8 calibration thresholds
    calibration_pass_accuracy: float = 0.80
    calibration_pass_acceptance_rate: float = 0.30
    calibration_pass_max_theta_drop: float = 0.05


# ── Coherence scheduler ──────────────────────────────────────────────────────


class CoherenceSchedulerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    throttle_high_threshold: float = 0.15
    throttle_medium_threshold: float = 0.30
    throttle_low_threshold: float = 0.50

    # E13 effectiveness
    effectiveness_window_beats: int = 50
    effectiveness_min_threshold: float = 0.1
    escalation_consecutive_windows: int = 3

    # Q4 parallelization (steps 6-7)
    overload_fallback_window_beats: int = 3000
    overload_fallback_threshold_seconds: float = 0.100


# ── Runtime (heartbeat + tick parallelization) ───────────────────────────────


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    heartbeat_hz: int = 10
    warmup_beats: int = 100  # cold start window per §5.4
    parallel_steps_6_7_threshold_seconds: float = 0.080  # Q4 trigger
    parallel_steps_6_7_disable_threshold_seconds: float = 0.060  # Q4 re-disable


# ── Persistence ──────────────────────────────────────────────────────────────


class PersistenceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot_period_beats: int = 600
    snapshot_root: str = "data/state"
    jsonl_root: str = "data/jsonl"
    sqlite_path: str = "data/state/axioma.sqlite"


class RetentionConfig(BaseModel):
    """V2 data retention policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    jsonl_retention_days: int = 7
    sqlite_aggregated_retention_days: int = 30
    snapshot_rolling_count: int = 24
    snapshot_daily_retention_days: int = 30
    daily_snapshot_local_time: str = "02:30"
    enforce_retention_period_hours: int = 24


# ── Observability ────────────────────────────────────────────────────────────


class ObservabilityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True
    metrics_enabled: bool = True


# ── External interface ──────────────────────────────────────────────────────


class InterfaceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ws_host: str = "127.0.0.1"
    ws_port: int = 8820
    http_host: str = "127.0.0.1"
    http_port: int = 8821
    registry_url: str = "http://localhost:8810/registry"  # Q1 still placeholder
    registry_retry_max_seconds: int = 300
    admin_api_key: SecretStr | None = None

    # V1 error handling
    ws_rate_limit_msgs_per_second: int = 100
    ws_rate_limit_consecutive_strikes: int = 3
    http_default_retry_after_seconds: int = 5

    # Peer-conversation multi-peer mode (v1.9.0 — Checkpoint SS)
    # "shared": one history across all peers; outbound replies are un-addressed
    # (v1.0-v1.8 behavior). "per_peer": per-speaker history dict; outbound
    # metadata always includes `to_speaker`. v1.9.1 (TT) will add server-side
    # filtering so subscribers can opt to receive only addressed replies.
    peer_conversation_multi_peer_mode: Literal["shared", "per_peer"] = "shared"


# ── Infra adapters (Ollama / Qdrant / Redis / GPU) ──────────────────────────


class OllamaConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    url: str = "http://localhost:11434"
    chat_model: str = "deepseek-v4-flash:cloud"
    embed_model: str = "nomic-embed-text-v2-moe"
    embed_dim: int = 768
    timeout_seconds: int = 600
    connect_timeout_seconds: int = 10
    retries: int = 1
    temperature: float = 0.4
    max_tokens: int = -1


class QdrantConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    url: str = "http://localhost:6333"
    api_key: SecretStr | None = None
    timeout_seconds: int = 30
    # Per-collection namespace prefix (avoids collision with the 10 existing collections)
    collection_prefix: str = "axioma_"


class RedisConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    url: str = "redis://localhost:6379"
    key_prefix: str = "axioma:"
    socket_timeout_seconds: int = 5


class GPUConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    prefer_device: Literal["cuda", "cpu"] = "cuda"
    require_cuda: bool = False  # if True, raise on CUDA missing


class InfraConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ollama: OllamaConfig = OllamaConfig()
    qdrant: QdrantConfig = QdrantConfig()
    redis: RedisConfig = RedisConfig()
    gpu: GPUConfig = GPUConfig()


# ── Release (scope reduction per Q8) ─────────────────────────────────────────


class ReleaseConfig(BaseModel):
    """Q8 scope reduction flags for the v1.0.1 fallback."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    recovery_learner_enabled: bool = True
    coherence_scheduler_full_features: bool = True


# ── Root ─────────────────────────────────────────────────────────────────────


class AxiomaConfig(BaseModel):
    """Top-level config. Frozen after load."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    substrate: SubstrateConfig = SubstrateConfig()
    measurement: MeasurementConfig = MeasurementConfig()
    compose: ComposeConfig = ComposeConfig()
    recovery: RecoveryConfig = RecoveryConfig()
    meta_cognition: MetaCognitionConfig = MetaCognitionConfig()
    coherence_scheduler: CoherenceSchedulerConfig = CoherenceSchedulerConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    persistence: PersistenceConfig = PersistenceConfig()
    retention: RetentionConfig = RetentionConfig()
    observability: ObservabilityConfig = ObservabilityConfig()
    interface: InterfaceConfig = InterfaceConfig()
    infra: InfraConfig = InfraConfig()
    release: ReleaseConfig = ReleaseConfig()
