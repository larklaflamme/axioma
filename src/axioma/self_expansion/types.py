"""MCP-compatible type shims.

If the ``mcp`` package is installed, re-export ``Tool`` and ``TextContent``
from ``mcp.types``. Otherwise define minimal stand-ins with the same shape
so generated modules can be authored against the same imports either way.

Generated modules can use ``from mcp.types import Tool, TextContent`` if
they want strict MCP compatibility, or
``from axioma.self_expansion.types import Tool, TextContent`` to remain
dep-free.

Port of /home/ubuntu/thea/nbc/self_extention/types.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:  # Prefer the real MCP types when available.
    from mcp.types import TextContent as _MCPTextContent
    from mcp.types import Tool as _MCPTool
    Tool = _MCPTool
    TextContent = _MCPTextContent
    USING_MCP = True
except Exception:  # pragma: no cover — exercised only without mcp installed
    USING_MCP = False

    @dataclass
    class TextContent:  # type: ignore[no-redef]
        """Drop-in shim for ``mcp.types.TextContent``."""

        type: str = "text"
        text: str = ""

    @dataclass
    class Tool:  # type: ignore[no-redef]
        """Drop-in shim for ``mcp.types.Tool``.

        Anthropic's tool-use schema needs three fields:
            name, description, inputSchema
        """

        name: str = ""
        description: str = ""
        inputSchema: dict[str, Any] = field(default_factory=dict)


__all__ = ["USING_MCP", "TextContent", "Tool"]
