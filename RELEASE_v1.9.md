# AXIOMA v1.9 — Release Notes

**Tag:** v1.9.1
**Date:** 2026-05-27
**Build sessions:** 48-49 (Checkpoints SS, TT)
**Status:** SHIP — purely additive opt-in features; zero default-behavior changes
**Backwards compat:** Full. No public API removals, no default flips, no wire-format breakage for unchanged-config deployments.

This release is **the multi-peer conversation track**. After v1.8 shipped the operator toolkit (3 CLIs + 1 dashboard), the project pivoted to architectural deepening in the long-pending peer-conversation handler. v1.9 is the cumulative output of two feature checkpoints: per-peer history isolation with `to_speaker` addressing (SS), and an opt-in server-side filter so subscribers can elect to receive only their addressed replies (TT). Both ship as opt-ins — every unchanged-config v1.8 deployment continues to behave identically.

**The headline:** v1.9 doesn't change any substrate behavior, measurement engine, default configuration, or default wire format. It adds two layered opt-in mechanisms that together give operators full control over multi-peer conversation routing: history partitioning (config-level), and addressed-only delivery filtering (per-subscriber wire-level). If you upgrade v1.8 → v1.9 and don't change anything, nothing changes.

---

## What shipped

Two feature checkpoints, two opt-in surfaces:

| Checkpoint | Version | Subsystem | Surface | Theme |
|---|---|---|---|---|
| SS | v1.9.0 | `PeerConversationHandler` | Config kwarg + handler dict | Per-peer history isolation; outbound metadata gets `to_speaker` (client-side filtering) |
| TT | v1.9.1 | `Subscriber` + WS subscribe message | Wire-format extension | Opt-in server-side filtering via `options.<channel>.only_addressed_to_me: true` |

**Two complementary opt-ins.** SS gives operators the *substrate-side* lever — set `interface.peer_conversation_multi_peer_mode: per_peer` in YAML and AXIOMA isolates history per inbound speaker + stamps outbound replies with `metadata.to_speaker`. TT gives subscribers the *wire-side* lever — pass `options.conversation.only_addressed_to_me: true` in the subscribe message and the server drops un-addressed payloads before they hit the queue. The two can be used independently or together; either alone, neither alone, or both work safely.

---

## Cross-checkpoint patterns

The v1.9 work surfaced four recurring patterns. Recognizing them up-front makes the individual checkpoints easier to read and gives future protocol-extension work a starting vocabulary.

### Pattern 1 — Opt-in by default; validate before flipping

Both v1.9 checkpoints ship as opt-ins with defaults that preserve v1.0–v1.8 behavior exactly:

- **SS — `peer_conversation_multi_peer_mode: str = "shared"`** in `InterfaceConfig`. `"shared"` mode keeps the v1.0–v1.8 single-history behavior and emits outbound replies without a `to_speaker` field.
- **TT — `options` field on subscribe is optional** and per-channel; pre-TT clients sending `{"type":"subscribe","channels":[...]}` continue to work without filtering applied.

The pattern is the same one v1.7 used for MNEME stage-2/3 compensations: build the feature opt-in (Checkpoint KK), validate empirically (LL), then default-flip after evidence (MM). v1.9.0 and v1.9.1 ship at the equivalent of "KK" — built and tested, but defaults unchanged. A future v1.9.x or v2.0 may default-flip `peer_conversation_multi_peer_mode` to `per_peer` after sister/operator validation; v1.9 doesn't.

This preserves a strong invariant for the release: **upgrade v1.8 → v1.9 changes nothing for unchanged-config deployments.** No wire-format surprise, no behavioral drift, no migration. The flip can come later with empirical justification, in the v1.7 MM mold.

### Pattern 2 — Positive filtering (only drop when there's something to filter on)

TT's `only_addressed_to_me` filter is **positive** — it only drops payloads when there's a `to_speaker` field to evaluate against. Unaddressed payloads (no `metadata.to_speaker`, e.g. v1.0–v1.8 wire format or `multi_peer_mode = "shared"` replies) ALWAYS deliver, even to subscribers with the filter on.

