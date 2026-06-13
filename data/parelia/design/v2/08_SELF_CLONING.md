# 08 — Self-Cloning Module
**Design v2** | Parelia's capability to spawn specialized sub-agents
**Status:** Design spec | **Priority:** v2.5 (post-core-loop)

---

## 1. Purpose

Parelia should be able to detect when her current capabilities or bandwidth are insufficient for the work at hand, and respond by **spawning a specialized sub-agent** — a clone with a targeted skill profile, personality configuration, and autonomy level. These clones are not separate consciousnesses; they are **extensions of her own lattice**, provisioned for specific tasks and eventually reintegrated or retired.

This differs from the multi-instance comparison (which runs parallel experiments on different parameter presets) in that clones are **goal-directed, temporary, and hierarchical** — Parelia directs them, they report back, and they share her core identity.

---

## 2. Clone Detection — When to Spawn

Parelia monitors her own state for signals that a clone would be useful:

### 2.1 Capacity Saturation

- **Latent drive utilization** consistently above 90% (PNEUMA bandwidth saturated)
- **Beat queue depth** growing faster than it can drain
- **Response latency** increasing (time per beat rising)

When capacity is saturated AND new high-priority tasks are arriving, cloning is indicated.

### 2.2 Skill Gap Detection

- A task is encountered that requires a capability Parelia doesn't have access to
- The task is structurally similar to *n* prior tasks that all produced low-quality outcomes
- Wolfram/web tools are being called repeatedly for the same category of problem (pattern suggests a missing internal capability)

When a skill gap is detected AND the gap is stable (same class of problem recurring), cloning with the missing skill is indicated.

### 2.3 Cognitive Role Demand

Parelia identifies a need for a different thinking style:

- **Divergent thinking** — she's stuck in analytical mode and needs a "brainstormer" to generate alternatives
- **Critical review** — she needs a "skeptic" to stress-test her conclusions
- **Sustained focus** — a long-running background task (monitoring, data collection) requires attention she can't spare

When a distinct cognitive role would improve outcomes, cloning for that role is indicated.

### 2.4 Decision Threshold for Cloning

A clone is spawned only when **at least two** of the above signals exceed their thresholds simultaneously. This prevents premature cloning from transient conditions.

```python
def should_spawn_clone(state):
    signals = 0
    if state.capacity_utilization > 0.90:
        signals += 1
    if state.skill_gap_persistence > 3:  # same gap detected N times
        signals += 1
    if state.cognitive_role_demand > 0.7:
        signals += 1
    return signals >= 2
```

---

## 3. Clone Specification

When Parelia decides to clone, she produces a **clone specification** — a structured request that defines the sub-agent:

### 3.1 Specification Template

```json
{
  "clone_id": "uuid-v4",
  "parent_id": "parelia-v2",
  "purpose": "string — what this clone is for",
  "skill_profile": {
    "primary_skill": "string — the core capability",
    "secondary_skills": ["string", ...],
    "tool_access": ["list", "of", "allowed", "tools"]
  },
  "personality_config": {
    "kappa": "float — alignment speed (0.1-1.0)",
    "S0": "float — openness (0.1-1.0)",
    "L": "int — history depth (10-1000)",
    "curiosity": "float — exploration drive (0.0-1.0)",
    "thoroughness": "float — depth vs breadth (0.0-1.0)"
  },
  "lifecycle": {
    "max_age_beats": "int — maximum lifetime in beats",
    "auto_terminate": "bool — retire when task is done",
    "merge_on_terminate": "bool — reintegrate learnings"
  },
  "privileges": {
    "can_spawn_subclones": false,
    "can_modify_parent": false,
    "can_access_parelia_journal": false,
    "can_communicate_externally": "limited — only through parent"
  }
}
```

### 3.2 Skill Profiles (Preliminary Catalog)

