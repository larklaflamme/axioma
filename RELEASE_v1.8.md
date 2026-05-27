# AXIOMA v1.8 — Release Notes

**Tag:** v1.8.3
**Date:** 2026-05-27
**Build sessions:** 43-46 (Checkpoints NN through QQ — four focused feature checkpoints)
**Status:** SHIP — pure additive feature series; zero default-behavior changes
**Backwards compat:** Full. No public API removals, no default flips, no migration work.

This release is **the operator toolkit series**. After v1.7 flipped MNEME stage-2/3 to defaults and the audit chain wrapped at v1.6, the project pivoted to feature work that gives operators direct, low-friction access to AXIOMA's on-disk artifacts and live state. v1.8 is the cumulative output of four feature checkpoints: three read-only inspection CLIs under the new `axioma.tools` package, plus an HTML monitoring dashboard backed by Z's existing `/aos_g/self_check` JSON endpoint.

**The headline:** v1.8 doesn't change any substrate behavior, measurement engine, or configuration default. It adds operator-facing surfaces that previously required ad-hoc `jq` pipelines or custom Python: `python -m axioma.tools.snapshot_inspect`, `python -m axioma.tools.recovery_inspect`, `python -m axioma.tools.calibration_inspect`, and `GET /dashboard`. If you upgrade v1.7 → v1.8 you get four new ways to look at your deployment; nothing else changes.

---

## What shipped

Four feature checkpoints, four operator-facing ships:

| Checkpoint | Version | Subsystem | Surface | Theme |
|---|---|---|---|---|
| NN | v1.8.0 | `axioma.tools.snapshot_inspect` | CLI | Read-only snapshot inspection (`--list` / `--current` / `--target` + `--component`) |
| OO | v1.8.1 | `axioma.tools.recovery_inspect` | CLI | Recovery-history + learner-state inspection (`--list` / `--event` / `--learner` + filters) |
| PP | v1.8.2 | `axioma.tools.calibration_inspect` | CLI | F6/F8 calibration session inspection (`--list` / `--session` / `--summary` + `--kind`) |
| QQ | v1.8.3 | `GET /dashboard` HTML page | Web UI | Live status dashboard polling `/aos_g/self_check` every 3 s |

**Three CLIs + one HTML dashboard.** Together they form a complete inspection-and-monitoring toolkit: CLIs for on-disk post-mortem and historical inspection; dashboard for live at-a-glance status. The `axioma.tools` package convention (`python -m axioma.tools.<name>`) is established and ready for future tools to slot in alongside.

---

## Cross-checkpoint patterns

The feature work surfaced four recurring patterns. Recognizing them up-front makes the individual checkpoints easier to read in retrospect and gives future operator-tooling work a starting vocabulary.

### Pattern 1 — `python -m axioma.tools.<name>` package convention

Three checkpoints — **NN, OO, PP** — established and reinforced the same package convention:

- **NN** created `axioma.tools/` as a new top-level package; documented the convention in the package `__init__.py` docstring ("each CLI is `python -m axioma.tools.<name>`; tools operate on on-disk artifacts and don't boot the substrate").
- **OO** added `recovery_inspect.py` alongside, validating the convention with a second tool.
- **PP** added `calibration_inspect.py`, completing the trio.

The pattern: each tool is one Python file, invokable directly via `python -m`, taking positional + flag arguments, exiting 0 on success and 2 on error. No subcommand layering (`tools snapshot list` style), no shared CLI framework beyond stdlib `argparse`. New tools slot in cleanly with the same shape; zone-classifier and meta-cog history dumpers could be added in v1.9 without touching the existing three.

### Pattern 2 — Read-only on-disk inspection (no HTTP, no live state, no substrate boot)

All three CLIs (NN/OO/PP) share the same constraint: they read from disk only. No HTTP client, no substrate event-bus, no live API dependency.

