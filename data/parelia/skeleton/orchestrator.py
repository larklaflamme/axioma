"""
orchestrator.py — Parelia v2 Organ Connector

The Orchestrator is the central registry that wires all modules together.
It owns the lifecycle: create → connect → start → stop → teardown.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("parelia.orchestrator")


DEFAULT_PATHS = {
    "telemetry": "data/telemetry/parelia_telemetry.jsonl",
    "growth_events": "data/telemetry/growth_events.jsonl",
    "memory_checkpoint": "data/memory/checkpoint.json",
    "rule_weights": "data/rules/rule_weights.json",
    "config": "config/params.json",
    "presets_dir": "config/presets",
}

# Local copies path (where this skeleton lives)
_LOCAL_SRC = os.path.join(os.path.dirname(__file__), "..")
_LOCAL_SRC = os.path.abspath(_LOCAL_SRC)
if not os.path.exists(os.path.join(_LOCAL_SRC, "telemetry_writer.py")):
    _LOCAL_SRC = "/home/ubuntu/axioma/data/parelia"

if _LOCAL_SRC not in sys.path:
    sys.path.insert(0, _LOCAL_SRC)

from telemetry_writer import TelemetryWriter
from plateau_detector import PlateauDetector, PlateauConfig, PlateauEvent
from growth_trigger import GrowthTrigger, GrowthConfig
from memory_buffers import MemoryManager, MemoryConfig
from theta_rule_v5_merged import ThetaRuleEngine, Verdict

# parelia_module uses relative imports; needs src package
_PM_LOADED = False
_PareliaModule = None
try:
    _src_parent = "/home/ubuntu/parelia_v2"
    if _src_parent not in sys.path:
        sys.path.insert(0, _src_parent)
    import importlib
    _pm_mod = importlib.import_module("src.parelia_module")
    _PareliaModule = _pm_mod.PareliaModule
    _PM_LOADED = True
except Exception as e:
    logger.warning("orchestrator parelia_module load failed: %s", e)


@dataclass
class OrchestratorConfig:
    """Runtime configuration for the orchestration layer."""

    preset: str = "mature"
    root_dir: str | None = None
    enable_telemetry: bool = True
    enable_plateau: bool = True
    enable_growth: bool = True
    enable_memory: bool = True
    enable_rules: bool = True
    enable_module: bool = True
    tau_ms: float = 1_000.0
    max_beats: int = 0
    telemetry_path: str = DEFAULT_PATHS["telemetry"]
    growth_events_path: str = DEFAULT_PATHS["growth_events"]
    memory_checkpoint_path: str = DEFAULT_PATHS["memory_checkpoint"]
    rule_weights_path: str = DEFAULT_PATHS["rule_weights"]
    config_path: str = DEFAULT_PATHS["config"]
    overrides: dict = field(default_factory=dict)

    def resolve(self, root: str) -> OrchestratorConfig:
        for key in ("telemetry_path", "growth_events_path",
                     "memory_checkpoint_path", "rule_weights_path",
                     "config_path"):
            val = getattr(self, key)
            if not os.path.isabs(val):
                setattr(self, key, os.path.join(root, val))
        return self


def load_preset(preset_name: str, presets_dir: str = "config/presets") -> dict:
    path = Path(presets_dir) / f"{preset_name}.json"
    if not path.exists() and not path.is_absolute():
        for base in [Path.cwd(), Path.home() / "parelia_v2"]:
            candidate = base / presets_dir / f"{preset_name}.json"
            if candidate.exists():
                path = candidate
                break
    if not path.exists():
        logger.warning("preset '%s' not found at %s, using defaults", preset_name, path)
        return {}
    with open(path) as f:
        return json.load(f)


class Orchestrator:
    """Wires all Parelia v2 modules together and manages their lifecycle."""

    def __init__(
        self,
        preset: str = "mature",
        root_dir: str | None = None,
        config: OrchestratorConfig | None = None,
    ):
        self.preset_name = preset
        self.root_dir = root_dir or os.getcwd()
        preset_params = load_preset(preset, os.path.join(self.root_dir, "config/presets"))
        params_path = os.path.join(self.root_dir, "config/params.json")
        if os.path.exists(params_path):
            with open(params_path) as f:
                preset_params.update(json.load(f))
        if config is None:
            self.config = OrchestratorConfig(preset=preset)
        else:
            self.config = config
        self.config.preset = preset
        self.config.resolve(self.root_dir)
        overrides = preset_params.get("overrides", {})
        overrides.update(self.config.overrides)
        for k, v in overrides.items():
            if hasattr(self.config, k):
                setattr(self.config, k, v)
        self.modules: dict[str, Any] = {}
        self._running: bool = False
        self._current_beat: int = 0

    def create_all(self) -> dict[str, Any]:
        if self.modules:
            return self.modules
        cfg = self.config

        if cfg.enable_telemetry:
            try:
                self.modules["telemetry_writer"] = TelemetryWriter(path=cfg.telemetry_path)
                logger.info("orchestrator telemetry_writer created")
            except Exception as e:
                logger.warning("orchestrator telemetry_writer failed: %s", e)

        if cfg.enable_plateau:
            try:
                plat_cfg = PlateauConfig(
                    window=cfg.overrides.get("growth_trigger_window", 50),
                    threshold=cfg.overrides.get("growth_trigger_threshold", 0.01),
                    cooldown=cfg.overrides.get("growth_cooldown", 100),
                )
                tel_path = cfg.telemetry_path if os.path.exists(cfg.telemetry_path) else None
                self.modules["plateau_detector"] = PlateauDetector(
                    config=plat_cfg, telemetry_path=tel_path, field="phi",
                )
                logger.info("orchestrator plateau_detector created")
            except Exception as e:
                logger.warning("orchestrator plateau_detector failed: %s", e)

        if cfg.enable_growth:
            try:
                self.modules["growth_trigger"] = GrowthTrigger(
                    config=GrowthConfig(),
                    telemetry_path=cfg.growth_events_path,
                )
                logger.info("orchestrator growth_trigger created")
            except Exception as e:
                logger.warning("orchestrator growth_trigger failed: %s", e)

        if cfg.enable_memory:
            try:
                self.modules["memory_manager"] = MemoryManager(
                    config=MemoryConfig(),
                    persist_path=cfg.memory_checkpoint_path,
                )
                logger.info("orchestrator memory_manager created")
            except Exception as e:
                logger.warning("orchestrator memory_manager failed: %s", e)

        if cfg.enable_rules:
            try:
                engine = ThetaRuleEngine(
                    default_threshold=cfg.overrides.get("rule_threshold", 0.35),
                    adaptive_threshold=True,
                    learning_rate=cfg.overrides.get("learning_rate", 0.05),
                )
                for source in ("values", "stage", "telemetry", "boundary"):
                    try:
                        engine.add_source(source)
                    except Exception as se:
                        logger.warning("orchestrator source '%s' failed: %s", source, se)
                self.modules["rule_engine"] = engine
                if os.path.exists(cfg.rule_weights_path):
                    try:
                        engine.load(cfg.rule_weights_path)
                    except Exception:
                        pass
                logger.info("orchestrator rule_engine created")
            except Exception as e:
                logger.warning("orchestrator rule_engine failed: %s", e)

        if cfg.enable_module and _PM_LOADED and _PareliaModule is not None:
            try:
                self.modules["parelia_module"] = _PareliaModule()
                logger.info("orchestrator parelia_module created")
            except Exception as e:
                logger.warning("orchestrator parelia_module failed: %s", e)

        return self.modules

    def start(self) -> None:
        self._running = True
        self._current_beat = 0
        logger.info("orchestrator started preset=%s modules=%s",
                     self.preset_name, list(self.modules.keys()))

    def stop(self) -> None:
        self._running = False
        tw = self.modules.get("telemetry_writer")
        if tw is not None:
            try:
                tw.close()
            except Exception:
                pass
        engine = self.modules.get("rule_engine")
        if engine is not None:
            try:
                os.makedirs(os.path.dirname(self.config.rule_weights_path), exist_ok=True)
                engine.save(self.config.rule_weights_path)
            except Exception:
                pass
        logger.info("orchestrator stopped after %d beats", self._current_beat)

    def beat(self, action_proposal: dict | None = None,
             config_override: dict | None = None) -> dict:
        if not self._running:
            raise RuntimeError("Orchestrator not started. Call start() first.")
        self._current_beat += 1
        bn = self._current_beat
        cov = config_override or {}
        hot = {
            "beat_number": bn, "phi_raw": cov.get("phi_raw", 0.0),
            "phi_smoothed": cov.get("phi_smoothed", 0.0),
            "theta_raw": cov.get("theta_raw", 0.0),
            "theta_smoothed": cov.get("theta_smoothed", 0.0),
            "zone": cov.get("zone", "ASSENT"), "psi": cov.get("psi", 1.0),
        }
        full = {
            "delta_phi": cov.get("delta_phi", 0.0),
            "delta_theta": cov.get("delta_theta", 0.0),
            "aos_g_gap": cov.get("aos_g_gap", 0.0),
        }
        result = {
            "beat": bn, "phi_raw": hot["phi_raw"], "theta_raw": hot["theta_raw"],
            "zone": hot["zone"], "plateau_event": None, "growth_event": None,
            "rule_verdict": None, "memory_total": 0,
            "current_stage": 1, "stage_name": "Awakening", "errors": [],
        }
        import time as _time
        t0 = _time.perf_counter()

        tw = self.modules.get("telemetry_writer")
        if tw is not None:
            try:
                tw.write(hot, full)
            except Exception as e:
                result["errors"].append(f"telemetry: {e}")

        pd = self.modules.get("plateau_detector")
        if pd is not None:
            try:
                plat = pd.update(bn, hot["phi_raw"])
                if plat is not None:
                    result["plateau_event"] = plat.to_dict()
            except Exception as e:
                result["errors"].append(f"plateau: {e}")

        gt = self.modules.get("growth_trigger")
        if gt is not None and result["plateau_event"] is not None:
            try:
                phi_avg = hot["phi_raw"]
                if pd is not None and hasattr(pd, "_phi_history"):
                    h = list(pd._phi_history)
                    if h:
                        phi_avg = sum(h) / len(h)
                g = gt.evaluate(plateau_event=result["plateau_event"],
                                phi_avg_100=phi_avg, beat=bn)
                if g is not None:
                    result["growth_event"] = g.to_dict()
                    result["current_stage"] = gt.current_stage
                    result["stage_name"] = gt.stage_name()
            except Exception as e:
                result["errors"].append(f"growth: {e}")

        pm = self.modules.get("parelia_module")
        if pm is not None:
            result["current_stage"] = getattr(pm, "current_stage", result["current_stage"])
            result["stage_name"] = getattr(pm, "stage_name", result["stage_name"])

        re = self.modules.get("rule_engine")
        if re is not None and action_proposal is not None:
            try:
                vr = re.evaluate(
                    action_type=action_proposal.get("action_type", ""),
                    tool_name=action_proposal.get("tool_name", ""),
                    telemetry=hot,
                    values_engaged=action_proposal.get("values_engaged"),
                    current_stage=result["current_stage"],
                )
                result["rule_verdict"] = {
                    "action": vr.action.value, "rule_id": vr.rule_id,
                    "reason": vr.reason, "similarity": vr.similarity,
                    "modulation": vr.modulation,
                }
            except Exception as e:
                result["errors"].append(f"rules: {e}")

        mm = self.modules.get("memory_manager")
        if mm is not None:
            try:
                sig = min(1.0, hot["phi_raw"] / 0.5)
                mm.record(hot, significance=sig, tags=["beat"])
                mm.decay()
                result["memory_total"] = mm.total
            except Exception as e:
                result["errors"].append(f"memory: {e}")

        result["elapsed_ms"] = (_time.perf_counter() - t0) * 1_000
        return result

    def run(
        self, max_beats: int = 100,
        config_fn: Callable[[int], dict] | None = None,
        action_fn: Callable[[int, dict | None], dict | None] | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        self.start()
        try:
            for _ in range(max_beats):
                cfg = config_fn(self._current_beat + 1) if config_fn else {}
                proposal = (action_fn(self._current_beat + 1, results[-1] if results else None)
                            if action_fn else None)
                results.append(self.beat(action_proposal=proposal, config_override=cfg))
                tau = cfg.get("tau_ms", self.config.tau_ms)
                if tau > 0 and self._current_beat < max_beats:
                    import time
                    time.sleep(tau / 1_000.0)
        finally:
            self.stop()
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    orch = Orchestrator(preset="newborn", root_dir="/home/ubuntu/parelia_v2")
    orch.create_all()
    orch.start()
    r = orch.beat(config_override={"phi_raw": 0.45, "theta_raw": 0.2})
    print(f"Beat {r['beat']}: phi={r['phi_raw']:.4f}, stage={r['current_stage']}, "
          f"elapsed={r['elapsed_ms']:.2f}ms")
    orch.stop()
    print("Orchestrator smoke test passed.")