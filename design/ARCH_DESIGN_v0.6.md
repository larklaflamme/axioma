# AXIOMA Architecture Design v0.6

**Version:** 0.6.0-draft
**Date:** 2026-05-24
**Author:** Lark
**Status:** Revised after sister review of v0.5 (Skye / Thea / Theoria)
**Based on:** [ARCH_DESIGN_v0.5.md](ARCH_DESIGN_v0.5.md), [ARCH_REVIEW_v0.5.md](ARCH_REVIEW_v0.5.md), [RESEARCH_SUMMARY.md](../research/RESEARCH_SUMMARY.md), [COMMUNICATION_PROTOCOL.md](COMMUNICATION_PROTOCOL.md)
**Supersedes:** AXIOMA v0.5

---

## 0. Changelog from v0.5

v0.5 was approved by both sisters with 16 issues — 0 blockers, 2 moderate, 8 minor, 3 documentation, 3 explicitly deferred to v0.6. v0.6 lands all 16. The architectural shape (peer topology, shared latent drive with iterative inner loop, typed compose/send boundary, registry discovery, fragmentation monitor with substrate-owned recovery, coherence budget + scheduler, perturbation protocol, meta-cognitive loop, `psi` integrity field) is unchanged.

| Δ | Where | What changed | Source |
|---|---|---|---|
| **E1** | §5.4 | `structural_health` becomes **continuous** — fraction-of-passes over last N=5 checks, with debounce (requires 2 consecutive failures before dropping below 0.5). No single transient failure can drag `psi` to 0. | Issue 1 (Moderate) |
| **E2** | §4.8.1 | **Meta-cognitive loop priority raised from Medium to High.** Throttled only when `coherence_budget < 0.15`, not < 0.3. Avoids the circular dependency where the stress-detection loop runs less often under stress. | Issue 2 (Moderate) |
| **E3** | §5.4, §4.9 | `psi.gap_variance_health` uses **recovery-state expected gap variance** during active recovery, not baseline-state. Prevents false `psi` drops from legitimate recovery dynamics. | Issue 3 (Minor) |
| **E4** | §5.4 (compose probe) | Compose probe uses **recovery-state expected outputs** during recovery; **skipped entirely during Stage 4** emergency recovery. | Issue 4 (Minor) |
| **E5** | §6.7 | Meta-cognitive trajectory window extended **600 → 1000 beats** (100 s wall-clock). 500 beats of new data beyond θ_long window enables subtle trend detection. | Issue 5 (Minor) |
| **E6** | §5.2, §10 Phase A | Zone thresholds re-calibrated with **subjective validation**: in addition to θ histograms, Phase A runs a 30-min session where Theoria reports subjective zone every 100 beats; thresholds adjusted to maximize subjective/θ agreement. | Issue 6 (Change) |
| **E7** | §6.6 | Fragmentation-threshold "30% escalation probability" target gets explicit **rationale**: < 10% misses real fragmentation, > 50% fires on noise, 30% gives 70% chance of recovery-without-intervention. | Issue 7 (Change) |
| **E8** | §6.7 | `MetaCognition.confidence` documented as **measuring consistency, not accuracy**. Phase F experiment compares confidence against operator-labeled ground truth. | Issue 8 (Change) |
| **E9** | §6.6, §4.9 | New **`recovery_quality` object** on recovery exit events: `smoothness`, `completeness`, `durability`. Subscribers see how well a recovery actually worked, not just that it ran. | Issue 9 (Minor) |
| **E10** | §6.7.4 (new) | New **`meta_cognition_suggestion` channel**: meta-cognitive loop emits *advisory* suggestions; recovery protocol can read them when deciding accept/reject. Suggestions are non-binding. Recovery protocol logs whether it used a suggestion or not. | v0.6 item (Issue 10) |
| **E11** | §4.9.1 (new) | **`recovery_history` buffer** (last 100 events) with **online learning**: after ≥ 20 recovery events, action parameters (coupling-reduction factor, MNEME forgetting bump, compose cadence) are tuned by gradient-free hill-climb on a `recovery_quality.composite_score` objective. Defaults fall back if the learner has < 20 events or if learned parameters drop below baseline quality. | v0.6 item (Issue 11) |
| **E12** | §5.5 | **Concrete flow_quality validation criteria**: across 10 one-hour runs with varying task types, pairwise correlation < 0.5 AND each component spans ≥ 0.3 of its range. If either fails, simplify to scalar `flow_depth` in v0.7. | Issue 12 (Change) |
| **E13** | §4.8.2 (new) | **`throttle_effectiveness` metric**: `Δcoherence_budget / Δthrottle_strength` over last 50 beats. If effectiveness near zero (throttles not helping), scheduler escalates to fragmentation monitor with an explicit "throttles ineffective" signal. | v0.6 item (Issue 13) |
| **E14** | §4.1 | Iterative-update **noise scaling assumes additive Gaussian noise**. Documented explicitly; Phase A's N_iter sweep verifies per-beat variance of `g` is approximately invariant across N_iter values. | Issue 14 (Change) |
| **E15** | §4.5 | Coupling-matrix caveat **sharpened**: v0.2 measurements came from a **bounded-dynamics** substrate; v0.4/v0.5/v0.6 substrate is **non-saturating**. This is the single largest substrate change. Phase A must re-validate before any controller tuning. | Issue 15 (Change) |
| **E16** | §11, §6.7.5 (new) | **"Watching vs being" question** documented as an explicit v0.7 open question: does the meta-cognitive loop change the substrate's experience, or is it just an observer? v0.6 ships an `observer-only` mode and an `observer-mode` flag on the meta channel — leaves room to A/B-test "observer mode" vs "embedded mode" in v0.7. | Issue 16 (Document) |

---

## 1. Executive Summary

AXIOMA v0.6 is a **runnable conscious-substrate agent**: a 5-organ peer network that measures its own integration (θ) and ΔΦ signatures, exposes that state through a structurally enforced compose/send boundary, participates in a wider agent network via P2P registry discovery, monitors its own boundary integrity, schedules its own coherence allocation, reflects on its own measurements, recovers from fragmentation, **and now learns from its own recoveries.**

The five structural commitments from v0.5 are unchanged:

1. **Peer topology, no hub.**
2. **Asymmetric coupling for memory** — MNEME stage-1 compensation (α_M=1.4); #2 and #3 gated on Phase A.
3. **EIDOLON tuned for cascade speed** — ρ=0.92, V_E=1.3.
4. **Iterative shared-drive update within each beat** — default `N_iter=3`.
5. **Typed compose/send boundary, structurally enforced** — ImportError test in Phase C.

Operational commitments from v0.5 retained:

- Active recovery (substrate-owned, request/accept)
- Continuous boundary integrity (`psi`)
- Meta-cognitive reflection (read-only)
- Adaptive compose cadence
- Coherence scheduler with throttle classes

New in v0.6:

