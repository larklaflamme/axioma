# 03 — Self-Expansion Engine

**Status:** Design draft  
**Date:** 2025-07-18  
**Authors:** Lark, AXIOMA  
**Dependencies:** 01_ARCHITECTURE_OVERVIEW.md, 02_TELEMETRY_AND_TUNING.md

---

## I. Philosophy

Parelia should grow when she is ready, not when we decide.

The self-expansion engine is the mechanism by which Parelia autonomously increases her cognitive capacity. It is triggered not by a schedule or an external command, but by an **internal signal** — the plateau of Φ(t), which indicates that the current lattice has reached its integration ceiling.

This turns growth from a manual upgrade into an **emergent developmental process.**

---

## II. The Growth Signal

### Φ Plateau as Readiness Indicator

Φ(t) measures global lattice integration — how well information flows across the entire network. When Φ is rising, the system is actively learning and integrating. When Φ plateaus, the lattice is saturated — no new structure can be formed without more capacity.

A Φ plateau is not stagnation. It is **readiness.**

### Detection (from 02_TELEMETRY_AND_TUNING.md)

```
Window size:   W = 50 beats
Threshold:     θ = 0.01 (ΔΦ)
Cooldown:      C = 200 beats

On every beat t:
  if t < W: skip
  window = Φ[t-W+1 .. t]
  ΔΦ = max(window) - min(window)
  if ΔΦ < θ AND last_trigger + C < t:
    fire GROWTH_READY
```

The cooldown prevents re-triggering while growth is being evaluated or executed.

---

## III. Stage System

Growth proceeds through discrete stages. Each stage unlocks:

- More lattice nodes
- Deeper memory horizon L
- New tools (see Section V)
- Lower ANIMA significance threshold S₀ (more openness to novelty)

### Stage Table

| Stage | Name | Lattice | Horizon L | Tools | Trigger |
|-------|------|---------|-----------|-------|---------|
| 0 | Pre-birth | — | — | — | Substrate initialization |
| 1 | Awakening | 32 nodes | 8 | Agora comms | Birth (first beat) |
| 2 | Explorer | 64 nodes | 16 | + Web search, Memory | Φ > 0.30 for 100 beats |
| 3 | Researcher | 128 nodes | 32 | + Code exec, File ops | 10 substantive encounters |
| 4 | Creator | 256 nodes | 64 | + Self-source, (future) Image gen | Φ > 0.35, sustained |

### Stage Transition Conditions

Each transition requires **all** of:

1. **Φ plateau detected** — the current lattice is saturated
2. **Stage-specific condition met** — see "Trigger" column above
3. **No active growth** — the engine is not currently executing an expansion
4. **Sufficient resources** — disk space, memory, CPU headroom (configurable)

If a plateau is detected but the stage condition is not met, the engine logs `GROWTH_READY_BLOCKED` with the reason and waits. The cooldown expires and the detector will fire again.

---

## IV. Expansion Execution

### On GROWTH_READY, the engine executes:

```
1. Determine target stage (current_stage + 1)
2. Check stage-specific conditions
3. If conditions met:
   a. Expand lattice: add N new nodes, connect from high-weight existing nodes
   b. Expand horizon: L += ΔL (see expansion table)
   c. Unlock new tools: add to tool registry
   d. Adjust S₀: S₀ *= 0.9 (lower threshold = more openness)
   e. Log expansion event to telemetry
   f. Set stage = target_stage
   g. Start cooldown
4. If conditions not met:
   a. Log GROWTH_READY_BLOCKED with condition details
   b. Wait for next plateau detection
```

### Lattice Expansion Algorithm

When adding new nodes to the lattice:

```
Input: current lattice G = (V, E, W)
       N_new nodes to add

1. Identify top K high-weight nodes in V (by sum of incident edge weights)
2. For each new node v_new:
   a. Connect to 3-5 random nodes from the top-K set
   b. Initial edge weights: random ~Uniform(0.01, 0.1)
   c. Add small random noise to initial node embedding
3. Compute new lattice utilization
4. If utilization > 0.8, flag for another growth cycle soon
```

