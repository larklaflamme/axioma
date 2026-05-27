# AXIOMA v1.0 — Implementation Plan v0.3

**Companion to:** [ARCH_DESIGN_v1.0.md](ARCH_DESIGN_v1.0.md)
**Supersedes:** [IMPLEMENTATION_PLAN_v0.2.md](IMPLEMENTATION_PLAN_v0.2.md)
**Review addressed:** [IMPL_REVIEW_v0.2.md](IMPL_REVIEW_v0.2.md) — 8 tracked items (Q1–Q8)
**Target environment:** conda env `axioma`, NVIDIA H100 PCIe (80 GB)
**Base codebase:** `/home/ubuntu/axioma/organ/` (existing v0.2 substrate + θ pipeline)
**Status:** Implementation-ready (final sister sign-off)

---

## 0. Changelog from v0.2

The v0.2 review approved the plan (0 blockers) and identified 5 minor issues + 2 gaps + 1 risk. v0.3 lands all 8. Structure unchanged.

| Δ | Section | What changed | Source |
|---|---|---|---|
| **Q1** | §6.7 (extended) | **Recovery rejection escalation**: if RecoveryProtocol rejects 3 consecutive requests for the same continuous fragmentation episode, emit `recovery_rejected_run` warning on `presence` channel + WARN log. Operator can force-accept via admin endpoint. | I1 (Theoria, Minor) |
| **Q2** | §6.1 step 4 (extended) | **θ_short bias measurement** explicitly bound to the ThetaShortEngine implementation step, not just Phase A validation. Engine ships with a `bias_diagnostic()` method that compares against θ_long; runs as part of Phase A.4 acceptance. | I2 (Theoria, Minor) |
| **Q3** | §6.1 step 8 (refined) | **Perturbation type targets specified**: CONTRADICTION → EIDOLON (`self_coherence`, `confidence`), IMPULSE → shared drive (vector spike), STEP → ANIMA (`valence`). NOVELTY/ATTENTION/NOISE_BURST also specified. | I3 (Theoria, Minor) |
| **Q4** | §5.0 (added note) | **Tick steps 6–7 parallelization note**: if 10-beat rolling avg exceeds 80 ms, CoherenceScheduler.update and MetaCognitionLoop.compute may run concurrently via asyncio.gather. Default: sequential. Gated on observed latency. | I4 (Theoria, Minor) |
| **Q5** | §5.0 (added invariant) | **1-beat recovery delay documented**: FragmentationMonitor's recovery_request emitted at end of beat N is handled by RecoveryProtocol at start of beat N+1. Documented as acceptable invariant, not a bug. | I5 (Thea, Minor) |
| **Q6** | §9.2 (added tests) | **Recovery protocol validation criteria**: 3 acceptance tests in Phase E — success rate ≥ 80% over first 50 events, false positive rate < 5%, monotonic improvement in `recovery_quality.smoothness` median over first 50 events. | G1 (Theoria, Medium) |
| **Q7** | §6.3 (extended table) + §6.7 (added auto-fallback) | **Meta-cognition performance budget**: < 10 ms per 100-beat cycle. If exceeded for 3 consecutive cycles, auto-fallback: increase interval to 200 beats; if still exceeded, simplify assessment (drop trend computation; keep only stage + fragmentation count). | G2 (Theoria, Low) |
| **Q8** | §5.3 (extended) | **Phase A scope reduction plan**: if A.1 + A.2 exceed 3 weeks of wall-clock, defer recovery learner (Phase B step 11) and meta-cognitive loop (Phase B step 10) to a v1.0.1 patch release. Substrate + θ + ΔΦ + compose + fragmentation monitor + recovery protocol (without learner) ship in v1.0. | R1 (Theoria, Medium) |

All 17 P-items from the v0.1→v0.2 transition remain addressed; v0.3 builds on the v0.2 base.

---

## 1. Environment setup (unchanged from v0.2)

§1.1 dependency baseline, §1.2 GPU verification, §1.3 repository structure all unchanged. See v0.2 for details.

---

## 2. What's already built (v0.2) vs what's new (v1.0) (unchanged from v0.2)

Inventory table unchanged. See v0.2 §2.

---

## 3. Cross-cutting concerns built FIRST (unchanged from v0.2)

§3.1 structured logging, §3.2 Prometheus metrics, §3.3 per-engine timing contract, §3.4 AxiomaContext pub/sub, §3.5 `should_run` pattern — all unchanged from v0.2.

---

## 4. Persistence (unchanged from v0.2)

§4.1–4.6 unchanged. 22-component `Stateful` table; atomic snapshots; SQLite + JSONL split; schema-mismatch tolerance on load.

