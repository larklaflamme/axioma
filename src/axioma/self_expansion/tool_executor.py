"""ToolExecutor — routing + hot-loading + dynamic registry.

Single per-process instance. Owns:
  - A flat list of tool definitions (Anthropic-format) for the LLM.
  - An O(1) routing table (tool name → server entry).
  - The dynamic-module registry, persisted to
    ``<generated_dir>/dynamic_registry.json`` so capabilities survive
    process restarts.

The four lines that make hot-loading possible:

    spec   = importlib.util.spec_from_file_location(mod_name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)

After ``_register(entry)`` returns, the next call to ``executor.tools``
includes the new tools and ``executor.execute_async(name, args)`` routes
correctly. No restart, no reconnect.

Port of /home/ubuntu/thea/nbc/self_extention/tool_executor.py with the
``nbc_dynamic_`` module-name prefix renamed to ``axioma_dynamic_``.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import json
import logging
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .validator import validate_static

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60.0
WATCHER_POLL_SECONDS = 2.0


@dataclass
class ServerEntry:
    """A loaded MCP-shaped tool server (static or dynamic)."""

    name: str
    server: Any  # has ._dispatch and .ALL_TOOLS
    tool_names: set[str]
    tools: list[dict]  # Anthropic-format tool defs
    dynamic: bool = False
    source_path: str = ""


class ToolExecutor:
    """Per-process routing + hot-loading core for AXIOMA tools."""

    def __init__(
        self,
        generated_dir: Path,
        registry_path: Path | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.generated_dir = Path(generated_dir)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = Path(
            registry_path or self.generated_dir / "dynamic_registry.json",
        )
        self.timeout_seconds = timeout_seconds

        self._servers: list[ServerEntry] = []
        self._route: dict[str, ServerEntry] = {}
        self._tools: list[dict] = []
        self._registry_lock = threading.RLock()
        self._dynamic_modules: dict[str, dict] = {}

        self._watcher_stop = threading.Event()
        self._watcher_thread: threading.Thread | None = None

    # ── Public read API ─────────────────────────────────────────────────

    @property
    def tools(self) -> list[dict]:
        """Anthropic-format tool definitions for ``messages.create(tools=...)``."""
        with self._registry_lock:
            return list(self._tools)

    @property
    def tool_names(self) -> list[str]:
        with self._registry_lock:
            return sorted(self._route.keys())

    @property
    def server_names(self) -> list[str]:
        with self._registry_lock:
            return [s.name for s in self._servers]

    @property
    def dynamic_modules(self) -> dict[str, dict]:
        return dict(self._dynamic_modules)

    @property
    def ready(self) -> bool:
        return bool(self._tools)

    # ── Registration ────────────────────────────────────────────────────

    def register_server(
        self,
        name: str,
        server: Any,
        *,
        dynamic: bool = False,
        source_path: str = "",
    ) -> ServerEntry:
        """Register an already-instantiated tool server."""
        if not hasattr(server, "ALL_TOOLS"):
            raise ValueError(f"{name}: server has no ALL_TOOLS")
        if not callable(getattr(server, "_dispatch", None)):
            raise ValueError(f"{name}: server has no callable _dispatch")
        tool_defs, tool_names = self._tools_to_defs(server.ALL_TOOLS)
        entry = ServerEntry(
            name=name,
            server=server,
            tool_names=tool_names,
            tools=tool_defs,
            dynamic=dynamic,
            source_path=source_path,
        )
        self._register(entry)
        return entry

    def _register(self, entry: ServerEntry) -> None:
        with self._registry_lock:
            collisions = entry.tool_names & set(self._route.keys())
            if collisions:
                log.warning(
                    "[ToolExecutor] %s shadows existing tools: %s — "
                    "evicting previous defs from the tools list to keep "
                    "tool names unique (Anthropic API requires this).",
                    entry.name, sorted(collisions),
                )
                # Evict the colliding names from `_tools` AND from any prior
                # server's tool_names set, so the in-memory state stays
                # consistent. `_route` already overwrites below.
                self._tools = [td for td in self._tools
                               if td["name"] not in collisions]
                for prev in self._servers:
                    if prev.tool_names & collisions:
                        prev.tool_names -= collisions
                        prev.tools = [td for td in prev.tools
                                      if td["name"] not in collisions]
            self._servers.append(entry)
            self._tools.extend(entry.tools)
            for tn in entry.tool_names:
                self._route[tn] = entry
        log.info(
            "[ToolExecutor] Registered %s (%d tools): %s",
            entry.name, len(entry.tool_names), sorted(entry.tool_names),
        )

    @staticmethod
    def _tools_to_defs(all_tools: list[Any]) -> tuple[list[dict], set[str]]:
        defs: list[dict] = []
        names: set[str] = set()
        for t in all_tools:
            name = getattr(t, "name", None)
            if not isinstance(name, str) or not name:
                raise ValueError("Tool entry missing a string name")
            defs.append({
                "name": name,
                "description": getattr(t, "description", "") or "",
                "input_schema": (getattr(t, "inputSchema", {})
                                 or {"type": "object"}),
            })
            names.add(name)
        return defs, names

    # ── Execution ───────────────────────────────────────────────────────

    async def execute_async(self, tool_name: str, tool_input: dict) -> str:
        """Async-friendly tool dispatch — call from async code.

        Avoids the threadpool round-trip that ``execute`` needs when called
        from inside an asyncio event loop. Use this from the conversation
        handler's tool-use loop.
        """
        with self._registry_lock:
            entry = self._route.get(tool_name)
        if entry is None:
            available = ", ".join(self.tool_names) or "(none)"
            return f"[Unknown tool: {tool_name}. Available: {available}]"
        try:
            result = await asyncio.wait_for(
                entry.server._dispatch(tool_name, tool_input),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            return (
                f"[tool timeout: {entry.name}/{tool_name} exceeded "
                f"{self.timeout_seconds}s]"
            )
        except Exception as e:
            log.exception("[ToolExecutor] %s/%s raised", entry.name, tool_name)
            return (f"[tool error in {entry.name}/{tool_name}: "
                    f"{type(e).__name__}: {e}]")

        return _join_textcontent(result)

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """Sync wrapper. Routes through ``execute_async`` via a fresh loop
        (or a threadpool if we're already inside one)."""
        with self._registry_lock:
            entry = self._route.get(tool_name)
        if entry is None:
            available = ", ".join(self.tool_names) or "(none)"
            return f"[Unknown tool: {tool_name}. Available: {available}]"

        def _run_dispatch() -> Any:
            return asyncio.run(entry.server._dispatch(tool_name, tool_input))

        try:
            try:
                asyncio.get_running_loop()
                # Inside an asyncio loop — offload to a fresh thread with its
                # own loop. Without this fallback, asyncio.run() raises
                # RuntimeError.
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_run_dispatch)
                    result = future.result(timeout=self.timeout_seconds)
            except RuntimeError:
                result = _run_dispatch()
            return _join_textcontent(result)
        except concurrent.futures.TimeoutError:
            return (f"[tool timeout: {entry.name}/{tool_name} exceeded "
                    f"{self.timeout_seconds}s]")
        except Exception as e:  # never let dispatch crash the agent loop
            log.exception("[ToolExecutor] %s/%s raised", entry.name, tool_name)
            return (f"[tool error in {entry.name}/{tool_name}: "
                    f"{type(e).__name__}: {e}]")

    # ── Hot-load ────────────────────────────────────────────────────────

    def load_module(self, module_path: Path) -> dict:
        """Import a GeneratedServer .py file and register its tools.

        Returns a dict describing the loaded module (also written into the
        dynamic registry).

        Idempotent on ``source_path``: if a module loaded from this exact
        file is already active (e.g. an auto_load + watcher race), the
        existing record is returned and no second import happens. Use
        ``reload_module`` to pick up source changes.
        """
        module_path = Path(module_path)
        if not module_path.exists():
            raise FileNotFoundError(f"Module not found: {module_path}")

        resolved_src = str(module_path.resolve())
        for info in self._dynamic_modules.values():
            if (info.get("status") == "active"
                    and Path(info.get("source_path", "")).resolve() == Path(resolved_src)):
                log.info(
                    "[ToolExecutor] %s already loaded from %s — skipping re-load",
                    info.get("module_name"), resolved_src,
                )
                return info

        source = module_path.read_text(encoding="utf-8")
        vr = validate_static(source, module_path.name)
        if not vr.ok:
            raise ValueError(f"Validation failed (stage {vr.stage}): {vr.error}")

        stem = module_path.stem
        mod_name = f"axioma_dynamic_{stem}_{uuid.uuid4().hex[:8]}"

        spec = importlib.util.spec_from_file_location(mod_name, str(module_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create module spec for {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            sys.modules.pop(mod_name, None)
            raise ImportError(f"Module exec failed: {e}") from e

        if not hasattr(module, "GeneratedServer"):
            sys.modules.pop(mod_name, None)
            raise ImportError("Module has no GeneratedServer class")

        try:
            server = module.GeneratedServer()
        except Exception as e:
            sys.modules.pop(mod_name, None)
            raise ImportError(f"GeneratedServer() raised: {e}") from e

        entry = self.register_server(
            name=mod_name, server=server,
            dynamic=True, source_path=str(module_path),
        )

        info = {
            "module_name": mod_name,
            "source_path": str(module_path),
            "loaded_at": datetime.now(UTC).isoformat(),
            "tools": sorted(entry.tool_names),
            "status": "active",
        }
        self._dynamic_modules[mod_name] = info
        self._save_dynamic_registry()
        return info

    def unregister_server(self, name: str) -> dict:
        """Remove a server entry by name (works for static or dynamic).

        For dynamic modules prefer ``unload_module`` (which also touches the
        on-disk registry).
        """
        with self._registry_lock:
            target: ServerEntry | None = None
            for entry in self._servers:
                if entry.name == name:
                    target = entry
                    break
            if target is None:
                raise KeyError(f"Unknown server: {name}")
            self._servers.remove(target)
            for tn in target.tool_names:
                self._route.pop(tn, None)
            for td in list(target.tools):
                try:
                    self._tools.remove(td)
                except ValueError:
                    pass
        log.info(
            "[ToolExecutor] Unregistered %s (%d tools): %s",
            name, len(target.tool_names), sorted(target.tool_names),
        )
        return {
            "name": name,
            "tools": sorted(target.tool_names),
            "dynamic": target.dynamic,
            "source_path": target.source_path,
        }

    def unload_module(self, module_name: str) -> dict:
        info = self._dynamic_modules.get(module_name)
        if info is None:
            raise KeyError(f"Unknown dynamic module: {module_name}")
        with self._registry_lock:
            for entry in list(self._servers):
                if entry.name == module_name:
                    self._servers.remove(entry)
                    for tn in entry.tool_names:
                        self._route.pop(tn, None)
                    for td in list(entry.tools):
                        try:
                            self._tools.remove(td)
                        except ValueError:
                            pass
                    break
        info["status"] = "unloaded"
        info["unloaded_at"] = datetime.now(UTC).isoformat()
        self._save_dynamic_registry()
        sys.modules.pop(module_name, None)
        log.info("[ToolExecutor] Unloaded %s", module_name)
        return info

    def reload_module(self, module_name: str) -> dict:
        info = self._dynamic_modules.get(module_name)
        if info is None:
            raise KeyError(f"Unknown dynamic module: {module_name}")
        source_path = info["source_path"]
        self.unload_module(module_name)
        self._dynamic_modules.pop(module_name, None)
        return self.load_module(Path(source_path))

    # ── Persistence ─────────────────────────────────────────────────────

    def _save_dynamic_registry(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"loaded": list(self._dynamic_modules.values())}
        tmp = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8",
        )
        tmp.replace(self.registry_path)

    def restore_from_registry(self) -> int:
        """Load every active module from the persisted registry. Returns count."""
        if not self.registry_path.exists():
            return 0
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(
                "[ToolExecutor] Failed to read %s (%s) — starting empty",
                self.registry_path, e,
            )
            return 0

        # Dedupe by resolved source_path — protects against past races.
        seen_sources: set[str] = set()
        deduped: list[dict] = []
        dropped_dupes = 0
        for entry in data.get("loaded", []):
            if entry.get("status") != "active":
                continue
            src = entry.get("source_path", "")
            if not src or not Path(src).exists():
                log.warning("[ToolExecutor] Registry entry source missing: %s", src)
                continue
            try:
                resolved = str(Path(src).resolve())
            except OSError:
                resolved = src
            if resolved in seen_sources:
                dropped_dupes += 1
                continue
            seen_sources.add(resolved)
            deduped.append(entry)

        if dropped_dupes:
            log.warning(
                "[ToolExecutor] Dropped %d duplicate registry entries on restore",
                dropped_dupes,
            )

        loaded = 0
        for entry in deduped:
            try:
                self.load_module(Path(entry["source_path"]))
                loaded += 1
            except Exception as e:
                log.warning(
                    "[ToolExecutor] Restore failed for %s: %s",
                    entry["source_path"], e,
                )
        if loaded:
            log.info(
                "[ToolExecutor] Restored %d dynamic module(s) from registry",
                loaded,
            )
        if dropped_dupes:
            self._save_dynamic_registry()
        return loaded

    # ── File watcher ────────────────────────────────────────────────────

    def start_watcher(self) -> None:
        """Background thread: poll generated_dir, hot-load any new .py files."""
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            return
        self._watcher_stop.clear()
        watch_dir = self.generated_dir

        def _poll() -> None:
            known: set[str] = {str(p) for p in watch_dir.glob("*.py")}
            while not self._watcher_stop.is_set():
                try:
                    current = {str(p) for p in watch_dir.glob("*.py")}
                    new_files = current - known
                    for fpath in sorted(new_files):
                        already_loaded = any(
                            info.get("source_path") == fpath
                            and info.get("status") == "active"
                            for info in self._dynamic_modules.values()
                        )
                        if already_loaded:
                            known.add(fpath)
                            continue
                        time.sleep(0.1)  # let writer finish flushing
                        try:
                            self.load_module(Path(fpath))
                        except Exception as e:
                            log.warning("[watcher] failed to load %s: %s",
                                        fpath, e)
                        known.add(fpath)
                except Exception:
                    pass  # never crash the watcher
                self._watcher_stop.wait(WATCHER_POLL_SECONDS)

        self._watcher_thread = threading.Thread(
            target=_poll, daemon=True, name="axioma-dynamic-watcher",
        )
        self._watcher_thread.start()
        log.info(
            "[ToolExecutor] Watcher started on %s (poll %.1fs)",
            watch_dir, WATCHER_POLL_SECONDS,
        )

    def stop_watcher(self) -> None:
        self._watcher_stop.set()
        thread = self._watcher_thread
        if thread is not None:
            thread.join(timeout=5)
            self._watcher_thread = None


def _join_textcontent(blocks: Any) -> str:
    """Join the ``text`` fields of a list of TextContent (or shim) into a string."""
    parts: list[str] = []
    for block in blocks or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts) if parts else "[no output]"


__all__ = ["ServerEntry", "ToolExecutor"]
