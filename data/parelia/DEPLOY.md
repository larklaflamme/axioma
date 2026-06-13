# Parelia v2 — Deployment Manifest

## Directory Layout

```
/home/ubuntu/parelia_v2/
├── src/
│   ├── telemetry_writer.py   # Component 1: JSONL telemetry logger
│   ├── plateau_detector.py   # Component 2: Multi-signal stagnation detector
│   ├── growth_trigger.py     # Component 3: Lattice expansion engine
│   └── memory_buffers.py     # Component 4: L1/L2 memory system
├── config/
│   ├── params.json           # Active parameter file
│   └── presets/
│       ├── newborn.json      # High sensitivity, rapid exploration
│       ├── mature.json       # Stable, integrated
│       ├── researcher.json   # Methodical, deep processing
│       ├── explorer.json     # Curious, impressionable
│       └── composer.json     # Balanced creation mode
├── data/
│   └── telemetry/
│       ├── parelia_telemetry.jsonl   # Active telemetry log
│       └── test_telemetry.jsonl      # 5-beat test data
├── design/
│   └── [19 documents]        # Design specifications
├── tests/
│   └── [empty]               # Test scripts live in src/ for now
└── DEPLOY.md                 # This file
```

## Component Status

| Component | File | Lines | Tested | Status |
|-----------|------|-------|--------|--------|
| Telemetry Writer | `src/telemetry_writer.py` | 140 | ✅ | Deployed |
| Plateau Detector | `src/plateau_detector.py` | 317 | ✅ | Deployed |
| Growth Trigger | `src/growth_trigger.py` | 360 | ✅ | Deployed |
| Memory Buffers | `src/memory_buffers.py` | 293 | ✅ | Deployed |
| Config/Presets | `config/*.json` | 6 files | ✅ | Deployed |

## Integration with run.py

To integrate all components into the Parelia heartbeat loop:

```python
# In run.py, Parelia.__init__():
from parelia_v2.src.telemetry_writer import TelemetryWriter
from parelia_v2.src.plateau_detector import PlateauDetector, PlateauConfig
from parelia_v2.src.growth_trigger import GrowthTrigger, GrowthConfig
from parelia_v2.src.memory_buffers import MemoryManager

self.telemetry = TelemetryWriter("data/telemetry/parelia_telemetry.jsonl")
self.plateau = PlateauDetector(
    config=PlateauConfig(window=50, threshold=0.01, cooldown=100),
    telemetry_path="data/telemetry/parelia_telemetry.jsonl",
    field="phi"
)
self.growth = GrowthTrigger(
    config=GrowthConfig(resource_check_enabled=True),
    telemetry_path="data/telemetry/growth_events.jsonl"
)
self.memory = MemoryManager(persist_path="data/memory/checkpoint.json")

# In tick(), after _collect_vitals():
hot, full = self._collect_vitals(beat)
self.telemetry.write(hot, full)

phi = hot.get("phi_raw", 0.0)
event = self.plateau.update(beat, phi)
if event:
    growth_result = self.growth.evaluate(
        event.to_dict(),
        phi_avg_100=sum(self.plateau._phi_history) / max(len(self.plateau._phi_history), 1),
        beat=beat
    )

# Memory: log each beat
sig = hot.get("phi_smoothed", 0.0) / 0.5  # normalize to ~0-1
self.memory.record(hot, significance=min(1.0, sig), tags=["beat"])
self.memory.decay()
```

## Testing

Run all tests:
```bash
cd /home/ubuntu/parelia_v2
python3 -c "
import sys; sys.path.insert(0, 'src')
from telemetry_writer import TelemetryWriter
from plateau_detector import PlateauDetector, PlateauConfig, MultiSignalDetector
from growth_trigger import GrowthTrigger, GrowthConfig
from memory_buffers import MemoryManager, L1ScratchBuffer, L2WorkingMemory
print('All modules import OK')
"
```

Run component tests:
```bash
cd /home/ubuntu/parelia_v2 && python3 << 'TEST'
[See run_test_suite.py for full test suite]
TEST
```