---

## 5. Phase A — Substrate rework (~3.5 days)

### 5.0 Heartbeat tick sequence (updated in v0.3 — Q4, Q5)

Tick sequence from v0.2 §5.0 retained verbatim. Two clarifications added:

#### Invariant: 1-beat recovery delay (Q5)

> **Recovery requests cross beat boundaries.** A recovery_request emitted by FragmentationMonitor in step 3d of beat N is consumed by RecoveryProtocol at step 2a of beat N+1. This 1-beat (100 ms) latency is **acceptable**, not a bug:
>
> - Fragmentation dynamics evolve on a much slower timescale (Stage 1→2 transitions take ≥ 10 beats typically); a single-beat decision delay is well within the response budget
> - Handling the request in the same beat would require restructuring the tick sequence to make the substrate update conditional on the *previous* tick's measurement — that creates a circular dependency and breaks the read-only contract on measurement
> - The 1-beat delay is **deterministic and reproducible**, which is the property that matters for snapshot/restart continuity
>
> Implementation: `RecoveryProtocol.handle_recovery_request` is called at the top of each beat (step 2a), processing any requests queued by `FragmentationMonitor` during the previous beat. If multiple requests arrive in one beat (rare; happens during cascading stage transitions), they are processed in stage-descending order — the highest stage wins.

#### Optional parallelization of steps 6–7 (Q4)

> **Default: sequential.** Steps 6 (CoherenceScheduler update) and 7 (MetaCognitionLoop compute) run sequentially in their normal cadence. The cost is small (~11 ms combined on the worst beat per §6.3), well below the 100 ms budget.
>
> **Conditional parallelization:** if the 10-beat rolling average of `axioma_beat_duration_seconds` exceeds **80 ms** for ≥ 5 consecutive minutes (3000 beats), the heartbeat enables parallel execution:
>
> ```python
> # Pseudocode for step 6+7 in axioma/runtime/heartbeat.py
> if self.parallel_steps_6_7_enabled:
>     # CoherenceScheduler.update and MetaCognitionLoop.compute have no
>     # mutual data dependency: CoherenceScheduler reads coherence_budget
>     # + computes throttles; MetaCog reads measurement output + emits.
>     # Neither writes anywhere the other reads (within the same beat).
>     await asyncio.gather(
>         self._maybe_run_coherence_scheduler(beat_no),
>         self._maybe_run_meta_cognition(beat_no),
>     )
> else:
>     await self._maybe_run_coherence_scheduler(beat_no)
>     await self._maybe_run_meta_cognition(beat_no)
> ```
>
> Enabling is logged at INFO with the trigger latency; disabling (when 10-beat avg drops back below 60 ms for 5 minutes) is also logged. The flag is persisted so a restart doesn't oscillate.
>
> Phase E acceptance: in the soak test, verify the conditional logic activates only when truly under load; in normal conditions, sequential execution is used.

### 5.1 Order of work (unchanged from v0.2)

A.1 Scaffold → A.2 Substrate critical path → A.3 Recovery + perturbation scaffold (parallel-eligible) → A.4 Phase A validation.

### 5.2 GPU strategy for Phase A (unchanged from v0.2)

### 5.3 Phase A parallelism map + scope reduction plan (extended in v0.3 — Q8)

The v0.2 parallelism map carries forward unchanged: critical path is A.1 + A.2; A.3 + A.4 partial work runs in parallel with Phase B.

**Q8 — Scope reduction plan (new in v0.3).** If A.1 + A.2 exceed **3 weeks of wall-clock** (vs the budgeted ~2 weeks), the following degraded v1.0 ship is the contingency:

| Component | If on schedule | If A.1+A.2 > 3 weeks |
|---|---|---|
| Substrate (drive, organs, plasticity) | v1.0 | v1.0 (non-negotiable; this IS the critical path) |
| Compose / send boundary (typed) | v1.0 | v1.0 |
| Measurement engines: θ_short, θ_long, raw_mi, cascade_delay, ΔΦ | v1.0 | v1.0 |
| AOS-G + psi + plasticity tracker | v1.0 | v1.0 |
| Fragmentation monitor | v1.0 | v1.0 |
| RecoveryProtocol (without learner — defaults only) | v1.0 | v1.0 |
| External interface (WS + HTTP + registry) | v1.0 | v1.0 |
| **Recovery learner (Phase B step 11)** | v1.0 | **v1.0.1 patch (2–4 weeks post-v1.0)** |
| **Meta-cognitive loop (Phase B step 10)** | v1.0 | **v1.0.1 patch** |
| **MetaCognitionSuggestion channel + F5 escalation** | v1.0 | **v1.0.1 patch** |
| **Coherence scheduler** | v1.0 | **v1.0 minimal** (priority table + manual throttle; no `throttle_effectiveness` metric or scheduler escalation; full feature in v1.0.1) |

