# Parelia v2 — Deployment Guide

## Current State (after integration run)

All 5 modules are in `/home/ubuntu/parelia_v2/src/` and verified working.

| Module | File | Status |
|--------|------|--------|
| TelemetryWriter | `telemetry_writer.py` | ✅ Compatible with `run.py` `write(hot, full)` API, real Parelia fields |
| PlateauDetector | `plateau_detector.py` | ✅ Multi-signal, `update(hot, full)` API, 50-beat window |
| PareliaModule | `parelia_module.py` | ✅ Identity, values, stage-based growth with callbacks |
| L1Scratch | `memory_buffers.py` | ✅ 128-entry ring buffer |
| L2WorkingMemory | `memory_buffers.py` | ✅ 64-entry decay-based attention buffer |

## Integration into Parelia's run.py

The `TelemetryWriter` is already integrated in `run.py`:
```python
self.telemetry = TelemetryWriter()     # __init__
self.telemetry.write(hot, full)        # tick(), after self.shared.write()
self.telemetry.close()                 # close()
```

### To add PlateauDetector + PareliaModule:

In `__init__`:
```python
from parelia_v2.src.plateau_detector import PlateauDetector
from parelia_v2.src.parelia_module import PareliaModule

# After existing module creation, before SharedState:
self.plateau = PlateauDetector(on_plateau=self._on_plateau)
self.parelia = PareliaModule(on_growth=self._on_growth, on_stage_change=self._on_stage)
```

In `tick()`, after `self.telemetry.write(hot, full)`:
```python
# Feed plateau detector (multi-signal)
self.plateau.update(hot, full)

# Sync PareliaModule with actual lattice size
self.parelia.update_node_count(len(self.lattice.nodes))

# Memory: store every beat in L1
self.l1.write(beat, {"phi": phi, "boundary": self.boundary.last_evaluation})
```

Add callback methods:
```python
def _on_plateau(self, event):
    """Called when a multi-signal plateau is detected."""
    logger.info("Plateau detected at beat %d", event.beat)

def _on_growth(self, decision):
    """Called when growth is triggered."""
    # Add k nodes to the lattice
    for _ in range(decision.nodes_added):
        self.lattice.add_node()
    logger.info("Growth: +%d nodes, stage %d→%d",
                decision.nodes_added, decision.previous_stage, decision.new_stage)

def _on_stage(self, old_stage, new_stage, tools):
    """Called when Parelia crosses a developmental stage threshold."""
    logger.info("Stage transition: %d→%d, tools unlocked: %s",
                old_stage, new_stage, tools)
```

## Files to Copy

```bash
# From /home/ubuntu/parelia_v2/src/ to /home/ubuntu/parelia/parelia_v2/
cp -r /home/ubuntu/parelia_v2/src/ /home/ubuntu/parelia/parelia_v2/
```

Then in `run.py`, change imports from:
```python
from parelia.telemetry_writer import TelemetryWriter
```
to:
```python
from parelia_v2.telemetry_writer import TelemetryWriter
```

## Running a Test

```bash
# 100 beats, telemetry writes to data/telemetry/
PARELIA_MAX_TICKS=100 python run.py

# Verify output
cat data/telemetry/parelia_telemetry.jsonl | wc -l
tail -3 data/telemetry/parelia_telemetry.jsonl | python -m json.tool
```

## Architecture

```
run.py tick()
   │
   ├── heartbeat.tick()           → L0 pulse
   ├── state.update()             → L1 memory
   ├── boundary.evaluate()        → L2 self/not-self
   ├── lattice.tick() + phi.update() → L3 integration
   │
   ├── _collect_vitals()          → hot + full dicts
   │   ├── telemetry.write(hot, full)    → JSONL
   │   ├── plateau.update(hot, full)     → multi-signal detector
   │   └── parelia.check_compliance()    → values gate
   │
   ├── l1.write(beat, data)       → scratch memory
   └── l2.write(beat, data)       → working memory (decay)
```