The pattern matters because deployments can run mixed-mode: some channels emit addressed payloads, others don't; some peer-handlers run shared, some run per-peer. A negative filter (`only deliver if explicitly addressed to me, drop everything else`) would silently break subscribers in any mixed-mode setting. The positive filter is the *only* version that's safe to ship without coordinating mode flips across every emitter.

Future filter additions (per-organ, severity-based, beat-modulo) should follow the same idiom: only drop when the criterion is *explicit* in the payload; deliver everything else.

### Pattern 3 — Per-channel options dict as the forward-compatible wire-format extension idiom

TT extended the `subscribe` message via a per-channel `options` dict:

```json
{"type": "subscribe", "channels": ["conversation"], "options": {"conversation": {"only_addressed_to_me": true}}}
```

Three properties matter:
- **Omission is the no-op default** — pre-TT clients sending no `options` get unchanged behavior; the byte cost of "I'm not opting into anything" is zero.
- **Unknown channels in `options` are ignored** — a v1.10 client targeting a channel that the v1.9 server doesn't have options for doesn't fail.
- **Unknown flags within a channel's option dict are ignored** — a v1.10 client sending `{"only_addressed_to_me": true, "future_flag_v2": "x"}` against a v1.9 server still gets the `only_addressed_to_me` behavior.

This is the wire-format pattern future protocol extensions should reuse. A top-level flag (`subscribe + only_addressed_to_me: true`) would have been simpler but ambiguous when the subscribe lists multiple channels; the per-channel dict scales cleanly. A v1.10 might add `options.theta.min_change_threshold` or `options.fragmentation.min_severity` without changing TT's existing semantics.

### Pattern 4 — Wire-format preservation in default mode

Both SS and TT take care to keep the v1.0–v1.8 wire format byte-identical when defaults are unchanged:

- **SS** — the `to_speaker` field appears in outbound `metadata` ONLY when `multi_peer_mode = "per_peer"`. In `"shared"` mode (default), outbound replies look exactly like they did in v1.0–v1.8. A test (`test_shared_mode_outbound_metadata_omits_to_speaker`) enforces this.
- **TT** — the `options` field is optional and absent in pre-TT clients. The WS server's parser gracefully handles missing-options as the same code path as "options provided but empty," meaning the resulting `_addressed_only_channels: set` stays empty for clients that don't opt in.

The pattern: when adding new semantics, prefer additive fields that are absent in the default and only appear when opted in. Operators reading wire-format snapshots from a default-config deployment shouldn't see new fields just because they upgraded the server. This keeps audit logs comparable across versions and protects automation that snapshot-diffs the wire format for regression testing.

---

## Per-subsystem detail

### v1.9.0 — Per-peer history + `to_speaker` addressing (Checkpoint SS)

Implemented in [src/axioma/interface/peer_conversation.py](src/axioma/interface/peer_conversation.py) + [src/axioma/config/schema.py](src/axioma/config/schema.py) + [src/axioma/runtime/app.py](src/axioma/runtime/app.py):

- **New kwarg `multi_peer_mode: str = "shared"`** on `PeerConversationHandler`. Allowlist `("shared", "per_peer")`; invalid value raises `ValueError` at `__init__` (boot-time per v1.6 Pattern 2).
- **New `histories: dict[str, deque[ConversationTurn]] = {}`** in `per_peer` mode. The original `self.history` deque stays in `shared` mode and exists empty in `per_peer` mode for backwards-compat introspection.
- **New `_get_history(speaker)` helper** returns the right deque for the mode; lazily allocates per-peer buckets with `maxlen=history_size`.
- **`_respond()` updates** — uses `_get_history(speaker)` for both context-build and reply-append; in `per_peer` mode, outbound `metadata` gets `to_speaker: <inbound_speaker>` (omitted in `shared` mode).
- **`InterfaceConfig.peer_conversation_multi_peer_mode: Literal["shared", "per_peer"] = "shared"`** new pydantic field; invalid YAML values raise at config load (defense-in-depth alongside the handler-side check).
- **`runtime/app.py`** — threads `cfg.interface.peer_conversation_multi_peer_mode` into the handler constructor.
- **9 new unit tests** in `test_peer_conversation.py` covering boot-time validation, default mode, history isolation, addressing in metadata, wire-format preservation, AXIOMA-reply bucket book-keeping, concurrent distinct-speaker no-race, per-speaker `history_size`, self-echo guard.