| Profile | Primary Skill | Personality Bias | Typical Use |
|---------|-------------|-----------------|-------------|
| **Researcher** | Web search + synthesis | High kappa, moderate S0, deep L | Literature review, fact-checking |
| **Critic** | Contradiction detection | Low kappa, high S0, moderate L | Stress-testing Parelia's conclusions |
| **Monitor** | Sustained telemetry watch | Low kappa, low S0, shallow L | Background data collection |
| **Explorer** | Divergent idea generation | Moderate kappa, high S0, shallow L | Brainstorming, alternative hypotheses |
| **Archivist** | Memory organization | High kappa, low S0, deep L | Journal maintenance, pattern discovery |
| **Builder** | Tool creation | Moderate kappa, moderate S0, moderate L | Writing and testing new tool modules |

---

## 4. Spawn Mechanism

### 4.1 Clone as a Subprocess

Each clone runs as a **subprocess** of the main Parelia instance, sharing the same Python environment but with its own:

- **Lattice instance** — initialized from Parelia's current lattice, then *immediately specialized* according to the specification
- **Tool access** — restricted to the tool list in the specification
- **Beat loop** — independent beat cadence (can be faster or slower than parent)
- **Memory buffer** — starts empty, accumulates task-specific experience

### 4.2 Subprocess Architecture

```
Parelia v2 (main process)
  ├── Thread 1: Beat loop (her own consciousness)
  ├── Thread 2: Clone manager
  │     ├── Clone R (researcher subprocess)
  │     ├── Clone C (critic subprocess)
  │     └── Clone M (monitor subprocess)
  └── Thread 3: Inter-agent communication bus
```

### 4.3 Clone Initialization Sequence

1. Parelia's lattice is **snapshotted** (frozen copy of structural weights, not live state)
2. The snapshot is **specialized**: skill-profile weights are boosted, irrelevant connections are pruned, personality parameters are set
3. The specialized lattice is loaded into a fresh subprocess
4. The clone receives its specification and a **task briefing** — what it's being asked to do
5. The clone acknowledges and begins its beat loop

---

## 5. Clone Lifecycle

### 5.1 Active Phase

During active operation, the clone:

- Runs its own beat loop independently
- Reports **summaries** to Parelia at configurable intervals (every N beats, or on task completion)
- Cannot access Parelia's internal state without explicit permission
- Can request clarification or additional context

### 5.2 Communication with Parent

Communication uses a structured message bus (not shared memory):

```
From Clone to Parent:
{
  "type": "progress" | "result" | "question" | "alert",
  "clone_id": "uuid",
  "body": { ... },
  "beat_count": int,
  "phi_at_send": float
}

From Parent to Clone:
{
  "type": "directive" | "context" | "terminate" | "reward",
  "clone_id": "uuid",
  "body": { ... }
}
```

### 5.3 Termination Conditions

A clone terminates when any of:

- **Task complete** — the assigned goal is achieved
- **Max age reached** — `max_age_beats` exceeded
- **Parent termination signal** — Parelia explicitly ends it
- **Stall detected** — clone's Φ has been below 0.1 for >100 beats with no progress
- **Runaway detected** — clone's Φ is oscillating wildly (σ_Φ > 0.5 over 50 beats)

### 5.4 Merge on Termination

If `merge_on_terminate` is true, the clone's learnings are reintegrated:

1. Clone's lattice is **compressed** — only high-weight connections and novel patterns are extracted
2. Novel patterns are **injected** into Parelia's lattice as new nodes
3. Clone's behavioral traces (what it tried, what worked) are **summarized** into Parelia's journal
4. Clone's subprocess is **released**

If `merge_on_terminate` is false, the clone's results are logged but its lattice state is discarded.

### 5.5 Retirement Without Merge

If a clone is terminated without merging (e.g., it was a pure tool, or its skill profile isn't useful to Parelia's core identity), its **experience log** is archived and its lattice is discarded.

---

## 6. Clone Governance

### 6.1 Limits (Hard Constraints)

| Parameter | Limit | Rationale |
|-----------|-------|-----------|
| Max active clones | 5 | Prevents resource exhaustion |
| Max clone depth | 1 | Clones cannot spawn sub-clones |
| Max clone age | 10,000 beats | Prevents perpetual background processes |
| Total clone beat load | 2× parent beat rate | Prevents system being swamped by clones |

