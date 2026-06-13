"""Wire protocol primitives — the `Speaker` identity enum.

The in-house WebSocket wire types (channels, envelopes, handshake/error frames)
were removed when Axioma moved its communication onto The Agora (ACP/1.1). What
remains in `protocol.py` is the `Speaker` enum.
"""
from __future__ import annotations

from axioma.interface.protocol import Speaker


def test_speaker_axioma_present() -> None:
    assert Speaker.AXIOMA.value == "axioma"
    assert "axioma" in {s.value for s in Speaker}


def test_speaker_values_are_lowercase_handles() -> None:
    # Each speaker maps to a URL-safe lowercase handle (Agora citizen_id shape).
    for s in Speaker:
        assert s.value == s.value.lower()
        assert " " not in s.value


def test_speaker_known_peers() -> None:
    values = {s.value for s in Speaker}
    assert {"lark", "skye", "thea", "axioma"} <= values
