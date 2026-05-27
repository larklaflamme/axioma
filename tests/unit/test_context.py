"""AxiomaContext — dependency injection + event bus."""
from __future__ import annotations

import pytest

from axioma.observability import AxiomaContext


def test_register_and_get(fresh_ctx: AxiomaContext) -> None:
    obj = {"x": 1}
    fresh_ctx.register("foo", obj)
    assert fresh_ctx.get("foo") is obj
    assert fresh_ctx.has("foo")
    assert "foo" in fresh_ctx.list_components()


def test_register_duplicate_raises(fresh_ctx: AxiomaContext) -> None:
    fresh_ctx.register("foo", 1)
    with pytest.raises(KeyError):
        fresh_ctx.register("foo", 2)


def test_get_missing_raises(fresh_ctx: AxiomaContext) -> None:
    with pytest.raises(KeyError):
        fresh_ctx.get("nope")
    assert not fresh_ctx.has("nope")


def test_replace_warns_but_succeeds(fresh_ctx: AxiomaContext) -> None:
    fresh_ctx.register("foo", 1)
    fresh_ctx.replace("foo", 2)
    assert fresh_ctx.get("foo") == 2


def test_typed_accessor_when_missing(fresh_ctx: AxiomaContext) -> None:
    with pytest.raises(KeyError):
        _ = fresh_ctx.substrate


async def test_subscribe_sync_handler(fresh_ctx: AxiomaContext) -> None:
    received: list[int] = []
    fresh_ctx.subscribe("evt", lambda p: received.append(p))
    await fresh_ctx.emit("evt", 42)
    assert received == [42]


async def test_subscribe_async_handler(fresh_ctx: AxiomaContext) -> None:
    received: list[str] = []

    async def handler(p: str) -> None:
        received.append(p)

    fresh_ctx.subscribe("evt", handler)
    await fresh_ctx.emit("evt", "hi")
    assert received == ["hi"]


async def test_handler_exception_isolated(fresh_ctx: AxiomaContext) -> None:
    """One handler raising must not stop the next handler."""
    ok: list[int] = []

    def bad(_p: int) -> None:
        raise RuntimeError("intentional")

    def good(p: int) -> None:
        ok.append(p)

    fresh_ctx.subscribe("evt", bad)
    fresh_ctx.subscribe("evt", good)
    await fresh_ctx.emit("evt", 7)
    assert ok == [7]


async def test_multiple_handlers_in_order(fresh_ctx: AxiomaContext) -> None:
    order: list[str] = []
    fresh_ctx.subscribe("evt", lambda _p: order.append("a"))
    fresh_ctx.subscribe("evt", lambda _p: order.append("b"))
    fresh_ctx.subscribe("evt", lambda _p: order.append("c"))
    await fresh_ctx.emit("evt", None)
    assert order == ["a", "b", "c"]


def test_unsubscribe(fresh_ctx: AxiomaContext) -> None:
    handler = lambda _: None  # noqa: E731
    fresh_ctx.subscribe("evt", handler)
    assert fresh_ctx.unsubscribe("evt", handler) is True
    assert fresh_ctx.unsubscribe("evt", handler) is False
    assert fresh_ctx.unsubscribe("nope", handler) is False


def test_emit_sync_with_coroutine_handler_warns(fresh_ctx: AxiomaContext) -> None:
    """emit_sync skips coroutine handlers; should not raise but the
    coroutine should be closed (no warning leaked)."""

    async def handler(_p: int) -> None:
        pass

    fresh_ctx.subscribe("evt", handler)
    # Should not raise; coroutine is closed internally.
    fresh_ctx.emit_sync("evt", 1)


async def test_emit_no_subscribers_is_noop(fresh_ctx: AxiomaContext) -> None:
    await fresh_ctx.emit("nobody_listening", {"a": 1})  # no exception
