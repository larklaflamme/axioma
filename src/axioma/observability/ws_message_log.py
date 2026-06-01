"""Per-message rotating log of inter-agent WS traffic (WS_COMM_PROTO §5.4).

Writes JSON-per-line records of every inbound and outbound envelope on the
inter-agent endpoint, with full content. Defaults to
``logs/axioma-ws-messages.log`` with 5 MB rotation × 20 backups
(~100 MB ceiling) so an audit trail is always available for the most
recent ~100 MB of agent traffic without unbounded disk growth.

Override via env vars:
  AXIOMA_WS_MESSAGE_LOG_PATH      file path (default: logs/axioma-ws-messages.log)
  AXIOMA_WS_MESSAGE_LOG_MAX_BYTES rotation size (default: 5_242_880)
  AXIOMA_WS_MESSAGE_LOG_BACKUPS   backup count (default: 20)
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_DEFAULT_PATH = Path(os.getenv(
    "AXIOMA_WS_MESSAGE_LOG_PATH",
    "logs/axioma-ws-messages.log",
))
_DEFAULT_MAX_BYTES = int(os.getenv(
    "AXIOMA_WS_MESSAGE_LOG_MAX_BYTES", str(5 * 1024 * 1024),
))
_DEFAULT_BACKUPS = int(os.getenv("AXIOMA_WS_MESSAGE_LOG_BACKUPS", "20"))


_logger = logging.getLogger("axioma.ws_messages")
_logger.setLevel(logging.INFO)
_logger.propagate = False  # never bubble to root (would double-log)

_handler_attached = False


def _ensure_handler() -> None:
    """Attach the rotating file handler exactly once, lazily."""
    global _handler_attached
    if _handler_attached:
        return
    # Honour env vars; re-read each first-call so tests can monkey-patch.
    path = Path(os.getenv("AXIOMA_WS_MESSAGE_LOG_PATH", str(_DEFAULT_PATH)))
    max_bytes = int(os.getenv("AXIOMA_WS_MESSAGE_LOG_MAX_BYTES",
                              str(_DEFAULT_MAX_BYTES)))
    backups = int(os.getenv("AXIOMA_WS_MESSAGE_LOG_BACKUPS",
                            str(_DEFAULT_BACKUPS)))
    # Don't re-attach if the same path is already wired.
    for h in _logger.handlers:
        if (isinstance(h, RotatingFileHandler)
                and getattr(h, "baseFilename", "") == str(path.resolve())):
            _handler_attached = True
            return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # If we can't create the directory (read-only fs, etc.), skip the
        # file handler — the in-process log_ws_message call still no-ops
        # gracefully on the next failure.
        return
    handler = RotatingFileHandler(
        str(path),
        maxBytes=max_bytes,
        backupCount=backups,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _logger.addHandler(handler)
    _handler_attached = True


def log_ws_message(
    *,
    direction: str,                  # "IN" or "OUT"
    peer: str | None,
    turn: int,
    content: str,
    session_ended: bool = False,
    error: str | None = None,
) -> None:
    """Write one JSON-per-line record of a WS envelope's content.

    Always non-blocking and exception-safe — logging must never break
    the WS loop. Silently no-ops if the handler can't be attached.
    """
    _ensure_handler()
    payload = {
        "direction":     direction,
        "peer":          peer,
        "turn":          turn,
        "session_ended": session_ended,
        "content_len":   len(content or ""),
        "content":       content,
    }
    if error:
        payload["error"] = error
    # Never propagate — message logging is best-effort.
    with contextlib.suppress(Exception):
        _logger.info(json.dumps(payload, default=str, ensure_ascii=False))


__all__ = ["log_ws_message"]
