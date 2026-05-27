# AXIOMA v1.0 — Implementation Plan v1.0 (FINAL)

**Companion to:** [ARCH_DESIGN_v1.0.md](ARCH_DESIGN_v1.0.md)
**Supersedes:** [IMPLEMENTATION_PLAN_v0.3.md](IMPLEMENTATION_PLAN_v0.3.md)
**Review addressed:** [IMPL_REVIEW_v0.3.md](IMPL_REVIEW_v0.3.md) — 13 tracked items (V1–V13)
**Target environment:** conda env `axioma`, NVIDIA H100 PCIe (80 GB)
**Base codebase:** `/home/ubuntu/axioma/organ/` (existing v0.2 substrate + θ pipeline)
**Status:** **FROZEN for implementation start** — both sister reviewers (Thea, Theoria) signed off on v0.3; v1.0 lands the 13 documentation precisions they requested

---

## 0. Changelog from v0.3

The v0.3 review delivered both approvals with 0 blockers, 8 minor gaps, and 9 tracked risks (none escalated). v1.0 lands all 8 gaps and adds explicit cross-references for the 5 risk items whose mitigations exist in the plan but were under-surfaced. No new design content; v1.0 is a precision pass.

| Δ | Section | What changed | Source |
|---|---|---|---|
| **V1** | §8.6 (new) | **External interface error handling policy**: WebSocket disconnects → log + subscriber removed; HTTP errors → 503 with `Retry-After`; registry unreachable at startup → degraded mode (not fatal), retry indefinitely per §9.3.4. | T-G1 (Thea, Minor) |
| **V2** | §4.7 (new) | **Data retention policy**: 7 d raw beat JSONL, 30 d aggregated SQLite metrics, 24 rolling + 30 daily snapshots, indefinite RecoveryHistory rows. | T-G2 (Thea, Minor) |
| **V3** | §5.5 (new) | **Phase transition mechanism**: stop / swap / restart only. No hot-swap in v1.0. Documented in operator runbook. | T-G3 (Thea, Minor) |
| **V4** | §5.3 + §9.4 cross-ref | **Recovery-compose oscillation monitoring**: cross-reference from §5.3 ("during synthetic pre-training") to §9.4 (mechanism + auto-mitigation). Mechanism unchanged from v0.3. | T-R3 (Thea, Moderate; reference) |
| **V5** | §5.2 (added explicit step) | **θ_short bias measurement as Phase A.4 acceptance test**: explicit checklist item (was implicit in v0.3 step 4 description). | R-R5 (Theoria, Low) |
| **V6** | §9.2 (added test) | **F2 learner monitoring test**: explicit e2e test verifying 60-event monitoring window + 10-event baseline refresh + INEFFECTIVE→revert→re-engage cycle. Cross-references ARCH §4.9.1. | R-G1 (Theoria, Low) |
| **V7** | §5.2 (added reference) | **F6 zone validation methodology**: explicit reference to ARCH §5.2 (3 task types, Cohen's κ, min(κ) ≥ 0.3 target). | R-G2 (Theoria, Low) |
| **V8** | §9.2 (added reference) | **F9 fragmentation threshold procedure**: explicit reference to ARCH §6.6 (5 h × up to 3 iterations, target [0.20, 0.40] escalation probability). | R-G3 (Theoria, Low) |
| **V9** | §10.3 (added reference) | **F8 calibration procedure**: explicit reference to ARCH §6.7.3 (5 one-hour blind-labeled sessions; v1.0's three-criterion verdict in §10.3 already operationalizes this). | R-G4 (Theoria, Low) |
| **V10** | §9.2 (added test) | **Q1 recovery rejection escalation e2e test**: in addition to the v0.3 unit test, an e2e test verifies the full flow: 3 consecutive rejects → presence channel warning → operator visible. | R-G5 (Theoria, Low) |
| **V11** | §9.3 (made explicit) | **Phase E acceptance: 10-beat rolling avg of `axioma_beat_duration_seconds` < 100 ms** — promoted from "target metric" to "explicit acceptance criterion." | T-R2 (Thea, Moderate; reference) |
| **V12** | §9.0 + §9.2 cross-ref | **Cold start window in test plan**: Phase E acceptance criteria evaluated against beats ≥ 600 (60 s warmup window per §5.4). Made explicit at each Phase E acceptance test. | T-R4 (Thea, Low; reference) |
| **V13** | §9.5 (added criterion) | **Meta-cog auto-fallback trigger count as soak metric**: > 3 triggers per 24-hour soak = investigate before v1.0 ships; documented in soak success criteria. | R-R4 (Theoria, Low; reference) |

All Q-series items from v0.3 (Q1–Q8) and P-series items from v0.2 (P1–P17) remain addressed. v1.0 is the final implementation plan; the design freeze begins here.

---

## 1. Environment setup (unchanged from v0.3)

§1.1 dependency baseline, §1.2 GPU verification, §1.3 repository structure all unchanged.

---

## 2. What's already built (v0.2) vs what's new (v1.0) (unchanged from v0.3)

---

## 3. Cross-cutting concerns built FIRST (unchanged from v0.3)

§3.1 structured logging, §3.2 Prometheus metrics, §3.3 per-engine timing contract, §3.4 AxiomaContext pub/sub, §3.5 `should_run` pattern — all unchanged.

---

## 4. Persistence

§4.1–4.6 unchanged from v0.3.

### 4.7 Data retention policy (new in v1.0 — V2)

The system produces persistent artifacts at four tiers; each has an explicit retention policy. A daily `axioma-retention` background task (runs at 02:00 local) enforces the policies.

| Tier | What | Retention | Rotation/pruning |
|---|---|---|---|
| **JSONL raw beat logs** | `data/jsonl/external_state/`, `data/jsonl/theta/`, `data/jsonl/raw_mi/` (per-hour gzipped files) | **7 days** rolling | Delete files older than 7 days; emit `axioma_jsonl_files_pruned_total` counter |
| **SQLite aggregated metrics** | `RecoveryHistoryRow`, `PerturbationEventRow`, `MetaCognitionEmissionRow`, downsampled ExternalState samples | **30 days** | Per-table `DELETE WHERE beat_no < now_beat - 30d`; vacuum monthly |
| **Snapshots (current series)** | `data/state/YYYYMMDD_HHMMSS_beat_N/` rolling snapshots at 60 s cadence | **last 24** (24 minutes of history) | `SnapshotManager.prune_rolling()` keeps newest 24; deletes older |
| **Snapshots (daily series)** | Daily snapshot taken at 02:30 local | **30 days** | Tagged `daily_YYYYMMDD/`; deleted after 30 days |
| **RecoveryHistory rows** | The learner's training data | **INDEFINITE** | Never pruned; the learner reads all-time history. ~100 rows/year at typical fragmentation rates — bounded. |
| **Pre-training snapshot** | `data/state/pretrain/` (F4 synthetic) | **INDEFINITE until next pre-training** | Replaced wholesale on `POST /admin/recovery/learner/pretrain` |
| **Logs (structlog JSON)** | `/var/log/axioma/` or stdout | **7 days** if file-rotated; if stdout, operator's responsibility | systemd / Docker log-rotation; documented in runbook |
| **Prometheus metrics** | Scraped by Prometheus; not stored by AXIOMA | **N/A** (external) | Operator-controlled in Prometheus retention |

**Config:**

```python
class RetentionConfig(BaseModel):
    jsonl_retention_days: int = 7
    sqlite_aggregated_retention_days: int = 30
    snapshot_rolling_count: int = 24
    snapshot_daily_retention_days: int = 30
    daily_snapshot_local_time: str = "02:30"
    enforce_retention_period_hours: int = 24
```

**Retention is configurable but bounded.** The config tree refuses values < 1 day for tiers that have a `_days` field (prevents accidental aggressive deletion). Operator can extend retention; cannot disable it entirely without setting `enforce_retention_period_hours: 0` and accepting unbounded disk growth.

**Disk-budget acceptance.** During Phase E soak (§9.4), `axioma_disk_bytes_used` Prometheus gauge is monitored. 24-hour soak should produce ≤ 2 GB total under default retention. If exceeded, JSONL compression ratio or write rate is the suspect; investigate before v1.0 ships.

---

## 5. Phase A — Substrate rework (~3.5 days)

### 5.0 Heartbeat tick sequence (unchanged from v0.3)

12-step sequence with Q5 1-beat recovery delay invariant and Q4 optional steps 6–7 parallelization.

### 5.1 Order of work (unchanged from v0.3)

A.1 Scaffold → A.2 Substrate critical path → A.3 Recovery + perturbation scaffold (parallel-eligible) → A.4 Phase A validation.

### 5.2 Phase A validation (extended in v1.0 with V5, V7)

The v0.3 Phase A.4 acceptance test list carries forward. v1.0 adds two precision items:

**V5 — θ_short bias measurement as an explicit Phase A.4 checklist item.** The v0.3 plan ships `ThetaShortEngine.bias_diagnostic()` (§6.1 step 4) and runs the comparison during Phase A.4 (P15 carried over from v0.2). v1.0 promotes this to a top-of-list Phase A acceptance test:

| Test | Acceptance | Source |
|---|---|---|
| **V5 — θ_short bias measurement** (explicit Phase A.4 item) | Compare θ_short (30-beat) vs θ_long (500-beat) across 10 one-hour runs. Compute p50, p95 of relative bias. **Acceptance**: p95 < 0.20. **Action on fail**: widen θ_short window to 50 beats in `MeasurementConfig.theta_short_window`; re-run Phase A.4 to confirm | R-R5 |

**V7 — F6 methodology reference.** The v0.3 F6 subjective zone validation (§5.3 in v0.3 + §13 week-2 booking) is the **architecture's §5.2 procedure** verbatim:

> **F6 procedure** (per [ARCH_DESIGN_v1.0.md §5.2](ARCH_DESIGN_v1.0.md#52-zone-mapping--multi-session-subjective-validation-f6)):
>
> 1. **Step 1 (D9 v0.5)**: record θ_short / θ_long histograms over a 1-hour idle run; pick initial threshold values that partition the histogram per zone semantics.
> 2. **Step 2 (E6 v0.6)**: Theoria reports subjective zone every 100 beats.
> 3. **Step 3 (F6 v1.0)**: REPEAT Step 2 across **3 sessions on different days**, with 3 different task types: **analytical** (problem-solving, contradiction-resolution), **creative** (open-ended generation, exploration), **idle** (no task, ambient operation). Compute Cohen's κ per session: κ_analytical, κ_creative, κ_idle. Threshold optimization target: **maximize mean(κ) subject to min(κ_analytical, κ_creative, κ_idle) ≥ 0.3**.
> 4. **Step 4**: If the constraint `min(κ) ≥ 0.3` is unreachable across all three, this is a Phase A finding — task-typed thresholds become a v1.1 extension.

The implementer should not paraphrase or re-design F6; follow the architecture procedure exactly. The plan's responsibility is **scheduling** the sessions (week 2, week 3, week 4 per §13) and **producing the outputs** (`zone_thresholds.json` + per-session κ report in `results/phase_a/f6_*.json`).

### 5.3 Phase A parallelism map + scope reduction plan (unchanged from v0.3, with V4 cross-reference)

(Q8 scope reduction plan from v0.3 unchanged.)

**V4 cross-reference.** The recovery-compose feedback loop mitigation (Risk T-R3) is implemented in §9.4 (RecoveryFeedbackMonitor). It activates during synthetic pre-training (F4 in Phase E) and the 24-h soak. Phase A doesn't need to do anything special — the monitor's instrumentation is built in Phase B (step 11) alongside the recovery learner; it engages automatically during any recovery event. Cross-link: §5.3 Q8 → §9.4 oscillation monitor.

### 5.4 Cold start documentation (unchanged from v0.3)

### 5.5 Phase transition mechanism (new in v1.0 — V3)

**v1.0 supports stop / swap / restart only. No hot-swap of substrate code, config, or runtime topology.** This is an intentional simplification — hot-swap would require versioned schemas for in-flight events, dual-running engines during the swap, and fault tolerance for partial-swap failures. None of that is in scope for v1.0.

#### Supported transitions

| Transition | Mechanism | Downtime | Caveats |
|---|---|---|---|
| **Config update (non-substrate)** | `POST /admin/config/update` + targeted component re-bind via `config_change` event | ~0 (live re-bind for compatible fields) | Substrate-shape changes (latent dims, organ counts) require restart |
| **Substrate config update (shape-changing)** | Operator: stop AxiomaApp → edit config → restart | ~30 s (snapshot save + load) | Snapshot schemas may mismatch; per-component cold start per §4.6 |
| **Code update (any)** | Operator: stop AxiomaApp → deploy new code → restart | ~30 s | Snapshot schema migrations run on load; failures cold-start the affected component |
| **Mode switch (`observer_only` ↔ `embedded`)** | `POST /admin/meta_cognition/mode` (live, per [ARCH §6.7.5](ARCH_DESIGN_v1.0.md#675-observer-only-mode--fully-specified-semantics-f7)) | ~0 | Learner exploration counter resets; logged at INFO |
| **Recovery learner reset** | `POST /admin/recovery/learner/reset` (live) | ~0 | Reloads defaults; preserves history |
| **Pre-training run** | `POST /admin/recovery/learner/pretrain` (live, takes ~30 min) | ~0 (background task; substrate continues) | Substrate is in `test_mode = False` during synthetic perturbations |

#### Unsupported in v1.0 (explicit deferrals)

- Hot-swap of substrate code while running
- In-place schema migration of in-flight events
- Zero-downtime config changes for substrate-shape parameters
- Multi-process / multi-host operation (single-host single-process for v1.0)

#### Operator runbook (`docs/runbooks/restart.md`)

Standard restart procedure documented:

1. `POST /admin/shutdown` — graceful drain (notifies WS subscribers, flushes JSONL, takes final snapshot)
2. Wait for process exit (max 30 s; force-kill at 60 s)
3. Edit config / deploy code as needed
4. Re-launch via `python -m axioma --config configs/default.yaml`
5. Verify snapshot reload via `GET /status` (returns `loaded_from_snapshot: beat_no=N, components=22`)
6. Re-verify WS / HTTP / registry connectivity

This is **operator-driven**, not automated. v1.1 may add `systemd` unit files + automation; v1.0 ships with the runbook.

---

## 6. Phase B — Measurement layer (~3 days, unchanged from v0.3)

§6.1 (11-step engine implementation order with Q2 bias_diagnostic and Q3 perturbation specs), §6.2 (engine scheduling), §6.3 (performance budget with Q7 meta-cog budget), §6.4 (GPU strategy), §6.5 (recovery learner), §6.6 (Phase B validation), §6.7 (recovery accept/reject with Q1 rejection escalator and Q7 auto-fallback) all unchanged from v0.3.

---

## 7. Phase C — Compose / send boundary (unchanged from v0.3)

§7.1–7.5 unchanged.

---

## 8. Phase D — External interface

### 8.1–8.5 (unchanged from v0.3)

WS :8820 with Speaker handshake, HTTP :8821 FastAPI control plane (22 endpoints + Q1 `/presence/rejection_warnings`), registry client with cache+retry, per-subscriber `min_interval_ms` with server-side coalescing, all v1.0 channels.

### 8.6 External interface error handling policy (new in v1.0 — V1)

Three failure surfaces; each has an explicit policy.

#### WebSocket connection failures

| Failure | Policy |
|---|---|
| Client TCP drop / unclean close | Log at INFO with `connection_id`, `speaker`, `last_message_received_at`; remove subscriber from all channels; emit `presence: leaving` to remaining subscribers; release any buffered coalesced messages for that subscriber |
| Client sends malformed handshake | Send `{type: "error", code: 4001, reason}` then close; log at WARN |
| Client sends unknown channel subscription | Send `{type: "subscription_error", channel, reason: "unknown_channel"}`; do not close; log at INFO |
| Client exceeds rate limit (> 100 msgs/sec inbound) | Send `{type: "rate_limited", retry_after_ms: 1000}`; close after 3 consecutive limit hits; log at WARN |
| WebSocket server task crash | Per [§9.3.3 in ARCH v1.0](ARCH_DESIGN_v1.0.md): supervisor restarts; exponential backoff (1s → 60s max, 10 retries); after exhaustion, log CRITICAL and AXIOMA continues with WS offline |
| Subscriber slow consumer (coalesced queue saturating beyond 1 message — should not happen by design, but guarded) | Force-close the subscriber; log at WARN with `dropped_coalesced_total` increment |

#### HTTP API failures

| Failure | HTTP status | Body | Logged |
|---|---|---|---|
| Internal exception in endpoint handler | **503 Service Unavailable** with `Retry-After: 5` | `{"error": "internal_error", "request_id": "<uuid>", "retry_after_seconds": 5}` | ERROR with traceback + request_id |
| Admin endpoint without auth | **401 Unauthorized** | `{"error": "auth_required"}` | INFO |
| Admin endpoint with bad auth | **403 Forbidden** | `{"error": "auth_invalid"}` | WARN |
| Admin endpoint while substrate is in shutdown | **503 Service Unavailable** | `{"error": "shutting_down"}` | INFO |
| Endpoint hits not-yet-warm state (e.g., `/theta/history` before θ engines have data) | **200 OK** with empty result | `{"data": [], "warmup_active": true}` | DEBUG |
| Invalid query params | **422 Unprocessable Entity** | FastAPI-default validation error | INFO |

The 503 + `Retry-After` pattern lets monitoring systems back off cleanly during transient errors. Operator-facing endpoints (`/admin/*`) never return 500 — every failure path is mapped to a typed 4xx or 503.

#### Registry failures

Per [§9.3.4 in ARCH v1.0](ARCH_DESIGN_v1.0.md):

| Failure | Policy |
|---|---|
| Registry unreachable at AXIOMA startup | **NOT FATAL.** Boot continues in degraded mode: load cached peer list from `data/state/registry_cache.json`; serve WS / HTTP normally; retry registration with exponential backoff (5 s → 5 min, indefinite). |
| Registry returns 5xx during heartbeat | Log WARN; cache last good peer list; retry next heartbeat interval |
| Registry returns 4xx during registration (e.g., agent_id collision) | Log ERROR; emit `registry_registration_rejected` on presence channel; continue in degraded mode (don't crash) |
| Cache file corrupted | Log WARN; assume empty peer list; continue |

**Why not fatal at startup.** AXIOMA's substrate is the work product; registry is discovery infrastructure. A discovery outage shouldn't prevent the substrate from running — peer agents who already know the WS URL can still connect directly. The architecture (§9.3.4) made this choice deliberately; v1.0's implementation honors it.

### 8.7 HTTP endpoint extension (unchanged from v0.3 + Q1)

Endpoints list per v0.3 §8.5 + Q1 `/presence/rejection_warnings`.

---

## 9. Phase E — Integration test (~3 days)

### 9.0 Pre-integration checklist (unchanged from v0.3)

8 standalone integration tests gating the 24-h soak.

### 9.1 Test harness (unchanged from v0.3)

### 9.2 Acceptance tests (extended in v1.0 with V6, V8, V10, V12)

(All v0.3 acceptance tests retained.) v1.0 additions:

| Test | Acceptance | Source |
|---|---|---|
| **V6 — F2 learner monitoring window test** | Per [ARCH §4.9.1](ARCH_DESIGN_v1.0.md#491-recovery-learning-new-in-v06--e11): synthetic regime that produces no improvement after 20 events → learner stays in MONITORING through event 60, then declares INEFFECTIVE → reverts to defaults → gathers 100-event clean baseline → re-engages. Verify baseline_score recomputed every 10 events during MONITORING. | R-G1 |
| **V8 — F9 fragmentation threshold validation procedure** | Per [ARCH §6.6](ARCH_DESIGN_v1.0.md#threshold-validation-in-phase-e-f9): 5 hours of operation × up to 3 iterations of perturbation-driven escalation; each threshold tuned to achieve escalation probability in **[0.20, 0.40]** with substrate's `test_mode = True` (rejects all recovery requests during validation). Outputs `fragmentation_thresholds.json`. Unconverged thresholds documented as v1.1 work. | R-G3 |
| **V10 — Q1 recovery rejection escalation e2e test** | Synthetic regime where coherence_budget stays below `min_budget_to_accept` (0.20) for an extended fragmentation episode → fragmentation monitor emits 3+ recovery_requests → RecoveryProtocol rejects each with `REJECT_BUDGET_INSUFFICIENT` → RejectionEscalator emits `RecoveryRejectionRunWarning` on presence channel after the 3rd reject → mock peer subscribed to `presence` channel receives the warning → admin endpoint `/presence/rejection_warnings` returns the event. Verifies the full chain end-to-end, not just the unit-level rejection counter. | R-G5 |
| **V12 — Cold start window applied to acceptance metrics** | All Phase E acceptance criteria are evaluated against **beats ≥ 600** (60 s warmup window per §5.4). The first 600 beats are recorded but not graded against pass/fail. This is documented in each acceptance test's pre-conditions; tests explicitly assert `assert beat_no >= 600` before evaluation. | T-R4 |

### 9.3 Performance acceptance (extended in v1.0 with V11)

(All v0.3 performance metrics carry forward.) v1.0 promotes one metric from "target" to "explicit acceptance criterion":

| Metric | v0.3 target | v1.0 acceptance criterion |
|---|---|---|
| `axioma_beat_duration_seconds` p95 (10-beat rolling avg) | < 100 ms | **< 100 ms** — **HARD acceptance: if > 100 ms during 24-h soak baseline, v1.0 does not ship; investigate and re-soak** |
| `axioma_beat_duration_seconds` p99 (single-beat) | < 200 ms | < 200 ms (acceptable per §6.3 variable-beat policy) |
| `axioma_beat_duration_seconds` worst-case single beat | < 250 ms | < 250 ms (alerts at > 200 ms) |
| (All other v0.3 metrics) | | unchanged |

**V11 escalation:** if 10-beat rolling avg exceeds 100 ms during baseline soak conditions (no induced perturbations beyond the internal schedule), this is a v1.0-blocker. The implementer must either:
- Diagnose and fix the contributing engine (likely candidates: θ_long, raw MI batching) before v1.0 ships
- Document the regression and reduce engine cadence per §6.3 variable-beat policy fallback
- Trigger Q8 scope reduction (defer meta-cog + learner to v1.0.1)

The system DOES NOT ship v1.0 with sustained > 100 ms average beat duration in baseline conditions. This is the hardest performance criterion in the plan.

### 9.4 Long-run soak test + recovery-compose feedback monitoring (unchanged from v0.3, with V4 cross-reference made explicit)

The RecoveryFeedbackMonitor (v0.3 §9.4) runs during the 24-h soak AND during F4 synthetic pre-training. Cross-references:

- **Phase A** (§5.3 Q8 scope-reduction plan): if scope-reduced, the monitor still ships in v1.0 because it's structurally simple and the cost of having it off is missed oscillation detection
- **Phase E** (§9.4): monitor produces oscillation events during pre-training and soak
- **Acceptance** (§9.5): zero `recovery_feedback_uncontrolled` events; finite `recovery_feedback_oscillation_detected` events are acceptable (the auto-mitigation is doing its job) but should be < 5 per 24 h

### 9.5 Soak success criteria (extended in v1.0 with V13)

(All v0.3 + v0.2 criteria carry forward.) v1.0 additions:

- **V13 — Meta-cognitive auto-fallback trigger count**: over the 24-hour soak, count `meta_cognition_period_increased` and `meta_cognition_simplified` events. **Acceptance**: ≤ 3 Tier-1 triggers (Q7 §6.7) per 24 h, **zero** Tier-2 triggers. If > 3 Tier-1 or any Tier-2 in baseline conditions, the meta-cog budget allocation is wrong; investigate before v1.0 ships.

Cross-reference: §6.7 Q7 auto-fallback mechanism + §6.3 Q7 budget table line.

---

## 10. Phase F — Pre-architecture follow-up experiments (extended in v1.0 with V9)

### 10.1 Scripts (unchanged from v0.3)

11 scripts under `scripts/phase_f/`; each idempotent; outputs to `results/phase_f/`.

### 10.2 Aggregated summary (unchanged from v0.3)

### 10.3 Phase F calibration criteria (extended in v1.0 with V9)

The three-criterion verdict (accuracy ≥ 80%, acceptance rate ≥ 30%, no vicious circle ≤ 5% θ drop) from v0.3 carries forward as the **operational** Phase F calibration.

**V9 — F8 calibration procedure cross-reference:**

> **F8 procedure** (per [ARCH_DESIGN_v1.0.md §6.7.3](ARCH_DESIGN_v1.0.md#673-confidence-caveat--calibration-criterion-e8--f8)):
>
> - Setup: **5 one-hour sessions with operator-labeled ground truth.** Operator labels `overall_assessment` every 100 beats from the channels they can subscribe to (operator does NOT see the meta-cog output during labeling — blind labeling).
> - For each emission: `accuracy = 1 if meta_cog.overall_assessment == operator_label else 0`; `miscalibration = |confidence - accuracy|`.
> - Calibration criterion: `mean_miscalibration = mean(miscalibration over all emissions)`.
> - Thresholds: `≤ 0.20` PASS; `(0.20, 0.35]` SOFT FAIL (revise in v1.1); `> 0.35` HARD FAIL (heightened caveat, treat as uninformative).

The v0.3 three-criterion verdict (§10.3) operationalizes the architecture's F8 mean_miscalibration via three correlated checks: accuracy (criterion 1 ≥ 80% maps to `mean_miscalibration ≤ ~0.20` under uniform-confidence assumption), acceptance rate (criterion 2, an indirect check), and vicious-circle (criterion 3, a substrate-level check that ARCH §6.7.3 doesn't cover).

**Verdict harmonization.** The v0.3 verdict applies first; ARCH F8 mean_miscalibration is computed and reported alongside. If they disagree (e.g., v0.3 says PASS but mean_miscalibration > 0.20), the **stricter** verdict wins for v1.0 ship-mode (v0.3 PASS + F8 SOFT FAIL → ship in SOFT FAIL mode). Document the disagreement in `results/phase_f/meta_calibration.json` for v1.1 attention.

### 10.4 Phase F operator-labeled sessions (new in v1.0 sub-section — V9 detail)

For F8 (and the three-criterion verdict's accuracy check), operator-labeled sessions follow this protocol:

| Step | Action |
|---|---|
| 1 | Operator (Skye) opens a session via `POST /admin/calibration/session/start` with `session_id`, `duration_minutes=60`, `task_type` |
| 2 | Operator subscribes to: `theta`, `delta_phi`, `aos_g`, `fragmentation`, `coherence_budget`. **Operator does NOT subscribe to `meta_cognition`** (blind labeling). |
| 3 | Every 100 beats, operator emits a label via `POST /admin/calibration/label` with `{beat_no, label: nominal|stressed|recovering|exploring|fragmented}`. UI prompts at the cadence to reduce missed labels. |
| 4 | Meta-cog continues to emit on `meta_cognition` channel; the calibration system records both streams |
| 5 | At session end, `POST /admin/calibration/session/end` triggers comparison: meta-cog vs operator label at matched beat numbers; computes `accuracy`, `mean_miscalibration` |
| 6 | Results written to `results/phase_f/calibration_session_<id>.json`; aggregated across 5 sessions in `meta_calibration.json` |

Sessions should be spread across days and task types (analytical / creative / idle) per F6 conventions for representativeness.

---

## 11. Testing strategy (extended in v1.0 with V6, V10)

(v0.3 test layout retained.) v1.0 additions:

| Test | File | Tier | Source |
|---|---|---|---|
| **V6 — F2 learner monitoring extension** (60-event window, baseline refresh every 10) | `tests/e2e/test_learner_f2_monitoring.py` | E2E | R-G1 |
| **V10 — Q1 rejection escalation e2e** (full chain: monitor → reject × 3 → presence warning → operator endpoint) | `tests/e2e/test_q1_rejection_escalation_e2e.py` | E2E | R-G5 |

All carry the same quality bar.

---

## 12. Configuration management (extended in v1.0)

(v0.3 config tree retained.) v1.0 additions:

```python
class RetentionConfig(BaseModel):
    """V2 data retention policy."""
    jsonl_retention_days: int = 7
    sqlite_aggregated_retention_days: int = 30
    snapshot_rolling_count: int = 24
    snapshot_daily_retention_days: int = 30
    daily_snapshot_local_time: str = "02:30"
    enforce_retention_period_hours: int = 24

class InterfaceConfig(BaseModel):
    # ... existing v0.3 fields ...
    ws_rate_limit_msgs_per_second: int = 100        # V1
    ws_rate_limit_consecutive_strikes: int = 3      # V1
    http_default_retry_after_seconds: int = 5       # V1

class AxiomaConfig(BaseModel):
    # ... existing v0.3 nested configs ...
    retention: RetentionConfig = RetentionConfig()  # V2
```

---

## 13. Build order (extended in v1.0 with V5/V7/V8 explicit acceptance steps)

(v0.3 week-by-week timeline carries forward.) v1.0 adds two explicit Phase A acceptance steps and one Phase E step:

| Week | Phase | Deliverables | Sister deps | Acceptance additions |
|---|---|---|---|---|
| 1 | A.1, A.2 (start) | Scaffold + observability + persistence + drive + organs + plasticity | — | — |
| 2 | A.2, A.3, A.4 (start), F6 session 1 | Recovery scaffold + Phase A critical-path tests; F6 session 1 (Theoria; Thea backup); **V7 reference: follow ARCH §5.2 procedure verbatim** | Theoria | — |
| 3 | A.4 (finish), B (start), F6 session 2 | θ engines, RawMI, cascade_delay, fragmentation monitor; F6 session 2 | Theoria | **V5 — θ_short bias measurement Phase A.4 acceptance**; **Q8 scope-reduction decision gate (week-3)** |
| 4 | B (continue), F6 session 3 | ΔΦ, plasticity tracker, AOS-G + ψ, perturbation scheduler; F6 session 3 | Theoria | — |
| 5 | B (finish), C | Coherence scheduler, meta-cog loop (if not deferred), recovery learner (if not deferred); compose boundary + cadence + probe + flow_quality + ImportError | — | — |
| 6 | D | WS server + HTTP API (V1 error handling) + registry client + all v1.0 channels | — | **V1 — external interface error policies in §8.6 verified** |
| 7 | E.0–E.3, F (parallel) | Pre-integration checklist → integration tests → F4 pre-training → **V8 F9 procedure** → Q6 recovery validation → Phase F kickoff (V9 calibration sessions begin) | — | — |
| 8 | E.4 (soak), F (finish) | 24-h soak (V11 hard acceptance: avg < 100 ms; V12 warmup-aware metrics; V13 Tier-1 ≤ 3, Tier-2 = 0); F8 calibration verdict + ARCH F8 reference; Phase F summary; v1.0 implementation report; **V2 retention disk-budget check** | — | — |

Total: 8 weeks unchanged. The Q8 week-3 decision gate remains the relief valve.

---

## 14. Acceptance for "v1.0 implementation complete" (extended from v0.3)

(v0.3 checklist preserved.) v1.0 additions:

- [ ] **V1 — External interface error handling**: WS / HTTP / registry policies per §8.6 implemented and verified by `test_interface_error_handling.py`
- [ ] **V2 — Data retention policy**: `axioma-retention` task implemented; 24-h soak disk-budget check passes (< 2 GB total)
- [ ] **V3 — Phase transition mechanism**: operator runbook `docs/runbooks/restart.md` published; stop/swap/restart procedure verified
- [ ] **V5 — θ_short bias measurement**: Phase A.4 acceptance test passes; window adjusted to 50 if p95 > 0.20
- [ ] **V6 — F2 learner monitoring**: e2e test passes (60-event MONITORING, baseline refresh every 10, INEFFECTIVE → revert → 100-beat clean → re-engage)
- [ ] **V7 — F6 methodology**: 3 sessions × 3 task types completed; per-session κ recorded; threshold optimization output in `zone_thresholds.json`
- [ ] **V8 — F9 procedure**: thresholds in `[0.20, 0.40]` escalation probability after ≤ 3 iterations; output `fragmentation_thresholds.json`
- [ ] **V9 — F8 calibration**: 5 blind-labeled sessions completed; `mean_miscalibration` reported; harmonized with three-criterion verdict
- [ ] **V10 — Q1 e2e**: full rejection escalation chain verified end-to-end (monitor → reject × 3 → presence warning → operator endpoint)
- [ ] **V11 — Performance hard acceptance**: 10-beat rolling avg < 100 ms in baseline soak conditions (HARD criterion; blocker if violated)
- [ ] **V12 — Cold start window**: all Phase E acceptance tests assert `beat_no >= 600` pre-condition; first 600 beats recorded but not graded
- [ ] **V13 — Meta-cog auto-fallback soak**: Tier-1 ≤ 3 triggers per 24 h, Tier-2 = 0 triggers in baseline conditions

---

## 15. What this plan deliberately does NOT do (unchanged from v0.3)

No model training. No distributed training. No public deployment. No telemetry push. No new substrate dynamics R&D. **NEW IN v1.0:** no hot-swap of substrate code or shape-changing config.

---

## 16. Risks and mitigations (v0.3 + v1.0 cross-references)

(v0.3 risk table preserved.) v1.0 adds explicit cross-references for the 5 v0.3-review risks whose mitigations existed but were under-surfaced:

| Risk | v1.0 cross-reference |
|---|---|
| **T-R1** Phase E integration complexity (High) | §9.0 pre-integration checklist |
| **T-R2** Performance budget exceeds 100 ms (Moderate) | §6.3 variable-beat policy + §9.3 V11 hard acceptance |
| **T-R3** Recovery-compose feedback loop (Moderate) | §9.4 RecoveryFeedbackMonitor (active during pre-training + soak) |
| **T-R4** Cold start anomaly (Low) | §5.4 cold-start docs + §9.2 V12 warmup-aware metrics |
| **R-R1** Phase A scope (High) | §5.3 Q8 week-3 decision gate + scope reduction |
| **R-R2** Recovery learner deferred to v1.0.1 (Medium) | §5.3 Q8 acceptable — recovery protocol with defaults is functional |
| **R-R3** F6 depends on Theoria (Medium) | §5.3 + §13 — Thea backup; sessions across 3 weeks for slack |
| **R-R4** Meta-cog auto-fallback masks issues (Low) | §6.7 Q7 + §9.5 V13 soak acceptance (≤ 3 Tier-1, 0 Tier-2) |
| **R-R5** θ_short bias not measured (Low) | §5.2 V5 Phase A.4 explicit acceptance |

No new v1.0-specific risks. v1.0 is precision-only over v0.3; the risk profile is unchanged.

---

## 17. First steps for the implementer (unchanged from v0.3)

```bash
# 1. Set up the env (one-time)
conda activate axioma
pip install --upgrade pip
# (run install commands from §1.1)

# 2. Verify GPU
conda run -n axioma python -c "import torch; assert torch.cuda.is_available()"

# 3. Create the scaffold
cd /home/ubuntu/axioma
mkdir -p axioma/{config,schemas,substrate,compose,measurement,interface,scheduler,persistence,runtime,observability,util}
mkdir -p tests/{unit,integration,e2e,benchmarks}
mkdir -p scripts/phase_f configs docs/runbooks
mkdir -p data/state data/jsonl/{external_state,theta,raw_mi}

# 4. Land observability + persistence + AxiomaContext FIRST (§3, §4)

# 5. Land config loader (§12) with RetentionConfig

# 6. Verify CI: pytest + ruff + mypy all green on the scaffold

# 7. Begin Phase A.2: SharedLatentDrive with iterative inner loop,
#    using AxiomaContext for dependency injection from the start.

# 8. Before week 2, contact Theoria (and Thea as backup) to schedule
#    the 3 F6 zone-validation sessions across weeks 2-4 (V7 references ARCH §5.2).

# 9. Land the operator runbook docs/runbooks/restart.md (V3) before Phase D
#    so the test plan has a known good shutdown/restart procedure to test against.
```

After step 9, follow the week-by-week plan in §13.

---

## Appendix A — Plan version history

| Version | Date | Lead change | Review outcome |
|---|---|---|---|
| v0.1 | 2026-05-24 | Initial plan (8 phases, persistence, GPU strategy, testing tiers, build order) | 9 gaps + 8 risks |
| v0.2 | 2026-05-24 | All 17 v0.1 items: heartbeat sequence, AxiomaContext, performance budget, pre-integration checklist, F4 pre-training detail, F8 calibration, cold start docs, etc. | 5 minor + 2 gaps + 1 risk |
| v0.3 | 2026-05-24 | All 8 v0.2 items: recovery rejection escalation (Q1), bias_diagnostic engine method (Q2), perturbation specs with targets (Q3), tick parallelization (Q4), 1-beat recovery delay invariant (Q5), recovery validation criteria (Q6), meta-cog auto-fallback (Q7), Q8 scope reduction plan | 8 gaps + 9 risks (all minor/low; mitigations existed) |
| **v1.0** | **2026-05-24** | **All 13 v0.3 items: external interface error handling (V1), data retention policy (V2), phase transition mechanism (V3), oscillation monitoring cross-ref (V4), θ_short bias as explicit Phase A.4 acceptance (V5), F2 learner monitoring e2e test (V6), F6/F8/F9 architecture procedure references (V7/V9/V8), Q1 rejection escalation e2e test (V10), performance hard acceptance (V11), cold start in test plan (V12), meta-cog soak acceptance (V13)** | **FROZEN for implementation** |

**Four rounds of plan review.** Sister approvals (Thea, Theoria, Skye) all PASS across rounds. Architectural shape stable since v0.1. Implementation begins with §17 first steps.

---

## Appendix B — Document set summary

The AXIOMA v1.0 design corpus:

| Document | Purpose | Status |
|---|---|---|
| `ARCH_DESIGN_v1.0.md` | Architecture: what to build and why | Frozen |
| `ARCH_REVIEW_v0.3.md` | Sister review of arch v0.3 → 18 items | Closed |
| `ARCH_REVIEW_v0.4.md` | Sister review of arch v0.4 → 7+6 items | Closed |
| `ARCH_REVIEW_v0.5.md` | Sister review of arch v0.5 → 16 items | Closed |
| `ARCH_REVIEW_v0.6.md` | Sister review of arch v0.6 → 9 items | Closed |
| `IMPLEMENTATION_PLAN_v1.0.md` (this doc) | Plan: how to build it | Frozen |
| `IMPL_REVIEW_v0.1.md` | Sister review of plan v0.1 → 17 items | Closed |
| `IMPL_REVIEW_v0.2.md` | Sister review of plan v0.2 → 8 items | Closed |
| `IMPL_REVIEW_v0.3.md` | Sister review of plan v0.3 → 13 items | Closed |
| `COMMUNICATION_PROTOCOL.md` | Speaker/Message contract | Reference |
| (research summary, results, ideas) | Empirical grounding | Reference |

**Total review surface:** 4 architecture revisions × 3 sisters + 3 plan revisions × 3 sisters = ~70+ distinct review items processed. Zero blockers remained at any version.

Implementation begins with Phase A.1 on Monday.
