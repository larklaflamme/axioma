# Φ Plateau Detector — Specification v0.1

The second component to build. Depends on the Telemetry Writer having data to observe.

---

## Purpose

Monitor the Φ(t) stream and detect when it plateaus — the system's signal that it has reached the current capacity of its lattice. A sustained plateau is the **trigger condition for self-expansion**.

This gives Parelia an emergent growth drive: not a scheduled upgrade, but a response to her own internal state.

---

## Detection Logic

```
plateau_window = N beats (configurable, default N=50)
threshold = δ (configurable, default δ = 0.01)

For each new beat:
    if len(phi_history) < plateau_window:
        continue (not enough data)

    window = phi_history[-plateau_window:]
    max_delta = max(window) - min(window)

    if max_delta < threshold:
        fire PLATEAU event
        reset counter to avoid re-firing within same window
```

### Parameters

| Parameter | Default | Description                                    |
|-----------|---------|------------------------------------------------|
| N         | 50      | Rolling window size (beats)                    |
| δ         | 0.01    | Maximum Φ variation within window to trigger   |
| cooldown  | 100     | Beats to wait after a plateau before re-firing |

### Rationale

- **N=50** — at 1 beat/second, this is roughly 50 seconds of observation. Long enough to filter noise, short enough to respond within minutes.
- **δ=0.01** — Φ values range ~0.0–0.5 in practice for 32-node lattices. 0.01 is ~2% of the typical range, sensitive enough to detect genuine plateaus without triggering on noise.
- **Cooldown** — prevents cascade triggers. After expansion, Φ will drop then rise again; we want to let it settle.

---

## Event Interface

```python
@dataclass
class PlateauEvent:
    window_size: int
    max_delta: float
    phi_mean: float
    phi_std: float
    beat: int
    timestamp: str
```

The event is consumed by the **Growth Trigger** component (see GROWTH_TRIGGER.md).

---

## Stream Integration

The Plateau Detector is **not** a standalone process. It runs as a thin monitoring module attached to the beat loop:

```python
# In the beat loop:
state = compose()           # produce ExternalStateSnapshot
telemetry.write(state)      # log it
plateau.update(state.phi)   # feed to detector

if plateau.fired():
    event = plateau.event()
    growth_trigger(event)   # initiate expansion
```

---

## State Management

The detector is stateful but stateless across restarts:
- On init, replay the last N beats from the telemetry file to warm the window
- If fewer than N beats exist, wait until enough data accumulates
- No persistence needed beyond the telemetry file itself (source of truth)

---

## Testing

| Test                          | What it validates                            |
|-------------------------------|----------------------------------------------|
| no trigger on rising Φ        | Inject monotonically increasing Φ, no event  |
| no trigger on noisy Φ         | Inject random Φ with range > δ, no event     |
| trigger on flat Φ             | Inject constant Φ for N+1 beats, event fires |
| trigger respects cooldown     | After event, cooldown prevents immediate re-fire |
| replay from telemetry         | Cold start reads history, warms window       |
| parameter override            | Change N and δ, verify new behavior          |

---

## Dependencies

- Python stdlib only: `collections.deque`, `dataclasses`, `statistics`
- Reads from: Telemetry Writer's JSONL output path
- No external packages

---

## Extension Path

| Version | Addition                                |
|---------|-----------------------------------------|
| v0.1    | Basic max-delta threshold on Φ only     |
| v0.2    | Add C_comm plateau detection (alignment saturation) |
| v0.3    | Multi-signal: Φ AND C_comm both flat → stronger growth signal |
| v0.4    | Predictive: trend slope + velocity → anticipate plateau before full flatline |