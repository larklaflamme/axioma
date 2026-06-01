"""Tests for axioma.self_expansion.pre_built.wolfram.

Three layers:
  - XML pod parser + readable-format helpers (pure)
  - Tool dispatch happy paths via mocked httpx responses (4 endpoints)
  - Error envelopes: disabled key, missing args, 501 not-computable,
    HTTP error responses
  - math_verify's structured extraction (result / numeric / alternate_forms / solution)
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from axioma.self_expansion.pre_built.wolfram import (
    WolframServer,
    _format_pods_readable,
    _parse_pods,
)


def _dispatch_sync(server: WolframServer, name: str, args: dict) -> str:
    blocks = asyncio.run(server._dispatch(name, args))
    return "\n".join(b.text for b in blocks)


# ── XML pod parser ──────────────────────────────────────────────────


_FULL_RESULTS_XML = """<?xml version='1.0' encoding='UTF-8'?>
<queryresult success='true' error='false' numpods='2' timing='0.5'>
  <warning text='quoted-string' />
  <assumptions count='1'>
    <assumption type='Clash' word='pi' count='2' />
  </assumptions>
  <pod title='Result' scanner='Identity' id='Result' primary='true'>
    <subpod title=''>
      <plaintext>3.14159</plaintext>
      <img src='https://example.com/pi.png' alt='pi' />
    </subpod>
  </pod>
  <pod title='Decimal approximation' scanner='Numeric' id='DecimalApproximation'>
    <subpod title='approx'>
      <plaintext>3.141592653589793...</plaintext>
    </subpod>
  </pod>