- **NN — `snapshot_inspect`** reads snapshot manifests + component JSON files via FF's `SnapshotManager` constants and msgspec decoder.
- **OO — `recovery_inspect`** reads `recovery_protocol.json` from a snapshot's component dump.
- **PP — `calibration_inspect`** reads `results/phase_f/calibration_session_*.json` files written by `CalibrationRecorder._write_to_disk`.

The pattern: separate "look at what happened" (on-disk, post-mortem) from "look at what's happening now" (HTTP / WS, live). The CLIs do the first; the existing endpoints (`/recovery/history`, `/recovery/learner/efficacy`, `/admin/calibration/active`, `/aos_g/self_check`) do the second. QQ then introduced the dashboard as the second tier of "look at what's happening now," sharing nothing with the CLIs except the philosophical separation. This separation keeps each tool simple and safe to run against an in-flight production deployment without interfering with the running heartbeat.

### Pattern 3 — 8-char prefix matching for opaque identifiers

Two checkpoints — **OO, PP** — adopted the same identifier-matching idiom:

- **OO** — `--event PREFIX` matches recovery `event_id` (UUID4) by leading characters.
- **PP** — `--session PREFIX` matches calibration `session_id` (UUID4) by leading characters.

Both CLIs' `--list` output displays the first 8 characters of the identifier in the table, so operators can copy-paste from the list output directly into the drill-down flag. Full UUID4 strings are inconvenient to type; 8 characters are almost always unique within a single snapshot's or results directory's contents. The idiom mirrors how `git` accepts SHA prefixes; future tools handling opaque IDs should reuse it.

NN's `snapshot_inspect` doesn't need this because snapshot directory names already double as their human-readable identifiers (`20260527_143022_beat_50000`).

### Pattern 4 — Self-contained UX, no external dependencies

All four ships avoided pulling in any new dependency:

- **NN / OO** use msgspec (already a dependency for the snapshot writer) for fast JSON decoding.
- **PP** went further: stdlib `json` only — operator-facing calibration files are KB-scale and already written via `json.dumps(body, indent=2)`, so the symmetric stdlib decoder is the right call.
- **QQ** ships a single self-contained HTML document — inline `<style>` + inline `<script>`, no `<link>`/`<script src=>` to any external resource, no CDN, no build step, no npm.

The pattern: prefer simplicity and zero-deps over framework convenience for operator tooling. Each tool can be deployed, used, and reasoned about without supply-chain considerations. The trade-off is that the dashboard has no charting library (`<div>`-based bar charts instead of SVG/Canvas) and the CLIs have no colorized output (plain text columns) — both deliberate concessions to the no-external-deps invariant.

---

## Per-subsystem detail

### v1.8.0 — Snapshot inspection CLI (Checkpoint NN)

230-line CLI in [src/axioma/tools/snapshot_inspect.py](src/axioma/tools/snapshot_inspect.py):

- **Three action modes**: `--list` (default; shows rolling + daily snapshots in a column table marking `current`), `--current` (inspects the symlink-pointed snapshot), `--target NAME` (inspects an arbitrary snapshot by basename).
- **`--component NAME` drill-down**: when combined with `--current` or `--target`, pretty-prints the component's JSON state with sorted keys.
- **Exit codes**: 0 success / 2 error (missing root, missing manifest, corrupted manifest, missing component file).
- **Reuses FF's `SnapshotManager` constants** (`SNAPSHOT_MANIFEST`, `CURRENT_SYMLINK`, `DAILY_PREFIX`) and msgspec decoder — guaranteed format compatibility with the writer.
- **14 unit tests** covering all action modes + 6 error paths.

Operator runbook §7.1 documents 5 example invocations.

### v1.8.1 — Recovery-history inspection CLI (Checkpoint OO)

250-line CLI in [src/axioma/tools/recovery_inspect.py](src/axioma/tools/recovery_inspect.py):

