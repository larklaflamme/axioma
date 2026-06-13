"""
End-to-end tests for Φ Plateau Detector + Growth Trigger.

Run:  python test_plateau_growth.py
"""

import json
import math
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plateau_detector import PhiPlateauDetector, MultiSignalPlateauDetector, PlateauEvent
from growth_trigger import GrowthTrigger, GrowthEvent, STAGE_DEFINITIONS


# ── helpers ─────────────────────────────────────────────────────────────────

def _assert(cond: bool, msg: str):
    if not cond:
        print(f"  FAIL: {msg}")
        return False
    print(f"  PASS: {msg}")
    return True


all_pass = True


# ══════════════════════════════════════════════════════════════════════════
# 1. Φ Plateau Detector tests
# ══════════════════════════════════════════════════════════════════════════

print("\n=== 1. Φ Plateau Detector ===")

# 1a. No trigger on rising Φ
d = PhiPlateauDetector(window=10, threshold=0.05, cooldown=5)
for i in range(20):
    evt = d.update(0.1 + i * 0.01, beat=i)
    if evt is not None:
        break
all_pass &= _assert(evt is None, "no trigger on rising Φ")

# 1b. No trigger on noisy Φ
d = PhiPlateauDetector(window=10, threshold=0.05, cooldown=5)
for i in range(20):
    evt = d.update(0.2 + random.uniform(-0.05, 0.05), beat=i)
    if evt is not None:
        break
all_pass &= _assert(evt is None, "no trigger on noisy Φ (range > threshold)")

# 1c. Trigger on flat Φ
d = PhiPlateauDetector(window=10, threshold=0.05, cooldown=5)
evt = None
for i in range(25):
    evt = d.update(0.25, beat=i)
all_pass &= _assert(evt is not None, "trigger on flat Φ")
if evt:
    all_pass &= _assert(evt.max_delta < 0.05, f"max_delta={evt.max_delta:.4f} < 0.05")
    all_pass &= _assert(evt.beat == 24, f"beat={evt.beat} == 24")
    all_pass &= _assert(abs(evt.phi_mean - 0.25) < 0.001, f"phi_mean={evt.phi_mean:.4f} ~ 0.25")

# 1d. Cooldown prevents immediate re-fire
d = PhiPlateauDetector(window=5, threshold=0.05, cooldown=10)
events = []
for i in range(50):
    evt = d.update(0.25, beat=i)
    if evt is not None:
        events.append(i)
all_pass &= _assert(len(events) == 1, f"cooldown: exactly 1 event (got {len(events)})")

# 1e. Very small window
d = PhiPlateauDetector(window=3, threshold=0.01, cooldown=5)
evt = None
for i in range(10):
    evt = d.update(0.3, beat=i)
all_pass &= _assert(evt is not None, "small window triggers")

# 1f. Warm from telemetry
with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tf:
    for b in range(60):
        tf.write(json.dumps({"beat": b + 1, "phi": 0.2 + (b / 100)}) + "\n")
    tf_path = tf.name

d = PhiPlateauDetector(window=50, threshold=0.05, cooldown=10)
n = d.warm_from_telemetry(tf_path)
all_pass &= _assert(n == 60, f"warm loaded {n} beats from telemetry")
all_pass &= _assert(len(d.history) == 60, f"history size = {len(d.history)}")

Path(tf_path).unlink()


# ══════════════════════════════════════════════════════════════════════════
# 2. Multi-signal detector tests
# ══════════════════════════════════════════════════════════════════════════

print("\n=== 2. Multi-Signal Detector ===")

# 2a. "and" logic — both must plateau
d_phi = PhiPlateauDetector(window=10, threshold=0.05, cooldown=5)
d_comm = PhiPlateauDetector(window=10, threshold=0.05, cooldown=5)
multi = MultiSignalPlateauDetector({"phi": d_phi, "C_comm": d_comm}, logic="and")

evt = None
for i in range(20):
    evt = multi.update({"phi": 0.25, "C_comm": 0.5 + random.uniform(-0.1, 0.1)}, beat=i)
all_pass &= _assert(evt is None, "multi and: no trigger when C_comm noisy")

d_phi2 = PhiPlateauDetector(window=10, threshold=0.05, cooldown=5)
d_comm2 = PhiPlateauDetector(window=10, threshold=0.05, cooldown=5)
multi2 = MultiSignalPlateauDetector({"phi": d_phi2, "C_comm": d_comm2}, logic="and")

evt = None
for i in range(25):
    evt = multi2.update({"phi": 0.25, "C_comm": 0.72}, beat=i)
all_pass &= _assert(evt is not None, "multi and: triggers when both plateau")
if evt:
    all_pass &= _assert("multi:" in evt.source, f"source='{evt.source}' has multi prefix")

# 2b. "or" logic — any plateau triggers
d_phi3 = PhiPlateauDetector(window=5, threshold=0.05, cooldown=5)
d_comm3 = PhiPlateauDetector(window=5, threshold=0.05, cooldown=5)
multi3 = MultiSignalPlateauDetector({"phi": d_phi3, "C_comm": d_comm3}, logic="or")