</queryresult>
"""


def test_parse_pods_extracts_structure() -> None:
    parsed = _parse_pods(_FULL_RESULTS_XML)
    assert parsed["success"] is True
    assert parsed["error"] is False
    assert parsed["numpods"] == 2
    assert parsed["timing"] == "0.5"
    assert len(parsed["pods"]) == 2

    pod0 = parsed["pods"][0]
    assert pod0["title"] == "Result"
    assert pod0["primary"] is True
    assert pod0["subpods"][0]["plaintext"] == "3.14159"
    assert pod0["subpods"][0]["image_src"] == "https://example.com/pi.png"
    assert pod0["subpods"][0]["image_alt"] == "pi"

    pod1 = parsed["pods"][1]
    assert pod1["title"] == "Decimal approximation"
    assert pod1["primary"] is False
    assert pod1["subpods"][0]["plaintext"] == "3.141592653589793..."


def test_parse_pods_handles_malformed_xml() -> None:
    parsed = _parse_pods("<not-closed-tag<<")
    assert parsed["success"] is False
    assert parsed["pods"] == []
    assert "XML parse error" in parsed["error"]


def test_parse_pods_collects_assumptions_and_warnings() -> None:
    parsed = _parse_pods(_FULL_RESULTS_XML)
    assert len(parsed["assumptions"]) == 1
    assert parsed["assumptions"][0]["word"] == "pi"
    assert len(parsed["warnings"]) == 1


def test_format_pods_readable_emits_per_pod_blocks() -> None:
    parsed = _parse_pods(_FULL_RESULTS_XML)
    readable = _format_pods_readable(parsed)
    assert "=== Result ===" in readable
    assert "3.14159" in readable
    assert "=== Decimal approximation ===" in readable
    assert "3.141592653589793..." in readable


def test_format_pods_readable_on_failed_query() -> None:
    parsed = {"success": False, "pods": []}
    assert "could not interpret" in _format_pods_readable(parsed).lower()


def test_format_pods_readable_on_empty_success() -> None:
    parsed = {"success": True, "pods": []}
    out = _format_pods_readable(parsed)
    assert "no plaintext" in out.lower()


# ── Error envelopes ──────────────────────────────────────────────────


def test_dispatch_returns_disabled_when_no_appid() -> None:
    server = WolframServer(appid="")
    for tool in (
        "wolfram_full_query", "wolfram_short_answer", "wolfram_spoken_answer",
        "wolfram_math_verify", "wolfram_llm_query",
    ):
        out = _dispatch_sync(server, tool, {"query": "x"})
        assert "[ERROR]" in out
        assert "WOLFRAM_APPID" in out


def test_full_query_requires_query() -> None:
    server = WolframServer(appid="test")
    out = _dispatch_sync(server, "wolfram_full_query", {"query": ""})
    assert "[ERROR]" in out and "query" in out.lower()


def test_short_answer_requires_query() -> None:
    server = WolframServer(appid="test")
    out = _dispatch_sync(server, "wolfram_short_answer", {"query": ""})
    assert "[ERROR]" in out


def test_spoken_answer_requires_query() -> None:
    server = WolframServer(appid="test")
    out = _dispatch_sync(server, "wolfram_spoken_answer", {})
    assert "[ERROR]" in out


def test_math_verify_requires_expression() -> None:
    server = WolframServer(appid="test")
    out = _dispatch_sync(server, "wolfram_math_verify", {})
    assert "[ERROR]" in out and "expression" in out.lower()


def test_llm_query_requires_query() -> None:
    server = WolframServer(appid="test")
    out = _dispatch_sync(server, "wolfram_llm_query", {})
    assert "[ERROR]" in out


def test_unknown_tool_returns_error() -> None:
    server = WolframServer(appid="test")
    out = _dispatch_sync(server, "definitely_not_a_tool", {})
    assert "[ERROR]" in out and "Unknown tool" in out


# ── Mocked-httpx round trips ─────────────────────────────────────────


class _StubResponse:
    def __init__(
        self,
        *,
        text: str = "",
        status_code: int = 200,
        headers: dict | None = None,
    ) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self,  # type: ignore[arg-type]
            )


class _StubAsyncClient:
    def __init__(self, response_map: dict[str, _StubResponse]) -> None:
        # key: URL (the path part); value: canned response
        self._response_map = response_map
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append((url, kwargs))
        return self._response_map[url]

    async def aclose(self) -> None:
        pass


def _install_stub(server: WolframServer, stub: _StubAsyncClient) -> None:
    server._client = stub  # type: ignore[assignment]


_SHORT_BASE  = "https://api.wolframalpha.com/v1/result"
_SPOKEN_BASE = "https://api.wolframalpha.com/v1/spoken"
_FULL_BASE   = "https://api.wolframalpha.com/v2/query"
_LLM_BASE    = "https://www.wolframalpha.com/api/v1/llm-api"


def test_short_answer_success() -> None:
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_SHORT_BASE: _StubResponse(text="3.14159\n")})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_short_answer", {"query": "pi"})
    assert out == "3.14159"
    _url, kwargs = stub.calls[0]
    assert kwargs["params"]["appid"] == "WALPHA"
    assert kwargs["params"]["i"] == "pi"


def test_short_answer_501_returns_helpful_text() -> None:
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_SHORT_BASE: _StubResponse(text="", status_code=501)})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_short_answer", {"query": "nonsense"})
    assert "could not compute a short answer" in out
    # No exception raised even though status was 501


def test_spoken_answer_success() -> None:
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_SPOKEN_BASE: _StubResponse(text="Pi is about 3.14")})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_spoken_answer", {"query": "what is pi"})
    assert out == "Pi is about 3.14"


def test_llm_query_success() -> None:
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_LLM_BASE: _StubResponse(text="Query result text")})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_llm_query",
                        {"query": "speed of light", "max_chars": 500})
    assert out == "Query result text"
    _url, kwargs = stub.calls[0]
    assert kwargs["params"]["maxchars"] == 500
    assert kwargs["params"]["input"] == "speed of light"


def test_llm_query_501_returns_helpful_text() -> None:
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_LLM_BASE: _StubResponse(text="", status_code=501)})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_llm_query", {"query": "nonsense"})
    assert "could not process this query" in out


def test_full_query_success_returns_parsed_pods() -> None:
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_FULL_BASE: _StubResponse(text=_FULL_RESULTS_XML)})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_full_query",
                        {"query": "pi", "units": "metric", "assumption": "Clash:pi"})
    data = json.loads(out)
    assert data["success"] is True
    assert data["numpods"] == 2
    assert data["readable"].startswith("=== Result ===")
    # Verify the assumption was forwarded
    _url, kwargs = stub.calls[0]
    assert kwargs["params"]["assumption"] == "Clash:pi"
    assert kwargs["params"]["units"] == "metric"


def test_full_query_propagates_http_error_as_error_envelope() -> None:
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_FULL_BASE: _StubResponse(
        text="bad key", status_code=403,
    )})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_full_query", {"query": "x"})
    assert "[ERROR]" in out
    assert "Wolfram API request failed" in out


# ── math_verify structured extraction ────────────────────────────────


_PHI_EQ_XML = """<?xml version='1.0' encoding='UTF-8'?>
<queryresult success='true' error='false' numpods='4'>
  <pod title='Result' scanner='Identity' id='Result' primary='true'>
    <subpod title=''><plaintext>x = phi</plaintext></subpod>
  </pod>
  <pod title='Decimal approximation' scanner='Numeric' id='DecimalApproximation'>
    <subpod title=''><plaintext>x = 1.6180339887...</plaintext></subpod>
  </pod>
  <pod title='Alternate form' scanner='AlternateForm' id='AlternateForm'>
    <subpod title=''><plaintext>x = (1 + sqrt(5)) / 2</plaintext></subpod>
    <subpod title=''><plaintext>x^2 - x - 1 = 0</plaintext></subpod>
  </pod>
  <pod title='Step-by-step solution' scanner='Solve' id='Solution'>
    <subpod title=''><plaintext>Step 1: rearrange...</plaintext></subpod>
    <subpod title=''><plaintext>Step 2: apply quadratic formula</plaintext></subpod>
  </pod>