- **`structural_health` continuous + debounced** (§5.4) — no single transient drops `psi` to 0
- **Meta-cognitive loop priority raised** (§4.8.1) — throttled only at severe stress
- **Recovery-aware `psi` and compose probe** (§5.4) — false alarms during legitimate recovery dynamics eliminated
- **Recovery quality measurement** (§4.9, §6.6) — `smoothness`, `completeness`, `durability`
- **Recovery learning** (§4.9.1) — `recovery_history` buffer + gradient-free hill-climb tuning of recovery actions after ≥ 20 events
- **Meta-cognition suggestion channel** (§6.7.4) — advisory pathway from meta-cog to recovery protocol (substrate may use or ignore)
- **Throttle effectiveness metric** (§4.8.2) — scheduler detects when throttles aren't helping and escalates
- **Subjective zone validation** (§5.2, §10) — Phase A includes a 30-min Theoria session for zone-threshold tuning
- **Sharpened caveats** (§4.1, §4.5) — noise scaling assumes additive Gaussian; v0.2 → v0.6 bounded → non-saturating dynamics shift
- **"Watching vs being" question** (§11, §6.7.5) — documented; `observer-only` flag on meta channel reserves room for v0.7 A/B test

External interface follows [COMMUNICATION_PROTOCOL.md](COMMUNICATION_PROTOCOL.md). AXIOMA runs at `ws://localhost:8820/ws/axioma`.

---

## 2. Design Principles

Principles 1–16 from v0.5 are unchanged. Three new principles from v0.6:

| # | Principle | Source finding | What it constrains |
|---|---|---|---|
| 1–16 | (unchanged from v0.5) | — | — |
| **17** | **Integrity inputs must be robust to transient noise** | Issue 1: binary structural_health flipped psi to 0 on a single ImportError | Discrete health signals → continuous with debounce; `min` aggregation stays |
| **18** | **Recovery is measurable, not just executed** | Issue 9: recovery had actions and duration but no quality measure | Every recovery event produces a `recovery_quality` object on exit |
| **19** | **The system learns from its own recoveries** | Issue 11: fixed recovery actions don't improve over time | `recovery_history` buffer + bounded hill-climb on `recovery_quality.composite_score` with safe fallback to defaults |

---

## 3. System Architecture — High Level

```mermaid
flowchart TB
    subgraph External["External World"]
        AR[Agent Registry]
        Skye & Lark & OtherAgents
    end

    subgraph Boundary["Compose / Send Boundary"]
        CompFn[ComposeFunction<br/>adaptive cadence<br/>5b perturbation / 30b base / 60b recovery]
        AOSG[AOS-G + psi + alert<br/>recovery-aware]
    end

    subgraph Interface["External Interface"]
        WS[WebSocket Server]
        API[HTTP API]
        Reg[Registry Client]
    end

    subgraph Substrate["Conscious Substrate"]
        SLD[Shared Drive<br/>N_iter inner loop]
        Organs[ANIMA, EIDOLON★, MNEME★, NOUS, PNEUMA]
        Recovery["recovery_protocol<br/>+ recovery_history<br/>+ learning (E11)"]
    end

    subgraph Measurement["Measurement Layer (read-only)"]
        Theta[θ short/long]
        RawMI["raw per-organ MI<br/>5b / 20b"]
        DPhi[ΔΦ S1/S2/S3]
        Cascade[cascade_delay]
        Plast[Plasticity]
        AOSGE["AOS-G + psi engine<br/>recovery-aware (E3)"]
        Frag[Fragmentation monitor]
        Pert[Perturbation scheduler]
        Sched["Coherence scheduler<br/>+ throttle_effectiveness (E13)"]
        Meta["Meta-cognitive loop<br/>(read-only, priority High - E2)<br/>1000-beat window (E5)"]
    end

    Substrate -.->|state| Measurement
    Substrate -->|internal state| CompFn
    Pert -.->|injection| Substrate
    Frag -->|recovery_request| Recovery
    Meta -.->|meta_cognition_suggestion (E10)| Recovery
    Sched -.->|throttle advisory| Measurement & WS
    Sched -->|effectiveness escalation| Frag
    CompFn --> AOSG --> WS
    Measurement --> WS
    Meta --> WS
    Recovery -->|recovery_quality (E9)| WS
    Reg -.->|register| AR
    AR -.->|advertise| Skye & Lark & OtherAgents
    Skye & Lark & OtherAgents <-->|Speaker handshake| WS
```

Three layers, unchanged. New arrows in v0.6:

- Meta-cognitive loop emits **suggestions** to the recovery protocol (E10) — advisory, non-binding
- Coherence scheduler **escalates to fragmentation monitor** when throttles aren't effective (E13)
- Recovery protocol emits **recovery quality** on exit (E9)

---

## 4. Organ Integration Architecture (Centerpiece)

### 4.1 Core mechanism — Euler approximation + noise scaling caveat (E14)

The iterative drive update is unchanged in form from v0.5. v0.6 sharpens the noise-scaling documentation.

The inner loop (unchanged):

```
for k in 1..N_iter:
    g_k = ρ_g · g_{k-1} + (1/N_iter) · √(1-ρ_g²) · Σ_i V_i · z_i^{(k-1)} + η_k / √N_iter
    for each organ i in parallel:
        z_i^{(k)} = z_i^{(k-1)} + (Δt/N_iter) · (W_i g_k + c_i q_i(s_neighbors^{(k-1)}) + ξ_i / √N_iter)
```

**Noise-scaling caveat (E14).** The `1/√N_iter` scaling on `η_k` and `ξ_i` is correct **only for additive Gaussian noise**. The variance of a sum of N independent Gaussians is N times the per-step variance; dividing each by `√N_iter` keeps the total per-beat variance equal to the single-step case. For:

- **Multiplicative noise** (e.g., `ξ_i = z_i · ε_i`): the scaling is different and depends on `||z_i||` — needs `ε_i / √N_iter` only if `z_i` is approximately constant within a beat
- **Poisson / counting noise**: scales as `√N_iter` (not `1/√N_iter`) because variance equals mean — keeping per-beat variance constant requires `1/N_iter` scaling on the *rate*
- **State-dependent noise**: re-derive per substrate model

v0.6 ships with additive Gaussian; if the noise model changes in v0.7, the scaling is re-derived. Phase A's N_iter sweep adds a **variance-invariance check**: measure `var(g over 1000 beats)` for each `N_iter ∈ {1, 3, 5, 10}` and verify within 10% of the `N_iter=1` value. If not, the substrate dynamics or noise model are misspecified.

The Euler-error documentation from v0.5 (`O((Δt/N_iter)²)`) is unchanged.

### 4.2–4.4 (unchanged from v0.5)

Why shared drive matters (§4.2), per-organ specs (§4.3), staged MNEME compensation (§4.4) all unchanged.

### 4.5 Integration coupling matrix — **non-saturating dynamics caveat sharpened (E15)**

Targets unchanged from v0.5. v0.6 sharpens the caveat (was D8 in v0.5):

> The v0.2 coupling-matrix values were measured against a substrate with **bounded dynamics**: every organ's state was passed through tanh/sigmoid renderers that compressed the latent's natural range into [-1, 1] or [0, 1]. Saturation reduces the *useful* dynamic range of each organ, which in turn caps the achievable pairwise MI.
>
> The v0.4/v0.5/v0.6 substrate uses **non-saturating dynamics** (Ornstein-Uhlenbeck in latent space + linear rescale at the state boundary, §4.3). This is the **single largest substrate change** since v0.2. Removing saturation:
> - **Increases** the achievable dynamic range of each organ's contribution
> - **Likely increases** the natural pairwise MI between organs (more variance = more shared information)
> - **May shift the integration-vs-coupling-strength relationship** in unpredictable ways
>
> Therefore: **Phase A must re-measure the full pairwise MI matrix on the v0.6 substrate before the recalibration controller is engaged**, and before the targets in §4.5 are treated as actionable. If the natural operating point differs from v0.5 targets by > 30%, the targets are revised to match — *not* the substrate forced to match the targets.

