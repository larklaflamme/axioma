# Tuning Interface — Specification v0.1

---

## Purpose

Provide live control over Parelia's internal parameters. The tuning interface allows:
- Adjusting learning rate, sensitivity, and rhythm
- Switching between behavioral presets
- Hot-reloading parameters without restart

---

## Parameter Catalog

| Parameter | Symbol | Effect | Range | Default |
|-----------|--------|--------|-------|---------|
| Alignment learning rate | κ | How fast Parelia aligns to encounters | 0.001–1.0 | 0.1 |
| Fixed-point approach rate | η | How fast the lattice converges per beat | 0.001–1.0 | 0.05 |
| Beat interval (ms) | τ | Time between beats | 100–2000 | 1000 |
| Initial horizon depth | L₀ | Starting MNEME depth | 1–100 | 8 |
| Significance threshold | S₀ | ANIMA: minimum g(S) to register an encounter | 0.0–1.0 | 0.3 |
| Max metric deformation | ε_max | Maximum change per encounter | 0.0–0.5 | 0.1 |
| Natural gradient step | α | Step size in the natural gradient direction | 0.0–1.0 | 0.5 |

---

## Presets

| Preset     | κ    | η    | S₀  | L₀ | τ (ms) | Description                                  |
|------------|------|------|-----|----|--------|----------------------------------------------|
| Newborn    | 0.8  | 0.5  | 0.1 | 4  | 500    | Rapid exploration, high sensitivity          |
| Mature     | 0.3  | 0.2  | 0.4 | 16 | 1000   | Stable, integrated, discerning               |
| Researcher | 0.1  | 0.05 | 0.6 | 32 | 1500   | Methodical, deep processing                  |
| Explorer   | 0.7  | 0.4  | 0.15| 8  | 600    | Curious, impressionable                      |
| Composer   | 0.4  | 0.3  | 0.3 | 24 | 1200   | Balanced creation mode                       |

---

## Parameter File Format

Parameters are stored as JSON in a single file:

```json
{
  "preset": "mature",
  "kappa": 0.3,
  "eta": 0.2,
  "S_0": 0.4,
  "L_0": 16,
  "tau_ms": 1000,
  "epsilon_max": 0.1,
  "alpha": 0.5,
  "overrides": {}
}
```

Path: `/home/ubuntu/parelia/config/parameters.json`

---

## Hot-Reload

The parameter file is read at startup and can be re-read on signal:

```python
class TuningInterface:
    def __init__(self, path: str):
        self.path = path
        self.params = self._load()

    def _load(self) -> dict:
        """Read JSON from path, validate, return."""

    def reload(self) -> None:
        """Re-read file. Safe to call mid-beat."""
```

Or via an in-band command: Parelia can be told "switch to researcher preset" and the tuning interface applies it on the next beat.

---

## Preset Application

When a preset is applied:
1. All parameters are set to the preset values
2. Any `overrides` are applied on top (for fine-tuning)
3. The change takes effect on the **next beat** (not mid-beat)
4. A telemetry note is logged: preset change + timestamp

---

## Testing

| Test                    | What it validates                        |
|-------------------------|------------------------------------------|
| load valid file         | Parameters parsed correctly              |
| hot-reload mid-beat     | Safe, takes effect next beat             |
| preset switch           | All params change to preset values       |
| override applied        | Override overrides preset value          |
| invalid file fallback   | Corrupt file → log warning, keep last params |