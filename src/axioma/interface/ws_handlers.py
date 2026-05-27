"""WebSocket subscriber handler module — substrate-private state firewall.

★ ARCHITECTURAL KEYSTONE — this module MUST NOT import `InternalState`.

The C12 ImportError test (Phase C) verifies that:
  1. This module exists in the axioma.interface namespace
  2. After import, `InternalState` is NOT in this module's __dict__
  3. Direct `from axioma.schemas.internal_state import InternalState` inside
     this module's namespace raises (when attempted in a test context)

Phase C builds the stub only; the real subscriber multiplexer ships in
Phase D (WebSocket server). Per ARCH §5 + §8.6: peer agents only ever see
ExternalState — never InternalState. The boundary is structural.

What IS allowed: importing ExternalState from axioma.schemas. The whole
peer-facing surface is built on ExternalState.

Lint enforcement: a `tool.ruff` rule (or `import-linter` in Phase D) blocks
`from axioma.schemas.internal_state import *` patterns in this module and
sibling interface modules. The runtime ImportError test is the belt-and-
suspenders verification that supplements the lint check.
"""
from __future__ import annotations

# DELIBERATE: only ExternalState. NEVER InternalState. The Phase C
# ImportError test verifies this constraint at runtime. The Phase D
# import-linter contract enforces it transitively at lint time, which
# is why we import directly from the submodule rather than the package
# __init__ — the package __init__ pulls in InternalState too.
from ..schemas.external_state import ExternalState


def stub() -> None:
    """Placeholder — Phase D replaces this with real WS handlers."""


__all__ = ["ExternalState", "stub"]