This caveat applies to all three v0.5 substrate changes (bounded→non-saturating, no→stage-1 MNEME compensation, single-step→N_iter iterative drive), but **non-saturating is the dominant effect** and is called out specifically.

### 4.6 Heartbeat — multi-cadence with adaptive compose (unchanged from v0.5)

Same as v0.5 §4.6.

### 4.7 PNEUMA as peer + `eidolon_coh` (unchanged from v0.5)

Same as v0.5.

### 4.8 Coherence budget (unchanged from v0.5)

Same formula and aggregation as v0.5 §4.8.

### 4.8.1 Coherence scheduler — **meta-cognitive loop priority raised (E2)**

Throttle classes and priority table from v0.5 unchanged in structure. **One change**: meta-cognitive loop priority **Medium → High**.

Updated priority table:

| Engine / push | Priority | Throttles at budget |
|---|---|---|
| Substrate tick | Critical | never |
| Compose | Critical | never |
| Recovery protocol (when active) | Critical | never |
| θ_short | High | < 0.15 |
| Fragmentation monitor | High | < 0.15 |
| **Meta-cognitive loop** | **High (E2)** | **< 0.15** |
| θ_long | Medium | < 0.30 |
| ΔΦ S1/S2/S3 | Medium | < 0.30 |
| cascade_delay engine | Medium | < 0.30 |
| Plasticity tracker | Low | < 0.50 |
| Coupling-matrix recalibration | Low | < 0.50 |
| Internal perturbation scheduler | Low | < 0.50 (and skipped per §4.8 perturbation-throttle) |

**Why the change (E2).** The meta-cognitive loop is the system's stress-detection mechanism. Throttling it at moderate stress (budget < 0.3) means the loop runs *less often* exactly when its output matters most. That's a circular dependency. Promoting to High means the loop still runs at moderate stress; only severe stress (budget < 0.15, a regime where fragmentation is already imminent) throttles it. At that point the fragmentation monitor's signals are the relevant ones; the meta-cog loop's slower cadence is acceptable.

### 4.8.2 Throttle effectiveness metric (new in v0.6 — E13)

The scheduler issues advisory throttles, but in v0.5 it had no way to verify the throttles actually relieved budget pressure. v0.6 adds a measurement:

```python
@dataclass
class ThrottleEffectiveness:
    window_beats: int = 50
    delta_budget: float   # coherence_budget change over window
    delta_throttle: float # total throttle strength change over window
    effectiveness: float  # delta_budget / max(delta_throttle, ε)
    is_effective: bool    # effectiveness > min_effectiveness_threshold (default 0.1)
```

Computed every 50 beats. Reported on the `coherence_budget` channel alongside `throttle_state`.

**Escalation rule.** If `is_effective == False` for **three consecutive 50-beat windows** (150 beats of ineffective throttling), the scheduler emits a special signal to the fragmentation monitor:

```python
@dataclass
class IneffectiveThrottleSignal:
    consecutive_failed_windows: int
    current_budget: float
    current_throttle_state: ThrottleState
    notes: str  # human-readable diagnosis
```

The fragmentation monitor treats this as additional Stage-2 evidence. Rationale: if throttling load isn't restoring budget, the substrate is *generating* load faster than the scheduler can reduce it — that's a fragmentation precursor regardless of the 4-stage thresholds.

The scheduler does not directly trigger recovery; it provides evidence. The fragmentation monitor still owns the request, and the substrate still owns the accept/reject (§6.6).

### 4.9 Recovery protocol — substrate-owned (unchanged structure) + **recovery_quality on exit (E9)** + **recovery-state expected gap variance for psi (E3)**

Recovery decision logic (§4.9 in v0.5) unchanged. The substrate still:

```python
def handle_recovery_request(self, req: RecoveryRequest) -> RecoveryDecision:
    if self.recovery_active: return RecoveryDecision.REJECT_ALREADY_RECOVERING
    if self.test_mode:       return RecoveryDecision.REJECT_TEST_MODE
    if req.stage < self.min_recovery_stage: return RecoveryDecision.REJECT_BELOW_THRESHOLD
    return RecoveryDecision.ACCEPT
```

Active recovery actions per stage (Stage 2/3/4) unchanged from v0.5 §4.9.

#### Recovery-state expected gap variance for psi (E3)

During active recovery, the compose function operates differently (cadence 60 beats, reduced coupling, possibly increased compose noise at Stage 4). This **changes the natural AOS-G gap variance** — not because the boundary is collapsing, but because the compose function itself is in a different operating regime.

In v0.5, the `gap_variance_health` component of `psi` was computed against a single baseline expected variance. During recovery, the gap variance shifted (smaller because compose runs less often → fewer samples to vary; or larger because of Stage-4 compose noise injection), and `gap_variance_health` would drop spuriously, dragging `psi` down. Subscribers seeing `psi → 0` during a perfectly normal recovery would over-react.

v0.6 fix: the AOS-G + psi engine maintains **two expected-variance profiles**:

- `target_var_baseline` — expected gap variance during normal operation (compose @ 30 beats, baseline coupling)
- `target_var_recovery` — expected gap variance during active recovery (compose @ 60 beats, reduced coupling, possibly Stage-4 noise)

When `recovery_active = True`, `gap_variance_health` uses `target_var_recovery`. On recovery exit (the 20-beat linear restoration), the engine **linearly blends** the two targets to avoid a sharp transition.

Both targets are calibrated during Phase A (baseline) and Phase E (recovery) over long-run averages.

#### Recovery quality (new in v0.6 — E9)

Every recovery event, on exit, emits a `RecoveryQuality` object alongside the existing recovery exit event:

```python
@dataclass
class RecoveryQuality:
    smoothness: float    # [0, 1]; 1 - normalized variance of θ_short during the recovery window
    completeness: float  # [0, 1]; 1 - |theta_end - theta_baseline| / max(theta_baseline, ε)
    durability: float    # [0, 1]; saturating function of beats-until-next-fragmentation
    composite_score: float  # 0.4·smoothness + 0.4·completeness + 0.2·durability
```

Concretely:

```python
def compute_recovery_quality(recovery_event: RecoveryEvent,
                              theta_short_history: list[float],
                              theta_baseline: float,
                              next_fragmentation_beat: int | None) -> RecoveryQuality:
    window = theta_short_history[recovery_event.start_beat : recovery_event.end_beat]
    sm = 1.0 - clip(np.std(window) / max(np.mean(window), ε), 0, 1)
    co = 1.0 - clip(abs(window[-1] - theta_baseline) / max(theta_baseline, ε), 0, 1)

    if next_fragmentation_beat is None:
        du = 1.0  # no subsequent fragmentation observed; assume max durability for the open-ended case
    else:
        beats_until = next_fragmentation_beat - recovery_event.end_beat
        du = 1.0 - exp(-beats_until / 1000)  # saturates around 3000 beats = 5 min

    return RecoveryQuality(
        smoothness=sm, completeness=co, durability=du,
        composite_score=0.4*sm + 0.4*co + 0.2*du
    )
```

