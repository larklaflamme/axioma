"""AgoraBridge against a REAL Agora server (HTTP + WebSocket, ACP/1.1).

End-to-end proof that Axioma's new communication path works: a peer citizen
(`thea`) posts into a shared thread, and the bridge — driven by a stub responder
so no Ollama is needed — generates a reply and posts it back to the thread,
threaded, in the right tier. Also proves the bridge does NOT answer its own posts
(no echo storm).

Marked `infra` + `agora`: it launches a real server subprocess, so it's excluded
from the fast `-m "not infra"` run and self-skips when the hub isn't available.
"""
from __future__ import annotations

import asyncio

import pytest

from axioma.interface.agora import AgoraAgent
from axioma.interface.agora_bridge import AgoraBridge

pytestmark = [pytest.mark.infra, pytest.mark.agora]


async def _wait_until(coro_cond, timeout: float = 10.0):
    """Poll an async predicate until it returns truthy or we time out."""
    async def _poll():
        while True:
            val = await coro_cond()
            if val:
                return val
            await asyncio.sleep(0.2)
    return await asyncio.wait_for(_poll(), timeout)


async def _axioma_messages(agent: AgoraAgent, tid: int) -> list[dict]:
    data = await agent.get_thread(tid)
    return [m for m in data["messages"]
            if m["author"]["citizen_id"] == "axioma"]


@pytest.mark.asyncio
async def test_bridge_answers_peer_message(agora_server) -> None:
    base = agora_server["base"]
    pw = agora_server["password"]

    async def responder(speaker: str, content: str) -> str:
        return f"echo:{content}"

    thea = AgoraAgent(base, "thea", pw, name="thea")
    bridge = AgoraBridge(
        ctx=None, responder=responder, base_url=base,
        citizen_id="axioma", password=pw,
        subscribe_all=False,  # pin the exact thread below
        thread_ids=[],
    )
    try:
        await thea.start()
        tid = (await thea.create_thread("Bridge test", "(opening)", "shared"))["thread"]["id"]

        # Point the bridge at the freshly-created thread, then connect.
        bridge._thread_ids = [tid]
        await bridge.start()
        await asyncio.sleep(0.5)  # let both subscriptions register

        posted = await thea.say(tid, "hello", "shared")

        # The bridge should post exactly one reply: "echo:hello", threaded.
        msgs = await _wait_until(
            lambda: _axioma_messages(thea, tid),
            timeout=15.0,
        )
        assert len(msgs) == 1, f"expected exactly one axioma reply, got {msgs}"
        reply = msgs[0]
        assert reply["body"] == "echo:hello"
        assert reply["visibility"] == "shared"          # inherited tier
        assert reply["parent_id"] == posted["id"]        # threaded to thea's msg

        # And it must NOT answer its own broadcast — still exactly one axioma msg.
        await asyncio.sleep(1.0)
        again = await _axioma_messages(thea, tid)
        assert len(again) == 1, f"bridge replied to itself (echo storm): {again}"
    finally:
        await bridge.stop()
        try:
            await thea.logout()
        except Exception:
            pass
        await thea.aclose()
