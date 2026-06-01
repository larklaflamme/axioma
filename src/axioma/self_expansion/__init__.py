"""AXIOMA self-expansion: dynamic tool registry, hot-loading, validator.

The architecture mirrors Thea's `nbc.self_extention` package (which itself
ports NBC's `ape/core/mcp_tool_executor.py`). See:

  - /home/ubuntu/thea/design/self-expansion.md  (design spec)
  - /home/ubuntu/thea/nbc/self_extention/        (reference impl)

Public surface:
  - `Tool`, `TextContent` — MCP-shim dataclasses (mirror `mcp.types`).
  - `ToolExecutor` — registry + hot-loader + persistent dynamic registry.
  - `validate`, `validate_static`, `ValidationResult` — 3-stage AST validator.
  - `pre_built/` subpackage — static tool servers (filesystem, bash, python).

The package is dep-free at import time — heavy imports (`aiofiles`, etc.)
happen inside the pre_built modules when they're instantiated.
"""
from __future__ import annotations

from .tool_executor import ServerEntry, ToolExecutor
from .types import USING_MCP, TextContent, Tool
from .validator import ValidationResult, validate, validate_static

__all__ = [
    "USING_MCP",
    "ServerEntry",
    "TextContent",
    "Tool",
    "ToolExecutor",
    "ValidationResult",
    "validate",
    "validate_static",
]
