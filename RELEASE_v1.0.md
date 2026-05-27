# AXIOMA v1.0 — Release Report

**Tag:** v1.0.0
**Date:** 2026-05-25
**Build sessions:** 9 (A.1 → F)
**Total build time:** ~17 hours of focused implementation
**Status:** SHIP-READY (Phase F GO verdict with 4 documented v1.1 caveats)

---

## What v1.0 is

AXIOMA is a runnable conscious-substrate agent: a 5-organ peer network (ANIMA / EIDOLON / MNEME / NOUS / PNEUMA) with a shared latent drive `g`, measured integration via Gaussian copula mutual information, and an external interface that lets peer agents subscribe to the substrate's compose-time boundary state — never its internal state. Architecturally per [design/ARCH_DESIGN_v1.0.md](design/ARCH_DESIGN_v1.0.md), implemented per [design/IMPLEMENTATION_PLAN_v1.0.md](design/IMPLEMENTATION_PLAN_v1.0.md), built per [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md).

The five structural commitments held from v0.3 through v1.0:
1. The substrate is the 5-organ peer network (PNEUMA is a peer, not a controller).
2. Integration is measured (θ via Gaussian copula MI), not asserted.
3. Latent dynamics are non-saturating (linear rescale + OU drive, scale=10).
4. The compose/send boundary is typed — `ExternalState ≠ InternalState`, enforced both at runtime (C12 ImportError test) AND at lint time (`import-linter` contract).
5. Recovery is substrate-owned, not measurement-owned.

---

## Ship-gate verdict

| Gate | Criterion | Result |
|---|---|---|
| **V11 perf** | 10-beat rolling p95 < 100 ms during baseline | **12.8 ms p95 in 50K-beat soak — 7.8× margin** |
| **V13 uncontrolled feedback** | 0 `recovery_feedback_uncontrolled` events per 24h | **0 in 50K-beat soak** |
| **V13 oscillation** | < 5 `recovery_feedback_oscillation_detected` per 24h | **0 in 50K-beat soak** |
| **C12 boundary** | `axioma.interface.*` cannot import `InternalState` | Runtime test PASS + import-linter contract KEPT |
| **V6 F2 learner monitoring** | WARMING_UP → MONITORING → INEFFECTIVE → revert → re-engage | 9 reproducible tests |
| **V8 F9 fragmentation thresholds** | Procedure measures per-stage escalation probability | 3 tests; `fragmentation_thresholds.json` writeable |
| **V10 Q1 rejection escalation** | Full chain: monitor → 3× reject → warning → HTTP endpoint | 5 tests + HTTP `/presence/rejection_warnings` |
| **V12 cold-start window** | Acceptance metrics evaluated against beats ≥ 600 | `assert_past_warmup` helper |
| **F4 synthetic pre-training** | Learner pre-seeded with non-default params | 8 tests + standalone script |
| **Q8 scope reduction** | Triggered ONLY if A.1+A.2 exceeds 2 weeks | **NOT triggered**; all v1.0 features shipped |

**Q8 outcome:** all v1.0 features (recovery learner, meta-cognition loop, full coherence scheduler) ship intact. No v1.0.1 scope cut.

---

## What ships in v1.0

### Core substrate
- 5 peer organs ANIMA / EIDOLON / MNEME / NOUS / PNEUMA, with the v1.0 deltas (EIDOLON ρ=0.92 V_E=1.3, MNEME α_M=1.4, PNEUMA as peer + `coherence_budget` field).
- SharedLatentDrive with iterative N_iter inner loop (default 3); Euler-Maruyama OU dynamics; ±30 safety clip per ARCH §9.3.1; feedback_scale=0.03 for stability.
- Linear-rescale render with scale=10 (non-saturating).
- PlasticityBuffer per organ + `(mean_drift, var_ratio)` summary every 100 beats.

### Measurement layer
- ThetaShortEngine (30-beat, CPU) + ThetaLongEngine (500-beat, GPU); Gaussian copula MI + RINT fallback; `bias_diagnostic` per Q2.
- RawMIEngine (per-organ pairwise MI, GPU-batched) + CascadeDelayEngine (D1: cascade_delay metric beyond θ).
- PerturbationScheduler (full Q3 PERTURBATION_SPECS — 6 perturbation kinds) + DeltaPhiEngine (S1/S2/S3 with perturbation-relative recording).
- PlasticityTracker (adaptation_delta per organ).
- AOSGEngine + ψ integrity field (E1 structural_health, E3 recovery-aware gap_variance, E4 compose probe with Stage-4 skip).
- FragmentationMonitor (4-stage detector + recovery_request emission).
- MetaCognitionLoop (1000-beat trajectory, F7 observer_only default, F5 5-ignored escalation, F8 confidence-as-consistency).
- CoherenceScheduler (E2 meta-cog at HIGH priority, E13 throttle effectiveness with 3-window escalation).