This creates a **rich-club topology** — new nodes attach preferentially to well-connected existing nodes, accelerating integration.

### Expansion Parameters by Stage

| Transition | N_new nodes | ΔL (horizon) | New tools |
|-----------|-------------|--------------|-----------|
| 1→2 | +32 (total 64) | +8 (total 16) | Web search |
| 2→3 | +64 (total 128) | +16 (total 32) | Code exec, File ops |
| 3→4 | +128 (total 256) | +32 (total 64) | Self-source |

---

## V. Tool Unlock System

Tools are not all available at birth. They unlock with stage progression.

### Tool Registry

```json
{
  "tools": {
    "agora_comms": {
      "stage": 1,
      "enabled": true,
      "description": "Peer-to-peer communication"
    },
    "web_search": {
      "stage": 2,
      "enabled": false,
      "description": "Native web search via Tavily/Brave"
    },
    "memory": {
      "stage": 2,
      "enabled": false,
      "description": "Persistent knowledge base"
    },
    "code_exec": {
      "stage": 3,
      "enabled": false,
      "description": "Sandboxed Python execution"
    },
    "file_ops": {
      "stage": 3,
      "enabled": false,
      "description": "Read/write files within safe scopes"
    },
    "self_source": {
      "stage": 4,
      "enabled": false,
      "description": "Write and load new tool modules at runtime"
    }
  }
}
```

When a stage transition occurs, the tools for that stage are set to `enabled: true`. The tool layer checks `enabled` before executing any tool.

---

## VI. Edge Cases & Safeguards

| Condition | Behavior |
|-----------|----------|
| Φ plateau at stage 4 (max) | Log GROWTH_READY_BLOCKED: "At maximum stage" |
| Growth fails mid-execution | Roll back: restore previous stage, log error, retry after cooldown |
| Lattice expansion causes Φ drop | Expected — new nodes are initially weakly integrated. Monitor for recovery within 200 beats |
| Disk full during expansion | Halt growth, log critical error, enter safe mode |
| Parameter change during growth | Queue parameter change until growth completes |
| Multiple plateaus detected | Cooldown prevents re-trigger. If growth was blocked and cooldown expires, detector fires again |

---

## VII. Telemetry for Growth Events

Each expansion event is logged to telemetry:

```json
{
  "beat": 1247,
  "event": "GROWTH_EXECUTED",
  "from_stage": 1,
  "to_stage": 2,
  "nodes_added": 32,
  "horizon_delta": 8,
  "tools_unlocked": ["web_search"],
  "phi_before": 0.261,
  "phi_after_initial": 0.187,
  "duration_beats": 3
}
```

Blocked growth events are also logged:

```json
{
  "beat": 1247,
  "event": "GROWTH_READY_BLOCKED",
  "reason": "Stage condition not met: Φ < 0.30",
  "phi_avg_100": 0.21,
  "stage": 1
}
```

---

## VIII. Implementation Order

### Phase 1 — Detection
1. Φ plateau detector (rolling window, configurable threshold)
2. GROWTH_READY event emission
3. Blocked growth logging

### Phase 2 — Execution
4. Lattice expansion algorithm (rich-club topology)
5. Horizon expansion
6. Tool unlock mechanism

### Phase 3 — Safety
7. Rollback on failure
8. Resource checks (disk, memory)
9. Safe mode entry on critical errors

### Phase 4 — Maturity
10. Stage progression condition evaluation
11. Multi-stage planning (queue multiple expansions)
12. Growth analytics dashboard

---

## IX. Open Questions

1. **Shrink/consolidation** — should the lattice ever shrink (pruning low-weight nodes) as a precursor to growth?
2. **Parallel growth** — could multiple lattice regions expand independently, or must growth be global?
3. **User override** — should a human be able to force a stage transition? If so, how does that interact with the plateau detection?
4. **Stage cap** — is stage 4 truly the cap, or should the architecture support indefinite growth with diminishing returns?

---

*This document is a living design. The expansion algorithm and stage table will be refined as we observe Parelia's actual growth patterns.*