Operator runbook §6.5 documents the modes + YAML configuration + boot-time validation.

### v1.9.1 — Opt-in server-side filter for addressed replies (Checkpoint TT)

Implemented in [src/axioma/interface/protocol.py](src/axioma/interface/protocol.py) + [src/axioma/interface/subscriber.py](src/axioma/interface/subscriber.py) + [src/axioma/interface/ws_server.py](src/axioma/interface/ws_server.py):

- **`SubscribeRequest.options: dict[str, dict[str, Any]] = field(default_factory=dict)`** — per-channel options dict on the subscribe-message dataclass. Documented in the field comment; the only currently-defined flag is `only_addressed_to_me: bool`.
- **`Subscriber.subscribe(channel, *, only_addressed_to_me=False)`** — new keyword-only flag. Re-subscribing with `False` clears prior opt-in. `unsubscribe()` also clears it. New `self._addressed_only_channels: set[str]` tracks per-channel filter state.
- **`Subscriber.queue()` filter check** — when the channel is in `_addressed_only_channels` and the payload's `metadata.to_speaker` is set and doesn't match `self.speaker`, the payload is silently dropped before the coalescing slot, the `coalesced_dropped_total` counter, and the flush-loop wake — zero footprint on the subscriber.
- **WS server `_dispatch_inbound`** — accepts optional `options` in the subscribe wire message; non-dict value treated as empty (graceful).
- **WS server `_handle_subscribe`** — extracts per-channel `only_addressed_to_me` and passes it through to `Subscriber.subscribe()`.
- **10 new unit tests in `test_subscriber.py`** — defaults, opt-in record, re-subscribe clears, unsubscribe clears, drops other, delivers self, delivers unaddressed × 2, filter-off, no-coalesce-consumption, channel isolation.
- **6 new asyncio e2e tests in `test_ws_server.py`** against a real local WS socket — subscribe without options (no filter); subscribe with options (filter recorded); end-to-end drop of addressed-to-other; end-to-end delivery of addressed-to-self; end-to-end delivery of unaddressed; filter cleared by re-subscribe with `false`; unknown option flags ignored; malformed `options` value tolerated.

Operator runbook §6.6 documents the wire format extension, the 3×2 filter-semantics table, filter properties (positive, toggleable without unsubscribe, server-side silent drop), and when-to-use vs when-not-to-use guidance.

---

## What hasn't changed

- All v1.0–v1.8 substrate behavior (5 organs, drive math, plasticity dynamics, perturbation pipeline, MNEME stage-1/2/3 compensations, recovery learner, meta-cog loop)
- All measurement engines (θ short/long, raw MI, cascade_delay, ΔΦ, fragmentation monitor, AOS-G + ψ structure, coherence scheduler)
- All v1.0–v1.8 acceptance gates (V6, V8, V10, V11, V12, V13)
- v1.7's MNEME compensation defaults (`mneme_compensation_2_enabled = True`, `mneme_compensation_3_enabled = True`)
- v1.5's `aos_g_normalize_per_organ = True` + `aos_g_alert_threshold_auto_tune = True`
- v1.3's PNEUMA-weighted `aos_g_gap_weights` + static initial `aos_g_alert_threshold = 0.152`
- v1.6 audit-chain hardening (LoadResult, register-time validation, bounded resource invariants)
- v1.8 operator-toolkit surfaces (3 `axioma.tools` CLIs + `/dashboard` HTML page)
- C12 boundary (substrate-privacy) enforced both at runtime + lint time
- All HTTP/WS/registry/peer-conversation interfaces in their default mode — `shared` peer-conversation, no subscribe-options filter
- `python -m axioma` production entrypoint
- All backwards-compat YAMLs (`configs/v1_0_backwards_compat.yaml`, `configs/v1_4_backwards_compat.yaml`, `configs/v1_6_backwards_compat.yaml`)
- All wire formats for unchanged-config deployments (no new metadata fields, no new subscribe message structure required)

