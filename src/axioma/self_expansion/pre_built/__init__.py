"""Pre-built static tool servers shipped with AXIOMA.

Each module exposes a `*Server` class with the same MCP-shaped contract as
generated modules (a `ALL_TOOLS` class attribute and an async `_dispatch`).
They register through `ToolExecutor.register_server` at boot.

Available servers:
  - `FileSystemServer` — scoped file I/O (read anywhere; write only in
    `data/state/generated/` by default)
  - `BashExecServer` — bash command execution via async subprocess, with
    a per-command timeout
  - `PythonExecServer` — Python execution in a fresh subprocess, with
    timeout + stdout/stderr capture + exit code
  - `WebSearchServer` — Tavily + Brave search + plain-text web fetch.
    Requires TAVILY_API_KEY / BRAVE_API_KEY in env (each provider can
    be disabled independently if its key is missing).
  - `WolframServer` — Wolfram|Alpha math + factual queries across 5 tools
    (full / short / spoken / math_verify / llm). Requires WOLFRAM_APPID
    in env; missing key disables every tool via an error envelope.

Each server's `ALL_TOOLS` list is the canonical surface AXIOMA's LLM sees
when these are installed in the conversation handler's tool-use loop.
"""
from __future__ import annotations

from .bash_exec import BashExecServer
from .filesystem import FileSystemServer
from .python_exec import PythonExecServer
from .web_search import WebSearchServer
from .wolfram import WolframServer

__all__ = [
    "BashExecServer",
    "FileSystemServer",
    "PythonExecServer",
    "WebSearchServer",
    "WolframServer",
]
