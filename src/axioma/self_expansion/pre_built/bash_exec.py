"""BashExecServer — static tool server for bash command execution.

Wraps ``asyncio.create_subprocess_exec(["bash", "-c", ...])`` with:
  - per-command timeout (default 60 s)
  - merged stdout+stderr capture
  - output truncation at MAX_OUTPUT_BYTES (1 MB) so a runaway command
    can't blow memory
  - working directory override
  - environment-variable additions on top of the inherited env

Tools:
  - bash_exec        — run an arbitrary bash command string, return text result
  - bash_which       — locate an executable on PATH
  - bash_env         — print the current process env vars (filtered to non-secrets)

The threat model: the operator trusts AXIOMA (her own Ollama, her own
prompts, her own host). Generated tool modules CANNOT import ``subprocess``
or ``shlex`` per the validator (§validator._FORBIDDEN_IMPORTS), so the only
shell path is through this server. That keeps the audit trail in one place
and lets future hardening (timeout enforcement, env scrubbing, command
allowlists) be added in exactly one module.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from ..types import TextContent, Tool
from ._proc import PREEXEC, kill_process_tree

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_BYTES = 1 * 1024 * 1024  # 1 MB combined stdout+stderr cap
# Substrings that mark an env var as secret-ish; values redacted on display.
_SECRET_SUBSTRINGS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "AUTH")


def _ok(data: Any) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=f"[ERROR] {msg}")]


def _truncate(b: bytes, cap: int = MAX_OUTPUT_BYTES) -> tuple[str, bool]:
    truncated = len(b) > cap
    if truncated:
        b = b[:cap] + b"\n[... output truncated ...]"
    try:
        text = b.decode("utf-8", errors="replace")
    except Exception:
        text = repr(b)
    return text, truncated


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(s in upper for s in _SECRET_SUBSTRINGS)


_TOOLS: list[Tool] = [
    Tool(
        name="bash_exec",
        description=(
            "Run an arbitrary bash command and return its combined output "
            "(stdout + stderr interleaved). The command runs in a fresh "
            "subprocess invoked as `bash -c '<command>'`. Timeout: 60 s by "
            "default, override via `timeout_seconds`. Output is capped at "
            "1 MB; anything over is truncated with a marker. Returns a JSON "
            "object: {exit_code, output, truncated, elapsed_seconds}."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command line to run.",
                },
                "cwd": {
                    "type": "string",
                    "description": (
                        "Optional working directory. Default: current dir."
                    ),
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Per-command timeout (default 60).",
                },
                "env": {
                    "type": "object",
                    "description": (
                        "Additional env vars merged on top of the inherited "
                        "process env."
                    ),
                },
            },
            "required": ["command"],
        },
    ),
    Tool(
        name="bash_which",
        description=(
            "Locate an executable on PATH. Returns the absolute path or "
            "`[ERROR] not found: ...` if not present."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Executable name (e.g. 'python3')."},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="bash_env",
        description=(
            "Print the current process env vars as a JSON object. Names "
            "matching common secret substrings (KEY, SECRET, TOKEN, "
            "PASSWORD, PASSWD, AUTH) have their values redacted. Use "
            "`include_secrets=true` to disable redaction (rare)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "include_secrets": {
                    "type": "boolean",
                    "default": False,
                    "description": "Show secret values without redaction.",
                },
                "filter_prefix": {
                    "type": "string",
                    "description": "Only return vars starting with this prefix.",
                },
            },
        },
    ),
]


class BashExecServer:
    """Bash subprocess wrapper with timeouts and output capping."""

    ALL_TOOLS = _TOOLS

    def __init__(self, default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.default_timeout_seconds = float(default_timeout_seconds)

    # ── Dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, name: str, args: dict) -> list[TextContent]:
        try:
            if name == "bash_exec":  return await self._exec(args)
            if name == "bash_which": return self._which(args)
            if name == "bash_env":   return self._env(args)
            return _err(f"Unknown tool: {name}")
        except Exception as e:
            log.exception("[BashExecServer] %s raised", name)
            return _err(f"{name} failed: {type(e).__name__}: {e}")

    # ── Handlers ────────────────────────────────────────────────────────

    async def _exec(self, args: dict) -> list[TextContent]:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return _err("`command` is required and must be a non-empty string.")
        cwd = args.get("cwd")
        if cwd is not None:
            cwd_path = Path(str(cwd)).expanduser().resolve()
            if not cwd_path.is_dir():
                return _err(f"cwd is not a directory: {cwd_path}")
            cwd_arg: str | None = str(cwd_path)
        else:
            cwd_arg = None
        timeout = float(args.get("timeout_seconds") or self.default_timeout_seconds)
        if timeout <= 0:
            return _err("timeout_seconds must be > 0.")

        env_overrides = args.get("env") or {}
        if not isinstance(env_overrides, dict):
            return _err("`env` must be a JSON object of strings.")
        env = os.environ.copy()
        for k, v in env_overrides.items():
            env[str(k)] = str(v)

        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
                cwd=cwd_arg,
                env=env,
                # Own process group + die-with-parent: a timeout reaps the whole
                # subtree (bash may fork children) and a crash can't leak it.
                preexec_fn=PREEXEC,
            )
        except Exception as e:
            return _err(f"failed to launch bash: {type(e).__name__}: {e}")

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
            elapsed = loop.time() - t0
            output, truncated = _truncate(stdout or b"")
            return _ok({
                "exit_code": proc.returncode,
                "output": output,
                "truncated": truncated,
                "elapsed_seconds": round(elapsed, 3),
                "command": command,
            })
        except TimeoutError:
            kill_process_tree(proc)
            stdout_partial = b""
            with contextlib.suppress(Exception):
                stdout_partial, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=2.0,
                )
            elapsed = loop.time() - t0
            output, truncated = _truncate(stdout_partial)
            return _ok({
                "exit_code": None,
                "output": output,
                "truncated": truncated,
                "elapsed_seconds": round(elapsed, 3),
                "command": command,
                "timed_out": True,
                "timeout_seconds": timeout,
            })

    def _which(self, args: dict) -> list[TextContent]:
        name = args.get("name")
        if not isinstance(name, str) or not name.strip():
            return _err("`name` is required.")
        found = shutil.which(name)
        if found is None:
            return _err(f"not found: {name}")
        return _ok(found)

    def _env(self, args: dict) -> list[TextContent]:
        include_secrets = bool(args.get("include_secrets", False))
        prefix = args.get("filter_prefix") or ""
        env_out: dict[str, str] = {}
        for k, v in os.environ.items():
            if prefix and not k.startswith(prefix):
                continue
            if not include_secrets and _is_secret_name(k) and v:
                env_out[k] = "(redacted)"
            else:
                env_out[k] = v
        return _ok(dict(sorted(env_out.items())))


__all__ = ["BashExecServer"]