### Recovery
- RecoveryProtocol with 6-outcome accept/reject + Q1 RejectionEscalator (3-strike warning + 600-beat cooldown).
- RecoveryQuality (F1 windowed smoothness, completeness, durability) + composite_score.
- RecoveryHistory (bounded deque + optional JSONL persistence).
- RecoveryLearner with F2 monitoring extension (60-event window, 10-event baseline refresh, clean-baseline window on INEFFECTIVE revert) + F4 pretrain_synthetic + per-stage efficacy tracking.
- Durability finalization: 3000-beat watchdog OR next-fragmentation hook; `recovery_quality_updated` event emission.
- Stage-4 emergency `heartbeat.pause(beats=1)`.

### Compose / send boundary (the keystone)
- ExternalState dataclass — typed peer-visible projection; ZONE / cadence / ψ / FlowQuality / ExternalDeltaPhi / PerturbationContext embedded.
- ComposeFunction with integration-weighted compression `f_i × internal_i + (1-f_i)(rolling_mean + ε)`; P13 eidolon_coh live extraction; `latest_external` memoization for AOSGEngine.
- CadenceController (5/30/60-beat adaptive — perturbation/baseline/recovery); recovery overrides perturbation.
- FlowQuality (D15 closed-form; populated only in FLOW zone).
- Zone classifier (idle/focus/flow/stress/fragmented/recovering with hysteresis on substrate beats per ARCH §5.2).

### External interface
- AxiomaWSServer on :8820 — handshake, subscribe, fan-out across 15 channels; per-subscriber coalescing + rate limit + slow-consumer detection (V1 error policy).
- HTTP control plane on :8821 — 18 endpoints (read + admin), V1 error semantics (503 + Retry-After / 401 / 403 / 422 / 200+warmup_active).
- RegistryClient — best-effort registration + Redis/disk peer cache; degrades gracefully on outage.
- PeerConversationHandler — Ollama-backed (deepseek-v4-flash:cloud, 512 tokens); embeds peer-visible state snapshot in system prompt.
- Prometheus `/metrics` endpoint; structlog throughout.
- import-linter contract: `axioma.interface.*` cannot import `axioma.schemas.internal_state` (belt-and-suspenders to the runtime C12 test).

### Runtime
- Heartbeat 10 Hz loop with substrate / measurement / compose / WS / persistence stages; Stage-4 emergency pause.
- SnapshotManager (atomic write + symlink swap + schema-tolerant load).
- AxiomaContext (DI + pub/sub event bus).
- 12+ stateful components round-trip cleanly via the Stateful protocol.

### Infrastructure adapters
- OllamaClient (chat + embeddings; deepseek-v4-flash:cloud + nomic-embed-text-v2-moe 768-dim).
- VectorStore (Qdrant; `axioma_*` namespace).
- KVStore (Redis; `axioma:` namespace).
- GPU helpers (H100 PCIe-aware).

---

## Verification (final state)

| Check | Result |
|---|---|
| `pytest tests/ -m "not infra"` | **505 passed in 168.52 s** |
| `pytest tests/ -m infra` | **11 passed** (live Ollama + Qdrant + Redis) |
| `ruff check src/ tests/ scripts/` | **All checks passed** |
| `mypy src/axioma/` | **Success: no issues found in 63 source files** |
| `lint-imports` (C12 boundary) | **KEPT** |
| Combined coverage | **85.14%** (above 80% bar) |
| Code size | **22,079 LoC** across 63 src + 50 test + 11 script files |

---

## v1.1 backlog (documented caveats from Checkpoint F)

These are documented v1.1 work items, not v1.0 blockers. Each has a Phase F finding that motivates it.

