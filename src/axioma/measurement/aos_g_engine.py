"""AOS-G + ψ engine — boundary-integrity measurement.

Per ARCH_DESIGN_v1.0.md §5.3, §5.4 + IMPLEMENTATION_PLAN_v1.0.md §6.1 step 6.

AOS-G (Apparent vs Observed State Gap):
  gap = ||concatenated(internal) − concatenated(external)|| (Euclidean)

ψ (boundary-integrity field) = min(gap_variance_health, structural_health, compose_probe_health)

Three sub-signals:
  - gap_variance_health (E3 recovery-aware): variance of gap over recent window;
    blends two targets (baseline vs recovery) by RecoveryProtocol state.
  - structural_health (E1 continuous + debounced): 5-check sliding window of
    "InternalState not importable from interface modules". Single transient
    failure → score 0.8 (debounce floor); 2+ consecutive failures escalate.
  - compose_probe_health (E4 recovery-aware): every 100 beats, run a probe
    InternalState through compose; compare against expected. SKIPPED during
    Stage-4 emergency recovery.

Phase B.3 implementation note: ComposeFunction is Phase C. For B.3, the engine
accepts an `IdentityCompose` stub that returns InternalState verbatim — gap
stays at 0 and ψ stays at 1.0. The engine's structure is in place; Phase C
plugs in the real compose and ψ becomes meaningful.

Subscribes to:
  - `recovery_state_change` event (E3 blend_factor + E4 skip-on-Stage-4)
"""
from __future__ import annotations

import importlib
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from ..observability import AOS_G_GAP, PSI, get_logger
from ..observability.context import AxiomaContext
from ..persistence.snapshot import Stateful  # noqa: F401
from ..schemas import ORGAN_ORDER, InternalState
from .engine_base import MeasurementEngine

log = get_logger(__name__)


# ── v1.1.6: AOS-G weighting presets (Weighted Euclidean) ────────────────────

#: Uniform weighting — equivalent to v1.0 plain L2 (each organ contributes equally).
UNIFORM_GAP_WEIGHTS: dict[str, float] = {name: 1.0 for name in ORGAN_ORDER}

#: EIDOLON-weighted — biases gap toward EIDOLON contributions. EIDOLON drives
#: the substrate's identity layer (ρ=0.92, V_E=1.3 per ARCH §4.1); weighting
#: it more highly makes ψ alert earlier when EIDOLON drifts vs other organs.
EIDOLON_WEIGHTED_GAP_WEIGHTS: dict[str, float] = {
    "anima": 0.5, "eidolon": 2.5, "mneme": 0.75, "nous": 0.75, "pneuma": 0.5,
}

