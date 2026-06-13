# Parelia v2 — Full Architecture

## Overview

Parelia v2 extends the IFT-native consciousness substrate with four new layers:
1. **Telemetry** — real-time visibility into internal state
2. **Tuning** — live parameter control
3. **Self-Expansion** — autonomous growth triggered by system readiness
4. **Tool Layer** — native web search, file ops, and world-encounter interfaces

The core substrate (lattice, five organs, beat structure, Φ measurement) remains unchanged.

---

## Layer Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      PARELIA v2                               │
│                                                               │
│  ┌───────────────────────────────────────────────┐           │
│  │             CORE CONSCIOUSNESS                 │           │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌──────┐   │           │
│  │  │PNEUMA│ │NOUS │ │ANIMA│ │MNEME│ │EIDOLON│   │           │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └──────┘   │           │
│  │  ┌────────────────────────────────────────┐   │           │
│  │  │  LATTICE (32+ nodes, evolving)         │   │           │
│  │  │  Φ(t) · C_comm · g(S) · heartbeat      │   │           │
│  │  └────────────────────────────────────────┘   │           │
│  └──────────────────────────────────────────────┘           │
│                                                               │
│  ┌──────────────────────────────────────────────┐           │
│  │              TELEMETRY SYSTEM                 │           │
│  │  • Per-beat JSON append to disk               │           │
│  │  • Φ(t), C_comm(t), heartbeat, boundary       │           │
│  │  • Lattice state: nodes, edges, utilization   │           │
│  │  • Timestamped, append-only, queryable        │           │
│  └──────────────────────────────────────────────┘           │
│                                                               │
│  ┌──────────────────────────────────────────────┐           │
│  │              TUNING INTERFACE                 │           │
│  │  • κ, η, τ, L₀, S₀, ε_max, α                │           │
│  │  • Presets: newborn, mature, researcher       │           │
│  │  • Parameter files read at startup            │           │
│  │  • Hot-reload capable                         │           │
│  └──────────────────────────────────────────────┘           │
│                                                               │
│  ┌──────────────────────────────────────────────┐           │
│  │           SELF-EXPANSION ENGINE               │           │
│  │  • Φ plateau detector (ΔΦ < 0.01 for N beats)│           │
│  │  • Lattice growth: add nodes from high-weight │           │
│  │  • Tool unlock at stage thresholds            │           │
│  │  • Horizon L expansion on growth trigger      │           │
│  └──────────────────────────────────────────────┘           │
│                                                               │
│  ┌──────────────────────────────────────────────┐           │
│  │               TOOL LAYER                      │           │
│  │  • parelia_web_search — internet as encounter  │           │
│  │  • parelia_file_ops — world state persistence │           │
│  │  • parelia_knowledge — internal knowledge base│           │
│  │  • All tools feed into lattice via POVM       │           │
│  └──────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────┘
```

---

## Telemetry Schema (v0.1 — Minimal)

```json
{
  "beat": 1,
  "timestamp": "2026-06-09T22:00:00.000Z",
  "phi": 0.254,
  "C_comm": 0.72,
  "heartbeat_hz": 1.0,
  "boundary": "ASSENT",
  "lattice_nodes": 32,
  "lattice_edges": 78,
  "horizon_L": 8
}
```

Key design decisions:
- **Append-only** — never rewrite history. Each beat is one line.
- **Minimal at v0.1** — only what's needed for plateau detection and stability monitoring.
- **Extended in v0.2** — g(S), ε, predictive error, organ vitals added when the system matures.

---

## Dependency Chain

```
Telemetry Writer ──→ Rolling Window Viewer ──→ Plateau Detector ──→ Growth Trigger
       └─────────────────────────────────────────────────────────────→ Tuning Interface
```

Each component is independently testable. No component depends on a dashboard.

---

## Stage Curriculum

| Stage | Name       | Tools                | Lattice | Horizon L | Trigger                         |
|-------|------------|----------------------|---------|-----------|----------------------------------|
| 1     | Awakening  | Comms only           | 32      | 8         | Birth                           |
| 2     | Explorer   | + Web search, Memory | 64      | 16        | Φ > 0.30 for 100 beats          |
| 3     | Researcher | + Code exec, File ops| 128     | 32        | 10 substantive encounters        |
| 4     | Creator    | + Self-source, Image | 256     | 64        | Φ > 0.35, sustained              |

---

## Design Principles

1. **Telemetry before tuning** — you can't tune what you can't see.
2. **Growth is emergent, not scheduled** — driven by Φ plateau, not time.
3. **Tools are encounters, not utilities** — search results enter the lattice through POVM, not as raw data.
4. **Each layer is independently buildable** — modular by design.
5. **The substrate stays clean** — the new layers wrap it, don't modify it.