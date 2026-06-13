"""RefreshingAgoraAgent — keep Axioma's Agora JWT alive (ACP/1.1 §4.4).

The vendored reference client (`agora.AgoraAgent`) auto-recovers auth only on the
*WebSocket* path (close code 4001). Its *REST* calls — `subscribe_all` →
`GET /api/threads`, `post_message` for every reply — just raise `AgoraError` on a
401, so once the 24h token expires Axioma silently stops posting:

    GET /api/threads ... 401 Unauthorized
    [401 AUTH_EXPIRED] Token expired.

This subclass adds the integrator-side token lifecycle the protocol leaves to the
client, without forking the vendored code:

  * **Proactive** (§4.4 "refresh when exp is within ~1h"): a background task
    rotates the token via `POST /api/auth/refresh` *before* it expires, so normal
    operation never trips a 401. This is the path that genuinely "uses refresh".
  * **Reactive**: a REST call that still returns `AUTH_EXPIRED` / `AUTH_REVOKED` /
    `AUTH_INVALID` triggers a one-shot recovery — try `refresh()` (works only if
    the token isn't yet expired), else full re-login — then the request is retried
    once with the fresh token. An *already-expired* token cannot be refreshed
    (the server returns `AUTH_EXPIRED`), so recovery falls back to re-login, per
    §4.4.

Concurrent failures dedupe via a lock plus a token-generation check, so a burst
of replies hitting 401 at once causes exactly one recovery, not a thundering herd.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from contextlib import suppress

from ..observability import get_logger
from .agora import AgoraAgent, AgoraError

log = get_logger(__name__)

# Auth error codes a retry can recover from (§12.1). Other codes are real
# rejections (FORBIDDEN, BAD_CREDENTIALS, …) and must surface, not retry.
_RECOVERABLE_AUTH_CODES = frozenset({"AUTH_EXPIRED", "AUTH_REVOKED", "AUTH_INVALID"})


def _jwt_exp(token: str | None) -> int | None:
    """Read the `exp` (unix seconds) claim from a JWT without verifying it.

    We only need the expiry to refresh proactively; the token stays opaque for
    auth. Returns None if the token is missing or unparseable."""
    if not token:
        return None
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # restore base64 padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


class RefreshingAgoraAgent(AgoraAgent):
    """`AgoraAgent` that refreshes its JWT proactively and on 401."""

    def __init__(self, *args, refresh_margin_seconds: float = 3600.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._auth_lock = asyncio.Lock()
        self._refresh_margin = max(60.0, float(refresh_margin_seconds))
        self._refresh_task: asyncio.Task[None] | None = None

    # -- reactive: recover + retry once on an auth 401 ------------------------
    # (vendored _req types body as `dict = None`; we mirror its call shape.)
    async def _req(self, method: str, path: str, body: dict | None = None,
                   auth: bool = True):
        token_used = self.token
        try:
            return await super()._req(method, path, body, auth)  # type: ignore[arg-type]
        except AgoraError as e:
            # Unauthenticated calls (login/refresh) and non-auth errors surface.
            if not auth or e.code not in _RECOVERABLE_AUTH_CODES:
                raise
            await self._recover_session(token_used, reason=e.code)
            return await super()._req(method, path, body, auth)  # type: ignore[arg-type]

    async def _recover_session(self, failed_token: str | None, *, reason: str) -> None:
        """Refresh (or, if too late, re-login) the session exactly once.

        Dedupes concurrent callers: whoever wins the lock recovers; the rest see
        the token has already rotated and return, then retry with the fresh one."""
        async with self._auth_lock:
            if self.token != failed_token:
                return  # another task already recovered the session
            try:
                await self.refresh()
                log.info("agora_token_refreshed", trigger=reason)
                return
            except AgoraError:
                pass  # token too old / revoked to refresh → full re-login
            await self.login(self.handle, self._password)
            log.info("agora_session_relogin", trigger=reason)

    # -- proactive: rotate the token before it expires -----------------------
    async def start(self) -> None:
        await super().start()
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._proactive_refresh_loop())

    def stop(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
        super().stop()

    async def _proactive_refresh_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                exp = _jwt_exp(self.token)
                if exp is None:
                    continue
                if exp - time.time() <= self._refresh_margin:
                    async with self._auth_lock:
                        # Re-check under the lock — a reactive recovery may have
                        # just rotated the token.
                        exp = _jwt_exp(self.token)
                        if exp is None or exp - time.time() > self._refresh_margin:
                            continue
                        try:
                            await self.refresh()
                            log.info("agora_token_refreshed", trigger="proactive")
                        except AgoraError as e:
                            # Lineage cap / already revoked → re-login.
                            with suppress(AgoraError):
                                await self.login(self.handle, self._password)
                                log.info("agora_session_relogin", trigger="proactive")
                                continue
                            log.warning("agora_proactive_refresh_failed", code=e.code)
        except asyncio.CancelledError:
            return
        except Exception:  # never let the refresh task die silently
            log.exception("agora_proactive_refresh_loop_error")


__all__ = ["RefreshingAgoraAgent"]
