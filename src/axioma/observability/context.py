"""AxiomaContext — single shared object holding all engine references + lightweight pub/sub.

Per IMPLEMENTATION_PLAN_v1.0.md §3.4.

Two purposes:
  1. Dependency injection — engines find each other via the context, not globals.
  2. Pub/sub — components emit named events; subscribers register handlers.

Events are processed in subscription order. Handlers may be coroutines or
plain callables. For high-throughput per-beat data flows use direct
context.<engine>.method() calls — events are for state changes, not the
data plane.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from .logging import get_logger

log = get_logger(__name__)

# Handler may be sync or async; we await if coroutine returned
EventHandler = Callable[[Any], Awaitable[None] | None]


class AxiomaContext:
    """Dependency injection + event bus."""

    def __init__(self) -> None:
        self._components: dict[str, Any] = {}
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    # ── Component registry (dependency injection) ─────────────────────────

    def register(self, name: str, component: Any) -> None:
        """Register a component under a stable name.

        Raises:
            KeyError: if name is already registered. Use replace() for
                intentional swaps during tests.
        """
        if name in self._components:
            raise KeyError(f"component already registered: {name}")
        self._components[name] = component
        log.debug("ctx_register", name=name, type=type(component).__name__)

    def replace(self, name: str, component: Any) -> None:
        """Replace an existing component. Test-only; logged at WARN."""
        if name not in self._components:
            log.warning("ctx_replace_no_existing", name=name)
        self._components[name] = component
        log.warning("ctx_replace", name=name, type=type(component).__name__)

    def get(self, name: str) -> Any:
        if name not in self._components:
            raise KeyError(f"component not registered: {name}")
        return self._components[name]

    def has(self, name: str) -> bool:
        return name in self._components

    def list_components(self) -> list[str]:
        return sorted(self._components.keys())

    # Typed accessors for common cases — avoids stringly-typed call sites.
    # Each returns Any to avoid a forward-ref dependency mess; the contract
    # is that the caller knows the type from convention.

    @property
    def substrate(self) -> Any:
        return self.get("substrate")

    @property
    def heartbeat(self) -> Any:
        return self.get("heartbeat")

    @property
    def perturbation_scheduler(self) -> Any:
        return self.get("perturbation_scheduler")

    @property
    def fragmentation_monitor(self) -> Any:
        return self.get("fragmentation_monitor")

    @property
    def recovery_protocol(self) -> Any:
        return self.get("recovery_protocol")

    @property
    def coherence_scheduler(self) -> Any:
        return self.get("coherence_scheduler")

    @property
    def meta_cognition_loop(self) -> Any:
        return self.get("meta_cognition_loop")

    @property
    def compose_function(self) -> Any:
        return self.get("compose_function")

    @property
    def cadence_controller(self) -> Any:
        return self.get("cadence_controller")

    @property
    def theta_short(self) -> Any:
        return self.get("theta_short")

    @property
    def theta_long(self) -> Any:
        return self.get("theta_long")

    @property
    def llm_client(self) -> Any:
        return self.get("llm_client")

    @property
    def vector_store(self) -> Any:
        return self.get("vector_store")

    @property
    def kv_store(self) -> Any:
        return self.get("kv_store")

    # ── Event bus ─────────────────────────────────────────────────────────

    def subscribe(self, event: str, handler: EventHandler) -> None:
        self._subscribers[event].append(handler)
        log.debug(
            "ctx_subscribe",
            event_name=event,
            handler=getattr(handler, "__qualname__", repr(handler)),
        )

    def unsubscribe(self, event: str, handler: EventHandler) -> bool:
        """Remove a handler. Returns True if removed, False if not found."""
        if event in self._subscribers and handler in self._subscribers[event]:
            self._subscribers[event].remove(handler)
            return True
        return False

    async def emit(self, event: str, payload: Any) -> None:
        """Synchronous-order dispatch. Handlers may return None or awaitable.

        One handler failing does NOT stop the others — safety property
        per IMPLEMENTATION_PLAN_v1.0.md §3.4.
        """
        handlers = list(self._subscribers.get(event, ()))  # snapshot
        for handler in handlers:
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception(
                    "ctx_event_handler_failed",
                    event_name=event,
                    handler=getattr(handler, "__qualname__", repr(handler)),
                )

    def emit_sync(self, event: str, payload: Any) -> None:
        """Synchronous-only emit: ignores any coroutines (test helper).

        Use in tests where you don't want to await; in production paths
        prefer the async emit().
        """
        handlers = list(self._subscribers.get(event, ()))
        for handler in handlers:
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    # Caller asked for sync; warn and skip
                    result.close()
                    log.warning(
                        "ctx_emit_sync_skipped_coroutine",
                        event_name=event,
                        handler=getattr(handler, "__qualname__", repr(handler)),
                    )
            except Exception:
                log.exception("ctx_event_handler_failed", event_name=event)