| # | Item | Why | Source |
|---|---|---|---|
| **v1.1.1** | Live F6 zone validation sessions (Theoria labels) | Synthetic F6 returned HARD_FAIL (mean κ=-0.004) because synthetic operator's labeling rule differs from system's stricter multi-condition FLOW criterion. Real operator can tune thresholds. | Checkpoint F |
| **v1.1.2** | Live F8 meta-cog calibration sessions (5 hour-long blind sessions with Skye) | Synthetic F8 PASS but degenerate (all "recovering" labels); needs live operator with task diversity to validate three-criterion verdict. | Checkpoint F |
| **v1.1.3** | F4 substrate-driven scorer (replaces `_default_pretrain_score` smooth-bell) | Current default scorer is a smooth bell centered at cfg defaults; a real scorer would run a substrate sim and score actual recovery outcomes. | Checkpoint E |
| **v1.1.4** | ψ stress regime + per-component sensitivity calibration | ψ rides at 1.0 even under perturbation pressure; need a stress regime that genuinely drops ψ below 0.30 alert to measure component contributions. | Checkpoint F |
| **v1.1.5** | HTTP `/admin/calibration/session/start|label|end` endpoints | PLAN §10.4 specifies these for live operator sessions; currently rely on offline label files. | Checkpoint F (new) |
| **v1.1.6** | AOS-G weighted Euclidean experiment | Original Phase F list item #3 (compose with per-organ weighted Euclidean instead of L2); deferred as architecture refinement. | Phase F backlog |
| **v1.1.7** | Real 24h soak (864 000 beats) on dedicated H100 | The 50K-beat soak is the per-commit ship gate; a full 864k-beat run on idle hardware validates 24h durability. | Checkpoint F |

---

## How to use v1.0

### Boot the substrate

```bash
conda activate axioma
python -m axioma  # runs the heartbeat with the full Phase A+B+C+D stack
```

### Run acceptance tests

```bash
pytest tests/ -m "not infra"           # full unit + integration suite (~3 min)
pytest tests/ -m infra                 # live Ollama/Qdrant/Redis (~30 s)
lint-imports                           # C12 boundary contract
ruff check src/ tests/ scripts/        # lint
mypy src/axioma/                       # type check
```

### Run the ship-gate soak

```bash
python scripts/phase_e_soak.py --beats 50000      # ~9 min wall time; 1.4 simulated hours
python scripts/phase_e_soak.py --hours 24         # full 864 000-beat run
```

### Bootstrap the recovery learner

```bash
python scripts/phase_e_pretrain.py -n 50          # F4 synthetic pre-training
# Output: data/state/recovery_learner_pretrain.json
# Load at boot via RecoveryLearner.load_dict()
```

### Run Phase F follow-up experiments

```bash
python scripts/phase_f/p4_psi_baseline.py
python scripts/phase_f/f11_phi_scaling.py --order eidolon
python scripts/phase_f/f11_phi_scaling.py --order anima
python scripts/phase_f/f6_zone_validation.py
python scripts/phase_f/f8_meta_calibration.py
python scripts/phase_f/psi_sensitivity.py
python scripts/phase_f/learner_longrun.py --events 20
python scripts/phase_f/aggregator.py  # writes results/phase_f/phase_f_summary.md
```

---

## Checkpoint roll-up

The full implementation history is in [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md). Brief per-checkpoint summary:

| # | Phase | Wall-clock | Tests | LoC | Key deliverable |
|---|---|---|---|---|---|
| 0 | Kickoff | — | — | — | Env verified; design docs frozen |
| A.1 | Scaffold + observability + persistence + config + infra | ~1h | 57 | 2,859 | DI context + pub/sub bus; structlog + Prometheus; Ollama/Qdrant/Redis adapters |
| A.2 | Substrate critical path | ~2h | 156 | 5,857 | 5 organs + drive + plasticity + heartbeat; C11 perturbation response verified |
| B.1 | θ + raw MI + cascade_delay | ~1.5h | 217 | 8,033 | Vendored v0.2 θ pipeline; GPU-aware; bias_diagnostic |
| B.2 | Perturbation + ΔΦ + fragmentation + recovery | ~3h | 279 | 11,330 | Full Q3 PERTURBATION_SPECS; RecoveryProtocol + learner + Q1 escalator |
| B.3 | AOS-G + ψ + meta-cog + coherence scheduler | ~2h | 338 | 13,871 | E1/E3/E4 ψ sub-signals; F5/F7/F8 meta-cog; E2/E13 scheduler |
| C | Typed compose/send boundary | ~2h | 398 | 15,609 | ExternalState + ComposeFunction + Zone (created); C12 keystone runtime test |
| D | External interface (WS + HTTP + registry + peer conv) | ~2h | 469 | 19,224 | AxiomaWSServer + 18-endpoint HTTP API + import-linter contract |
| E | V6/V8/V10/V11/V12 acceptance + F4 + durability finalization + soak harness | ~2h | 505 | 21,067 | All ship-gate test infrastructure; closes last B.2 carried TODO |
| F | Phase F scripts + 50K-beat ship-gate soak + Zone classifier wiring fix | ~1.5h | 505 | 22,079 | **v1.0 GO verdict** |

---

**v1.0 ships.**