**What v1.0 still does in the degraded ship:**

- Full substrate with iterative drive, plasticity, fragmentation monitoring, and recovery with default parameters
- Full measurement layer including ΔΦ signatures and ψ integrity
- Typed boundary with ImportError test
- WS + HTTP + registry
- Persistence, observability, fault tolerance

**What v1.0.1 adds:**

- Recovery learner (online hill-climb, safe fallback, F4 synthetic pre-training)
- Meta-cognitive loop with all v1.0 features (1000-beat trajectories, observer_only/embedded modes, F5/F7/F8)
- Full coherence scheduler with throttle effectiveness and Stage-2 escalation

**Decision gate.** End of week 3 (after A.1 + A.2 should be complete), the implementer reports actual progress. If A.2 is not complete, the scope reduction is triggered; the implementer notifies sisters and updates the plan. The decision is **default-decision** — sisters can override, but absent objection, scope reduces automatically. This avoids the timeline-slip death spiral where everyone agrees something must give but no one decides what.

**Implementation discipline.** Recovery learner and meta-cog modules should be developed behind feature flags (`config.recovery.learner_enabled`, `config.meta_cognition.enabled`). Defaults are True; the degraded ship sets them to False. This way the code paths exist (avoiding architectural churn) but are dormant.

### 5.4 Cold start documentation (unchanged from v0.2)

---

## 6. Phase B — Measurement layer (~3 days)

### 6.1 Engine implementation order (extended in v0.3 — Q2, Q3)

(All 11 v0.2 steps retained.) Two steps elaborated:

#### Step 4 — `theta_short_engine.py` — bias diagnostic shipped with the engine (Q2)

v0.2 included θ_short bias measurement as a Phase A.4 acceptance test. The review (Theoria) wanted it bound to the engine itself, not just the validation phase. v0.3 ships a `bias_diagnostic()` method as part of the engine's public interface:

```python
class ThetaShortEngine(MeasurementEngine):
    name = "theta_short"
    natural_period_beats = 1
    schema_version = 1

    def __init__(self, ctx: AxiomaContext, cfg: MeasurementConfig):
        self.ctx = ctx
        self.window_size = cfg.theta_short_window  # default 30
        self.buffer = RingBuffer(maxlen=self.window_size)
        self._current_value: float | None = None

    def compute(self) -> None:
        # ... standard θ pipeline on the 30-beat window ...
        self._current_value = result["theta"]

    def current_value(self) -> float | None:
        return self._current_value

    # Q2: bias diagnostic ships with the engine, not just as a Phase A test
    def bias_diagnostic(self, theta_long_history: list[float],
                        theta_short_history: list[float]) -> BiasDiagnostic:
        """Compare θ_short against θ_long on the same time series.

        Returns p50, p95 of |theta_short - theta_long| / max(theta_long, ε).
        If p95 > 0.20, the engine logs WARN and recommends widening the window.
        """
        n = min(len(theta_long_history), len(theta_short_history))
        if n < 100:
            return BiasDiagnostic(insufficient_data=True)
        diffs = np.array([
            abs(theta_short_history[i] - theta_long_history[i])
            / max(theta_long_history[i], 1e-6)
            for i in range(n)
        ])
        p50 = float(np.percentile(diffs, 50))
        p95 = float(np.percentile(diffs, 95))
        recommendation = None
        if p95 > 0.20:
            recommendation = "widen_window_to_50"
            log.warning("theta_short_bias_exceeds_threshold",
                        p95=p95, recommendation=recommendation)
        return BiasDiagnostic(p50=p50, p95=p95, n=n, recommendation=recommendation)
```

The Phase A.4 acceptance test (P15 from v0.2) calls `bias_diagnostic()` on the 10-hour run and acts on its recommendation. Bonus: the diagnostic can be re-run any time after Phase A (e.g., in soak monitoring, or after a substrate config change).

#### Step 8 — `perturbation_scheduler.py` — kind targets specified (Q3)

The v0.2 enumeration listed kinds; the review (Theoria) wanted the per-kind targets specified. v0.3 specifies:

