# AXIOMA v1.6 — Release Notes

**Tag:** v1.6.1
**Date:** 2026-05-26
**Build sessions:** 31-38 (Checkpoints BB through II — eight focused audit checkpoints)
**Status:** SHIP — pure audit-and-harden release; zero default-behavior changes
**Backwards compat:** Full. All operator-facing public APIs preserved; configuration defaults unchanged.

This release is **the substrate-and-subsystem audit pass**. After v1.5 shipped the AOS-G metric-refinement work, the project entered a structured audit phase: walk each major subsystem in turn, identify concrete bugs and UX gaps via survey, fix them with focused single-checkpoint patches, and verify. v1.6 is the cumulative output of that work.

**The headline:** v1.6 doesn't change any default behavior or add new operator-facing features. It removes a substantial class of latent bugs (silent shape corruption on snapshot reload, unbounded resource growth, wrong-metric increments, missing reproducibility seeds, blocked-forever async waits) and adds operator observability primitives (`LoadResult`, `last_load_skipped_*`, structured warnings for partial loads). If you upgrade v1.5 → v1.6 and your deployment was working correctly under v1.5, it will continue to work correctly — but with sharper failure modes, better diagnostics, and tighter invariants.

---

## What shipped

Eight subsystems audited; **22 concrete fixes across 6 patch-checkpoints** plus 2 survey-only checkpoints:

