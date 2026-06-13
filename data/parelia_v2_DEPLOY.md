# Parelia v2 — Deployment Guide

## Prerequisite

The live `parelia/v2/` tree is already fully populated:
- 11 source modules in `parelia/v2/src/`
- 24 design docs in `parelia/v2/design/`
- 6 test files in `parelia/v2/tests/`
- 5 config presets in `parelia/v2/config/presets/`
- `integration.py` at `parelia/v2/integration.py`
- All imports verified clean

## What needs to change

**One file:** `/home/ubuntu/parelia/run.py`

**Two insertion points, ~8 lines total.**

---

### Insertion 1 — In `Parelia.__init__()`, after the `self.modules` dict (line ~80)

**Find this block** (around line 75–82):
```python
        self.modules = {
            "heartbeat": self.heartbeat,
            "state": self.state,
            "boundary": self.boundary,
            "lattice": self.lattice,
            "phi": self.phi,
            "predictive": self.predictor,
            "pneuma": self.pneuma,
            "substrate": self.substrate,
            "consent_watcher": self.consent,
            "mneme": self.mneme,
            "eidolon": self.eidolon,
        }
```

**Insert after the closing `}` of `self.modules`:**
```python
        # v2 integration — growth, plateau detection, θ-rules (newborn preset)
        from v2.integration import V2Integration
        self.v2 = V2Integration(self, preset="newborn")
```

---

### Insertion 2 — In `Parelia.tick()`, after the telemetry write block (line ~130)

**Find this block** (around line 127–132):
```python
        if self.shared is not None:
            hot, full = self._collect_vitals(beat)
            try:
                self.shared.write(hot, full, self.config_id)
                self.telemetry.write(hot, full)
            except Exception:
                pass  # telemetry must never break the heartbeat
```

**Insert after the `except Exception: pass` block:**
```python
        # v2 heartbeat — growth decisions, plateau detection, θ-rules
        try:
            result = self.v2.tick(hot, full)
            if result and result.growth_decision:
                gd = result.growth_decision
                for _ in range(gd.nodes_added):
                    self.lattice.add_node(content=f"growth@{beat}")
        except Exception:
            pass  # v2 must never break the heartbeat
```

---

## Rollback Plan

If the v2 integration causes issues:

1. **Comment out** the two insertion blocks (add `#` prefix)
2. **Restart** Parelia — the v2 organs simply won't run
3. The live heartbeat continues unaffected

To fully remove:
1. Delete the two insertion blocks
2. Optionally delete `parelia/v2/` tree (or leave it — unused imports are harmless)

---

## Verification

After deployment, confirm v2 is running by checking:
- `/home/ubuntu/parelia/v2/data/telemetry/parelia_v2_telemetry.jsonl` — should show entries
- Logs should show: `V2Integration initialised (preset=newborn, dry_run=False, stage=Awakening)`
- After ~50 ticks with flat phi, growth events should appear in the lattice