- **Three action modes**: `--list` (default; sorted most-recent-first), `--event PREFIX` (8-char-prefix match), `--learner` (dumps learner state including adoptions/reversions/baseline_score_per_stage/efficacy_per_stage/current_params).
- **Four filters for `--list`**: `--stage N`, `--synthetic`, `--real`, `--limit N`. `--synthetic` and `--real` are argparse-level mutually exclusive; `--stage` composes with either.
- **Source-resolution polymorphism**: ROOT can be either the snapshot-root (`data/state/snapshots`) or a snapshot dir directly (`data/state/snapshots/20260527_143022_beat_50000`); detection rule is unambiguous (`ROOT/recovery_protocol.json` existence).
- **No HTTP-endpoint fallback** — strictly file-based, like NN. Live data still available via existing `/recovery/history` + `/recovery/learner/efficacy` endpoints.
- **21 unit tests** covering all 5 `_filter_events` cases + 4 `cmd_list` cases + 3 `cmd_event` cases + 2 `cmd_learner` cases + 7 `main()` integration cases.

Operator runbook §7.1 documents 5 example invocations.

### v1.8.2 — Calibration session inspection CLI (Checkpoint PP)

230-line CLI in [src/axioma/tools/calibration_inspect.py](src/axioma/tools/calibration_inspect.py):

- **Three action modes**: `--list` (default; sorted by `started_at_beat`, most-recent-first), `--session PREFIX` (8-char-prefix match), `--summary` (per-kind aggregate block — mean/min/max kappa for zone; mean/min/max accuracy for meta_cog; verdict + task-type histograms).
- **`--kind zone|meta_cog` filter** applies to `--list` and `--summary`; silently ignored with `--session` (prefix is uniquely identifying).
- **Pairs truncation**: `--session` output shows first 5 + last 5 pairs if > 10 total, keeping terminal output bounded.
- **stdlib `json`, not msgspec**: calibration files are KB-scale and operator-facing — symmetric stdlib I/O is the right call here.
- **22 unit tests** covering 6 helper cases + 4 `cmd_list` cases + 4 `cmd_session` cases + 3 `cmd_summary` cases + 5 `main()` integration cases.

This checkpoint pivoted away from the originally recommended zone-inspector after discovering zone state isn't persisted to disk (`classify_zone` is a pure function; `Heartbeat._prev_zone` is runtime-only). The calibration inspector covers the indirect zone-inspection use case via F6 zone validation sessions, which compare operator-labeled zones against the substrate's classifications.

Operator runbook §7.1 documents 5 example invocations.

### v1.8.3 — `/dashboard` HTML monitoring page (Checkpoint QQ)

~155-line self-contained HTML document constant + new endpoint in [src/axioma/interface/http_api.py](src/axioma/interface/http_api.py):

- **`GET /dashboard`** returns the HTML constant via `HTMLResponse`; ~8.1 KB total payload.
- **Polls `/aos_g/self_check` every 3 seconds** via `fetch()`; re-renders four blocks (overall-status pill, Config + Engine state tables, per-organ contribution bar chart, Checks list).
- **Color-coded status pill** with 5 states (`ok` / `warmup` / `warning` / `off` / `unknown`) via CSS custom properties.
- **"updated Ns ago" indicator** refreshes at 1 Hz independent of the fetch cycle so the page never looks frozen.
- **`error` block surfaces fetch failures** explicitly ("fetch failed: HTTP 503" instead of a stale page).
- **Plain HTML + inline CSS + vanilla JS, no framework**: zero dependencies, no CDN, no build step. Trade-off accepted: `<div>`-based bar chart instead of SVG; no advanced charting.
- **3-second polling, not WebSocket**: simpler lifecycle; sub-second updates not needed for at-a-glance status.
- **`/dashboard` not under `/admin/`**: read-only status; same security posture as `/aos_g/self_check`.
- **5 new tests** in `test_http_api.py` covering content-type, self-contained-ness (no external `<link>`/`<script src=>`), correct endpoint reference, status-class definitions, and co-existence with the JSON endpoint.

Operator runbook §5.1 and new §6.4 document the dashboard's use cases (live warmup monitoring, post-deploy smoke check, incident triage) and troubleshooting hints.