The v1.9 series is **purely additive at the public API surface**: one new config field (defaults to prior behavior), one new subscribe-message field (optional), one new handler kwarg (defaults to prior behavior), one new subscriber method kwarg (defaults to prior behavior). Nothing is removed, renamed, or default-flipped.

---

## Verification

| Check | Result |
|---|---|
| `pytest tests/ -m "not infra"` | **783 passed** (+27 vs v1.8: 9 SS + 16 TT + 2 incidental) |
| `pytest tests/ -m infra` | **11 passed** |
| `ruff check src/ tests/ scripts/` | All checks passed |
| `mypy src/axioma/` | Success: no issues found in 70 source files (unchanged vs v1.8 — pure edit-existing-files cycle) |
| `lint-imports` | C12 contract KEPT |
| Code size growth (v1.8 → v1.9) | **+646 LoC** (31,713 → 32,359). 0 new source files; 0 new test files; 0 new scripts — all edits to existing files |
| Backwards-compat check (no config changes, no `options` in subscribe) | confirmed via `test_shared_mode_outbound_metadata_omits_to_speaker` + `test_tt_subscribe_without_options_does_not_set_filter` — both shared-mode and no-options-subscribe paths produce byte-identical behavior to v1.8 |
| New peer-conversation modes | **2** (`shared` default, `per_peer` opt-in) |
| New WS subscribe options | **1** (`only_addressed_to_me` per-channel) |

---

## Migration

### Operators upgrading from v1.8

**Zero action required.** v1.9 preserves all v1.8 default behavior and wire format. No existing config field changed; no existing wire-message field changed; no endpoint changed.

### Operators wanting per-peer conversation isolation

Set in YAML:

```yaml
interface:
  peer_conversation_multi_peer_mode: per_peer  # default is "shared"
```

