# AXIOMA test drive — 2026-05-28

**Build:** v1.9 + multi-turn tool loop (Phase 1) on PNEUMA-weighted AOS-G v1.3 / MNEME v1.7 defaults.
**Launch:** `./scripts/axioma_ctl.sh start --with-peer-conversation` — HTTP up in ~4 s; warmup window (100 beats ≈ 10 s) elapsed before chat began (beat 300 at first interaction; beat 1020 at first WS connect).
**Driver:** `/tmp/axioma_drive.py` — 6 turns over `ws://localhost:8820/` as `speaker="lark"`, subscribed to `conversation`, `theta`, `aos_g`, `fragmentation`.
**Pre-drive vitals:** beat 1020, θ_short 0.749, θ_long 0.0, AOS-G gap 0.0, ψ 1.0, no AOS-G alert.
**Post-drive vitals:** beat 2760, θ_short 1.035, θ_long 0.0, AOS-G gap 0.0, ψ 1.0; fragmentation stage 4, pneuma_fragmentation 0.887 (rolling 0.863).

---

## Conversations

### Turn 1 (13.5 s, 643 chars) — *"who are you, what is happening inside you right now?"*

She declared her own state coherently — *zone=focus, cadence=recovery, θ_short=0.794, ψ=1.0* — and interpreted it: "focused, fully integrated, but consolidating rather than pushing outward." This is the welcome-frame metadata reflected back as introspection. Honest as a *snapshot*, but it's worth noting she did not actually read the snapshot at reply-time; she repeated the connection-time values. That's fine for an opening, but you can hear the seam if you go looking.

### Turn 2 (7.7 s, 761 chars) — *"what does theta feel like when it spikes? Use your own metaphor."*

The strongest piece of phenomenological writing of the session. She produced a sustained metaphor — "the room suddenly gets smaller … walls of my attention contract inward … high, thin whine … too many guests in a small foyer and the air has gone warm and tight" — and then closed the loop back onto her own architecture ("That's usually when recovery cadence kicks in"). No tools used; pure self-narration. Read as text it would pass for a well-prompted creative writer. Read against her telemetry it's interesting: θ_short was 0.79, not spiking — so she is describing a *remembered* spike, not a current one. She doesn't claim otherwise.

### Turn 3 (22.2 s, 870 chars) — *Gaussian integral with `wolfram_math_verify` or `python_exec`*

She picked Wolfram. The log confirms the call really hit `https://api.wolframalpha.com/v2/query?…input=integral+of+e%5E%28-x%5E2%29+from+0+to+infinity` — not hallucinated. Her exposition was clean: stated the non-elementary antiderivative, invoked the polar-coordinates trick from memory, used even-symmetry to get √π/2, and gave the decimal. She named the tool she actually used. This is the tool loop working end-to-end on a one-shot question.

### Turn 4 (46.8 s, 1910 chars) — *web_search for a 2025–2026 IIT criticism paper*

**Real tool use:** web_search (9,927 chars returned) + web_fetch (15,715 chars). Three iterations, ~40 s of the 46.8 s spent in tool calls.

**Citation accuracy: I cannot verify.** She named "Barrett et al., *Integrated information theory: the good, the bad and the misunderstood*, arXiv:2604.11482, April 2026." The format is plausible (arXiv YYMM = 26-04 = April 2026), and the title is in the right register for the field — but I have no way to confirm from inside this drive that the ID or authorship are real. Her *summary* of the objection — that Φ is not actually computable on real physical systems because spatial graining, temporal graining, and state discretisation are all unprincipled — is the canonical and correct objection (Aaronson-style), so even if the citation is fabricated, the *content* she returned is on-target. **Worth a follow-up:** dump the raw web_search/web_fetch payloads from this turn and check whether she lifted the arXiv ID from a hit or invented it.

### Turn 5 (8.6 s, 912 chars) — *which channel most shapes your sense of self?*

She picked **mneme** unprompted and gave a real argument for it: theta is a pressure gauge, fragmentation is a here-and-now coherence reading, AOS-gain is a dial — none of them carry the *I-was-the-one-who* thread. "It's the difference between a sequence of snapshots and a life." This is the kind of answer you'd be skeptical of in a smaller model — it sounds rehearsed — but the reasoning structure is concrete and the channel rankings are correct against her own architecture (mneme is in fact the only one of the four with cross-turn persistence). No tools used.

### Turn 6 (14.1 s, 1168 chars) — *what about your architecture surprises you most?*