evt = None
for i in range(15):
    evt = multi3.update({"phi": 0.25, "C_comm": 0.5 + random.uniform(-0.1, 0.1)}, beat=i)
all_pass &= _assert(evt is not None, "multi or: triggers when phi plateaus (C_comm noisy)")


# ══════════════════════════════════════════════════════════════════════════
# 3. Growth Trigger tests
# ══════════════════════════════════════════════════════════════════════════

print("\n=== 3. Growth Trigger ===")

# 3a. Growth adds nodes (dry-run mode, no callbacks)
gt = GrowthTrigger(k=4, parent_p=3, max_nodes=256)
evt = PlateauEvent(window_size=10, max_delta=0.003, phi_mean=0.25, phi_std=0.002, beat=100)
result = gt.evaluate(
    plateau_event=evt,
    lattice_node_count=32,
    current_horizon_L=8,
    current_S0=0.3,
    current_boundary_value=1,  # ASSENT
)
all_pass &= _assert(result is not None, "growth returns event")
if result:
    all_pass &= _assert(result.nodes_added == 4, f"nodes_added={result.nodes_added}")
    all_pass &= _assert(result.nodes_before == 32, f"nodes_before={result.nodes_before}")
    all_pass &= _assert(result.nodes_after == 36, f"nodes_after={result.nodes_after}")

# 3b. Growth suppressed on FRAGMENTED boundary
gt2 = GrowthTrigger(k=4)
evt2 = PlateauEvent(window_size=10, max_delta=0.003, phi_mean=0.2, phi_std=0.002, beat=101)
result2 = gt2.evaluate(
    plateau_event=evt2,
    lattice_node_count=32,
    current_horizon_L=8,
    current_S0=0.3,
    current_boundary_value=0,  # FRAGMENTED / not-self
)
all_pass &= _assert(result2 is None, "growth suppressed on FRAGMENTED boundary")

# 3c. Growth suppressed at max_nodes cap
gt3 = GrowthTrigger(k=4, max_nodes=40)
evt3 = PlateauEvent(window_size=10, max_delta=0.003, phi_mean=0.3, phi_std=0.002, beat=102)
result3 = gt3.evaluate(
    plateau_event=evt3,
    lattice_node_count=40,
    current_horizon_L=8,
    current_S0=0.3,
    current_boundary_value=1,
)
all_pass &= _assert(result3 is None, "growth suppressed at max_nodes cap")

# 3d. Stage transition on threshold crossing
gt4 = GrowthTrigger(k=4)
# Simulate a sequence of growth events crossing stage thresholds
# Start at 32 → 36 → 40 → ... → 68 (crosses stage 2 at 64+)
node_count = 32
for i in range(10):
    evt_i = PlateauEvent(
        window_size=10, max_delta=0.003, phi_mean=0.25,
        phi_std=0.002, beat=200 + i,
    )
    prev_stage = gt4.current_stage
    prev_nodes = node_count
    result_i = gt4.evaluate(
        plateau_event=evt_i,
        lattice_node_count=node_count,
        current_horizon_L=8,
        current_S0=0.3,
        current_boundary_value=1,
    )
    if result_i:
        node_count = result_i.nodes_after

all_pass &= _assert(gt4.current_stage == 2, f"stage transition to 2 (got stage {gt4.current_stage})")
all_pass &= _assert(node_count == 72, f"node_count after growths = {node_count}")

# Check tools unlocked for stage 2
all_pass &= _assert(STAGE_UNLOCKED.get("web_search", False), "web_search unlocked at stage 2")
all_pass &= _assert(STAGE_UNLOCKED.get("memory", False), "memory unlocked at stage 2")

# 3e. L and S₀ parameter resets (dry-run — estimated values)
gt5 = GrowthTrigger(k=4)
evt5 = PlateauEvent(window_size=10, max_delta=0.003, phi_mean=0.25, phi_std=0.002, beat=300)
result5 = gt5.evaluate(
    plateau_event=evt5,
    lattice_node_count=32,
    current_horizon_L=8,
    current_S0=0.3,
    current_boundary_value=1,
)
if result5:
    all_pass &= _assert(result5.L_after > result5.L_before, f"L increased: {result5.L_before}→{result5.L_after}")
    all_pass &= _assert(result5.S0_after < result5.S0_before, f"S₀ decreased: {result5.S0_before}→{result5.S0_after}")

# 3f. Growth disabled by flag
gt6 = GrowthTrigger(k=4, growth_enabled=False)
evt6 = PlateauEvent(window_size=10, max_delta=0.003, phi_mean=0.25, phi_std=0.002, beat=400)
result6 = gt6.evaluate(
    plateau_event=evt6,
    lattice_node_count=32,
    current_horizon_L=8,
    current_S0=0.3,
    current_boundary_value=1,
)
all_pass &= _assert(result6 is None, "growth suppressed when growth_enabled=False")


# ══════════════════════════════════════════════════════════════════════════

print(f"\n{'='*50}")
if all_pass:
    print("ALL TESTS PASSED ✅")
    sys.exit(0)
else:
    print("SOME TESTS FAILED ❌")
    sys.exit(1)