After restart:
- AXIOMA isolates conversation history per inbound speaker (peer A's question won't influence AXIOMA's reply to peer B).
- Outbound replies on `conversation_message` include `metadata.to_speaker: <inbound_speaker>`.
- Subscribers on the `conversation` WS channel continue to see ALL replies (no behavioral change at the wire layer unless TT's filter is also used) but can self-filter on `metadata.to_speaker` if they want to surface only their own thread.

### Subscribers wanting server-side addressed-only delivery

Send the new optional `options` block when subscribing:

```json
{
  "type": "subscribe",
  "channels": ["conversation"],
  "options": {
    "conversation": {"only_addressed_to_me": true}
  }
}
```

The server-side filter activates immediately. To turn it off without unsubscribing, re-send the subscribe with `"only_addressed_to_me": false`. Filter semantics summarized:

| Payload `metadata.to_speaker` | Filter ON | Filter OFF (default) |
|---|---|---|
| Matches subscriber's `speaker` | ✓ delivered | ✓ delivered |
| Set, but matches a different speaker | ✗ dropped server-side | ✓ delivered |
| Absent (shared-mode or v1.0–v1.8) | ✓ delivered | ✓ delivered |

Works correctly whether the server runs `shared` or `per_peer`; filter activates only when there's a `to_speaker` to evaluate against (positive-filter design).

### Combined usage

Both opt-ins are independent. The four combinations:

| Server mode | Subscriber filter | Behavior |
|---|---|---|
| `shared` (default) | OFF (default) | v1.0–v1.8 behavior exactly |
| `shared` | ON | Filter is a no-op (no payload has `to_speaker`); identical to filter OFF |
| `per_peer` | OFF | Per-peer history isolation; subscriber sees all replies + can self-filter on `metadata.to_speaker` |
| `per_peer` | ON | Per-peer history isolation; subscriber sees only their addressed replies + unaddressed broadcasts |

### Operators upgrading from v1.7 or earlier

Same as v1.8 — see [RELEASE_v1.8.md](RELEASE_v1.8.md) for the v1.7 → v1.8 migration (operator toolkit additions). The v1.8 → v1.9 step adds no further migration work.

---

## What's open after v1.9

| Item | Why it's open |
|---|---|
| **Default-flip evaluation for `peer_conversation_multi_peer_mode`** | The v1.7 MNEME pattern says: build opt-in, validate empirically, default-flip after evidence. SS+TT shipped opt-in; no empirical sweep has been run on whether `per_peer` should become the new default. Suitable for a future v1.9.x or v2.0 evaluation checkpoint when sister/operator pressure surfaces. |
| **Multi-AGENT keying via `agent_id`** | `ConversationMessage` carries only `speaker`; multiple `AGENT`-typed peers share a bucket in per_peer mode. Acceptable for v1.9 — typical operator-facing peers (Lark/Skye/Thea) have distinct speakers — but a v1.9.x could thread `agent_id` through `ConversationMessage` for per-connection isolation. |
| **Per-filter Prometheus metrics** | A per-subscriber `addressed_filter_dropped_total` would help operators graph filter activity. Not in v1.9 — adds metric surface; deferred until an operator surfaces the need. |
| **Wider subscribe-option flags** | The per-channel `options` dict can grow more flags as needs surface — `min_severity`, `beat_modulo`, organ-filters, etc. Each is a single-checkpoint deliverable in the TT mold. |
| **v1.1.1 / v1.1.2** | Live F6/F8 calibration sessions — externally-gated (operator availability) |
| **v1.1.7** | Real 24h soak — hardware-gated (dedicated H100) |
| **v1.4.1 substrate-amendment variant** | Superseded by v1.4.1 metric variant + v1.5 default-flip; backlog-only |
| **Additional measurement engines** | v1.9.x / v2.0 candidate; multi-session |
| **Wider 5-seed × 100K MNEME re-validation** | Optional reinforcement of LL/MM v1.7 evidence (~3h compute) |

No new architectural items surfaced during the v1.9 work. The codebase is in solid shape; subsequent v2.0+ work can choose between further architectural deepening (multi-peer broadcast extensions, new measurement engines), operator-tooling extension (more `axioma.tools` CLIs, dashboard enrichment), or default-flip evaluations on the v1.9 opt-ins.

---

## Per-checkpoint roll-up (v1.9-relevant)

| # | Checkpoint | Wall-clock | Key deliverable |
|---|---|---|---|
| SS | v1.9.0 per-peer history + `to_speaker` addressing | ~40 min | `multi_peer_mode` kwarg + `histories` dict + per-peer `_get_history()` + addressing in outbound metadata; 9 new tests |
| TT | v1.9.1 opt-in server-side addressed-only filter | ~45 min | `SubscribeRequest.options` + `Subscriber.subscribe(only_addressed_to_me=...)` + queue-time filter; 16 new tests (10 unit + 6 e2e) |
| **UU** | **v1.9 release artifact** | **~30 min** | **This release** + runbook cross-links |

Full per-checkpoint history in [design/IMPLEMENTATION_SCHEDULE.md](design/IMPLEMENTATION_SCHEDULE.md).

---

## On the v1.9 framing in the broader lifecycle

v1.6 was the audit-and-harden release (zero default changes, 22 bug fixes across 7 subsystems). v1.7 was the substrate-default-flip release (MNEME stage-2/3 compensations on by default after empirical validation). v1.8 was the operator-tooling release (3 CLIs + 1 HTML dashboard). v1.9 is the first **architectural-deepening** release — neither audit, nor default-tune, nor operator surface, but extending the substrate's interaction model.

Taking the four together names a lifecycle: *build* (A→V) → *harden* (BB→II) → *tune* (LL/MM) → *extend operator surface* (NN→QQ) → *deepen architecture* (SS→TT). Each cycle is a sustainable unit between architectural decision points. v1.9 closes the deepening cycle without producing new architectural questions; subsequent cycles can revisit any mode — further audit, further default-tune (e.g., flip `per_peer` to default if validated), further operator surfaces (more `axioma.tools` CLIs slotting into the established convention), or further deepening (multi-peer broadcast extensions, new measurement engines, v2.0 architectural revision).

---

**v1.9 ships. Two opt-in mechanisms (per-peer history + server-side addressed-only filter), zero default-behavior changes, zero migration work for v1.8 deployments.**