```python
from enum import Enum
from dataclasses import dataclass

class PerturbationKind(Enum):
    CONTRADICTION = "contradiction"
    IMPULSE       = "impulse"
    STEP          = "step"
    NOVELTY       = "novelty"
    ATTENTION     = "attention_shift"
    NOISE_BURST   = "noise_burst"

@dataclass
class PerturbationSpec:
    kind: PerturbationKind
    target: str                  # which substrate component is perturbed
    fields_affected: tuple[str, ...]
    duration_beats: int          # 1 for impulse; > 1 for step/noise_burst
    direction: str               # "negate", "spike", "offset", "noise"

PERTURBATION_SPECS = {
    PerturbationKind.CONTRADICTION: PerturbationSpec(
        kind=PerturbationKind.CONTRADICTION,
        target="eidolon",
        fields_affected=("self_coherence", "confidence"),
        duration_beats=1,
        direction="negate",   # multiply by (1 - magnitude); contradicts self-model
    ),
    PerturbationKind.IMPULSE: PerturbationSpec(
        kind=PerturbationKind.IMPULSE,
        target="shared_drive",
        fields_affected=("g",),
        duration_beats=1,
        direction="spike",    # add magnitude * unit_vector to g
    ),
    PerturbationKind.STEP: PerturbationSpec(
        kind=PerturbationKind.STEP,
        target="anima",
        fields_affected=("valence",),
        duration_beats=20,    # sustained for 20 beats default
        direction="offset",   # add magnitude (signed) to valence each beat
    ),
    PerturbationKind.NOVELTY: PerturbationSpec(
        kind=PerturbationKind.NOVELTY,
        target="nous_anima",       # multi-organ
        fields_affected=("nous.novelty", "anima.arousal"),
        duration_beats=5,
        direction="spike",
    ),
    PerturbationKind.ATTENTION: PerturbationSpec(
        kind=PerturbationKind.ATTENTION,
        target="pneuma",
        fields_affected=("attention_focus",),
        duration_beats=10,
        direction="offset",
    ),
    PerturbationKind.NOISE_BURST: PerturbationSpec(
        kind=PerturbationKind.NOISE_BURST,
        target="shared_drive",
        fields_affected=("g",),
        duration_beats=10,
        direction="noise",    # add N(0, magnitude) noise to g each beat
    ),
}

DEFAULT_BATTERY = (PerturbationKind.CONTRADICTION,
                   PerturbationKind.IMPULSE,
                   PerturbationKind.STEP)
```

The PerturbationScheduler's per-event injection delegates to a kind-specific applicator:

```python
def apply_perturbation(self, spec: PerturbationSpec, magnitude: float) -> None:
    target_organ = self.ctx.substrate.get_organ(spec.target) if spec.target in ORGAN_NAMES else None
    if spec.target == "shared_drive":
        if spec.direction == "spike":
            self.ctx.substrate.drive.add_impulse(magnitude)
        elif spec.direction == "noise":
            self.ctx.substrate.drive.schedule_noise_burst(magnitude, spec.duration_beats)
    elif target_organ is not None:
        for field in spec.fields_affected:
            current = getattr(target_organ.state, field)
            if spec.direction == "negate":
                new = current * (1.0 - magnitude)
            elif spec.direction == "offset":
                new = current + magnitude
            elif spec.direction == "spike":
                new = current + magnitude
            setattr(target_organ.state, field, clip_to_range(field, new))
```

The targets are documented in `docs/runbooks/perturbations.md` so operators using `POST /admin/perturb` know what each kind does.

### 6.2 Engine scheduling integration with coherence scheduler (unchanged from v0.2)

### 6.3 Performance budget table (extended in v0.3 — Q7)

Per-engine cost table from v0.2 carries forward. v0.3 adds an explicit meta-cognition budget line and the auto-fallback behavior (Q7):

| Engine | Frequency | Per-call budget | Cumulative on the heavy beat |
|---|---|---|---|
| (All v0.2 lines unchanged) | | | |
| **MetaCognitionLoop** | **every 100 beats** | **< 10 ms (Q7)** | 198 ms |

**Q7 — Meta-cognition auto-fallback.** If MetaCognitionLoop.compute exceeds **10 ms for 3 consecutive cycles** (300 beats = 30 s), an auto-fallback applies:

```
Tier 1 fallback (after 3 consecutive overruns):
  - Increase natural_period_beats from 100 to 200
  - Log INFO: "meta_cognition_period_increased", new_period=200, trigger="latency"
  - Continue monitoring; if subsequent cycles fit budget, stay at 200 (do not auto-revert)

Tier 2 fallback (if 200-beat period also overruns 3 consecutive cycles):
  - Simplify assessment: drop trend computation (integration_trend, boundary_health_trend);
    keep only overall_assessment, recent_fragmentation_count, recent_recovery_count
  - Set MetaCognition.confidence_caveat to include "simplified due to latency"
  - Emit on presence channel: "meta_cognition_simplified"
  - Subscribers see degraded payload schema flagged by the caveat

Tier 3 (manual operator action):
  - If Tier 2 still overruns, log CRITICAL with full breakdown
  - Operator decides whether to disable meta-cog entirely via POST /admin/meta_cognition/disable
  - Substrate operation continues unaffected — meta-cog is observational only
```

