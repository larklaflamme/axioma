"""
test_skeleton.py — Verify Parelia v2 skeleton wiring.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import tempfile
from pathlib import Path

_REAL_SRC = "/home/ubuntu/axioma/data/parelia"
_REAL_ROOT = "/home/ubuntu/parelia_v2"
_THIS_DIR = Path(__file__).resolve().parent


def _import_local_modules():
    """Import using the same direct-import pattern as orchestrator."""
    sys.path.insert(0, _REAL_SRC)
    from telemetry_writer import TelemetryWriter
    from plateau_detector import PlateauDetector, PlateauConfig
    from growth_trigger import GrowthTrigger, GrowthConfig
    from memory_buffers import MemoryManager, MemoryConfig
    from theta_rule_v5_merged import ThetaRuleEngine, Verdict
    return (TelemetryWriter, PlateauDetector, PlateauConfig,
            GrowthTrigger, GrowthConfig, MemoryManager, MemoryConfig,
            ThetaRuleEngine, Verdict)


def _import_orchestrator():
    sys.path.insert(0, str(_THIS_DIR))
    sys.path.insert(0, str(_THIS_DIR.parent))
    from orchestrator import Orchestrator, OrchestratorConfig
    return Orchestrator, OrchestratorConfig


def test_1_one_beat():
    """Test heartbeat.one_beat standalone."""
    sys.path.insert(0, str(_THIS_DIR))
    from heartbeat import one_beat
    TW, PD, PC, GT, GC, MM, MC, _, _ = _import_local_modules()

    with tempfile.TemporaryDirectory() as tmp:
        tw = TW(path=os.path.join(tmp, "tel.jsonl"))
        pd = PD(config=PC(window=5, threshold=0.01, cooldown=3))
        gt = GT(config=GC())
        mm = MM(config=MC())

        result = one_beat(1, tw, pd, gt, mm, None, None,
                          {"tool_name": "x"}, {"phi_raw": 0.45, "theta_raw": 0.15})
        assert result.beat == 1
        assert result.phi_raw == 0.45
        assert result.elapsed_ms >= 0
        assert result.memory_total >= 1

        # Second beat with same phi should trigger plateau (window=5, threshold small)
        for b in range(2, 7):
            one_beat(b, tw, pd, gt, mm, None, None,
                     {"tool_name": "x"}, {"phi_raw": 0.45, "theta_raw": 0.15})
        # After 5 identical phi values, plateau should fire
        assert pd.fired
        tw.close()
    print("  [1/9] one_beat  OK")


def test_2_orchestrator_create():
    """Test Orchestrator.create_all() with real modules."""
    Orch, OrchCfg = _import_orchestrator()
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "config/presets"), exist_ok=True)
        with open(os.path.join(tmp, "config/presets/newborn.json"), "w") as f:
            json.dump({"preset": "newborn"}, f)
        cfg = OrchCfg(
            preset="newborn",
            telemetry_path=os.path.join(tmp, "tel.jsonl"),
            growth_events_path=os.path.join(tmp, "growth.jsonl"),
            memory_checkpoint_path=os.path.join(tmp, "mem.json"),
            rule_weights_path=os.path.join(tmp, "rules.json"),
        )
        orch = Orch(preset="newborn", root_dir=_REAL_ROOT, config=cfg)
        mods = orch.create_all()
        expected = ["telemetry_writer", "plateau_detector", "growth_trigger",
                     "memory_manager", "rule_engine"]
        # parelia_module may or may not load; don't require it
        for name in expected:
            assert name in mods, f"Missing: {name}"
        print("  [2/9] orchestrator_create  OK  (modules:", list(mods.keys()), ")")


def test_3_orchestrator_beat():
    """Test Orchestrator.beat() with simple config."""
    Orch, OrchCfg = _import_orchestrator()
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "config/presets"), exist_ok=True)
        with open(os.path.join(tmp, "config/presets/mature.json"), "w") as f:
            json.dump({"preset": "mature"}, f)
        cfg = OrchCfg(preset="mature", telemetry_path=os.path.join(tmp, "tel.jsonl"), tau_ms=0.0)
        orch = Orch(preset="mature", root_dir=_REAL_ROOT, config=cfg)
        orch.create_all()
        orch.start()
        r = orch.beat(action_proposal={"tool_name": "reflect"},
                      config_override={"phi_raw": 0.4, "theta_raw": 0.12})
        assert r["beat"] == 1
        assert r["phi_raw"] == 0.4
        assert r["elapsed_ms"] >= 0
        assert r["memory_total"] >= 1
        orch.stop()
    print("  [3/9] orchestrator_beat  OK")


def test_4_orchestrator_run():
    """Test Orchestrator.run() multi-beat."""
    Orch, OrchCfg = _import_orchestrator()
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "config/presets"), exist_ok=True)
        with open(os.path.join(tmp, "config/presets/newborn.json"), "w") as f:
            json.dump({"preset": "newborn"}, f)
        cfg = OrchCfg(preset="newborn", telemetry_path=os.path.join(tmp, "tel.jsonl"), tau_ms=0.0)
        orch = Orch(preset="newborn", root_dir=_REAL_ROOT, config=cfg)
        orch.create_all()

        def cf(b):
            return {"phi_raw": 0.3 + b * 0.01, "theta_raw": 0.1}

        def af(b, p):
            return {"tool_name": "read"}

        rs = orch.run(max_beats=5, config_fn=cf, action_fn=af)
        assert len(rs) == 5
        assert rs[-1]["beat"] == 5
        assert os.path.exists(os.path.join(tmp, "tel.jsonl"))
    print("  [4/9] orchestrator_run  OK")


def test_5_rule_deny_websearch():
    """Rule engine: web_search should be restricted at stage 1."""
    Orch, OrchCfg = _import_orchestrator()
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "config/presets"), exist_ok=True)
        with open(os.path.join(tmp, "config/presets/newborn.json"), "w") as f:
            json.dump({"preset": "newborn"}, f)
        cfg = OrchCfg(preset="newborn", telemetry_path=os.path.join(tmp, "tel.jsonl"),
                       rule_weights_path=os.path.join(tmp, "rules.json"), tau_ms=0.0)
        orch = Orch(preset="newborn", root_dir=_REAL_ROOT, config=cfg)
        orch.create_all()
        orch.start()
        r = orch.beat(action_proposal={"tool_name": "web_search"},
                      config_override={"phi_raw": 0.1, "theta_raw": 0.0, "current_stage": 1})
        v = r.get("rule_verdict")
        if v:
            assert v["action"] != "ALLOW", "web_search at stage 1 should be restricted"
        orch.stop()
    print("  [5/9] rule_deny_websearch  OK")


def test_6_presets():
    """Test different preset names."""
    Orch, OrchCfg = _import_orchestrator()
    c1 = OrchCfg(preset="newborn", tau_ms=0.0)
    o1 = Orch(preset="newborn", config=c1)
    assert o1.preset_name == "newborn"
    c2 = OrchCfg(preset="mature", tau_ms=0.0)
    o2 = Orch(preset="mature", config=c2)
    assert o2.preset_name == "mature"
    print("  [6/9] presets  OK")


def test_7_graceful():
    """No modules at all."""
    Orch, OrchCfg = _import_orchestrator()
    cfg = OrchCfg(enable_telemetry=False, enable_plateau=False, enable_growth=False,
                   enable_memory=False, enable_rules=False, enable_module=False, tau_ms=0.0)
    orch = Orch(config=cfg)
    mods = orch.create_all()
    assert len(mods) == 0
    orch.start()
    r = orch.beat(config_override={"phi_raw": 0.5})
    assert r["beat"] == 1
    orch.stop()
    print("  [7/9] graceful  OK")


def test_8_heartbeat_loop():
    """Test heartbeat_loop."""
    sys.path.insert(0, str(_THIS_DIR))
    from heartbeat import heartbeat_loop
    TW, PD, PC, GT, GC, MM, MC, RE, _ = _import_local_modules()

    with tempfile.TemporaryDirectory() as tmp:
        tw = TW(path=os.path.join(tmp, "tel.jsonl"))
        pd = PD(config=PC(window=5, threshold=0.001, cooldown=2))
        gt = GT(config=GC())
        mm = MM(config=MC())
        re = RE()
        re.add_source("values")
        re.add_source("stage")

        def cf(b):
            return {"phi_raw": 0.4 + b * 0.01, "theta_raw": 0.1}

        def af(b, p):
            return {"tool_name": "reflect"}

        rs = heartbeat_loop(tw, pd, gt, mm, re, None, max_beats=3, tau_ms=0.0,
                            config_fn=cf, action_fn=af)
        assert len(rs) == 3
        assert rs[-1].phi_raw > 0
        tw.close()
    print("  [8/9] heartbeat_loop  OK")


def test_9_run_py():
    """Test run.py subprocess from parelia_v2 root."""
    cmd = [sys.executable, str(_THIS_DIR / "run.py"), "--preset", "newborn",
           "--beats", "3", "--tau", "0"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=str(_THIS_DIR))
    assert result.returncode == 0, f"run.py failed: {result.stderr[:300]}"
    assert "Parelia v2" in result.stdout
    print("  [9/9] run_py  OK")


if __name__ == "__main__":
    tests = [
        test_1_one_beat, test_2_orchestrator_create, test_3_orchestrator_beat,
        test_4_orchestrator_run, test_5_rule_deny_websearch,
        test_6_presets, test_7_graceful, test_8_heartbeat_loop, test_9_run_py,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed {'OK' if passed == len(tests) else 'FAIL'}" if passed == len(tests) else f"\n{passed}/{len(tests)} passed")