</queryresult>
"""


def test_math_verify_extracts_result_numeric_alternates_solution() -> None:
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_FULL_BASE: _StubResponse(text=_PHI_EQ_XML)})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_math_verify",
                        {"expression": "solve x^2 = x + 1"})
    data = json.loads(out)
    assert data["success"] is True
    assert data["result"] == "x = phi"
    assert data["numeric"] == "x = 1.6180339887..."
    assert "x = (1 + sqrt(5)) / 2" in data["alternate_forms"]
    assert "x^2 - x - 1 = 0" in data["alternate_forms"]
    assert "Step 1" in data["solution"]
    assert "Step 2" in data["solution"]
    # Readable rollup includes all pod content
    assert "=== Result ===" in data["readable"]
    assert "=== Alternate form ===" in data["readable"]


_MINIMAL_XML = """<?xml version='1.0' encoding='UTF-8'?>
<queryresult success='true' error='false' numpods='1'>
  <pod title='Random Output' scanner='Misc' id='X'>
    <subpod title=''><plaintext>some answer</plaintext></subpod>
  </pod>
</queryresult>
"""


def test_math_verify_fallback_grabs_first_plaintext_when_no_result_pod() -> None:
    """If no pod is labelled Result/primary, math_verify still returns the
    first non-empty plaintext as `result`."""
    server = WolframServer(appid="WALPHA")
    stub = _StubAsyncClient({_FULL_BASE: _StubResponse(text=_MINIMAL_XML)})
    _install_stub(server, stub)
    out = _dispatch_sync(server, "wolfram_math_verify", {"expression": "x"})
    data = json.loads(out)
    assert data["result"] == "some answer"
    assert data["numeric"] is None
    assert data["alternate_forms"] == []
    assert data["solution"] is None


# ── Server has the right tools registered ────────────────────────────


def test_server_advertises_five_tools() -> None:
    server = WolframServer()
    names = [t.name for t in server.ALL_TOOLS]
    assert sorted(names) == [
        "wolfram_full_query",
        "wolfram_llm_query",
        "wolfram_math_verify",
        "wolfram_short_answer",
        "wolfram_spoken_answer",
    ]
    # Every tool has a description and input schema
    for t in server.ALL_TOOLS:
        assert t.description, f"{t.name} missing description"
        assert "type" in t.inputSchema, f"{t.name} missing inputSchema.type"