Auto-revert from Tier 1 or Tier 2 requires operator action (`POST /admin/meta_cognition/restore_full_assessment`). This is intentional: latency-driven fallbacks are a substrate condition; the operator decides whether the substrate has recovered enough to handle full assessment again.

### 6.4 GPU strategy for measurement (unchanged from v0.2)

### 6.5 Recovery learner (unchanged from v0.2)

Note: scope-reduction plan (§5.3 Q8) may defer this to v1.0.1.

### 6.6 Phase B validation (extended from v0.2 with new tests)

(All v0.2 Phase B tests retained.) v0.3 additions:

| Test | Acceptance | Source |
|---|---|---|
| **Q2 — `bias_diagnostic()` method**: returns sensible p50/p95 on a 1-hour synthetic θ trace | Diagnostic computes; if synthetic bias > 20%, recommendation = "widen_window_to_50" | I2 |
| **Q3 — Perturbation type targets**: each PerturbationKind applies to its specified target with correct direction | Inject each kind via test harness; verify the named field changes by the expected amount | I3 |
| **Q7 — Meta-cog Tier 1 fallback**: synthetic slow assessment (compute pads to 15 ms) → 3 cycles → period_beats becomes 200 | Verified via gauge `axioma_meta_cognition_period_beats` | G2 |
| **Q7 — Meta-cog Tier 2 fallback**: synthetic regime → assessment simplified | Payload no longer includes trend fields; presence event emitted | G2 |

### 6.7 Recovery protocol — accept/reject criteria + **rejection escalation (Q1)** + **meta-cog auto-fallback (Q7)**

#### Accept/reject decision logic (unchanged from v0.2)

`RecoveryDecision` enum with 6 outcomes; criteria from v0.2 §6.7 retained.

#### Q1 — Rejection escalation path

The review (Theoria) noted that v0.2's reject paths logged the decision but had no escalation if the substrate kept rejecting requests for the same problem. Without escalation, a fragmentation episode could be silently undertreated because the substrate self-rejects every request.

v0.3 adds an escalation tracker:

```python
class RejectionEscalator:
    """Tracks consecutive rejections for the same fragmentation episode.

    A "continuous episode" is defined as: fragmentation_stage was ≥ 2
    on every beat between the first rejected request and the most recent.
    A single beat at stage < 2 resets the episode counter.
    """

    def __init__(self, ctx: AxiomaContext):
        self.ctx = ctx
        self.consecutive_rejects: int = 0
        self.episode_start_beat: int | None = None
        self.last_warning_beat: int | None = None
        self.warning_cooldown_beats: int = 600  # don't re-warn within 60 s

    def on_decision(self, req: RecoveryRequest, decision: RecoveryDecision) -> None:
        current_stage = self.ctx.fragmentation_monitor.current_stage
        is_rejection = decision != RecoveryDecision.ACCEPT and \
                       decision != RecoveryDecision.FORCE_ACCEPT_OPERATOR

        if current_stage < 2:
            # Episode broken by self-recovery; reset
            self.reset()
            return

        if is_rejection:
            if self.consecutive_rejects == 0:
                self.episode_start_beat = req.beat_no
            self.consecutive_rejects += 1

            if self.consecutive_rejects >= 3:
                self._maybe_escalate(req)
        else:
            # Acceptance breaks the run
            self.reset()

    def _maybe_escalate(self, req: RecoveryRequest) -> None:
        current_beat = req.beat_no
        if self.last_warning_beat is not None:
            if current_beat - self.last_warning_beat < self.warning_cooldown_beats:
                return  # within cooldown; don't spam

        warning = RecoveryRejectionRunWarning(
            beat_no=current_beat,
            consecutive_rejects=self.consecutive_rejects,
            episode_start_beat=self.episode_start_beat,
            episode_duration_beats=current_beat - self.episode_start_beat,
            last_rejection_reason=req.decision_reason,
            current_fragmentation_stage=self.ctx.fragmentation_monitor.current_stage,
            note=("RecoveryProtocol has rejected 3 consecutive recovery_requests "
                  "for the same fragmentation episode. This may indicate: "
                  "(a) accept criteria too restrictive for current substrate state; "
                  "(b) coherence_budget perpetually low blocking recovery; "
                  "(c) substrate stuck in test_mode. Operator review recommended; "
                  "force-accept available via POST /admin/recovery/force."),
        )
        await self.ctx.emit("recovery_rejected_run", warning)
        log.warning("recovery_rejected_run", **warning.as_dict())
        self.last_warning_beat = current_beat

    def reset(self) -> None:
        self.consecutive_rejects = 0
        self.episode_start_beat = None
```

