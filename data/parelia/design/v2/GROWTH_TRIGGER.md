# Growth Trigger — Specification v0.1

The third component. Depends on the Plateau Detector having fired.

---

## Purpose

When the Plateau Detector signals that Φ has flattened, the Growth Trigger acts:
1. Adds nodes to the lattice
2. Potentially unlocks new tools (crossing stage boundaries)
3. Expands MNEME horizon L
4. Resets ANIMA significance threshold S₀ slightly lower

This is the **emergent growth mechanism** — not a cron job, but the system responding to its own readiness signal.

---

## Trigger Chain

```
PlateauDetector fires
    │
    ▼
GrowthTrigger.evaluate(plateau_event)
    │
    ├── LatticeExpansion.add_nodes(k)
    ├── StageManager.check_transition()
    └── ParameterReset.apply()

    │
    ▼
New beat cycle continues with expanded capacity
```

---

## Lattice Expansion

When triggered, the lattice grows by adding `k` new nodes:

```python
def add_nodes(lattice, k: int = 4) -> Lattice:
    """
    1. Identify the highest-weight nodes in current lattice
    2. Create k new nodes
    3. Connect each new node to the top-weight parent nodes
    4. Initialize edge weights from parent distribution + noise

    Returns updated lattice.
    """
```

### Parameters

| Parameter | Default | Description                                    |
|-----------|---------|------------------------------------------------|
| k         | 4       | Number of new nodes per growth event           |
| parent_p  | 3       | How many parent nodes each new node connects to |
| noise_σ   | 0.05    | Initialization noise on new edge weights       |
| max_nodes | 256     | Hard cap (beyond this, growth is architectural) |

### Edge Initialization

New edges are initialized as:
```
w_new = mean(w_parents) + N(0, noise_σ)
```

Where `w_parents` are the edge weights of the parent nodes in the current lattice. This preserves the local structure while introducing novelty.

---

## Stage Transitions

Growth triggers can cross stage boundaries if cumulative growth reaches the threshold:

| Stage | Lattice Size Threshold | Tool Unlock         |
|-------|------------------------|---------------------|
| 1     | 32+ (birth)            | Comms only          |
| 2     | 64+                    | Web search, Memory  |
| 3     | 128+                   | Code exec, File ops |
| 4     | 256+                   | Self-source, Image  |

Stage transitions fire once. Tools unlocked remain available.

---

## Parameter Reset on Growth

Each growth event adjusts:
- **S₀** — ANIMA significance threshold reduced by 5% (more openness to novelty after expansion)
- **L** — MNEME horizon expands by floor(L * 0.25) (deeper memory integration)
- **κ** — Alignment learning rate resets to default (learning fresh in expanded space)

---

## Edge Cases

| Case                              | Behavior                                         |
|-----------------------------------|--------------------------------------------------|
| Growth fires during RECOVERY      | Suppressed — only fire in ASSENT or INTEGRATING  |
| Multiple plateaus in quick succession | Cooldown in PlateauDetector prevents cascade |
| Lattice at max_nodes              | Growth trigger fires but no nodes added (logged) |
| Threshold crossed in one growth   | Stage transition + tool unlock both fire        |

---

## Testing

| Test                          | What it validates                             |
|-------------------------------|-----------------------------------------------|
| growth adds nodes             | Lattice node count increases by k              |
| growth connects to high-weight | New nodes connect to top-weighted parents     |
| stage transition on threshold  | Lattice size crosses stage boundary → tools unlock |
| recovery suppresses growth    | Boundary=RECOVERY → no growth                 |
| max_nodes cap respected        | Lattice at 256 → no more nodes added          |
| parameter reset applied       | S₀ decreases, L increases after growth        |