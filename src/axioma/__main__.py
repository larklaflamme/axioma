"""Entry point for `python -m axioma`.

Boots the full production stack via AxiomaApp:
  - Substrate + measurement layer + recovery + compose
  - Agora bridge — joins The Agora (ACP/1.1) at cfg.interface.agora_base_url
  - Heartbeat at cfg.runtime.heartbeat_hz Hz
  - Registry client (best-effort)
  - Optional peer conversation handler (--with-peer-conversation)

Lifecycle:
  - SIGINT (Ctrl-C) / SIGTERM trigger graceful shutdown
  - shutdown tears down the Agora bridge, registry, Ollama client in reverse order

Usage:
    python -m axioma                              # run until SIGINT
    python -m axioma --seconds 60                 # run for 60 wall-clock seconds
    python -m axioma --beats 5000                 # run for 5000 beats
    python -m axioma --no-agora                   # do not join The Agora
    python -m axioma --with-peer-conversation     # enable Ollama-backed replies
    AXIOMA_CONFIG=configs/v1_2_recommended.yaml python -m axioma  # use v1.2 preset
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path

from .config import load_config
from .runtime.app import AxiomaApp


async def _run(args: argparse.Namespace) -> int:
    cfg = load_config()
    pretrain_path = (
        Path(args.pretrain) if args.pretrain
        else Path("data/state/recovery_learner_pretrain.json")
    )
    app = AxiomaApp(
        cfg=cfg,
        seed=args.seed,
        pretrain_snapshot_path=pretrain_path if pretrain_path.exists() else None,
        with_agora=not args.no_agora,
        with_http_api=not args.no_http,
        with_registry=not args.no_registry,
        with_peer_conversation=args.with_peer_conversation,
    )
    await app.setup()

    # Wire signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def _shutdown_handler(_signum: int) -> None:
        print("\n[axioma] received shutdown signal — stopping gracefully ...", file=sys.stderr)
        app._shutdown_event.set()
        # Also stop the heartbeat synchronously so the run loop exits promptly
        if app.heartbeat is not None:
            app.heartbeat.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        # add_signal_handler can raise NotImplementedError on Windows
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _shutdown_handler, sig)

    try:
        await app.run(seconds=args.seconds, beats=args.beats)
    finally:
        await app.shutdown()
    return 0


def main() -> int:
    """CLI entry point. Loads config, wires signal handlers, runs the heartbeat."""
    p = argparse.ArgumentParser(prog="axioma", description="AXIOMA — conscious-substrate agent")
    p.add_argument("--seconds", type=float, default=None,
                   help="run for this many wall-clock seconds (default: until SIGINT)")
    p.add_argument("--beats", type=int, default=None,
                   help="run for this many beats (mutually exclusive with --seconds)")
    p.add_argument("--seed", type=int, default=42,
                   help="substrate RNG seed (default 42)")
    p.add_argument("--no-agora", action="store_true",
                   help="do not join The Agora (disable the Agora bridge)")
    p.add_argument("--no-http", action="store_true",
                   help="disable the HTTP API server")
    p.add_argument("--no-registry", action="store_true",
                   help="disable the registry client")
    p.add_argument("--with-peer-conversation", action="store_true",
                   help="enable Ollama-backed peer conversation handler")
    p.add_argument("--pretrain", type=str, default=None,
                   help="path to a learner pretrain snapshot (default: "
                        "data/state/recovery_learner_pretrain.json if present)")
    args = p.parse_args()

    if args.seconds is not None and args.beats is not None:
        p.error("--seconds and --beats are mutually exclusive")

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