| Checkpoint | Version | Subsystem | Fix count | Theme |
|---|---|---|---|---|
| BB | v1.5.1 | RecoveryLearner | 3 | correctness + reproducibility (`_matches_params` ignored compose_period; `baseline_score` was global scalar; learner RNG unseeded) |
| CC | v1.5.2 | PeerConversation | 3 | concurrency + observability (`deque mutated during iteration` race; `wait_idle` no timeout; outbound emit missing `request_id` / `timestamp` / `in_reply_to`) |
| DD | v1.5.3 | InterfaceProtocol (WS) | 3 | semantics (`WS_MESSAGES_SENT_TOTAL` incremented on inbound; `BAD_HANDSHAKE` used for post-handshake errors; unsubscribe didn't validate channel names) |
| EE | v1.5.4 | GracefulShutdown | 3 | guarantees (`shutdown()` claimed idempotent but re-ran teardown; `ws_server.stop()` unbounded; peer in-flight tasks not drained) |
| FF | v1.5.5 | Persistence/Snapshot | 3 | observability (`load_latest()` returned `int \| None` with no detail; corrupted manifest masqueraded as cold start; `register()` deferred `save_state`/`load_state` checks to runtime) |
| GG | n/a | SubstrateDynamics | 0 (survey only) | identified 7 substrate-side findings; produced punch list for v1.6.x |
| HH | v1.6.0 | Substrate (load + polish) | 5 | shape validation in `drive`/`plasticity`/`Organ` `load_state` + render docstring drift + bounded plasticity window |
| II | v1.6.1 | Substrate (polish bundle) | 3 | PNEUMA magic numbers → named constants + hard-clip kwargs + `last_load_skipped_*` on `SubstrateApp` |

**Total: 22 fixes across 8 audited subsystems** (one of which, GG, is survey-only; six are 3-fix patches; HH is a 5-fix patch).

---

## Cross-checkpoint patterns

The audit work surfaced four recurring patterns. Recognizing them up-front makes the individual checkpoints easier to read in retrospect, and gives future architectural work a starting vocabulary.

### Pattern 1 — Observability detail at load time (`LoadResult`-style)

Three checkpoints — **FF, GG-7 (II)** — added richer load-time observability:

- **FF — `SnapshotManager.last_load_result: LoadResult`** with status (`no_snapshot` / `no_manifest` / `manifest_corrupt` / `loaded`), loaded/skipped component lists, per-component skip reasons.
- **II GG-7 — `SubstrateApp.last_load_skipped_organs` + `last_load_skipped_plasticity`** at the substrate-app level (lighter than FF's full `LoadResult` since the surface is simpler).

The pattern: operators were unable to distinguish "load succeeded" from "load partial" from "load failed silently" because every non-loaded outcome returned `None`. The fix preserves the existing `int | None` (or implicit no-op) return semantics for backwards compat, but adds an attribute exposing the rich detail. Callers opt in: `if mgr.last_load_result.is_partial: alert()` / `if app.last_load_skipped_organs: warn()`.

This is the same idea applied at two layers (snapshot manager + substrate app). v1.7 could apply it to other restore paths (recovery-learner snapshot, calibration-recorder snapshot) using the same shape.

### Pattern 2 — Boot-time vs runtime error surfacing

Two checkpoints — **FF (register-time `save_state`/`load_state` check), HH (`load_state` shape validation)** — moved error detection from "first time the bug bites" to "as early as we can reasonably check":

- **FF** — `SnapshotManager.register()` checked only `name` + `schema_version` attrs; a component missing `save_state`/`load_state` registered fine and crashed at first snapshot. New behavior: register-time `TypeError` listing the missing methods.
- **HH** — `drive.load_state` / `plasticity.load_state` / `Organ.load_state` accepted any-shape arrays from snapshots; a cross-dimension reload produced cryptic broadcast errors at the next drive step. New behavior: explicit shape validation at load time, `ValueError` raise with the actual vs. expected shape.

The pattern: prefer to fail loudly *as early as possible* in the lifecycle. Configuration errors should surface at boot/register/load, not at first use. The cost is minor (one extra check); the benefit is dramatic (operator gets a precise error pointing at the cause instead of a stack trace 50 beats later).

### Pattern 3 — Reproducibility primitives

Two checkpoints touched RNG seeding:

- **BB** — `RecoveryLearner` was constructing `np.random.default_rng()` (unseeded) by default. Adoption decisions in two runs of the same substrate seed produced different counts because the learner's exploration RNG was non-deterministic. Fix: thread substrate seed through `RecoveryProtocol(rng=...)` → `RecoveryLearner(rng=...)`. The dramatic empirical follow-on: post-fix, adoption Δ between normalize-on / normalize-off was **+0 for all 5 seeds**, retroactively explaining AA's adoption-variance finding as exploration-RNG noise rather than metric-induced drift.
- **CC** — `PeerConversation` already had reproducible behavior in tests (stub Ollama); but the snapshot-before-await pattern added there preserves consistent history across concurrent in-flight tasks (single-thread determinism within the event loop).

The pattern: reproducibility is an architectural property worth designing-in explicitly. Same-seed runs should produce same outputs. The "decorrelate substrate seed and learner seed via `seed + 1`" idiom is now established and could be applied wherever future subsystems need their own RNG substream.

### Pattern 4 — Bounded-resource invariants

Three checkpoints touched bounded-resource concerns:

- **CC** — `wait_idle(timeout=None)` could block forever on a wedged Ollama task. Fix: optional `timeout` kwarg, `asyncio.wait_for`.
- **EE** — `ws_server.stop()` had no timeout (HTTP server already did); peer in-flight tasks weren't drained on shutdown. Fix: bounded `wait_for` on WS stop + `wait_idle(timeout=peer_drain_timeout)` before WS teardown.
- **HH GG-5** — `plasticity._window` was an unbounded `list`; in steady state bounded by `update_period`-discipline, but circumstantial rather than structural. Fix: `deque(maxlen=update_period * 2)` makes the invariant structural.

The pattern: prefer structural guarantees over operational discipline. "We call clear() every N beats so the window stays bounded" is fragile (one missed clear → unbounded growth); `deque(maxlen=N)` is the same behavior expressed as an enforced invariant.

---

## Per-subsystem detail

### v1.5.1 — RecoveryLearner (Checkpoint BB)

Three correctness/reproducibility fixes in [src/axioma/substrate/recovery.py](src/axioma/substrate/recovery.py):

1. `_is_default` + `_matches_params` now include `recovery_compose_period_beats` (previously ignored, polluting baseline mean and current_score median in adoption decisions).
2. `baseline_score: float` → `baseline_score_per_stage: dict[int, float]` (the single scalar was overwritten inside the per-stage loop; stages 2 and 3 had wrong baselines).
3. `RecoveryProtocol.__init__` accepts `rng=`; AxiomaApp + phase_e_harness thread `np.random.default_rng(seed + 1)` for reproducible adoption decisions.

**Empirical follow-on (the load-bearing finding from BB):** 5-seed × 50K-beat sweep with the fixes showed **adoption Δ = +0 across ALL 5 seeds** between normalize-on/off conditions, confirming AA's "adoption variance" finding was exploration-RNG noise rather than substrate or metric pathology.

### v1.5.2 — PeerConversation (Checkpoint CC)

Three fixes in [src/axioma/interface/peer_conversation.py](src/axioma/interface/peer_conversation.py):

1. **History-deque race** — concurrent `_respond` tasks could interleave deque reads/writes, raising `RuntimeError: deque mutated during iteration`. Fix: snapshot history into a list before any await.
2. **`wait_idle` infinite-block** — added optional `timeout` kwarg via `asyncio.wait_for`.
3. **Outbound metadata gap** — outbound emits now carry `metadata={request_id: uuid4(), timestamp: time.time(), in_reply_to?: <inbound_request_id>}` for operator traceability.

### v1.5.3 — InterfaceProtocol (Checkpoint DD)

Three fixes:

1. **Wrong metric** — `WS_MESSAGES_SENT_TOTAL.inc()` fired on inbound unsubscribe, polluting the outbound-message counter. Removed (and the unused import).
2. **`ErrorCode.BAD_REQUEST = 4020`** — new code for post-handshake malformed inputs (was misusing `BAD_HANDSHAKE = 4001`).
3. **Symmetric `_handle_unsubscribe`** — validates channel names like `_handle_subscribe` does (was silently no-op'ing on typos).

### v1.5.4 — GracefulShutdown (Checkpoint EE)

Three fixes in [src/axioma/runtime/app.py](src/axioma/runtime/app.py):

1. **True idempotency** — `_shutdown_done` flag short-circuits subsequent calls (was claimed-idempotent but re-ran every teardown step).
2. **Bounded `ws_server.stop()`** — `wait_for(timeout=ws_stop_timeout)` (was unbounded; matched HTTP server's pattern).
3. **Peer-conversation in-flight drain** — `shutdown()` now calls `peer_conversation.wait_idle(timeout=peer_drain_timeout)` after detach (uses CC's `wait_idle` primitive).

### v1.5.5 — Persistence/Snapshot (Checkpoint FF)

Three fixes in [src/axioma/persistence/snapshot.py](src/axioma/persistence/snapshot.py):

1. **`LoadResult` dataclass + `last_load_result` attribute** — rich load observability; status (`no_snapshot` / `no_manifest` / `manifest_corrupt` / `loaded`) + loaded/skipped lists + per-component reasons. `is_loaded` + `is_partial` properties.
2. **Corrupted-manifest detection** — non-dict JSON (e.g., `[]`) now surfaces as `status="manifest_corrupt"` instead of silently masquerading as cold start.
3. **Register-time `save_state`/`load_state` validation** — `register()` now requires both methods present + callable (was deferred to first-snapshot crash).

### v1.6.0 — Substrate load-state shape validation + polish (Checkpoint HH)

Five fixes:

1. **`drive.load_state` shape check** — `ValueError` on cross-dimension snapshot reload.
2. **`plasticity.load_state` shape check** — `buffer`, `rolling_mean`, `rolling_var`, and per-window-entry shapes validated.
3. **`Organ.load_state` shape check** — `latent`, `W`, `V` shapes validated; pre-existing dtype-promotion fix (`self.V` now consistently float32).
4. **`render` module docstring drift** — `to_unit_centered` / `to_unit` docstrings now describe actual `_DEFAULT_SIGMA_SCALE = 10.0` (was claiming scale=3 + 0.3% clip rate).
5. **`plasticity._window`** — now `deque(maxlen=update_period * 2)` (was unbounded list).

### v1.6.1 — Substrate polish bundle (Checkpoint II)

Three fixes:

1. **PNEUMA coherence_budget magic numbers** — `_WM_LOAD_CAPACITY = 7.0` and `_CASCADE_DELAY_THRESHOLD = 20.0` extracted from `_compute_coherence_budget`.
2. **Drive `hard_clip` + Organ `latent_hard_clip`** — class-attr constants (30.0) became `__init__` kwargs; all 5 organ subclasses thread the new kwarg through to `super().__init__`. Validates `> 0`.
3. **`SubstrateApp.last_load_skipped_organs` + `last_load_skipped_plasticity`** — `load_state` now tracks + warns on missing components (mirrors FF's `LoadResult` pattern at the substrate-app level).

---

## What hasn't changed

- All v1.0–v1.5 substrate behavior (5 organs, drive math, plasticity dynamics, perturbation pipeline)
- All measurement engines (θ short/long, raw MI, cascade_delay, ΔΦ, fragmentation monitor, AOS-G + ψ structure, meta-cog, coherence scheduler)
- All v1.0–v1.5 acceptance gates (V6, V8, V10, V11, V12, V13)
- v1.5's default-flipped pairing: `aos_g_normalize_per_organ = True` + `aos_g_alert_threshold_auto_tune = True`
- v1.3's PNEUMA-weighted `aos_g_gap_weights` + static initial `aos_g_alert_threshold = 0.152`
- v1.4.3's per-component ψ thresholds (opt-in)
- C12 boundary (substrate-privacy) enforced both at runtime + lint time
- All HTTP/WS/registry/peer-conversation interfaces (plus DD/II improvements)
- `python -m axioma` production entrypoint
- All backwards-compat YAMLs (`configs/v1_0_backwards_compat.yaml`, `configs/v1_4_backwards_compat.yaml`)
- All ComposeConfig field defaults

The v1.6 series is **purely additive at the public API surface**: new validation paths, new diagnostic attributes, new `__init__` kwargs (with defaults that preserve old behavior). Nothing is removed, renamed, or default-flipped.

---

## Verification

| Check | Result |
|---|---|
| `pytest tests/ -m "not infra"` | **686 passed** (+63 vs v1.5: 8 BB + 5 CC + 6 DD + 3 EE + 9 FF + 10 HH + 13 II + ~9 incidental tests) |
| `pytest tests/ -m infra` | **11 passed** |
| `ruff check src/ tests/ scripts/` | All checks passed |
| `mypy src/axioma/` | Success: no issues found in 66 source files |
| `lint-imports` | C12 contract KEPT |
| Code size growth (v1.5 → v1.6) | **+1,367 LoC** (27,626 → 28,993). Includes ~50% new tests, ~40% inline rationale comments, ~10% net new code |
| Subsystems freshly audited in v1.6 series | **7** (RecoveryLearner, PeerConversation, InterfaceProtocol, GracefulShutdown, Persistence/Snapshot, SubstrateDynamics survey, SubstrateDynamics fix) |

---

## Migration

### Operators upgrading from v1.5

**Zero action required.** v1.6 preserves all v1.5 default behavior. Public APIs are backwards-compat (`shutdown()` still returns `None`; `load_latest()` still returns `int | None`; organ constructors still accept all v1.5 kwargs; etc.). New observability attributes (`last_load_result`, `last_load_skipped_organs`) are opt-in.

### Operators wanting to use the new diagnostics

After any `load_state` / `load_latest` call:

```python
# Snapshot-manager level
beat = await mgr.load_latest()
if not mgr.last_load_result.is_loaded:
    log.error("snapshot restore failed", reason=mgr.last_load_result.reason)
elif mgr.last_load_result.is_partial:
    log.warning("partial restore", skipped=mgr.last_load_result.skipped_reasons)

# Substrate-app level
app.load_state(snap)
if app.last_load_skipped_organs:
    log.warning("substrate partial restore", missing=app.last_load_skipped_organs)
```

### Operators wanting tighter substrate clips (stress testing)

```python
from axioma.substrate import SharedLatentDrive, Anima
drive = SharedLatentDrive(drive_dim=16, hard_clip=15.0)  # tighter
anima = Anima(drive_dim=16, latent_hard_clip=15.0)
```

### Operators upgrading from v1.4 or earlier

Same as v1.5 — see [RELEASE_v1.5.md](RELEASE_v1.5.md) for the v1.4 → v1.5 migration. The v1.5 → v1.6 step adds no further migration work.

---

## What's open after v1.6

| Item | Why it's open |
|---|---|
| **GG-2 — MNEME stage-2/3 dead-code decision** | The only un-addressed finding from the substrate survey. `Mneme(stage2_enabled=True, stage3_enabled=True)` accepts the kwargs but `ensure_stage2`/`set_neighbor_states` are never called and `stage3_enabled` has no consumers. Needs an architectural decision (wire properly per ARCH §4.4 OR remove honestly) rather than a fix-checkpoint. |
| **v1.1.1 / v1.1.2** | Live F6/F8 calibration sessions — externally-gated (operator availability) |
| **v1.1.7** | Real 24h soak — hardware-gated (dedicated H100) |
| **v1.4.1 substrate-amendment variant** | Superseded by the v1.4.1 metric variant + v1.5 default-flip; backlog-only |

No new architectural items surfaced during the v1.6 audit chain. The audit confirmed the project is in solid shape; subsequent v1.7+ work can return to building features rather than auditing existing ones.

---

## Per-checkpoint roll-up (v1.6-relevant)

| # | Checkpoint | Wall-clock | Key deliverable |
|---|---|---|---|
| BB | v1.5.1 RecoveryLearner | ~2.5 hours | 3 fixes + 5-seed × 50K sweep → adoption Δ = +0 across all seeds |
| CC | v1.5.2 PeerConversation | ~45 min | 3 fixes (race, timeout, metadata) |
| DD | v1.5.3 InterfaceProtocol | ~35 min | 3 fixes (metric, error code, validation symmetry) |
| EE | v1.5.4 GracefulShutdown | ~30 min | 3 fixes (idempotency, bounded ws stop, peer drain) |
| FF | v1.5.5 Persistence/Snapshot | ~35 min | 3 fixes (LoadResult, corrupted manifest, register validation) |
| GG | Substrate survey | ~25 min | 7-item punch list (no fixes) |
| HH | v1.6.0 Substrate shape validation + polish | ~50 min | 5 fixes from GG-1/GG-3/GG-5 |
| II | v1.6.1 Substrate polish bundle | ~40 min | 3 fixes from GG-4/GG-6/GG-7 |
| **JJ** | **v1.6 release artifact** | **~30 min** | **This release** + runbook cross-links |

Full per-checkpoint history in [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md).

---

**v1.6 ships. Eight subsystems audited; 22 fixes; zero default-behavior changes; zero migration work for v1.5 deployments.**
