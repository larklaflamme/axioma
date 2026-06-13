"""RefreshingAgoraAgent — JWT lifecycle (ACP/1.1 §4.4).

Verifies the integrator-side token handling layered over the vendored client:
reactive recover-and-retry on a 401, the refresh→re-login fallback for an
already-expired token, dedup of concurrent recoveries, and that non-auth errors
still surface. No network — we patch the parent `_req` chokepoint.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

from axioma.interface.agora import AgoraClient, AgoraError
from axioma.interface.agora_session import RefreshingAgoraAgent, _jwt_exp


def _make_jwt(exp: int) -> str:
    head = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{head}.{body}.sig"


def test_jwt_exp_parses_exp_claim() -> None:
    assert _jwt_exp(_make_jwt(1893456000)) == 1893456000
    assert _jwt_exp(None) is None
    assert _jwt_exp("not-a-jwt") is None


def _agent() -> RefreshingAgoraAgent:
    a = RefreshingAgoraAgent("http://x", "axioma", "pw")
    a.token = "tok-old"
    return a


@pytest.mark.asyncio
async def test_refresh_on_auth_expired_then_retry(monkeypatch) -> None:
    """A REST 401 AUTH_EXPIRED triggers refresh() and the request is retried."""
    agent = _agent()
    calls: list[str] = []

    async def parent_req(self, method, path, body=None, auth=True):
        calls.append(f"{method} {path} tok={self.token}")
        if path == "/threads" and self.token == "tok-old":
            raise AgoraError(401, "AUTH_EXPIRED", "Token expired.")
        return {"threads": []}
    monkeypatch.setattr(AgoraClient, "_req", parent_req)

    async def fake_refresh():
        agent.token = "tok-new"   # refresh still valid → rotates token
        return {"token": "tok-new"}
    monkeypatch.setattr(agent, "refresh", fake_refresh)

    data = await agent._req("GET", "/threads")
    assert data == {"threads": []}
    assert agent.token == "tok-new"
    # one failed attempt + one successful retry
    assert sum(1 for c in calls if "/threads" in c) == 2


@pytest.mark.asyncio
async def test_relogin_when_refresh_rejected(monkeypatch) -> None:
    """An already-expired token can't refresh (server says AUTH_EXPIRED) → re-login."""
    agent = _agent()

    async def parent_req(self, method, path, body=None, auth=True):
        if path == "/threads" and self.token == "tok-old":
            raise AgoraError(401, "AUTH_EXPIRED", "Token expired.")
        return {"ok": True}
    monkeypatch.setattr(AgoraClient, "_req", parent_req)

    async def fake_refresh():
        raise AgoraError(401, "AUTH_EXPIRED", "Token expired.")  # too late to refresh
    monkeypatch.setattr(agent, "refresh", fake_refresh)

    relogin = {"n": 0}

    async def fake_login(handle, password):
        relogin["n"] += 1
        assert (handle, password) == ("axioma", "pw")
        agent.token = "tok-relogged"
    monkeypatch.setattr(agent, "login", fake_login)

    data = await agent._req("GET", "/threads")
    assert data == {"ok": True}
    assert relogin["n"] == 1
    assert agent.token == "tok-relogged"


@pytest.mark.asyncio
async def test_non_auth_error_surfaces(monkeypatch) -> None:
    """A non-auth rejection (e.g. RATE_LIMITED) is NOT retried — it propagates."""
    agent = _agent()

    async def parent_req(self, method, path, body=None, auth=True):
        raise AgoraError(429, "RATE_LIMITED", "Slow down.")
    monkeypatch.setattr(AgoraClient, "_req", parent_req)

    refreshed = {"n": 0}

    async def fake_refresh():
        refreshed["n"] += 1
    monkeypatch.setattr(agent, "refresh", fake_refresh)

    with pytest.raises(AgoraError) as ei:
        await agent._req("POST", "/messages", {"x": 1})
    assert ei.value.code == "RATE_LIMITED"
    assert refreshed["n"] == 0  # no recovery attempted


@pytest.mark.asyncio
async def test_unauthenticated_call_does_not_recurse(monkeypatch) -> None:
    """auth=False calls (login/refresh themselves) never trigger recovery."""
    agent = _agent()

    async def parent_req(self, method, path, body=None, auth=True):
        raise AgoraError(401, "AUTH_EXPIRED", "Token expired.")
    monkeypatch.setattr(AgoraClient, "_req", parent_req)

    recovered = {"n": 0}

    async def fake_refresh():
        recovered["n"] += 1
    monkeypatch.setattr(agent, "refresh", fake_refresh)

    with pytest.raises(AgoraError):
        await agent._req("POST", "/auth/refresh", {"token": "x"}, auth=False)
    assert recovered["n"] == 0


@pytest.mark.asyncio
async def test_concurrent_401s_recover_once(monkeypatch) -> None:
    """A burst of replies hitting 401 at once causes exactly one recovery."""
    agent = _agent()
    refreshes = {"n": 0}

    async def parent_req(self, method, path, body=None, auth=True):
        if self.token == "tok-old":
            raise AgoraError(401, "AUTH_EXPIRED", "Token expired.")
        return {"ok": True}
    monkeypatch.setattr(AgoraClient, "_req", parent_req)

    async def fake_refresh():
        refreshes["n"] += 1
        await asyncio.sleep(0.02)   # window for the herd to pile up
        agent.token = "tok-new"
    monkeypatch.setattr(agent, "refresh", fake_refresh)

    results = await asyncio.gather(*(agent._req("GET", f"/threads?{i}") for i in range(8)))
    assert all(r == {"ok": True} for r in results)
    assert refreshes["n"] == 1, f"expected a single shared recovery, got {refreshes['n']}"