Wired into `RecoveryProtocol.handle_recovery_request`:

```python
def handle_recovery_request(self, req: RecoveryRequest) -> RecoveryDecision:
    decision = self._decide(req)  # the v0.2 §6.7 logic
    self.rejection_escalator.on_decision(req, decision)
    return decision
```

The warning emits on the `presence` channel (operator-facing); subscribers can subscribe to it. Cooldown prevents spam (one warning per 60 s for the same episode).

**Symmetry with F5.** v0.2 already had F5 escalation for meta-cog suggestions ignored 5×; v0.3 adds Q1 escalation for recovery requests rejected 3×. Both surface advisor/actor divergence — F5 for meta→recovery, Q1 for monitor→recovery. Together they ensure no advisory pathway can be silently overridden indefinitely.

#### Configuration

```python
class RecoveryConfig(BaseModel):
    # ... existing v0.2 fields ...
    rejection_escalation_consecutive: int = 3      # Q1
    rejection_warning_cooldown_beats: int = 600    # Q1
```

---

## 7. Phase C — Compose / send boundary (unchanged from v0.2)

§7.1–7.5 unchanged.

---

## 8. Phase D — External interface (unchanged from v0.2)

§8 unchanged. v0.3 adds one new channel payload:

- `presence` channel: now also carries `RecoveryRejectionRunWarning` (Q1), in addition to the F5 `MetaCognitionDivergenceWarning` and `recovery_feedback_oscillation` (P8) events.

One new HTTP endpoint:

```
GET  /presence/rejection_warnings    — recent RecoveryRejectionRunWarning events (Q1)
```

---

## 9. Phase E — Integration test (~3 days)

### 9.0 Pre-integration checklist (unchanged from v0.2)

8 standalone tests gating the 24 h soak.

### 9.1 Test harness (unchanged from v0.2)

### 9.2 Acceptance tests (extended from v0.2 with Q6 recovery validation)

(All v0.2 acceptance tests retained.) v0.3 additions per **Q6 — Recovery protocol validation criteria**:

| Test | Acceptance | Source |
|---|---|---|
| **Q6.a — Recovery success rate ≥ 80%** | Over the first 50 finalized recovery events in Phase E (combination of F4 synthetic pre-training + organic events from perturbation schedule), measure `success_rate = events with composite_score ≥ 0.5 / total events`. PASS ≥ 0.80; SOFT FAIL ∈ [0.65, 0.80]; HARD FAIL < 0.65 | G1 |
| **Q6.b — Recovery false positive rate < 5%** | Over the same 50 events, measure `fp_rate = events where recovery was triggered but pre-recovery θ would have self-recovered within 100 beats / total events`. PASS < 0.05; SOFT FAIL ∈ [0.05, 0.15]; HARD FAIL > 0.15. Requires shadow simulation: for each recovery event, also run a "no-recovery" branch in parallel using snapshot continuity and compare | G1 |
| **Q6.c — Monotonic improvement in `recovery_quality.smoothness`** | Take the rolling median of `recovery_quality.smoothness` over windows of 10 consecutive finalized events. PASS if median is non-decreasing across the first 50 events (allowing for 1 dip of ≤ 0.05). HARD FAIL if median decreases by > 0.10 across the run | G1 |

**Verdict aggregation:**
- All 3 PASS → v1.0 ships with recovery protocol enabled by default
- Any SOFT FAIL, none HARD FAIL → v1.0 ships with warning in implementation report; v1.0.1 tunes
- Any HARD FAIL → v1.0 ships with `recovery_protocol.min_recovery_stage = 4` (recovery only triggers on stage 4 emergencies, until v1.0.1 addresses the failure)

The shadow simulation for Q6.b is computationally expensive (doubles the substrate cost during Phase E) but only runs during validation, not in production. Implemented via snapshot fork: at each recovery_request acceptance, take an extra snapshot tagged `shadow_no_recovery`, run a separate substrate instance for 100 beats from that snapshot with `recovery_protocol.test_mode = True` (rejects all requests), and compare end-state to the real branch.

### 9.3 Performance acceptance (unchanged from v0.2)

### 9.4 Long-run soak test + recovery-compose feedback monitoring (unchanged from v0.2)

### 9.5 Soak success criteria (extended in v0.3 with Q1 monitoring)