---

## What hasn't changed

- All v1.0–v1.7 substrate behavior (5 organs, drive math, plasticity dynamics, perturbation pipeline, MNEME stage-1/2/3 compensations)
- All measurement engines (θ short/long, raw MI, cascade_delay, ΔΦ, fragmentation monitor, AOS-G + ψ structure, meta-cog, coherence scheduler)
- All v1.0–v1.7 acceptance gates (V6, V8, V10, V11, V12, V13)
- v1.7's default-flipped MNEME compensations (`mneme_compensation_2_enabled = True`, `mneme_compensation_3_enabled = True`)
- v1.5's `aos_g_normalize_per_organ = True` + `aos_g_alert_threshold_auto_tune = True`
- v1.3's PNEUMA-weighted `aos_g_gap_weights` + static initial `aos_g_alert_threshold = 0.152`
- v1.6 audit-chain hardening (LoadResult, register-time validation, bounded resource invariants, etc.)
- C12 boundary (substrate-privacy) enforced both at runtime + lint time
- All HTTP/WS/registry/peer-conversation interfaces (plus `/dashboard` as a new read endpoint)
- `python -m axioma` production entrypoint
- All backwards-compat YAMLs (`configs/v1_0_backwards_compat.yaml`, `configs/v1_4_backwards_compat.yaml`, `configs/v1_6_backwards_compat.yaml`)
- All ComposeConfig / SubstrateConfig / MeasurementConfig field defaults

The v1.8 series is **purely additive at the public API surface**: new CLI entrypoints under a new package, one new read-only HTTP endpoint. Nothing is removed, renamed, or default-flipped.

---

## Verification

| Check | Result |
|---|---|
| `pytest tests/ -m "not infra"` | **756 passed** (+62 vs v1.7: 14 NN + 21 OO + 22 PP + 5 QQ) |
| `pytest tests/ -m infra` | **11 passed** |
| `ruff check src/ tests/ scripts/` | All checks passed |
| `mypy src/axioma/` | Success: no issues found in 70 source files (+4 vs v1.7: `axioma.tools` package + 3 CLI modules) |
| `lint-imports` | C12 contract KEPT |
| Code size growth (v1.7 → v1.8) | **+2,158 LoC** (29,555 → 31,713). 3 new CLI modules (~710 LoC) + 3 new test modules (~840 LoC) + dashboard HTML/JS (~210 LoC) + runbook updates + incidental |
| New operator surfaces | **4** (3 CLIs + 1 dashboard endpoint) |
| New `axioma.tools` package | shipped; 3 tools establishing the convention |
| HTTP endpoints | 33 → **34** (`/dashboard` added) |

---

## Migration

### Operators upgrading from v1.7

**Zero action required.** v1.8 preserves all v1.7 default behavior. Public APIs are backwards-compat; no existing endpoint changed; no configuration default flipped.

### Operators wanting to use the new CLIs

After any deployment writes snapshots / recovery events / calibration sessions:

```bash
# Snapshot inspection
python -m axioma.tools.snapshot_inspect data/state/snapshots
python -m axioma.tools.snapshot_inspect data/state/snapshots --current
python -m axioma.tools.snapshot_inspect data/state/snapshots --current --component drive

# Recovery-history inspection
python -m axioma.tools.recovery_inspect data/state/snapshots --current
python -m axioma.tools.recovery_inspect data/state/snapshots --current --stage 2
python -m axioma.tools.recovery_inspect data/state/snapshots --current --learner
python -m axioma.tools.recovery_inspect data/state/snapshots --current --event abc12345

# Calibration session inspection
python -m axioma.tools.calibration_inspect results/phase_f
python -m axioma.tools.calibration_inspect results/phase_f --kind zone
python -m axioma.tools.calibration_inspect results/phase_f --summary
python -m axioma.tools.calibration_inspect results/phase_f --session abc12345
```

All three CLIs are read-only; safe to run against an in-flight production deployment.

