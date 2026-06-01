"""PythonExecServer — static tool server for Python subprocess execution.

Tools:
  - python_exec      — run a Python code string in a fresh subprocess
  - python_run_file  — run an existing .py file in a fresh subprocess
  - python_version   — report the Python interpreter version + executable path

Both execution tools:
  - launch a fresh subprocess via the current ``sys.executable`` (so the
    AXIOMA conda env's interpreter is used);
  - apply a configurable timeout (default 60 s);
  - capture stdout + stderr separately;
  - return {exit_code, stdout, stderr, truncated, elapsed_seconds}.

The threat model: same as bash_exec — AXIOMA-trusted only. Generated
modules CANNOT import ``subprocess`` per the validator, so this is the
only path for Python subprocess execution from generated code.

Port of /home/ubuntu/thea/nbc/self_extention/python_exec.py (trimmed).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from ..types import TextContent, Tool

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_BYTES = 1 * 1024 * 1024  # 1 MB per stream cap


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


_TOOLS: list[Tool] = [
    Tool(
        name="python_exec",
        description=(
            "Run a Python code string in a fresh subprocess (same interpreter "
            "AXIOMA is using). Use this to compute things, run small scripts, "
            "inspect environments, etc. — anything you'd write a quick `.py` "
            "for. Returns {exit_code, stdout, stderr, truncated_*, "
            "elapsed_seconds}."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source code to execute.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Per-call timeout (default 60).",
                },
                "stdin": {
                    "type": "string",
                    "description": "Optional stdin payload piped to the subprocess.",
                },
                "env": {
                    "type": "object",
                    "description": (
                        "Additional env vars merged on top of inherited env."
                    ),
                },
            },
            "required": ["code"],
        },
    ),
    Tool(
        name="python_run_file",
        description=(
            "Run an existing Python file in a fresh subprocess. Use this when "
            "the script already lives on disk (e.g. one you wrote via "
            "file_write). Returns {exit_code, stdout, stderr, "
            "truncated_*, elapsed_seconds}."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to a .py file."},
                "args": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Command-line arguments after the file path.",
                },
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "number"},
                "env": {"type": "object"},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="python_version",
        description=(
            "Report the running Python interpreter version and executable path. "
            "No args."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


class PythonExecServer:
    """Python subprocess wrapper with timeouts and per-stream output capping."""

    ALL_TOOLS = _TOOLS

    def __init__(self, default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.default_timeout_seconds = float(default_timeout_seconds)

    # ── Dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, name: str, args: dict) -> list[TextContent]:
        try:
            if name == "python_exec":     return await self._exec(args)
            if name == "python_run_file": return await self._run_file(args)
            if name == "python_version":  return self._version(args)
            return _err(f"Unknown tool: {name}")
        except Exception as e:
            log.exception("[PythonExecServer] %s raised", name)
            return _err(f"{name} failed: {type(e).__name__}: {e}")

    # ── Handlers ────────────────────────────────────────────────────────

    async def _exec(self, args: dict) -> list[TextContent]:
        code = args.get("code")
        if not isinstance(code, str):
            return _err("`code` is required and must be a string.")
        timeout = float(args.get("timeout_seconds") or self.default_timeout_seconds)
        if timeout <= 0:
            return _err("timeout_seconds must be > 0.")
        cwd = args.get("cwd")
        cwd_arg = str(Path(str(cwd)).expanduser().resolve()) if cwd else None
        if cwd_arg and not Path(cwd_arg).is_dir():
            return _err(f"cwd is not a directory: {cwd_arg}")
        stdin = args.get("stdin")
        env_overrides = args.get("env") or {}
        if not isinstance(env_overrides, dict):
            return _err("`env` must be a JSON object of strings.")
        env = os.environ.copy()
        for k, v in env_overrides.items():
            env[str(k)] = str(v)

        argv = [sys.executable, "-c", code]
        return await self._run(argv, cwd=cwd_arg, env=env, stdin=stdin,
                               timeout=timeout, label=f"python -c <{len(code)} chars>")

    async def _run_file(self, args: dict) -> list[TextContent]:
        path = args.get("path")
        if not isinstance(path, str):
            return _err("`path` is required.")
        py_path = Path(path).expanduser().resolve()
        if not py_path.exists():
            return _err(f"File not found: {py_path}")
        if not py_path.is_file():
            return _err(f"Not a regular file: {py_path}")

        extra_args = args.get("args") or []
        if not isinstance(extra_args, list) or not all(isinstance(a, str) for a in extra_args):
            return _err("`args` must be a list of strings.")

        timeout = float(args.get("timeout_seconds") or self.default_timeout_seconds)
        cwd = args.get("cwd")
        cwd_arg = str(Path(str(cwd)).expanduser().resolve()) if cwd else None
        env_overrides = args.get("env") or {}
        env = os.environ.copy()
        for k, v in (env_overrides or {}).items():
            env[str(k)] = str(v)

        argv = [sys.executable, str(py_path), *extra_args]
        return await self._run(argv, cwd=cwd_arg, env=env, stdin=None,
                               timeout=timeout, label=f"python {py_path.name}")

    async def _run(
        self,
        argv: list[str],
        *,
        cwd: str | None,
        env: dict[str, str],
        stdin: str | None,
        timeout: float,
        label: str,
    ) -> list[TextContent]:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        except Exception as e:
            return _err(f"failed to launch {label}: {type(e).__name__}: {e}")

        stdin_bytes = stdin.encode("utf-8") if isinstance(stdin, str) else None
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes), timeout=timeout,
            )
            elapsed = loop.time() - t0
            stdout, stdout_trunc = _truncate(stdout_b or b"")
            stderr, stderr_trunc = _truncate(stderr_b or b"")
            return _ok({
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "truncated_stdout": stdout_trunc,
                "truncated_stderr": stderr_trunc,
                "elapsed_seconds": round(elapsed, 3),
            })
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            stdout_b = stderr_b = b""
            with contextlib.suppress(Exception):
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=2.0,
                )
            elapsed = loop.time() - t0
            stdout, stdout_trunc = _truncate(stdout_b)
            stderr, stderr_trunc = _truncate(stderr_b)
            return _ok({
                "exit_code": None,
                "stdout": stdout,
                "stderr": stderr,
                "truncated_stdout": stdout_trunc,
                "truncated_stderr": stderr_trunc,
                "elapsed_seconds": round(elapsed, 3),
                "timed_out": True,
                "timeout_seconds": timeout,
            })

    def _version(self, _args: dict) -> list[TextContent]:
        return _ok({
            "version": sys.version,
            "version_info": list(sys.version_info[:5]),
            "executable": sys.executable,
            "platform": sys.platform,
        })


__all__ = ["PythonExecServer"]