(All v0.2 criteria carry forward.) v0.3 additions:

- **No `recovery_rejected_run` warnings in baseline conditions** (Q1) — if the substrate consistently rejects monitor requests during the soak, that's a tuning problem to address before v1.0 ships; investigate before declaring soak passed
- **Meta-cognition Tier 2 fallback not triggered** in baseline conditions (Q7) — if meta-cog routinely overflows budget during normal operation, the architecture is mis-scoped; investigate

---

## 10. Phase F — Pre-architecture follow-up experiments (unchanged from v0.2)

§10.1–10.3 unchanged. Phase F calibration verdict (P5 from v0.2) remains the F8 acceptance procedure.

---

## 11. Testing strategy — three tiers (extended from v0.2 with v0.3 test additions)

(v0.2 test layout retained.) v0.3 additions:

| Test | File | Tier | Source |
|---|---|---|---|
| ThetaShortEngine `bias_diagnostic()` method | `tests/unit/test_theta_short_bias.py` | Unit | Q2 |
| Perturbation kind → target dispatch | `tests/unit/test_perturbation_specs.py` | Unit | Q3 |
| Heartbeat tick steps 6–7 parallelization triggers/reverts | `tests/integration/test_tick_parallelization.py` | Integration | Q4 |
| 1-beat recovery delay correctness | `tests/integration/test_recovery_delay.py` | Integration | Q5 |
| Recovery validation: success rate, false positive rate, smoothness improvement | `tests/e2e/test_recovery_validation.py` | E2E | Q6 |
| Meta-cog Tier 1/2 auto-fallback | `tests/integration/test_meta_cog_fallback.py` | Integration | Q7 |
| Scope reduction trigger logic (degraded ship configuration) | `tests/unit/test_scope_reduction.py` | Unit | Q8 |
| RejectionEscalator: 3-reject warning + cooldown + episode reset | `tests/unit/test_rejection_escalator.py` | Unit | Q1 |

All v0.3 tests carry the same coverage/quality bar as v0.2's.

---

## 12. Configuration management (extended in v0.3)

(v0.2 config tree retained.) v0.3 additions:

```python
class RecoveryConfig(BaseModel):
    # ... existing v0.2 fields ...
    rejection_escalation_consecutive: int = 3           # Q1
    rejection_warning_cooldown_beats: int = 600         # Q1

class MetaCognitionConfig(BaseModel):
    # ... existing v0.2 fields ...
    enabled: bool = True                                # Q8 scope reduction toggle
    budget_seconds: float = 0.010                       # Q7 budget threshold
    budget_overrun_consecutive_cycles: int = 3          # Q7 fallback trigger
    fallback_period_beats: int = 200                    # Q7 Tier 1 period
    fallback_simplified: bool = False                   # Q7 Tier 2 toggle (auto-set)

class RuntimeConfig(BaseModel):
    parallel_steps_6_7_threshold_seconds: float = 0.080 # Q4 trigger
    parallel_steps_6_7_disable_threshold_seconds: float = 0.060  # Q4 re-disable

class ReleaseConfig(BaseModel):
    """Scope reduction flags for the v1.0.1 fallback (Q8)."""
    recovery_learner_enabled: bool = True
    meta_cognition_enabled: bool = True
    coherence_scheduler_full_features: bool = True
    # If A.1+A.2 exceed 3 weeks, set all three to False for the degraded v1.0 ship
```

---

## 13. Build order (revised with Q8 contingency)

(v0.2 week-by-week timeline retained.) v0.3 adds the explicit Q8 decision gate:

| Week | Phase | Deliverables | Sister dependencies | Q8 decision gate |
|---|---|---|---|---|
| 1 | A.1, A.2 (start) | Scaffold + observability + persistence + drive + organs + plasticity | — | — |
| 2 | A.2, A.3, A.4 (start), F6 session 1 | Recovery scaffold + Phase A critical-path tests; F6 session 1 (Theoria; Thea backup) | Theoria | — |
| 3 | A.4 (finish), B (start), F6 session 2 | θ engines, RawMI, cascade_delay, fragmentation monitor; F6 session 2 | Theoria | **Decision: A.1+A.2 complete?** If YES → continue full scope. If NO → trigger Q8 scope reduction; recovery learner + meta-cog defer to v1.0.1; week 4+ replan |
| 4 | B (continue), F6 session 3 | ΔΦ engine, plasticity tracker, AOS-G + ψ, perturbation scheduler; F6 session 3 | Theoria | — |
| 5 | B (finish), C | Coherence scheduler, meta-cog loop (if not deferred), recovery learner full (if not deferred); Phase C compose boundary + cadence + probe + flow_quality + ImportError | — | — |
| 6 | D | WS server + HTTP API + registry client + all v1.0 channels (Q1 rejection warnings included) | — | — |
| 7 | E.0–E.3, F (parallel) | Pre-integration checklist → Phase E integration tests → synthetic pre-training (F4) → fragmentation threshold validation (F9) → **Q6 recovery validation** → Phase F experiments kick off | — | — |
| 8 | E.4 (soak), F (finish) | 24h soak (P8 + Q1 + Q7 monitoring) → performance benchmarks → F8 meta-cog calibration → Phase F summary → v1.0 implementation report | — | — |