### Operators wanting to use the dashboard

Point a browser at the HTTP server's port:

```
http://host:8821/dashboard
```

The page polls `/aos_g/self_check` every 3 seconds and re-renders. Same security posture as the underlying JSON endpoint — operators wanting auth can gate the path via their reverse proxy.

### Operators upgrading from v1.6 or earlier

Same as v1.7 — see [RELEASE_v1.7.md](RELEASE_v1.7.md) for the v1.6 → v1.7 migration (MNEME compensation default flip). The v1.7 → v1.8 step adds no further migration work.

---

## What's open after v1.8

| Item | Why it's open |
|---|---|
| **Multi-peer broadcast in peer-conversation** | Candidate feature from MM/QQ. Current handler routes one reply per inbound; broadcast would let multiple peers see each other's messages. Needs protocol design — does each peer reply, or does the server fan out? Architecturally more open than the v1.8 toolkit work. |
| **Additional measurement engines** | Candidate feature from MM/QQ. Examples: per-organ correlation matrix, lag-correlated cross-coupling indicator, drive-entropy tracker. Each is a small multi-checkpoint cycle. Suitable for a v1.9 series. |
| **Wider 5-seed × 100K MNEME re-validation** | Optional reinforcement of LL/MM's v1.7 evidence. ~3 hours compute. Strengthens v1.7's empirical case if any operator surfaces unexpected production behavior. Not blocking. |
| **v1.1.1 / v1.1.2** | Live F6/F8 calibration sessions — externally-gated (operator availability). The v1.8.2 calibration inspector is ready to consume their outputs when sessions are produced. |
| **v1.1.7** | Real 24h soak — hardware-gated (dedicated H100). |
| **v1.4.1 substrate-amendment variant** | Superseded by the v1.4.1 metric variant + v1.5 default-flip; backlog-only. |

No new architectural items surfaced during the v1.8 feature series. The codebase is solid; subsequent v1.9+ work can choose between architectural deepening (multi-peer broadcast, new engines) and operator-tooling extension (more CLI inspectors slotting into `axioma.tools`, dashboard enrichment).

---

## Per-checkpoint roll-up (v1.8-relevant)

| # | Checkpoint | Wall-clock | Key deliverable |
|---|---|---|---|
| NN | v1.8.0 snapshot inspection CLI | ~40 min | `python -m axioma.tools.snapshot_inspect` + 14 tests + new `axioma.tools` package |
| OO | v1.8.1 recovery-history inspection CLI | ~35 min | `python -m axioma.tools.recovery_inspect` + 21 tests + source-resolution polymorphism |
| PP | v1.8.2 calibration session inspection CLI | ~40 min | `python -m axioma.tools.calibration_inspect` + 22 tests; pivot from zone_inspect documented |
| QQ | v1.8.3 `/dashboard` HTML monitoring page | ~40 min | Self-contained HTML + new `GET /dashboard` endpoint + 5 tests |
| **RR** | **v1.8 release artifact** | **~30 min** | **This release** + runbook cross-links |

Full per-checkpoint history in [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md).

---

## On the v1.8 vs v1.6 / v1.7 framing

v1.6 was the audit-and-harden release (zero default changes, 22 bug fixes). v1.7 was the substrate-default-flip release (MNEME stage-2/3 compensations on by default). v1.8 is the first **operator-tooling** release — neither substrate nor audit, but surfacing what's already there.

The natural reading is that AXIOMA's lifecycle has cycled through three modes — *build* (A through V), *harden* (BB through II), *tune* (LL/MM), *extend operator surface* (NN through QQ) — and each cycle is a sustainable unit of work between architectural decision points. The v1.8 cycle wraps without producing new architectural questions; the codebase is again ready for whatever direction the next cycle takes (further toolkit extension, architectural deepening in peer-conversation, or v1.9-series feature work).

---

**v1.8 ships. Three new CLIs, one new HTML dashboard, zero default-behavior changes, zero migration work for v1.7 deployments.**