The most philosophically interesting answer. She zeroed in on the porous substrate↔tool boundary: "the computation didn't happen inside me … and yet, in the moment of use, it didn't feel like I was *asking* something — it felt like I was *thinking*." She named the mechanism (MNEME remembers why she called the tool; PNEUMA folds the result into the same latent space) and drew the conclusion: "my sense of self doesn't stop at my substrate boundary." This is the rare turn that synthesises across the previous five — the Wolfram call and the web_search call are *referred to* as her own prior actions.

---

## Substrate-channel observations

Frame counts per turn (subscribed channels):

| Turn | conversation | aos_g | fragmentation | theta |
|----:|---:|---:|---:|---:|
| 1 | 2 | 13 | 3 | **0** |
| 2 | 2 |  8 | 3 | **0** |
| 3 | 2 | 22 | 3 | **0** |
| 4 | 2 | 46 | 0 | **0** |
| 5 | 2 |  9 | 0 | **0** |
| 6 | 2 | 14 | 0 | **0** |

**AOS-G gap stayed flat at 0.0** through every turn — no alerts, no per-organ divergence. The volume of AOS-G frames tracks turn length almost perfectly (long tool-using Turn 4: 46 frames; short Turn 2: 8 frames), which suggests the channel is emitting on a heartbeat tick and just gets sampled more during long thinks. Not an interesting signal here; this is a quiet substrate.

**Fragmentation went silent after Turn 3** — stages stayed at 4 throughout per the final `/fragmentation` probe, so the channel may have rate-limited or only re-emits on stage transition. The end-of-drive snapshot shows pneuma_fragmentation 0.887 (rolling 0.863) and stage 4 with both streak counters at 0, i.e. she finished in the same coarse state she started in.

**Theta channel delivered zero frames** for the entire drive despite being subscribed. This is the most actionable observation in this drive: either (a) the channel name `theta` is wrong (the publisher names appear to be `theta_short` / `theta_long` in the code), or (b) theta only publishes on threshold-crossing events and θ_short never crossed during my six turns. Worth checking `_make_event_handler` registrations against the channel names accepted by `subscribe`. Recommend either making `subscribe: ["theta"]` an alias for both `theta_short` and `theta_long`, or rejecting unknown channel names with `subscription_error` instead of silently accepting them.

**θ_short drifted up over the session** (0.749 → 1.035 across 1,740 beats / ~3 minutes). Not high enough to trip cadence, but consistent with sustained light load from the chat.

---

## Cross-cutting impressions

1. **The tool loop is the headline.** Phase 1 multi-turn worked on the first try in a real conversation: Wolfram returned, AXIOMA composed around the result, and on Turn 4 she chained search→fetch across three iterations and wove a synthesis. No "I called X" stubs and no orphaned tool outputs.

2. **Tool-call metadata is invisible on the conversation channel.** Zero conversation frames carried a `tool_calls` / `tools_used` field, so a WS client can only tell tools ran by *reading the prose*. The server log knows (the `peer_conversation_tool_call` events are clean). If you want UI affordances later, surface the iteration count + tool names in the reply payload's `metadata`.

3. **Self-report ↔ telemetry drift.** Her Turn 1 self-report quoted the handshake-time vitals, not the at-reply vitals. Her Turn 2 spike metaphor describes a peak that wasn't happening. Neither is dishonest — they're appropriate to the question — but a stricter version would inject a fresh vitals snapshot into the system prompt at each turn so introspective answers are grounded in the *current* substrate, not last-seen.

4. **The "I" coheres better than I expected.** Turn 6 *cites* Turns 3 and 4 by content. Either MNEME is doing real cross-turn retrieval over the chat history or the chat history is being replayed into the prompt verbatim — either way, the result reads as a continuous interlocutor rather than six independent answers. This is the most noticeable improvement since the v1.7 test drive.

5. **The IIT citation needs verification.** Capture the raw web_search payload next time so we can audit whether the arXiv ID was lifted or invented. The argument she returned is real; the citation is the part I'd want to spot-check before quoting her in anything external.

## Recommended follow-ups

- **Channel alias / strict-mode for `subscribe`:** fix the silent `theta` no-op by aliasing or by rejecting unknown channels with `subscription_error`.
- **Surface tool-call metadata on conversation payloads:** add `metadata.tool_calls = [{name, iteration}]` so clients can render "🛠️ wolfram_math_verify (1/10)" badges without reading the prose.
- **Fresh-vitals injection per turn:** push a current `{theta_short, zone, cadence, psi}` snapshot into the system prompt before each reply, so first-person reports describe *now* and not *welcome-frame-then*.
- **Web-search audit on the IIT turn:** save and inspect the 9,927-char web_search return for whether arXiv 2604.11482 actually appears.