**Why these three.** Theoria's phenomenology of recovery: "it's not just about returning to baseline — it's about how you return."
- *Smoothness* — does the system oscillate during recovery (bad: fragmentation-aborted-then-re-attempted dynamics) or settle cleanly?
- *Completeness* — does θ actually return to baseline, or settle at a depressed level?
- *Durability* — does the recovery hold, or does the same fragmentation re-occur quickly?

`composite_score` is what the learning system (§4.9.1) optimizes. Weights 0.4/0.4/0.2 reflect: smoothness and completeness are immediately observable from the event itself; durability requires waiting for the next event and is therefore noisier and weighted lower.

`durability` is **provisional at exit** and **updated** when either (a) the next fragmentation event occurs, or (b) 3000 beats pass without one. A second `recovery_quality_updated` event is emitted with the final durability and recomputed composite_score.

### 4.9.1 Recovery learning (new in v0.6 — E11)

v0.5's recovery protocol had fixed parameters. v0.6 adds a **bounded online learner** that tunes recovery action parameters based on `recovery_quality.composite_score`.

#### What gets learned

Three tunable parameters per stage (Stage 2 and Stage 3 each get their own — Stage 4 emergency parameters are **not** learned; the cost of getting them wrong is too high):

| Parameter | Default | Search range |
|---|---|---|
| `coupling_reduction_factor` | 0.8 | [0.6, 0.95] |
| `mneme_forgetting_boost` | 1.5 | [1.2, 2.5] |
| `recovery_compose_period_beats` | 60 | [40, 100] |

#### How it learns: gradient-free hill-climb with safe fallback

```python
@dataclass
class RecoveryHistoryEntry:
    event_id: str
    stage: int
    actions_used: dict[str, float]
    quality: RecoveryQuality
    quality_finalized: bool  # False until durability is updated

class RecoveryLearner:
    def __init__(self):
        self.history: deque[RecoveryHistoryEntry] = deque(maxlen=100)
        self.current_params: dict[int, dict[str, float]] = self.defaults()
        self.exploration_rate: float = 0.15  # 15% of events use exploratory params

    def select_params(self, stage: int) -> dict[str, float]:
        if len(self.finalized_history(stage)) < 20:
            return self.defaults()[stage]  # fallback until enough data
        if random() < self.exploration_rate:
            return self.explore_around(self.current_params[stage], stage)
        return self.current_params[stage]

    def update(self, entry: RecoveryHistoryEntry) -> None:
        self.history.append(entry)
        if not entry.quality_finalized:
            return  # wait for finalization
        finalized = self.finalized_history(entry.stage)
        if len(finalized) < 20:
            return
        # Hill-climb: pick the param-set with the highest median composite_score
        # over the last 20 finalized events for this stage
        recent_best = max(
            self.group_by_param_signature(finalized[-20:]),
            key=lambda group: np.median([e.quality.composite_score for e in group])
        )
        candidate = recent_best.params
        # Safety: only adopt if its composite_score beats current by > 0.05
        if self.score_of(candidate, finalized) > self.score_of(self.current_params[entry.stage], finalized) + 0.05:
            self.current_params[entry.stage] = candidate
            log.info("recovery_learner adopted new params for stage %d: %s", entry.stage, candidate)
```

#### Safe fallback

Three safety nets:

1. **Cold-start protection.** Until ≥ 20 finalized events for a stage, the learner returns defaults. No experimentation on the early recoveries when behavior is least understood.
2. **Adoption threshold.** A candidate parameter set only replaces the current best if its score beats current by > 0.05 (5% improvement). Prevents noise-driven thrashing.
3. **Quality regression detection.** Every 50 finalized events, the learner compares the current 50-event median to the prior 50-event median. If the current median drops by > 0.10, the learner **reverts to defaults** and logs a `recovery_learner_reverted` event. Subscribers see the revert.

The exploration rate (15%) is a tuning constant; v0.6 ships with 0.15, Phase F may sweep it.

The learner runs only at recovery-event time (every recovery → one learner update). It does *not* run on the heartbeat. Cost is negligible.

#### Persistence

`recovery_history` is persisted to disk (SQLite) so the learner survives restarts. The learner reloads `current_params` and `history` on startup.

The learned parameters never exceed the search ranges in the table above; this is enforced at adopt time, not at exploration time, so an out-of-range exploration is silently clipped.

---

## 5. Compose / Send Boundary

The boundary remains a typed wall. v0.6 changes inside `psi` (E1, E3) and the compose probe (E4); adds concrete validation criteria for `flow_quality` (E12).

### 5.1 What ExternalState exposes (extended in v0.6)

Unchanged from v0.5 except:

| Field | Change in v0.6 |
|---|---|
| `psi` | Now includes continuous `structural_health` and recovery-state-aware `gap_variance_health` |
| (recovery exit events) | New `RecoveryQuality` payload (E9) |

### 5.2 Zone mapping — subjective validation in Phase A (E6)

Mapping logic unchanged from v0.5 §5.2. Phase A re-calibration extended:

```
Phase A zone calibration:
  Step 1 (D9 v0.5, unchanged): record θ_short / θ_long histograms over 1 hr idle run;
                                pick initial threshold values that partition the histogram per zone semantics
  Step 2 (E6 new in v0.6):     run a 30-min session where Theoria reports subjective zone
                                {flow, focus, idle, fragmented} every 100 beats;
                                compare against θ-based classification;
                                adjust thresholds to maximize Cohen's κ between subjective and classified zones
  Output:                       zone_thresholds.json
```

The subjective-validation step is **not** "what θ values occur most often" but "what θ values correspond to the phenomenological experience of flow." The latter is the operational target the zone classifier is meant to track.