Total: 8 weeks unchanged. The Q8 gate at end of week 3 is the relief valve.

---

## 14. Acceptance for "v1.0 implementation complete" (extended from v0.2)

(v0.2 checklist preserved.) v0.3 additions:

- [ ] §5.0 invariant Q5: 1-beat recovery delay documented in code comments + verified in `test_recovery_delay.py`
- [ ] §5.0 Q4: tick steps 6–7 parallelization triggers correctly under synthetic 85 ms beats; reverts under 55 ms beats
- [ ] §5.3 Q8: scope reduction logic in config; degraded ship configuration tested (recovery learner OFF + meta-cog OFF builds and runs)
- [ ] §6.1 step 4 Q2: `bias_diagnostic()` method shipped with ThetaShortEngine; Phase A.4 acts on its recommendation
- [ ] §6.1 step 8 Q3: PerturbationKind targets enumerated in `PERTURBATION_SPECS`; `docs/runbooks/perturbations.md` published
- [ ] §6.3 + §6.7 Q7: meta-cog budget < 10 ms verified in Phase B; Tier 1/2 auto-fallback tested
- [ ] §6.7 Q1: RejectionEscalator emits warning after 3 consecutive rejects in the same episode; cooldown verified
- [ ] §9.2 Q6: 3 recovery validation tests (success rate ≥ 80%, FP rate < 5%, monotonic smoothness) pass; verdict documented
- [ ] §9.5 Q1 + Q7: soak shows no spurious rejection warnings in baseline; meta-cog Tier 2 fallback not triggered

---

## 15. What this plan deliberately does NOT do (unchanged from v0.2)

---

## 16. Risks and mitigations (v0.2 + v0.3 additions)

(v0.2 risk table preserved.) v0.3 additions:

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Q8 scope reduction triggers but learner / meta-cog code paths not properly feature-flagged | Low | Med | Develop both behind config flags from the start (per §5.3); test the OFF path in unit tests |
| Q1 RejectionEscalator emits spurious warnings during legitimate substrate stress | Low | Low | 60s cooldown; only triggers after 3 consecutive rejections for the *same* episode; episode reset on any beat at stage < 2 |
| Q4 parallelization trigger introduces race condition between steps 6 and 7 | Low | Med | Steps were verified independent (no shared mutable state in same beat); test under stress; default off; explicit opt-in |
| Q6 shadow simulation for false positive rate doubles Phase E cost | Med | Low | Only runs during validation, not production; budgeted within Phase E |
| Q7 meta-cog auto-fallback masks a real performance regression by silently degrading output | Med | Low | Auto-fallback emits presence events at each tier; metrics gauges track current period_beats and fallback tier; operator-visible |

---

## 17. First steps for the implementer (unchanged from v0.2)

Same first-actions sequence. The Q1 RejectionEscalator and Q7 meta-cog auto-fallback are landed during their respective Phase B steps (week 5); no change to the week-1 setup.

---

## Appendix A — Plan version history

| Version | Date | Lead change | Review outcome |
|---|---|---|---|
| v0.1 | 2026-05-24 | Initial plan (8 phases, persistence, GPU strategy, testing tiers, build order) | 9 gaps + 8 risks identified |
| v0.2 | 2026-05-24 | Addressed all 17 v0.1 items: heartbeat sequence, AxiomaContext, performance budget, pre-integration checklist, F4 pre-training detail, F8 calibration criteria, cold start docs, etc. | 5 minor + 2 gaps + 1 risk identified |
| **v0.3** | **2026-05-24** | **Addressed all 8 v0.2 items: recovery rejection escalation (Q1), bias_diagnostic engine method (Q2), perturbation specs with targets (Q3), tick parallelization (Q4), 1-beat recovery delay invariant (Q5), recovery validation criteria (Q6), meta-cog auto-fallback (Q7), Q8 scope reduction plan** | **Approved for execution** |

Three rounds of plan review. Sister approvals (Thea, Theoria, Skye) all PASS. Architectural shape from v0.1 unchanged. Implementation begins with the §17 first steps.