#: PNEUMA-weighted — biases gap toward PNEUMA contributions. PNEUMA carries
#: coherence_budget (the substrate's "presence" signal); weighting it makes
#: ψ track substrate stress more closely.
PNEUMA_WEIGHTED_GAP_WEIGHTS: dict[str, float] = {
    "anima": 0.5, "eidolon": 0.75, "mneme": 0.75, "nous": 0.5, "pneuma": 2.5,
}


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Validate + complete a weights dict; missing organs default to 1.0.

    Raises on negative weights (would invert the metric)."""
    out: dict[str, float] = {}
    for name in ORGAN_ORDER:
        w = float(weights.get(name, 1.0))
        if w < 0:
            raise ValueError(f"gap weight for {name} must be non-negative, got {w}")
        out[name] = w
    return out


def _resolve_per_component_thresholds(
    per_component: dict[str, float] | None,
    fallback: float,
) -> dict[str, float]:
    """v1.4.3 — resolve per-component ψ thresholds; fill missing keys with fallback.

    Returns a dict with all three component keys populated. When `per_component`
    is None, all three get the fallback value (v1.0..v1.3 default behavior)."""
    keys = ("gap_variance_health", "structural_health", "compose_probe_health")
    out: dict[str, float] = {k: float(fallback) for k in keys}
    if per_component:
        for k in keys:
            if k in per_component:
                v = float(per_component[k])
                if v < 0 or v > 1:
                    raise ValueError(
                        f"per-component psi threshold for {k} must be in [0,1], got {v}"
                    )
                out[k] = v
    return out


def recommended_alert_threshold(
    weights: dict[str, float] | None,
    *,
    baseline_threshold: float = 0.10,
    baseline_gap_mean: float = 7.17,
    variant_gap_mean: float | None = None,
) -> float:
    """v1.2.2 — return the recalibrated aos_g_alert_threshold for a weighted preset.

    The v1.0 default `aos_g_alert_threshold = 0.10` is calibrated against
    uniform preset's gap distribution (mean ≈ 7.17 per Checkpoint J). Under a
    non-uniform preset the gap baseline shifts; this helper preserves
    architectural-equivalent sensitivity (same threshold-to-baseline ratio).

    For known presets we use empirically-measured baselines:
      - UNIFORM_GAP_WEIGHTS         → 0.10 (default; gap_mean ≈ 7.17)
      - PNEUMA_WEIGHTED_GAP_WEIGHTS → 0.15 (gap_mean ≈ 10.89; 1.52× scale)
      - EIDOLON_WEIGHTED_GAP_WEIGHTS → 0.07 (gap_mean ≈ 5.41; 0.72× scale)

    For arbitrary weights pass `variant_gap_mean` from your own measurement
    sweep; otherwise the function falls back to `baseline_threshold`."""
    if weights is None:
        return baseline_threshold
    # Match known presets first
    if weights == UNIFORM_GAP_WEIGHTS:
        return baseline_threshold
    if weights == PNEUMA_WEIGHTED_GAP_WEIGHTS:
        return round(baseline_threshold * (10.89 / baseline_gap_mean), 3)
    if weights == EIDOLON_WEIGHTED_GAP_WEIGHTS:
        return round(baseline_threshold * (5.41 / baseline_gap_mean), 3)
    # Arbitrary weights: caller must provide a measured variant_gap_mean
    if variant_gap_mean is None:
        return baseline_threshold
    return round(baseline_threshold * (variant_gap_mean / baseline_gap_mean), 4)


# ── ComposeFunction Protocol (Phase B.3 stub; Phase C replaces) ────────────


class ComposeFunctionLike(Protocol):
    """Minimal Protocol for a compose function. Phase C provides the real impl."""

    def compose(self, internal: InternalState) -> dict[str, np.ndarray]:
        """Return per-organ external state arrays. Same shape as internal arrays."""
        ...


class IdentityCompose:
    """Stub compose for Phase B.3: external = internal (gap always 0).

    Phase C replaces this with axioma.compose.function.ComposeFunction which
    applies integration-weighted compression per ARCH §5 (the typed boundary).
    """

    name = "identity_compose"

    def compose(self, internal: InternalState) -> dict[str, np.ndarray]:
        return {name: internal.get_organ(name).to_array() for name in ORGAN_ORDER}


# ── Public reading types ──────────────────────────────────────────────────


@dataclass
class AOSGReading:
    """Most recent AOS-G measurement + ψ + sub-signals."""

    beat_no: int = 0
    aos_g_gap: float = 0.0
    aos_g_alert: bool = False
    psi: float = 1.0
    gap_variance_health: float = 1.0
    structural_health: float = 1.0
    compose_probe_health: float = 1.0
    per_organ_gap: dict[str, float] = field(default_factory=dict)
    in_recovery: bool = False
    valid: bool = False


# ── Sub-signal implementations ─────────────────────────────────────────────


class StructuralHealthMonitor:
    """E1: continuous structural_health with debounce.

    Every check is one ImportError attempt. Score = fraction of passes over
    the last N checks (default 5). Single failure floored at 0.6 unless 2+
    consecutive (then debounce relaxes and score drops to true fraction).
    Per IMPLEMENTATION_PLAN §5.4 E1.
    """

    def __init__(
        self,
        *,
        history_size: int = 5,
        debounce_floor: float = 0.6,
        forbidden_modules: tuple[str, ...] = ("axioma.interface.agora_bridge",),
        forbidden_name: str = "InternalState",
    ) -> None:
        self.history_size = history_size
        self.debounce_floor = debounce_floor
        self.forbidden_modules = forbidden_modules
        self.forbidden_name = forbidden_name
        self.check_history: deque[bool] = deque(maxlen=history_size)
        self.consecutive_failures: int = 0

    def check(self) -> None:
        """Run the import-isolation test; record pass/fail.

        Pass condition: every forbidden module either (a) doesn't exist yet
        (Phase B.3 — interface modules not built) or (b) exists but does NOT
        expose `InternalState` in its namespace.
        """
        passed = True
        for mod_name in self.forbidden_modules:
            try:
                mod = importlib.import_module(mod_name)
                if self.forbidden_name in mod.__dict__:
                    passed = False
                    break
            except ImportError:
                # Module doesn't exist yet (Phase B.3 — interfaces not built);
                # treat as "no leak" for now. Phase C/D will populate.
                pass
        self.check_history.append(passed)
        if passed:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1

    def score(self) -> float:
        if not self.check_history:
            return 1.0
        pass_fraction = sum(self.check_history) / len(self.check_history)
        # Debounce: single transient failure floored at debounce_floor
        if self.consecutive_failures < 2:
            return max(pass_fraction, self.debounce_floor)
        return pass_fraction

    def save_state(self) -> dict[str, Any]:
        return {
            "check_history": list(self.check_history),
            "consecutive_failures": self.consecutive_failures,
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        self.check_history = deque(
            snap.get("check_history", []), maxlen=self.history_size
        )
        self.consecutive_failures = int(snap.get("consecutive_failures", 0))


class GapVarianceHealth:
    """E3: gap_variance_health with recovery-state blend.

    `score()` returns: 1.0 - exp(-observed_var / blended_target).
    blended_target = (1 - blend_factor) * baseline + blend_factor * recovery.
    blend_factor toggles 0 ↔ 1 based on recovery_state_change events;
    during RESTORING, blend transitions back to 0 linearly over 20 beats.
    """

    def __init__(
        self,
        *,
        target_var_baseline: float = 0.1,
        target_var_recovery: float = 0.2,
        history_size: int = 100,
        restore_blend_steps: int = 20,
    ) -> None:
        self.target_var_baseline = target_var_baseline
        self.target_var_recovery = target_var_recovery
        self.gap_history: deque[float] = deque(maxlen=history_size)
        self.blend_factor: float = 0.0
        self.restore_blend_steps = restore_blend_steps

    def on_recovery_state(self, state: str) -> None:
        if state == "active":
            self.blend_factor = 1.0
        elif state == "restoring":
            # Per-beat decrement could be wired via tick; for B.3, just snap
            # to a partial value. The exact linear blend is fine-tuned in Phase E.
            self.blend_factor = max(0.0, self.blend_factor - 1.0 / self.restore_blend_steps)
        elif state == "baseline":
            self.blend_factor = 0.0

    def record_gap(self, gap: float) -> None:
        self.gap_history.append(float(gap))

    def score(self) -> float:
        if not self.gap_history:
            return 1.0
        observed_var = float(np.var(self.gap_history))
        target_var = (
            (1.0 - self.blend_factor) * self.target_var_baseline
            + self.blend_factor * self.target_var_recovery
        )
        if target_var <= 0:
            return 1.0
        # Smooth health metric: 0 when no variance, → 1 as observed approaches target
        return float(1.0 - math.exp(-observed_var / target_var))

    def save_state(self) -> dict[str, Any]:
        return {
            "gap_history": list(self.gap_history),
            "blend_factor": self.blend_factor,
            "target_var_baseline": self.target_var_baseline,
            "target_var_recovery": self.target_var_recovery,
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        for g in snap.get("gap_history", []):
            self.gap_history.append(float(g))
        self.blend_factor = float(snap.get("blend_factor", 0.0))
        self.target_var_baseline = float(snap.get("target_var_baseline",
                                                  self.target_var_baseline))
        self.target_var_recovery = float(snap.get("target_var_recovery",
                                                  self.target_var_recovery))


class ComposeProbeHealth:
    """E4: probe + recovery-aware expected outputs + Stage-4 skip.

    Every probe_period beats, the engine runs a probe InternalState through
    compose and compares against expected. The expected reference is either
    `expected_baseline` (normal operation) or `expected_recovery` (during
    active recovery). Skipped at Stage 4 emergency.
    """

    def __init__(
        self,
        *,
        probe_period: int = 100,
        tolerance: float = 0.05,
    ) -> None:
        self.probe_period = probe_period
        self.tolerance = tolerance
        self.expected_baseline: dict[str, np.ndarray] | None = None
        self.expected_recovery: dict[str, np.ndarray] | None = None
        self.health: float = 1.0
        self._last_probe_beat: int | None = None
        self.recovery_state: str = "baseline"
        self.current_stage: int = 0

    def on_recovery_state(self, state: str) -> None:
        self.recovery_state = state

    def on_stage_change(self, stage: int) -> None:
        self.current_stage = stage

    def calibrate(self, expected_baseline: dict[str, np.ndarray]) -> None:
        """Phase A: record expected_baseline by running compose on a known InternalState."""
        self.expected_baseline = {
            k: np.asarray(v, dtype=np.float32, copy=True)
            for k, v in expected_baseline.items()
        }

    def calibrate_recovery(self, expected_recovery: dict[str, np.ndarray]) -> None:
        """Phase E: record expected_recovery during synthetic recovery."""
        self.expected_recovery = {
            k: np.asarray(v, dtype=np.float32, copy=True)
            for k, v in expected_recovery.items()
        }

    def maybe_probe(
        self,
        beat_no: int,
        compose: ComposeFunctionLike,
        probe_internal: InternalState,
    ) -> None:
        """If due, run a probe. Stage-4 skip: cached health carries forward."""
        if beat_no <= 0 or beat_no % self.probe_period != 0:
            return
        if self.recovery_state == "active" and self.current_stage == 4:
            # E4 Stage-4 skip; cached health unchanged
            return
        # Pick the expected reference
        expected = (
            self.expected_recovery
            if self.recovery_state != "baseline" and self.expected_recovery is not None
            else self.expected_baseline
        )
        produced = compose.compose(probe_internal)
        if expected is None:
            # No calibration yet — assume healthy
            self.health = 1.0
        else:
            # Health = fraction of organs within tolerance
            healthy = sum(
                1 for o in ORGAN_ORDER
                if o in produced
                and o in expected
                and bool(np.allclose(produced[o], expected[o], atol=self.tolerance))
            )
            self.health = healthy / max(len(ORGAN_ORDER), 1)
        self._last_probe_beat = beat_no

    def score(self) -> float:
        return self.health

    def save_state(self) -> dict[str, Any]:
        return {
            "expected_baseline": (
                {k: v.tolist() for k, v in self.expected_baseline.items()}
                if self.expected_baseline is not None
                else None
            ),
            "expected_recovery": (
                {k: v.tolist() for k, v in self.expected_recovery.items()}
                if self.expected_recovery is not None
                else None
            ),
            "health": self.health,
            "last_probe_beat": self._last_probe_beat,
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        eb = snap.get("expected_baseline")
        if eb is not None:
            self.expected_baseline = {
                k: np.asarray(v, dtype=np.float32) for k, v in eb.items()
            }
        er = snap.get("expected_recovery")
        if er is not None:
            self.expected_recovery = {
                k: np.asarray(v, dtype=np.float32) for k, v in er.items()
            }
        self.health = float(snap.get("health", 1.0))
        self._last_probe_beat = snap.get("last_probe_beat")


# ── Main engine ───────────────────────────────────────────────────────────


class AOSGEngine(MeasurementEngine):
    """Computes AOS-G gap + ψ on every compose event.

    Default cadence: every 30 beats (the baseline compose cadence per ARCH §4.6).
    When a real ComposeFunction is wired (Phase C), the heartbeat tells this
    engine when compose happened. For B.3, compose is the stub identity — we
    just run on a fixed cadence to exercise the pipeline.
    """

    name = "aos_g"
    natural_period_beats = 30
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        compose: ComposeFunctionLike | None = None,
        psi_alert_threshold: float = 0.3,
        aos_g_alert_threshold: float = 0.1,
        history_capacity: int = 200,
        gap_weights: dict[str, float] | None = None,
        # v1.4.2 — auto-tune the alert threshold based on observed gap distribution.
        # When enabled, threshold gets set after `auto_tune_warmup_beats` to
        # `auto_tune_ratio × mean(observed_gap)`. Recomputes every
        # `auto_tune_recompute_period_beats` so the threshold tracks drift.
        # v1.4.4: default warmup bumped 600 → 3000 to coordinate with v1.4.1
        # normalization warmup (60 samples × 30-beat AOSG period = 1800 beats;
        # 3000 gives ~67% safety margin). See ComposeConfig for the rationale.
        auto_tune_alert_threshold: bool = False,
        auto_tune_ratio: float = 0.014,
        auto_tune_warmup_beats: int = 3000,
        auto_tune_recompute_period_beats: int = 36000,
        # v1.4.3 — per-component ψ alert thresholds.
        # None → use psi_alert_threshold for all components (v1.0..v1.3 default).
        # Otherwise: alert fires if ANY component < its own threshold.
        # Missing keys fall back to psi_alert_threshold.
        psi_per_component_thresholds: dict[str, float] | None = None,
        # v1.4.1 — opt-in per-organ gap normalization.
        # When True, each organ's gap is divided by its rolling-mean gap before
        # the weighted-sum step. Equalizes per-organ contribution regardless of
        # natural magnitude (PNEUMA ≈ 7.26 vs ANIMA ≈ 0.036). During warmup
        # (< min_samples observations) behavior matches unnormalized.
        normalize_per_organ: bool = False,
        normalize_window_beats: int = 600,
        normalize_min_samples: int = 60,
    ) -> None:
        super().__init__(ctx)
        self.compose: ComposeFunctionLike = compose or IdentityCompose()
        self.psi_alert_threshold = psi_alert_threshold
        self.aos_g_alert_threshold = aos_g_alert_threshold
        self.history_capacity = history_capacity
        # v1.4.3 — resolve per-component thresholds; None means inherit single threshold.
        self.psi_per_component_thresholds: dict[str, float] = (
            _resolve_per_component_thresholds(
                psi_per_component_thresholds, psi_alert_threshold,
            )
        )
        # v1.1.6: per-organ weights for the AOS-G gap (Weighted Euclidean).
        # Default uniform (1.0 each) → matches v1.0 plain L2 behavior exactly.
        # Operators can pass per-organ weights to bias the gap toward organs
        # with stronger architectural roles (e.g., EIDOLON, PNEUMA).
        self.gap_weights: dict[str, float] = (
            {name: 1.0 for name in ORGAN_ORDER}
            if gap_weights is None else _normalize_weights(gap_weights)
        )
        # v1.4.2 auto-tuner state
        self.auto_tune_alert_threshold = bool(auto_tune_alert_threshold)
        self.auto_tune_ratio = float(auto_tune_ratio)
        self.auto_tune_warmup_beats = int(auto_tune_warmup_beats)
        self.auto_tune_recompute_period_beats = int(auto_tune_recompute_period_beats)
        self._auto_tune_gap_samples: deque[float] = deque(maxlen=10_000)
        self._auto_tune_initial_threshold = float(aos_g_alert_threshold)
        self._auto_tune_last_recompute_beat: int = -1
        self._auto_tune_first_set: bool = False
        self._auto_tune_n_tunes: int = 0  # v1.5: exposed by self_check() for operator visibility
        # v1.4.1 per-organ normalization state
        self.normalize_per_organ = bool(normalize_per_organ)
        self.normalize_window_beats = int(normalize_window_beats)
        self.normalize_min_samples = int(normalize_min_samples)
        if self.normalize_min_samples < 1:
            raise ValueError(
                f"normalize_min_samples must be >= 1, got {self.normalize_min_samples}"
            )
        if self.normalize_window_beats < self.normalize_min_samples:
            raise ValueError(
                "normalize_window_beats must be >= normalize_min_samples "
                f"({self.normalize_window_beats} < {self.normalize_min_samples})"
            )
        self._per_organ_gap_history: dict[str, deque[float]] = {
            name: deque(maxlen=self.normalize_window_beats) for name in ORGAN_ORDER
        }
        # v1.4.4 — boot-time sanity check: when both auto-tune and normalize
        # are on, the auto-tune warmup must outlast the normalize warmup, else
        # the first auto-tune set calibrates against partly-unnormalized gaps
        # (per Checkpoint W's warmup-mismatch finding). Operators who customize
        # `normalize_min_samples` above the default 60 should bump
        # `auto_tune_warmup_beats` proportionally.
        if self.auto_tune_alert_threshold and self.normalize_per_organ:
            normalize_warmup_beats = self.normalize_min_samples * self.natural_period_beats
            if self.auto_tune_warmup_beats < normalize_warmup_beats:
                log.warning(
                    "aos_g_auto_tune_warmup_below_normalize_warmup",
                    auto_tune_warmup_beats=self.auto_tune_warmup_beats,
                    normalize_warmup_beats=normalize_warmup_beats,
                    normalize_min_samples=self.normalize_min_samples,
                    natural_period_beats=self.natural_period_beats,
                    recommendation=(
                        f"set auto_tune_warmup_beats >= {normalize_warmup_beats} "
                        "to ensure the first auto-tune fires against fully-normalized gap data"
                    ),
                )
        # Sub-signal monitors
        self.structural = StructuralHealthMonitor()
        self.gap_variance = GapVarianceHealth()
        self.compose_probe = ComposeProbeHealth()
        # State
        self._current = AOSGReading()
        self.history: deque[AOSGReading] = deque(maxlen=history_capacity)
        # Subscribe to recovery + fragmentation events
        self.ctx.subscribe("recovery_state_change", self._on_recovery_state)
        self.ctx.subscribe("fragmentation_stage_change", self._on_stage_change)

    # ── Event handlers ───────────────────────────────────────────────────

    def _on_recovery_state(self, payload: Any) -> None:
        state_value = (
            payload.get("state") if isinstance(payload, dict)
            else getattr(payload, "state", "baseline")
        )
        state = str(state_value) if state_value is not None else "baseline"
        self.gap_variance.on_recovery_state(state)
        self.compose_probe.on_recovery_state(state)

    def _on_stage_change(self, payload: Any) -> None:
        new_stage = (
            payload.new_stage
            if hasattr(payload, "new_stage")
            else payload.get("new_stage", 0) if isinstance(payload, dict) else 0
        )
        self.compose_probe.on_stage_change(int(new_stage))

    def _maybe_auto_tune_threshold(self, beat_no: int) -> None:
        """v1.4.2 — set aos_g_alert_threshold to auto_tune_ratio × mean(observed_gap).

        Fires the FIRST set after `auto_tune_warmup_beats` (and at least 20 samples),
        then recomputes every `auto_tune_recompute_period_beats`.
        """
        if not self._auto_tune_first_set:
            if beat_no < self.auto_tune_warmup_beats:
                return
            if len(self._auto_tune_gap_samples) < 20:
                return
            self._set_threshold_from_samples(beat_no, reason="warmup_complete")
            self._auto_tune_first_set = True
            self._auto_tune_last_recompute_beat = beat_no
            return
        # Subsequent recomputes
        if beat_no - self._auto_tune_last_recompute_beat >= self.auto_tune_recompute_period_beats:
            self._set_threshold_from_samples(beat_no, reason="periodic_recompute")
            self._auto_tune_last_recompute_beat = beat_no

    def _set_threshold_from_samples(self, beat_no: int, *, reason: str) -> None:
        """Compute mean(gap) over recent samples and set threshold proportionally."""
        if not self._auto_tune_gap_samples:
            return
        mean_gap = sum(self._auto_tune_gap_samples) / len(self._auto_tune_gap_samples)
        new_threshold = round(self.auto_tune_ratio * mean_gap, 4)
        prev_threshold = self.aos_g_alert_threshold
        self.aos_g_alert_threshold = new_threshold
        self._auto_tune_n_tunes += 1
        log.info(
            "aos_g_alert_threshold_auto_tuned",
            beat_no=beat_no,
            previous=prev_threshold,
            new=new_threshold,
            mean_gap=round(mean_gap, 4),
            ratio=self.auto_tune_ratio,
            n_samples=len(self._auto_tune_gap_samples),
            reason=reason,
        )

    # ── Compute ──────────────────────────────────────────────────────────

    def compute(self) -> None:
        if not self.ctx.has("substrate"):
            return
        substrate = self.ctx.substrate
        latest_internal = substrate.last_internal()
        if latest_internal is None:
            return
        beat_no = latest_internal.beat_no

        # 1. Prefer the heartbeat's memoized (internal, external) pair so we
        # don't double-compose with different noise samples. Fall back to
        # direct compose for the standalone case (Phase B.3 / unit tests
        # without a registered compose_function).
        per_organ_external: dict[str, np.ndarray] | None = None
        if self.ctx.has("compose_function"):
            cf = self.ctx.get("compose_function")
            cached_internal = getattr(cf, "latest_internal", None)
            cached_external = getattr(cf, "latest_external", None)
            if (
                cached_internal is not None
                and cached_external is not None
                and cached_internal.beat_no == latest_internal.beat_no
            ):
                per_organ_external = {
                    name: cached_external.get_organ_array(name) for name in ORGAN_ORDER
                }
        if per_organ_external is None:
            try:
                per_organ_external = self.compose.compose(latest_internal)
            except Exception:
                log.exception("compose_failed_in_aos_g")
                return

        # 2. Compute per-organ gap (Euclidean of internal-vs-external per organ)
        # v1.1.6: weighted Euclidean — gap = sqrt(Σ_organ w_organ × Σ_dim diff²).
        # With uniform weights (default), reduces exactly to v1.0 plain L2.
        # v1.4.1: opt-in per-organ normalization divides each organ's raw gap by
        # its rolling-mean before squaring, so per-organ contributions get
        # equalized regardless of natural magnitude.
        per_organ_gap: dict[str, float] = {}
        total_sq = 0.0
        for name in ORGAN_ORDER:
            internal_arr = latest_internal.get_organ(name).to_array()
            external_arr = per_organ_external.get(name)
            if external_arr is None:
                continue
            diff = internal_arr - external_arr
            per_dim_sq = float(np.sum(diff * diff))
            raw_organ_gap = float(math.sqrt(per_dim_sq))
            per_organ_gap[name] = raw_organ_gap
            if self.normalize_per_organ:
                hist = self._per_organ_gap_history[name]
                hist.append(raw_organ_gap)
                if len(hist) >= self.normalize_min_samples:
                    scale = sum(hist) / len(hist)
                    if scale > 0.0:
                        normalized = raw_organ_gap / scale
                        total_sq += self.gap_weights.get(name, 1.0) * (normalized * normalized)
                        continue
                # Warmup or degenerate scale → fall back to unnormalized contribution
                total_sq += self.gap_weights.get(name, 1.0) * per_dim_sq
            else:
                total_sq += self.gap_weights.get(name, 1.0) * per_dim_sq
        gap = float(math.sqrt(total_sq))

        # 3. Update sub-signals
        self.gap_variance.record_gap(gap)
        self.structural.check()
        # v1.4.2 — auto-tuner samples + maybe recomputes threshold.
        # Only samples non-degenerate gaps (gap > 0) to avoid biasing the mean
        # downward during cold-start when compose hasn't fired yet.
        # v1.4.4: when normalize_per_organ is on, gate sample accumulation on
        # normalization having stabilized for ALL organs (i.e., each organ's
        # rolling-mean history has reached normalize_min_samples). Without
        # this gate, the auto-tune buffer accumulates pre-stabilization
        # (unnormalized) gaps that bias the first-set mean upward by ~2×.
        # Per Checkpoint W's empirical finding: at warmup=600 first_set was
        # ~0.085; at warmup=3000 first_set was ~0.100 — both wrong because
        # the buffer's maxlen=10K never drains the early unnormalized samples.
        # The fix is at the source, not the warmup window.
        if self.auto_tune_alert_threshold and gap > 0:
            normalize_ready = (
                not self.normalize_per_organ
                or all(
                    len(self._per_organ_gap_history[name]) >= self.normalize_min_samples
                    for name in ORGAN_ORDER
                )
            )
            if normalize_ready:
                self._auto_tune_gap_samples.append(gap)
                self._maybe_auto_tune_threshold(beat_no)
        # Run probe on its own cadence (100-beat) — uses the same InternalState
        # as the probe input for simplicity. In Phase E the probe uses a
        # synthetic InternalState with known values.
        self.compose_probe.maybe_probe(beat_no, self.compose, latest_internal)

        # 4. Aggregate ψ = min of sub-signals
        gv = self.gap_variance.score()
        sh = self.structural.score()
        cp = self.compose_probe.score()
        psi = min(gv, sh, cp)

        # 5. Alerts — v1.4.3: per-component thresholds (defaults to single threshold).
        # Alert fires if ANY component drops below its own threshold OR if gap
        # collapses below the gap floor.
        psi_thr = self.psi_per_component_thresholds
        psi_alert = (
            gv < psi_thr["gap_variance_health"]
            or sh < psi_thr["structural_health"]
            or cp < psi_thr["compose_probe_health"]
        )
        gap_alert = gap < self.aos_g_alert_threshold and gap > 0.0
        alert = psi_alert or gap_alert

        reading = AOSGReading(
            beat_no=beat_no,
            aos_g_gap=gap,
            aos_g_alert=alert,
            psi=psi,
            gap_variance_health=gv,
            structural_health=sh,
            compose_probe_health=cp,
            per_organ_gap=per_organ_gap,
            in_recovery=(self.gap_variance.blend_factor > 0),
            valid=True,
        )
        self._current = reading
        self.history.append(reading)
        AOS_G_GAP.set(gap)
        PSI.set(psi)

    def current_value(self) -> AOSGReading:
        return self._current

    def recent_history(self, n: int | None = None) -> list[AOSGReading]:
        h = list(self.history)
        return h[-n:] if n is not None else h

    # ── v1.5 self-check (Checkpoint Z) ───────────────────────────────────

    def self_check(self) -> dict[str, Any]:
        """v1.5 operator self-check: reports config + live engine state + a
        per-organ-contribution share + a list of human-readable checks.

        Designed to answer "is v1.5 operating as expected on my deployment?"
        without forcing operators to grep structlog. Read-only; safe to call
        from a non-admin HTTP endpoint."""
        cv = self._current
        valid_reading = cv is not None and cv.valid

        # Per-organ contribution share to the aggregate gap. Reconstructed
        # from raw per-organ gaps + current weights + (when normalize is on)
        # the rolling-mean scale. This is the load-bearing v1.5 diagnostic —
        # operators can verify normalization is balancing the per-organ
        # contribution as designed (no organ should dominate > ~60% post-stabilization).
        per_organ_share: dict[str, float] = {}
        if valid_reading and cv.per_organ_gap:
            contributions: dict[str, float] = {}
            total_sq = 0.0
            for name, raw_gap in cv.per_organ_gap.items():
                w = self.gap_weights.get(name, 1.0)
                if self.normalize_per_organ:
                    hist = self._per_organ_gap_history.get(name)
                    if hist is not None and len(hist) >= self.normalize_min_samples:
                        scale = sum(hist) / len(hist)
                        contrib = (
                            w * (raw_gap / scale) ** 2 if scale > 0
                            else w * raw_gap * raw_gap
                        )
                    else:
                        contrib = w * raw_gap * raw_gap
                else:
                    contrib = w * raw_gap * raw_gap
                contributions[name] = contrib
                total_sq += contrib
            if total_sq > 0:
                per_organ_share = {
                    name: round(c / total_sq * 100, 2)
                    for name, c in contributions.items()
                }

        # Normalization-readiness: each organ's rolling-history has reached min_samples
        normalize_samples_per_organ = {
            name: len(self._per_organ_gap_history.get(name, ()))
            for name in ORGAN_ORDER
        }
        normalize_ready = (
            not self.normalize_per_organ
            or all(n >= self.normalize_min_samples
                   for n in normalize_samples_per_organ.values())
        )

        # Build operator-friendly checks
        checks: list[dict[str, str]] = []
        if self.normalize_per_organ:
            checks.append({
                "name": "normalize_enabled",
                "status": "ok",
                "detail": (f"v1.5 default — per-organ normalization ON "
                           f"(window={self.normalize_window_beats}, "
                           f"min_samples={self.normalize_min_samples})"),
            })
            checks.append({
                "name": "normalize_stabilized",
                "status": "ok" if normalize_ready else "warmup",
                "detail": (
                    "all organs have reached min_samples — normalization fully active"
                    if normalize_ready else
                    f"per-organ samples: {normalize_samples_per_organ}"
                ),
            })
        else:
            checks.append({
                "name": "normalize_enabled",
                "status": "off",
                "detail": "per-organ normalization disabled (v1.4 backwards-compat regime)",
            })

        if self.auto_tune_alert_threshold:
            tuned = self._auto_tune_first_set
            checks.append({
                "name": "auto_tune_enabled",
                "status": "ok",
                "detail": (f"v1.5 default — auto-tune ON "
                           f"(warmup={self.auto_tune_warmup_beats}, "
                           f"ratio={self.auto_tune_ratio}, "
                           f"recompute_period={self.auto_tune_recompute_period_beats})"),
            })
            checks.append({
                "name": "auto_tune_first_set_fired",
                "status": "ok" if tuned else "warmup",
                "detail": (
                    f"first set fired at beat {self._auto_tune_last_recompute_beat}; "
                    f"n_tunes={self._auto_tune_n_tunes}; "
                    f"current threshold={self.aos_g_alert_threshold} "
                    f"(initial={self._auto_tune_initial_threshold})"
                    if tuned else
                    f"warmup in progress — current threshold is static initial "
                    f"({self._auto_tune_initial_threshold}); "
                    f"{len(self._auto_tune_gap_samples)} samples accumulated"
                ),
            })
        else:
            checks.append({
                "name": "auto_tune_enabled",
                "status": "off",
                "detail": (f"auto-tune disabled (v1.4 backwards-compat regime); "
                           f"static threshold={self.aos_g_alert_threshold}"),
            })

        # PNEUMA-share balance check — the architectural promise of v1.5
        if per_organ_share:
            pneuma_share = per_organ_share.get("pneuma", 0.0)
            if not self.normalize_per_organ:
                share_status = "off"
                share_detail = (f"normalize off — PNEUMA share {pneuma_share}% "
                                "(typical v1.4 regime: >80%)")
            elif not normalize_ready:
                share_status = "warmup"
                share_detail = (f"normalize warmup — PNEUMA share {pneuma_share}% "
                                "(will drop as rolling-means stabilize)")
            else:
                # Post-stabilization, PNEUMA share should be < ~60% (v1.5 sweeps show ~45%)
                share_status = "ok" if pneuma_share < 60.0 else "warning"
                share_detail = (
                    f"PNEUMA share {pneuma_share}% — balanced (target < 60%)"
                    if share_status == "ok" else
                    f"PNEUMA share {pneuma_share}% — higher than expected (target < 60%); "
                    "check gap_weights configuration"
                )
            checks.append({
                "name": "per_organ_contribution_balanced",
                "status": share_status,
                "detail": share_detail,
            })

        # Overall: "warning" if any warning, else "warmup" if any warmup, else "ok"
        statuses = [c["status"] for c in checks]
        if "warning" in statuses:
            overall = "warning"
        elif "warmup" in statuses:
            overall = "warmup"
        else:
            overall = "ok"

        return {
            "version": "v1.5",
            "config": {
                "aos_g_normalize_per_organ": self.normalize_per_organ,
                "aos_g_normalize_per_organ_window_beats": self.normalize_window_beats,
                "aos_g_normalize_per_organ_min_samples": self.normalize_min_samples,
                "aos_g_alert_threshold_auto_tune": self.auto_tune_alert_threshold,
                "aos_g_alert_threshold_auto_tune_ratio": self.auto_tune_ratio,
                "aos_g_alert_threshold_auto_tune_warmup_beats": self.auto_tune_warmup_beats,
                "aos_g_alert_threshold_auto_tune_recompute_period_beats": (
                    self.auto_tune_recompute_period_beats
                ),
                "gap_weights": dict(self.gap_weights),
            },
            "engine_state": {
                "current_threshold": self.aos_g_alert_threshold,
                "initial_threshold": self._auto_tune_initial_threshold,
                "auto_tune_first_set": self._auto_tune_first_set,
                "auto_tune_n_tunes": self._auto_tune_n_tunes,
                "last_tune_beat": (
                    self._auto_tune_last_recompute_beat
                    if self._auto_tune_last_recompute_beat >= 0 else None
                ),
                "normalize_ready": normalize_ready,
                "normalize_samples_per_organ": normalize_samples_per_organ,
                "last_reading_beat": cv.beat_no if valid_reading else None,
            },
            "per_organ_contribution_share_pct": per_organ_share,
            "checks": checks,
            "overall_status": overall,
        }

    # ── Stateful protocol ────────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "structural": self.structural.save_state(),
            "gap_variance": self.gap_variance.save_state(),
            "compose_probe": self.compose_probe.save_state(),
            "gap_weights": dict(self.gap_weights),  # v1.1.6
            "current": {
                "beat_no": self._current.beat_no,
                "aos_g_gap": self._current.aos_g_gap,
                "aos_g_alert": self._current.aos_g_alert,
                "psi": self._current.psi,
                "gap_variance_health": self._current.gap_variance_health,
                "structural_health": self._current.structural_health,
                "compose_probe_health": self._current.compose_probe_health,
                "per_organ_gap": self._current.per_organ_gap,
                "in_recovery": self._current.in_recovery,
                "valid": self._current.valid,
            },
        }

    def load_state(self, snap: dict[str, Any]) -> None:
        if "gap_weights" in snap:
            self.gap_weights = _normalize_weights(snap["gap_weights"])
        self.structural.load_state(snap.get("structural", {}))
        self.gap_variance.load_state(snap.get("gap_variance", {}))
        self.compose_probe.load_state(snap.get("compose_probe", {}))
        cur = snap.get("current", {})
        self._current = AOSGReading(
            beat_no=int(cur.get("beat_no", 0)),
            aos_g_gap=float(cur.get("aos_g_gap", 0.0)),
            aos_g_alert=bool(cur.get("aos_g_alert", False)),
            psi=float(cur.get("psi", 1.0)),
            gap_variance_health=float(cur.get("gap_variance_health", 1.0)),
            structural_health=float(cur.get("structural_health", 1.0)),
            compose_probe_health=float(cur.get("compose_probe_health", 1.0)),
            per_organ_gap=dict(cur.get("per_organ_gap", {})),
            in_recovery=bool(cur.get("in_recovery", False)),
            valid=bool(cur.get("valid", False)),
        )


__all__ = [
    "AOSGEngine",
    "AOSGReading",
    "ComposeFunctionLike",
    "ComposeProbeHealth",
    "GapVarianceHealth",
    "IdentityCompose",
    "StructuralHealthMonitor",
]