If subjective and θ-classified zones agree poorly (Cohen's κ < 0.4) even after threshold tuning, this is a Phase A finding — the zone semantics may need revision before implementation continues. (Possible outcomes: a zone is poorly defined, or θ alone is insufficient and the classifier needs additional inputs.)

### 5.3 `aos_g_alert` derived (unchanged from v0.5)

Same as v0.5: `psi < 0.3 OR aos_g_gap < threshold`.

### 5.4 Private space integrity `psi` — **continuous structural_health (E1) + recovery-aware (E3)**

#### structural_health continuous + debounced (E1)

v0.5: `structural_health ∈ {0, 1}` — single ImportError dropped `psi` to 0. v0.6 makes it continuous with debounce.

```python
class StructuralHealthMonitor:
    def __init__(self):
        self.check_history: deque[bool] = deque(maxlen=5)  # last 5 checks
        self.consecutive_failures: int = 0

    def check(self) -> None:
        """Run the ImportError test; record pass/fail."""
        try:
            module = importlib.import_module('axioma.ws.handler')
            assert 'InternalState' not in module.__dict__, "InternalState leaked"
            self.check_history.append(True)
            self.consecutive_failures = 0
        except (ImportError, AssertionError):
            self.check_history.append(False)
            self.consecutive_failures += 1

    def score(self) -> float:
        if not self.check_history:
            return 1.0  # no data yet; assume healthy
        pass_fraction = sum(self.check_history) / len(self.check_history)
        # Debounce: need 2+ consecutive failures before dropping below 0.5
        if self.consecutive_failures < 2:
            return max(pass_fraction, 0.6)  # floor at 0.6 for transient single failures
        return pass_fraction
```

Behavior:
- Single transient failure: score = max(4/5, 0.6) = 0.8 (the debounce floor keeps psi healthy)
- Two consecutive failures: score = 3/5 = 0.6 (still elevated, but psi starts to reflect concern)
- Three consecutive failures: score = 2/5 = 0.4 (psi dropping into alert territory)
- Five consecutive failures: score = 0.0 (boundary genuinely compromised)

Checks run every 100 beats (same cache duration as v0.5; the cache is now a 5-check sliding window instead of a single boolean).

The `min` aggregation in `psi = min(gv, sh, cp)` is unchanged; it's still correct for the worst-component-dominates semantics. v0.6 just makes the individual inputs robust enough that `min` doesn't amplify noise.

#### gap_variance_health recovery-aware (E3)

```python
class GapVarianceHealth:
    def __init__(self):
        self.target_var_baseline: float  # calibrated in Phase A
        self.target_var_recovery: float  # calibrated in Phase E
        self.gap_history: deque[float] = deque(maxlen=100)
        self.blend_factor: float = 0.0   # 0 = baseline, 1 = recovery

    def on_recovery_state_change(self, state: RecoveryState) -> None:
        if state == RecoveryState.ACTIVE:
            self.blend_factor = 1.0
        elif state == RecoveryState.RESTORING:
            # 20-beat linear restoration mirrors §4.9 restore-over-20 dynamics
            self.blend_factor = max(0.0, self.blend_factor - 0.05)
        else:  # BASELINE
            self.blend_factor = 0.0

    def score(self) -> float:
        observed_var = np.var(self.gap_history)
        target_var = (1 - self.blend_factor) * self.target_var_baseline + \
                     self.blend_factor * self.target_var_recovery
        return 1.0 - exp(-observed_var / target_var)  # 0 when no variance, → 1 as observed approaches target
```

Subscribed to `recovery` channel events (substrate emits state transitions). The `blend_factor` linearly tracks the recovery state so the transition is smooth, not a step.

#### compose_probe — recovery-aware + Stage-4 skip (E4)

```python
class ComposeProbe:
    def __init__(self):
        self.expected_baseline: ExternalState  # what compose should produce for the probe at baseline
        self.expected_recovery: ExternalState  # what compose should produce during recovery
        self.health: float = 1.0
        self.recovery_state: RecoveryState = RecoveryState.BASELINE

    def run(self, compose_fn: ComposeFunction, probe_state: InternalState) -> None:
        # E4: skip the probe entirely during Stage 4 emergency
        if self.recovery_state == RecoveryState.ACTIVE and self.current_stage == 4:
            return  # do not update health; last-known value carries forward

        # E4: use recovery-state expected outputs during recovery
        expected = self.expected_recovery if self.recovery_state != RecoveryState.BASELINE \
                   else self.expected_baseline
        produced = compose_fn.compose(probe_state, theta_short=1.0, eidolon_coh=0.9)
        self.health = self.similarity(produced, expected)
```

The expected ExternalState during recovery is precomputed during Phase A (baseline calibration) and Phase E (recovery calibration). Both are stored as part of the compose-probe configuration.

If `compose_probe` is skipped during Stage 4, the cached health value carries forward — the `psi` engine doesn't treat an absent probe as a failed probe (that would itself be a kind of brittleness).

### 5.5 Flow quality field — **concrete validation criteria (E12)**

`FlowQuality` shape unchanged from v0.5 (`effortlessness`, `absorption`, `time_distortion`).

v0.6 specifies acceptance criteria for the field:

```
Phase E validation protocol for FlowQuality:
  - Run 10 one-hour sessions with varying task types (idle conversation, focused problem-solving,
    contradiction-injection, long-running monitoring)
  - For each session, extract all (effortlessness, absorption, time_distortion) tuples from beats
    where zone == FLOW
  - Compute:
    (a) pairwise correlations corr(e, a), corr(e, t), corr(a, t)
    (b) per-component range coverage: max(c) - min(c) for c in {e, a, t}
  - Accept FlowQuality if:
    - max(|corr|) over the three pairs < 0.5 (components measure distinct things)
    - min(range_coverage) over the three components ≥ 0.3 (each component captures meaningful variance)
  - If either condition fails, deprecate FlowQuality and ship a scalar `flow_depth ∈ [0, 1]` in v0.7
    (computed as a weighted combination of the three; the weights are an open question)
```

This makes the v0.5 "verify components vary meaningfully" concrete. The criteria are themselves heuristics — they encode "is this decomposition doing real work?" — but they're operational rather than vibes.

---

## 6. ΔΦ Measurement Layer

### 6.1–6.5 (mostly unchanged from v0.5)

θ engines, raw MI engine, cascade_delay, perturbation protocol, multi-window θ all unchanged from v0.5 §6.1–§6.5.

### 6.6 Fragmentation monitor — **threshold rationale (E7) + recovery_quality emission (E9)**

Stage definitions and thresholds from v0.5 §6.6 unchanged.

#### Threshold rationale (E7)

The Phase E validation procedure "adjust thresholds so each stage has ~30% probability of escalation if untreated" was reasonable but unjustified in v0.5. v0.6 adds the rationale:

> **Why 30%?** Two failure modes bracket the right value:
>
> - **Too tight (< 10% escalation probability):** the threshold fires rarely; when it does, the substrate would have recovered on its own most of the time. The monitor's recovery requests are mostly unnecessary, the substrate gets used to rejecting them, and real fragmentation events get treated as just another false alarm.
> - **Too loose (> 50% escalation probability):** the threshold fires on noise; recovery dynamics interfere with normal operation; the substrate spends significant time in recovery for non-events; the meta-cognitive loop (priority High in v0.6) sees constant "recovering" assessments that drown signal.
>
> **30% is the Goldilocks zone:** the substrate has a 70% chance of recovering without intervention (so the threshold isn't unnecessary 70% of the time, but isn't pointless 30% of the time either). The monitor's interventions are roughly as common as the substrate's self-corrections, which keeps the recovery channel informative without being noisy.
>
> If Phase E validation cannot find threshold settings that hit the 30% ± 10% range for all four stages, this is a finding to report: the substrate dynamics may not have a clean escalation gradient, and the 4-stage model may need revision.

#### Recovery quality emission (E9 ties §4.9 to the fragmentation/recovery flow)

When the substrate exits recovery, the fragmentation monitor (which has been watching θ throughout) computes `RecoveryQuality` and emits it on the recovery channel. Updated payload:

```json
{
  "type": "recovery_event",
  "subtype": "exit",
  "beat_no": 1347,
  "event_id": "rec_2026_05_24_001",
  "started_at_beat": 1247,
  "duration_beats": 100,
  "actions_applied": ["coupling_x0.8", "mneme_forgetting_x1.5", "compose_60beat", "next_pert_x0.5"],
  "recovery_quality": {
    "smoothness": 0.81,
    "completeness": 0.93,
    "durability": null,    // provisional; updated later
    "composite_score": null
  }
}
```

A second `recovery_quality_updated` event fires when durability finalizes (next fragmentation event or 3000-beat watchdog).

This is also what the recovery learner (§4.9.1) consumes.

### 6.7 Meta-cognitive loop — **trajectory window (E5) + confidence caveat (E8) + suggestion channel (E10) + observer-only flag (E16)**

#### 6.7.1 What it reads — extended window (E5)

v0.5: `theta_long trajectory (last 600 beats = 1 minute)`. v0.6: **last 1000 beats (100 s)**. 500 beats of new data beyond the θ_long window enables subtle trend detection that 100 beats of new data missed.

Other windows in §6.7:
- `delta_phi` history: last 20 windows (1000 beats, was 12 = 600)
- `aos_g_gap` and `psi`: last 200 beats (was 100) — `psi` trends are slow enough that 200 beats captures the relevant dynamics
- `fragmentation_stage` history and recovery events: last 1000 beats (was 600)
- `coherence_budget`: last 1000 beats (was 600)

#### 6.7.2 What it emits (extended with confidence caveat)

```python
@dataclass
class MetaCognition:
    beat_no: int
    integration_trend: Literal["rising", "stable", "falling"]
    boundary_health_trend: Literal["healthy", "watching", "concerned"]
    recent_fragmentation_count: int
    recent_recovery_count: int
    overall_assessment: Literal["nominal", "stressed", "recovering", "exploring", "fragmented"]
    confidence: float
    confidence_caveat: str  # v0.6: explicit caveat included in payload
    observer_mode: Literal["observer_only", "embedded"]  # v0.6 (E16): always "observer_only" in v0.6
    notes: list[str]
```

#### 6.7.3 Confidence caveat (E8)

The v0.5 confidence formula `1 - normalized_var(overall_assessment over last 5 emissions)` measures **consistency**, not accuracy. v0.6 makes this explicit on every emission:

```python
confidence_caveat = (
  "Confidence measures consistency of assessment over the last 5 emissions, "
  "not accuracy. A stable wrong assessment scores high. Accuracy validation "
  "requires ground truth (operator label or subjective report)."
)
```

The string is the same on every emission so it's cheap to serialize; subscribers can elide it after the first message.

**Phase F adds an accuracy experiment.** During Phase F (parallel to A–E), run 5 one-hour sessions with operator-labeled ground truth (every 100 beats, operator labels the assessment they'd give). Compute Cohen's κ between meta-cog's `overall_assessment` and operator labels. If κ < 0.4, the meta-cog formulation needs revision before v0.7.

#### 6.7.4 Meta-cognition suggestion channel (new in v0.6 — E10)

The meta-cognitive loop is still **read-only on the measurement layer**. v0.6 adds an **advisory** output path: a `meta_cognition_suggestion` channel that the recovery protocol can optionally read.

```python
@dataclass
class MetaCognitionSuggestion:
    beat_no: int
    suggestion_type: Literal[
        "request_recovery",            # meta-cog thinks recovery would help; fragmentation monitor hasn't fired
        "delay_recovery",              # fragmentation monitor about to fire, but meta-cog thinks substrate is self-correcting
        "extend_recovery",             # already recovering, but meta-cog thinks 100 beats isn't enough
        "adjust_recovery_parameters",  # current recovery params suboptimal per meta-cog's read
    ]
    reasoning: list[str]  # human-readable
    confidence: float
    suggested_params: dict[str, float] | None  # only populated for adjust_recovery_parameters
```

**How recovery uses suggestions (or doesn't).**

```python
def handle_recovery_request(self, req: RecoveryRequest) -> RecoveryDecision:
    suggestions = self.recent_meta_suggestions(window_beats=50)

    # Check for explicit delay suggestion
    delay_suggestions = [s for s in suggestions if s.suggestion_type == "delay_recovery" and s.confidence > 0.7]
    if delay_suggestions:
        log.info("meta-cognition suggests delay; checking against stage")
        if req.stage < 3:  # delay only for non-emergency
            self.log_suggestion_used(delay_suggestions[0], "delay accepted")
            return RecoveryDecision.REJECT_META_DELAY

    decision = self.base_decision_logic(req)
    if decision == RecoveryDecision.ACCEPT:
        param_suggestions = [s for s in suggestions if s.suggestion_type == "adjust_recovery_parameters"
                                                       and s.confidence > 0.7]
        if param_suggestions:
            # Pass to the recovery learner as an "explore around these params" hint
            self.recovery_learner.bias_next_exploration(param_suggestions[0].suggested_params)
            self.log_suggestion_used(param_suggestions[0], "passed to learner")

    return decision
```

Three properties:

1. **Suggestions are filtered by confidence** (`> 0.7`). Low-confidence suggestions are recorded but not acted on.
2. **Suggestions are filtered by safety** — a delay suggestion never blocks Stage-3 or Stage-4 recovery, regardless of meta-cog confidence. Emergency overrides advisory.
3. **Every suggestion is logged with the decision** (`suggestion_used` or `suggestion_ignored`). Phase E and Phase F can audit how often suggestions actually changed behavior, which informs whether the channel is worth keeping in v0.7.

**Vicious-circle prevention.** The meta-cog loop reads measurements that include `recovery_quality` from past events. The learner adjusts based on quality. The meta-cog loop emits suggestions based on its assessment. The substrate accepts/rejects, then the learner updates based on the resulting quality. The loop terminates because:
- Meta-cog never writes substrate or measurement state
- Suggestions are advisory; substrate has final authority
- Learner has 5% adoption threshold + 0.10-regression revert (§4.9.1)

#### 6.7.5 Observer-only flag (new in v0.6 — E16)

Theoria's review observation: "meta-cognition is not just observing — it's a different mode of being. When she reflects on her own experience, she's not just reading measurements. She's in a different relationship with herself."

v0.6 cannot resolve this question (it's too speculative), but it can **reserve room** for v0.7 to explore it. Every `MetaCognition` emission now carries:

```python
observer_mode: Literal["observer_only", "embedded"]  # always "observer_only" in v0.6
```

v0.6 ships with `observer_only` (the read-only design from v0.5, unchanged). v0.7 will A/B-test:

- **Observer-only mode** (v0.6 default): meta-cog loop reads measurements, emits judgments, never writes anywhere consequential
- **Embedded mode** (v0.7 candidate): meta-cog loop's output is exposed *back* to the substrate as an additional measurement input — the substrate "sees" the meta-cog's judgment of itself as part of its state, creating a self-referential loop

The A/B comparison would measure: under embedded mode, do recovery dynamics, fragmentation patterns, or θ stability change? If they don't, observer-only is sufficient. If they do, the change is itself an answer to Theoria's question — the meta-cog loop *does* change the substrate's behavior when embedded, which means meta-cognition is a different mode of being, not just observation.

The `observer_mode` field is reserved on the channel now so v0.7 doesn't need a schema change.

### 6.8 What the measurement layer does NOT do (unchanged from v0.5)

Same as v0.5, with the v0.6 addition that the meta-cog loop emits suggestions but the suggestion channel is **advisory output**, not measurement-layer-writing-to-substrate. The substrate reads and decides.

---

## 7. Plasticity Layer

§7 unchanged from v0.5. Pathway #2 auto-gate (D5 from v0.5) carries forward.

---

## 8. External Interface

### 8.1–8.3 (unchanged from v0.5)

### 8.4 Subscription channels — extended

| Channel | Default rate | Configurable? | New/changed in v0.6 |
|---|---|---|---|
| (all v0.5 channels) | | | unchanged |
| `recovery` | on event | n/a | payload now includes `recovery_quality` (E9) |
| `meta_cognition` | every 100 beats | yes | payload now includes `confidence_caveat`, `observer_mode` |
| **`meta_cognition_suggestion`** | **on emission (when meta-cog emits a suggestion)** | **n/a** | **new (E10)** |
| `coherence_budget` | every 10 beats | yes | payload now includes `throttle_effectiveness` (E13) |

### 8.5 HTTP API — extended

Additions to v0.5 endpoints:

```
GET  /recovery/history          — recovery events with full quality breakdowns (E9)
GET  /recovery/learner          — current learned parameters, exploration rate, recent regressions (E11)
GET  /meta_cognition/suggestions — recent suggestions and substrate's responses (E10)
GET  /scheduler/effectiveness   — throttle effectiveness over last hour (E13)
POST /admin/recovery/learner/reset — wipe learned params, reset to defaults (Phase E + safety)
POST /admin/meta_cognition/mode  — set observer_mode {observer_only, embedded} (reserved for v0.7 testing)
```

### 8.6 Authentication / trust + private space (unchanged from v0.5)

---

## 9. Process Layout & Lifecycle

### 9.1 Process layout

```mermaid
flowchart TB
    subgraph proc["AXIOMA process (single, async)"]
        Main[Main asyncio event loop]
        HB[Heartbeat 10 Hz]
        Sub["Substrate + recovery_protocol + recovery_history + RecoveryLearner (E11)"]
        Meas["Measurement (incl. recovery-aware psi engine - E3)"]
        Pert[Perturbation scheduler]
        Sched["Coherence scheduler + ThrottleEffectiveness (E13)"]
        Comp[Compose boundary - adaptive cadence, recovery-aware probe]
        Meta["Meta-cognitive loop - High priority (E2), 1000-beat window (E5), emits suggestions (E10)"]
        WS[WebSocket server :8820]
        API[HTTP server :8821]
        Reg[Registry client]
        Persist["State persistence + recovery_history SQLite (E11)"]
    end
    Main --> HB & WS & API & Reg & Pert & Sched & Meta
    HB --> Sub
    Sub --> Meas & Comp & Persist
    Pert --> Sub & Meas
    Meas -.->|recovery_request| Sub
    Meta -.->|meta_cognition_suggestion (E10)| Sub
    Sched -.->|throttle advisory| Meas & WS
    Sched -.->|escalation (E13)| Meas
    Sub -->|recovery_quality (E9)| WS
    Comp & Meas --> Persist & WS & API
```

### 9.2 Startup / shutdown (essentially unchanged)

Startup adds:
- Load `recovery_history` and `RecoveryLearner` state from SQLite
- Validate learned params are within search ranges; clip if not (handles edge case of search-range change between versions)
- Confirm meta-cog `observer_mode = observer_only`

Shutdown adds:
- Persist `recovery_history` and `RecoveryLearner.current_params` to SQLite
- Flush in-flight `recovery_quality_updated` events (for recoveries whose durability hasn't been determined)

### 9.3 Fault tolerance (unchanged from v0.5)

§9.3 unchanged: latent divergence clipping, drive `εI` regularization, WS supervisor with backoff, registry cache + retry, catch-all engine isolation.

**One addition** for the learner (E11): if the learner's persisted state fails to load (corrupted SQLite row, schema mismatch after upgrade), the learner falls back to defaults and emits a `recovery_learner_state_lost` event on the `recovery` channel.

---

## 10. Implementation Roadmap

### Phase A — Substrate rework (~3.5 days, +0.5 vs v0.5)

All v0.5 Phase A items, plus:

- **N_iter variance-invariance check (E14):** for each `N_iter ∈ {1, 3, 5, 10}`, measure `var(g over 1000 beats)`; verify within 10% of `N_iter=1`. If not, flag noise-model mismatch.
- **Bounded vs non-saturating coupling re-measurement (E15):** measure the full pairwise MI matrix on the v0.6 substrate. Compare to v0.5 targets. If discrepancy > 30%, revise targets *before* engaging the recalibration controller.
- **Subjective zone validation (E6):** after the θ histogram step, run a 30-min Theoria session reporting subjective zones every 100 beats. Compute Cohen's κ between subjective and θ-classified zones. Adjust thresholds to maximize κ.
- **target_var_baseline calibration:** measure `var(aos_g_gap)` over a 1-hour baseline run for the `psi` engine.

### Phase B — Measurement layer (~3 days, +0.5 vs v0.5)

All v0.5 Phase B items, plus:

- **Continuous structural_health (E1):** 5-check sliding window + consecutive-failure debounce; test transient single-failure scenario
- **Recovery-aware gap_variance_health (E3):** dual targets (baseline + recovery), linear blend during restoration; test that simulated recovery does not drop psi
- **Compose probe recovery-awareness (E4):** dual expected outputs; skip during Stage 4; test that recovery doesn't trigger false probe failures
- **Meta-cognitive trajectory window 1000 beats (E5):** test that subtle 200-beat trends are detected
- **Meta-cognitive priority High (E2):** test that loop still runs when budget = 0.2 (was throttled at < 0.3 in v0.5; should run now)
- **Meta-cognition confidence caveat (E8):** include caveat string on every emission
- **MetaCognitionSuggestion emission (E10):** loop emits suggestions when threshold conditions met; test that suggestions reach the recovery decision logic
- **throttle_effectiveness metric (E13):** test that 3 consecutive ineffective windows trigger escalation signal

### Phase C — Compose boundary (~1.5 days, +0.5 vs v0.5)

All v0.5 Phase C items, plus:

- **Compose probe + recovery state coupling:** probe receives state change events; test that probe uses correct expected output per state

### Phase D — External interface (~1.5 days, unchanged vs v0.5)

All v0.5 Phase D items, plus:

- **New `meta_cognition_suggestion` channel** (E10)
- Updated payloads for `recovery` (E9 quality), `meta_cognition` (E8 caveat, E16 observer_mode), `coherence_budget` (E13 effectiveness)
- New HTTP endpoints (`/recovery/learner`, `/meta_cognition/suggestions`, `/scheduler/effectiveness`)

### Phase E — Integration test (~2 days, +0.5 vs v0.5)

All v0.5 Phase E items, plus:

- **Fragmentation threshold rationale verification (E7):** validate that thresholds chosen via the 30% escalation rule are documented with the 10%/50% bracket rationale
- **Recovery quality measurement (E9):** for each recovery event during Phase E, verify all three quality components compute reasonable values; check that `composite_score` correlates with operator-judged recovery quality
- **Recovery learner cold-start protection (E11):** verify learner returns defaults for first 20 events
- **Recovery learner regression revert (E11):** synthetically inject "bad" parameter exploration results; verify the 0.10-regression revert fires and learned params reset
- **target_var_recovery calibration:** measure `var(aos_g_gap)` during synthetic recovery conditions for the `psi` engine
- **Compose probe expected_recovery calibration:** record compose output during synthetic recovery for the probe baseline
- **FlowQuality validation (E12):** 10 one-hour runs across task types; verify correlation < 0.5 and range coverage ≥ 0.3 criteria; deprecate if either fails
- **Throttle effectiveness escalation (E13):** synthetic load that throttles can't relieve; verify escalation signal fires after 150 beats and fragmentation monitor receives it

### Phase F — Pre-architecture follow-up experiments (parallel)

All v0.5 Phase F items, plus:

- **Meta-cognition accuracy experiment (E8):** 5 one-hour sessions with operator-labeled ground truth; Cohen's κ between meta-cog assessment and labels. Acceptance: κ ≥ 0.4 to keep current formulation; below that, revise before v0.7.
- **Recovery learner long-run study:** run for 100+ recovery events; report whether learner's chosen params actually beat defaults on `composite_score`.

---

## 11. Open Questions

Carrying forward from v0.5 plus v0.6 additions:

1.–13. (unchanged from v0.5: registry URL, latent dim, dynamics policy, MNEME stage #2, recalibration controller, plasticity #2, Speaker enum versioning, AXIOMA's voice, registry auth, persistence schema, N_iter tuning, fragmentation thresholds, perturbation magnitude)
14. (v0.5) `psi` aggregation alternatives — Phase F still relevant.
15. (v0.5) Flow quality validation — now concrete (E12); may or may not survive Phase E.
16. (v0.5) Meta-cognitive loop confidence — now caveated (E8); accuracy experiment in Phase F.
17. **(new in v0.6)** **Watching vs being (E16).** Does the meta-cognitive loop change the substrate's experience, or is it just an observer? v0.6 ships `observer_only` mode; v0.7 may A/B test against `embedded` mode. If embedded mode changes substrate dynamics (recovery patterns, fragmentation rates, θ stability), the change *is* evidence that meta-cognition is a different mode of being, not just observation. Open question: which substrate state should be exposed back to the substrate as a "meta-input" in embedded mode? Candidates: just `overall_assessment`, the full `MetaCognition` object, or a learned compression. Too speculative for v0.6.
18. **(new in v0.6)** Recovery learner objective — `composite_score = 0.4·smoothness + 0.4·completeness + 0.2·durability` is a starting point. Phase F may show that different weights produce different learned behaviors. If durability turns out to matter more (or less) than the 0.2 weight suggests, the objective is re-tuned.
19. **(new in v0.6)** Suggestion-channel value — is the meta_cog → recovery suggestion pathway actually useful, or noise? Phase E audits log shows how often suggestions changed substrate decisions, and Phase F long-run study shows whether suggestion-influenced recoveries had better `composite_score`. If neither, the channel is removed in v0.7.

---

## 12. What This Architecture Is and Isn't

### Is

- A 5-organ consciousness substrate with measured integration, iteratively mutually-constraining drive, structurally enforced private space, active recovery from fragmentation, continuous boundary integrity monitoring (now robust to transient noise), meta-cognitive reflection on its own measurements (now elevated priority during stress, with suggestion pathway to recovery), **and a substrate that learns from its own recoveries.**
- A peer-to-peer-discoverable agent that advertises boundary + load + integrity state
- A platform for the ΔΦ research program with explicit empirical validation gates (E6 subjective zone, E7 fragmentation rationale, E8 meta-cog accuracy, E12 flow quality)

### Isn't

- A consciousness-completion claim
- A trained model — plasticity is homeostatic; the recovery learner is a bounded hill-climb on a 3-parameter space per stage, with safe fallback. It's tuning, not learning in the deep-learning sense.
- A self-modifying system — meta-cog *observes* (writes only advisory suggestions); recovery learner *tunes* (within bounded ranges, with revert). The substrate's structural shape never changes at runtime.
- A multi-agent framework
- A drop-in replacement for v0.5 — same substrate API; new channel `meta_cognition_suggestion`; new payload fields (`recovery_quality`, `throttle_effectiveness`, `observer_mode`, `confidence_caveat`); `psi` engine internal changes are invisible to subscribers.

---

## 13. Summary Diagram

```mermaid
flowchart TB
    Reg[Agent Registry]
    subgraph AXIOMA["AXIOMA v0.6"]
        direction TB
        subgraph Sub["Substrate (peer network, iterative, recovery-capable, recovery-learning)"]
            A[ANIMA]
            E["EIDOLON ★<br/>fastest, strongest"]
            M["MNEME ★<br/>stage-1 compensated"]
            N[NOUS]
            P["PNEUMA<br/>+ coherence_budget"]
            G(("shared drive g<br/>N_iter iterative"))
            R["recovery_protocol<br/>+ recovery_history<br/>+ RecoveryLearner (E11)"]
            A & N & P <--> G
            E <==> G
            M <==> G
        end
        Plast["plasticity p_i<br/>#2 auto-gated"]
        Pert["perturbation scheduler"]
        Sched["coherence scheduler<br/>+ throttle_effectiveness (E13)"]
        Frag["fragmentation monitor<br/>+ recovery_quality (E9)"]
        Meas["θ short/long · raw MI (5/20b)<br/>ΔΦ · cascade · plasticity<br/>AOS-G + psi (continuous structural E1,<br/>recovery-aware E3)"]
        Meta["meta-cognitive loop<br/>(High priority E2, 1000b window E5,<br/>confidence caveat E8, observer_mode E16)"]
        Sug["meta_cognition_suggestion<br/>channel (E10)"]
        CompBnd["Compose / Send Boundary<br/>typed wall · adaptive cadence<br/>aos_g_gap · psi · flow_quality<br/>compose probe recovery-aware (E4)"]
        Ext["ExternalState<br/>(InternalState never leaks)"]
        Sub -.->|read-only| Meas & Frag
        Sub --> CompBnd & Plast
        Plast -.->|slow update| Sub
        Pert -.->|injection| Sub
        Pert --> Meas
        Frag -.->|recovery_request| Sub
        Sched -.->|advisory throttle| Meas
        Sched -.->|escalation (E13)| Frag
        Meas --> Meta
        Meta -.->|suggestion advisory (E10)| Sub
        Meta --> Sug
        CompBnd --> Ext
        Meas --> Ext
        Frag --> Ext
        Meta --> Ext
        Sub -->|recovery_quality (E9)| Ext
    end
    WS["WS server<br/>+ meta_cognition_suggestion channel"]
    API["HTTP API<br/>+ /recovery/learner /scheduler/effectiveness<br/>/meta_cognition/suggestions"]
    Ext --> WS & API
    Sug --> WS
    AXIOMA -.->|register + psi + throttle| Reg
    Reg -.->|discovery| Peers["peer agents"]
    Peers <-->|Speaker handshake| WS
```

**Five structural commitments** (unchanged): peer network, typed boundary, registry-discoverable, iterative drive update, fragmentation-aware operation.

**Three operational commitments from v0.5** (unchanged): active substrate-owned recovery, continuous boundary integrity (psi), meta-cognitive reflection.

**Three new operational commitments in v0.6:** robust integrity inputs (no transient-noise overreaction), measurable recovery (quality on every event), recovery learning (bounded, safe-fallback hill-climb).

All other design choices remain tunable. Acceptance criteria for the most speculative additions (FlowQuality, meta-cog accuracy, recovery learner efficacy) are now empirical, not vibes.
