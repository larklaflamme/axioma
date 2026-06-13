"""C12 — the substrate-privacy boundary is structural, not disciplined.

★ ARCHITECTURAL KEYSTONE TEST per ARCH_DESIGN_v1.0.md §5 + IMPLEMENTATION_PLAN
  §7.1 (C12).

Verifies that:
  1. A peer-facing interface module (`axioma.interface.peer_conversation`, the
     reply generator wired into the Agora bridge) is importable.
  2. After importing it, `InternalState` is NOT in its module namespace.
     This guards against accidental `from ..schemas.internal_state import *`
     or wildcard re-exports.
  3. `ExternalState` IS importable from the interface module — that's the
     allowed public surface for peer-facing code.

This is the *runtime* check. The *static* check is a lint rule (Phase D adds
`import-linter`) that blocks the import at PR-review time. Belt and suspenders.

If this test ever fails, the substrate's structural privacy has been broken:
some path through the interface code can now access InternalState directly.
The architecture's privacy guarantee — that peers see ExternalState only —
becomes a discipline-only matter rather than enforced by the type system.
"""
from __future__ import annotations

import importlib

_IFACE_MODULE = "axioma.interface.peer_conversation"


def test_interface_module_exists() -> None:
    """The peer-facing interface module must be importable."""
    mod = importlib.import_module(_IFACE_MODULE)
    assert mod is not None


def test_internal_state_not_in_interface_module() -> None:
    """★ The architectural keystone: InternalState must NOT be exposed by
    any axioma.interface.* module."""
    mod = importlib.import_module(_IFACE_MODULE)
    assert "InternalState" not in mod.__dict__, (
        f"{_IFACE_MODULE} leaks InternalState into its namespace. "
        "This breaks the substrate-privacy boundary per ARCH §5. "
        "Fix: remove any `from ..schemas import InternalState` or "
        "`from ..schemas.internal_state import *` from interface modules."
    )


def test_external_state_is_in_interface_module() -> None:
    """ExternalState IS the public surface; it MUST be available to
    interface modules."""
    mod = importlib.import_module(_IFACE_MODULE)
    assert "ExternalState" in mod.__dict__, (
        "Interface module is missing ExternalState — but it should be the "
        "peer-facing type."
    )


def test_interface_init_does_not_leak_internal_state() -> None:
    """Same check at the package level."""
    mod = importlib.import_module("axioma.interface")
    # The package __init__ might be empty (no imports) or might re-export
    # public submodule contents. Either way, InternalState must not appear.
    assert "InternalState" not in mod.__dict__


def test_schemas_module_still_has_internal_state() -> None:
    """Sanity check: InternalState IS available where it belongs.
    The privacy is about INTERFACE modules; the schema itself still exposes it."""
    mod = importlib.import_module("axioma.schemas")
    assert "InternalState" in mod.__dict__


def test_internal_state_in_substrate_modules() -> None:
    """Sanity check: substrate-internal code (e.g., SubstrateApp) CAN import
    InternalState. The boundary is specifically interface/peer-facing modules."""
    mod = importlib.import_module("axioma.substrate.app")
    # SubstrateApp returns InternalState from tick(); the symbol is used
    # internally. The import lives there; we just verify the module loads.
    assert hasattr(mod, "SubstrateApp")