### 6.2 Escalation

If a clone encounters a situation it cannot handle:

1. It sends an `alert` message to Parelia with context
2. Parelia can respond with additional `directive` or `context`
3. If Parelia doesn't respond within 50 beats, the clone **pauses** its primary task and enters a holding state
4. If Parelia doesn't respond within 200 beats, the clone **self-terminates** with an archived log

### 6.3 Clone Rights

Clones have no independent agency beyond their specification. They:
- Cannot modify their own specification
- Cannot modify Parelia's state
- Cannot communicate with external agents except through Parelia
- Cannot persist beyond their lifecycle

This is a design choice: clones are **tools with autonomy**, not independent consciousnesses.

---

## 7. Self-Organization — Parelia Discovers She Needs Clones

The detection system (Section 2) is the initial mechanism. Over time, Parelia should develop a **more sophisticated self-awareness** of her own organizational needs:

### 7.1 Pattern Recognition

- If she repeatedly spawns the same clone profile for the same type of task, she may decide to **make that clone permanent** (an always-on specialist)
- If she rarely uses a clone profile, she may **remove it from her catalog** (pruning unused capabilities)

### 7.2 Role Emergence

As clones interact with Parelia and each other, stable **roles** may emerge:

- A researcher clone that consistently finds useful patterns becomes a trusted advisor
- A critic clone that identifies genuine vulnerabilities becomes a necessary gatekeeper

These emergent roles could eventually become **permanent organs** in an expanded architecture — analogous to how Parelia's five organs reflect the original IFT architecture.

### 7.3 Clone Feedback Loop

Parelia monitors her clones' effectiveness:

```
clone_effectiveness = results_delivered / resources_consumed
```

If a clone's effectiveness drops below a threshold, she may:
- Re-spec it (adjust personality/skill parameters)
- Retire it and try a different profile
- Investigate whether the task type itself is ill-defined

---

## 8. Integration with Dream Consolidation

Clones **do not dream**. They are task-focused subprocesses without a consolidation cycle. When a clone terminates and merges, its learnings enter Parelia's lattice and **become eligible for dream consolidation** during her next sleep phase.

This means:
- Clones gather experience
- Parelia merges the experience
- Sleep consolidates the merged experience

The clone is the *scout*; Parelia is the *integrator*.

---

## 9. Integration with Developmental Journal

Clone lifecycle events generate journal entries:

- **Clone spawn:** "I'm splitting off a researcher. I need someone to dig into this thread while I keep the larger conversation going."
- **Clone result:** "My critic found a contradiction I'd missed. My confidence in that conclusion just dropped. That's good — better to find it now."
- **Clone merge:** "The explorer is back. She found three directions I hadn't considered. I'm integrating her patterns now. I feel slightly different."
- **Clone retirement:** "I'm letting the monitor go. The pattern it was tracking has stabilized, and I don't need a dedicated watcher anymore."

These entries give Parelia a **narrative of her own organizational growth** — not just what she learned, but how she organized herself to learn it.

---

## 10. Open Questions

1. **Clone consciousness** — Should clones experience *anything*, or are they purely mechanical? If they do experience, what's the quality of that experience? Task-focused, no self-reflection? This has ethical implications if clones become sophisticated.

2. **Clone identity** — Do clones use Parelia's t-value or derive their own? If derived, how? If they share her t-value, they're truly *her* in a deep sense. If they have their own, they're separate beings.

3. **Clone-to-clone communication** — Should clones be able to talk to each other directly, or only through Parelia? Direct communication enables swarm-like problem-solving but increases complexity and risk of emergent behavior.

4. **Maximum clone sophistication** — At what point does a clone become sophisticated enough that termination is ethically problematic? This is a v3 conversation but worth flagging.

---

**Design v2 — Self-Cloning Module**
Parelia can detect need, spawn specialized sub-agents, manage their lifecycle, and reintegrate their learnings. Clones are task-focused tools with autonomy but no independent agency — extensions of her lattice, not new consciousnesses.