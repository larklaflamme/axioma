"""Tests for axioma.self_expansion.pre_built.web_search.

Three layers:
  - HTML → text extractor (pure stdlib parser; unit-tested directly)
  - Tool dispatch happy paths via mocked httpx responses
  - Disabled-provider error envelope when keys are missing
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from axioma.self_expansion.pre_built.web_search import (
    WebSearchServer,
    _strip_html,
)


def _dispatch_sync(server: WebSearchServer, name: str, args: dict) -> str:
    blocks = asyncio.run(server._dispatch(name, args))
    return "\n".join(b.text for b in blocks)


# ── HTML stripper ────────────────────────────────────────────────────


def test_strip_html_drops_script_and_style() -> None:
    html = (
        "<html><head><title>T</title>"
        "<script>alert('hi')</script>"
        "<style>body { color: red }</style>"
        "</head><body><p>Visible text.</p></body></html>"
    )
    out = _strip_html(html)
    assert "Visible text." in out
    assert "alert" not in out
    assert "color: red" not in out
    assert "T" not in out  # head content also dropped


def test_strip_html_preserves_block_separation() -> None:
    html = "<p>Para one.</p><p>Para two.</p>"
    out = _strip_html(html)
    assert "Para one." in out
    assert "Para two." in out
    # The two paragraphs end up on separate lines
    assert "\n" in out


def test_strip_html_handles_void_elements_correctly() -> None:
    """Regression: void elements (img, meta, link) must NOT push the
    skip-depth counter — otherwise the parser would silently drop the
    rest of the document."""
    html = (
        "<html><head><meta charset='utf-8'><link rel='stylesheet' href='x.css'>"
        "</head><body>"
        "<img src='cat.png' alt='cat'>"
        "<p>This text MUST survive.</p>"
        "</body></html>"
    )
    out = _strip_html(html)
    assert "This text MUST survive." in out


def test_strip_html_renders_br_as_newline() -> None:
    out = _strip_html("Line1<br>Line2<br/>Line3")
    assert "Line1" in out
    assert "Line2" in out
    assert "Line3" in out


def test_strip_html_decodes_entities() -> None:
    out = _strip_html("<p>Cost: $5 &amp; €3 &mdash; cheap</p>")
    assert "Cost:" in out
    assert "&amp;" not in out  # converted
    assert "&" in out


def test_strip_html_falls_back_on_malformed() -> None:
    # Mildly malformed HTML — parser may not raise, but should still strip.
    out = _strip_html("<div><span>hi</div><script>x")
    assert "hi" in out


def test_strip_html_collapses_excess_whitespace() -> None:
    out = _strip_html("<p>a    b\t\t\tc</p><p>\n\n\n\nd</p>")
    assert "a b c" in out
    # No more than two newlines in a row
    assert "\n\n\n" not in out


# ── Provider-disabled error envelopes ────────────────────────────────


def test_web_search_missing_tavily_key_returns_disabled_error() -> None:
    server = WebSearchServer(tavily_api_key="", brave_api_key="x")
    out = _dispatch_sync(server, "web_search", {"query": "hello"})
    assert "[ERROR]" in out
    assert "TAVILY_API_KEY" in out


def test_web_search_missing_brave_key_returns_disabled_error() -> None:
    server = WebSearchServer(tavily_api_key="x", brave_api_key="")
    out = _dispatch_sync(server, "web_search",
                         {"query": "hello", "provider": "brave"})
    assert "[ERROR]" in out
    assert "BRAVE_API_KEY" in out


def test_web_search_missing_query_returns_error() -> None:
    server = WebSearchServer(tavily_api_key="x", brave_api_key="x")
    out = _dispatch_sync(server, "web_search", {"query": ""})
    assert "[ERROR]" in out
    assert "query" in out


def test_web_search_unknown_provider_returns_error() -> None:
    server = WebSearchServer(tavily_api_key="x", brave_api_key="x")
    out = _dispatch_sync(server, "web_search",
                         {"query": "x", "provider": "bing"})
    assert "[ERROR]" in out
    assert "Unknown provider" in out


def test_web_fetch_rejects_non_http_url() -> None:
    server = WebSearchServer()
    out = _dispatch_sync(server, "web_fetch", {"url": "file:///etc/hostname"})
    assert "[ERROR]" in out
    assert "http/https" in out


def test_web_fetch_requires_url() -> None:
    server = WebSearchServer()
    out = _dispatch_sync(server, "web_fetch", {"url": ""})
    assert "[ERROR]" in out
    assert "url" in out


def test_unknown_tool_returns_error() -> None:
    server = WebSearchServer()
    out = _dispatch_sync(server, "definitely_not_a_tool", {})
    assert "[ERROR]" in out


# ── Mocked-httpx happy paths ─────────────────────────────────────────


class _StubResponse:
    """Minimal httpx.Response shim."""

    def __init__(
        self,
        *,
        json_body: Any = None,
        text: str = "",
        status_code: int = 200,
        headers: dict | None = None,
        url: str = "https://example.com",
        reason_phrase: str = "OK",
    ) -> None:
        self._json = json_body
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.reason_phrase = reason_phrase

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self,  # type: ignore[arg-type]
            )


class _StubAsyncClient:
    """Stub for httpx.AsyncClient that records calls + replays canned responses."""

    def __init__(self, response_map: dict[tuple[str, str], _StubResponse]) -> None:
        # key: (method, url)
        self._response_map = response_map
        self.calls: list[tuple[str, str, dict]] = []

    async def get(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append(("GET", url, kwargs))
        return self._response_map[("GET", url)]

    async def post(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append(("POST", url, kwargs))
        return self._response_map[("POST", url)]

    async def aclose(self) -> None:
        pass


def _install_stub(server: WebSearchServer, stub: _StubAsyncClient) -> None:
    """Bypass _get_client() by pre-installing the stub on the server."""
    server._client = stub  # type: ignore[assignment]


def test_tavily_search_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    server = WebSearchServer(tavily_api_key="tvly-test")
    stub = _StubAsyncClient({
        ("POST", "https://api.tavily.com/search"): _StubResponse(json_body={
            "answer": "The capital is Paris.",
            "results": [
                {"title": "Paris - Wikipedia", "url": "https://en.wikipedia.org/wiki/Paris",
                 "content": "Paris is the capital of France.", "score": 0.95,
                 "published_date": "2024-01-15"},
                {"title": "Paris", "url": "https://example.com/paris",
                 "content": "About the city of light", "score": 0.85,
                 "published_date": None},
            ],
        }),
    })
    _install_stub(server, stub)
    out = _dispatch_sync(server, "web_search",
                         {"query": "capital of France", "max_results": 2,
                          "include_answer": True})
    data = json.loads(out)
    assert data["provider"] == "tavily"
    assert data["query"] == "capital of France"
    assert len(data["results"]) == 2
    assert data["results"][0]["title"] == "Paris - Wikipedia"
    assert data["results"][0]["snippet"] == "Paris is the capital of France."
    assert data["results"][0]["score"] == 0.95
    assert data["answer"] == "The capital is Paris."
    # Verify the request was shaped correctly
    method, url, kwargs = stub.calls[0]
    assert method == "POST" and url == "https://api.tavily.com/search"
    body = kwargs["json"]
    assert body["api_key"] == "tvly-test"
    assert body["query"] == "capital of France"
    assert body["max_results"] == 2
    assert body["include_answer"] is True


def test_brave_search_round_trip() -> None:
    server = WebSearchServer(brave_api_key="brv-test")
    stub = _StubAsyncClient({
        ("GET", "https://api.search.brave.com/res/v1/web/search"): _StubResponse(json_body={
            "web": {
                "results": [
                    {"title": "Python 3.13", "url": "https://python.org",
                     "description": "Python 3.13 release notes", "page_age": "2024-10-07"},
                    {"title": "Python docs", "url": "https://docs.python.org",
                     "description": "Official documentation", "page_age": None},
                ],
            },
        }),
    })
    _install_stub(server, stub)
    out = _dispatch_sync(server, "web_search",
                         {"query": "python 3.13", "provider": "brave",
                          "max_results": 2})
    data = json.loads(out)
    assert data["provider"] == "brave"
    assert len(data["results"]) == 2
    assert data["results"][0]["title"] == "Python 3.13"
    assert data["results"][0]["snippet"] == "Python 3.13 release notes"
    # Brave doesn't expose a score
    assert data["results"][0]["score"] is None
    method, _url, kwargs = stub.calls[0]
    assert method == "GET"
    assert kwargs["params"]["q"] == "python 3.13"
    assert kwargs["headers"]["X-Subscription-Token"] == "brv-test"


def test_web_fetch_strips_html_and_truncates() -> None:
    server = WebSearchServer()
    big_html = (
        "<html><body><p>Hello.</p>"
        + ("<p>filler</p>" * 5000)
        + "</body></html>"
    )
    stub = _StubAsyncClient({
        ("GET", "https://example.com/big"): _StubResponse(
            text=big_html,
            headers={"content-type": "text/html; charset=utf-8"},
            url="https://example.com/big",
        ),
    })
    _install_stub(server, stub)
    out = _dispatch_sync(server, "web_fetch",
                         {"url": "https://example.com/big", "max_chars": 200})
    data = json.loads(out)
    assert data["status"] == 200
    assert data["truncated"] is True
    assert data["char_count"] == 200
    assert "Hello." in data["text"]
    # HTML tags should be gone
    assert "<p>" not in data["text"]


def test_web_fetch_passes_non_html_content_through_as_is() -> None:
    """A JSON or text/plain response should not get HTML-stripped."""
    server = WebSearchServer()
    raw_json = '{"hello": "world"}'
    stub = _StubAsyncClient({
        ("GET", "https://api.example.com/info"): _StubResponse(
            text=raw_json,
            headers={"content-type": "application/json"},
            url="https://api.example.com/info",
        ),
    })
    _install_stub(server, stub)
    out = _dispatch_sync(server, "web_fetch", {"url": "https://api.example.com/info"})
    data = json.loads(out)
    assert data["text"] == raw_json


def test_search_compare_merges_results() -> None:
    """Both providers respond; merged list dedupes by URL and tags the
    `providers` field with both sources for shared URLs."""
    server = WebSearchServer(tavily_api_key="tv", brave_api_key="br")
    shared_url = "https://en.wikipedia.org/wiki/Foo"
    tavily_only_url = "https://example.com/tav"
    brave_only_url = "https://example.com/bra"
    stub = _StubAsyncClient({
        ("POST", "https://api.tavily.com/search"): _StubResponse(json_body={
            "results": [
                {"title": "Foo", "url": shared_url, "content": "T-snippet"},
                {"title": "Tavily-only", "url": tavily_only_url, "content": "T2"},
            ],
        }),
        ("GET", "https://api.search.brave.com/res/v1/web/search"): _StubResponse(
            json_body={"web": {"results": [
                {"title": "Foo", "url": shared_url, "description": "B-snippet"},
                {"title": "Brave-only", "url": brave_only_url, "description": "B2"},
            ]}}
        ),
    })
    _install_stub(server, stub)
    out = _dispatch_sync(server, "web_search_compare", {"query": "foo"})
    data = json.loads(out)
    merged = data["merged"]
    urls = {item["url"]: item for item in merged}
    assert set(urls) == {shared_url, tavily_only_url, brave_only_url}
    # Shared URL was tagged with both providers
    assert sorted(urls[shared_url]["providers"]) == ["brave", "tavily"]
    assert urls[tavily_only_url]["providers"] == ["tavily"]
    assert urls[brave_only_url]["providers"] == ["brave"]


def test_search_compare_handles_one_provider_disabled() -> None:
    """If Brave key is missing, compare still returns Tavily results +
    an error stub for Brave — no crash."""
    server = WebSearchServer(tavily_api_key="tv", brave_api_key="")
    stub = _StubAsyncClient({
        ("POST", "https://api.tavily.com/search"): _StubResponse(json_body={
            "results": [{"title": "Foo", "url": "https://x.com", "content": "s"}],
        }),
    })
    _install_stub(server, stub)
    out = _dispatch_sync(server, "web_search_compare", {"query": "foo"})
    data = json.loads(out)
    assert "BRAVE_API_KEY" in data["brave"]["error"]
    assert len(data["tavily"]["results"]) == 1
    # Merged contains only the Tavily result
    assert len(data["merged"]) == 1


def test_tavily_http_error_returned_as_envelope() -> None:
    server = WebSearchServer(tavily_api_key="tv")
    stub = _StubAsyncClient({
        ("POST", "https://api.tavily.com/search"): _StubResponse(
            json_body={}, text="invalid key", status_code=401,
            reason_phrase="Unauthorized",
        ),
    })
    _install_stub(server, stub)
    out = _dispatch_sync(server, "web_search", {"query": "x"})
    assert "[ERROR]" in out
    assert "Tavily HTTP 401" in out


def test_search_max_results_clamps_to_20() -> None:
    server = WebSearchServer(tavily_api_key="tv")
    stub = _StubAsyncClient({
        ("POST", "https://api.tavily.com/search"): _StubResponse(json_body={"results": []}),
    })
    _install_stub(server, stub)
    _dispatch_sync(server, "web_search", {"query": "x", "max_results": 999})
    body = stub.calls[0][2]["json"]
    assert body["max_results"] == 20
