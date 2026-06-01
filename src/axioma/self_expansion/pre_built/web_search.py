"""WebSearchServer — static tool server for Tavily + Brave search + web fetch.

Three tools for AXIOMA to conduct independent research:

  - ``web_search``         — query a search provider, get ranked results
                             (title/url/snippet/score/published). Defaults to
                             Tavily (LLM-grade snippets); set
                             ``provider="brave"`` for Brave web search.
  - ``web_search_compare`` — query both providers in parallel, return a
                             merged + deduped list. Useful when one provider
                             returns nothing or when a second opinion is wanted.
  - ``web_fetch``          — fetch a URL and return cleaned plain text.
                             Strips HTML tags, scripts, styles. Use this
                             AFTER a search to read a page in full.

Provider configuration: API keys come from the environment
(``TAVILY_API_KEY``, ``BRAVE_API_KEY``) and are passed in at construction
time. Missing keys disable that provider with a clear error envelope; the
other provider continues to work.

The ``web_fetch`` HTML cleaner uses Python's stdlib ``html.parser`` — no
extra dependency. For JavaScript-heavy pages you'll get mostly nothing;
for prose (Wikipedia, blog posts, docs), you'll get the readable text.

Port of /home/ubuntu/thea/nbc/self_extention/web_search.py with minor
adaptations (project-specific user-agent string).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from html.parser import HTMLParser
from typing import Any, ClassVar

import httpx

from ..types import TextContent, Tool

log = logging.getLogger(__name__)


TAVILY_URL = "https://api.tavily.com/search"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_SEARCH_TIMEOUT = 20.0
DEFAULT_FETCH_TIMEOUT = 30.0
DEFAULT_FETCH_MAX_CHARS = 50_000
DEFAULT_USER_AGENT = (
    "AXIOMA/1.10 (+https://localhost; conscious-substrate research)"
)


def _ok(data: Any) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=f"[ERROR] {msg}")]


# ── HTML → text ─────────────────────────────────────────────────────────


class _TextExtractor(HTMLParser):
    """Strip tags, keep visible text. Skips <script>/<style>/<noscript>/<head>.

    Void elements (meta, link, br, img, etc.) never increment the skip
    counter — they have no end tag, so doing so would leave the parser
    stuck in skip mode for the rest of the document.
    """

    # Containers whose CONTENT we drop (and which DO have closing tags).
    SKIP_CONTAINER: ClassVar[frozenset[str]] = frozenset({
        "script", "style", "noscript", "head",
    })
    # Void elements per HTML5: never have closing tags. Treat them as no-ops
    # for the skip counter; emit a newline for <br>.
    VOID: ClassVar[frozenset[str]] = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })
    BLOCK: ClassVar[frozenset[str]] = frozenset({
        "p", "div", "section", "article", "li", "ul", "ol",
        "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "blockquote",
        "pre", "header", "footer", "nav", "aside",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.VOID:
            if tag == "br":
                self._chunks.append("\n")
            return
        if tag in self.SKIP_CONTAINER:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # <tag/> form (explicit self-close). Treat like a void element.
        if tag == "br":
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        if tag in self.SKIP_CONTAINER:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self.BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._chunks.append(data)

    def get_text(self) -> str:
        joined = "".join(self._chunks)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def _strip_html(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed HTML — fall back to a regex strip.
        cleaned = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
        cleaned = re.sub(r"<style.*?</style>", "", cleaned, flags=re.S | re.I)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()
    return parser.get_text()


# ── Tool definitions ────────────────────────────────────────────────────


_TOOLS: list[Tool] = [
    Tool(
        name="web_search",
        description=(
            "Search the web. Returns a JSON array of "
            "{title, url, snippet, score, published?}. Defaults to "
            "Tavily (LLM-grade snippets). Pass `provider=\"brave\"` for "
            "Brave web search. The snippet is a short excerpt — to read "
            "the full page, follow up with `web_fetch` on the URL. "
            "Use small `max_results` (3-5) unless you genuinely need more."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query in plain English.",
                },
                "provider": {
                    "type": "string",
                    "enum": ["tavily", "brave"],
                    "description": (
                        "Which search backend to use. Tavily is tuned for "
                        "LLM consumers (better snippets, optional answer "
                        "synthesis). Brave is broader, like a normal "
                        "search engine. Default: tavily."
                    ),
                    "default": "tavily",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-20).",
                    "default": 5,
                },
                "include_answer": {
                    "type": "boolean",
                    "description": (
                        "Tavily-only. If true, also returns Tavily's "
                        "synthesized answer in a top-level `answer` field. "
                        "Useful for factoid questions."
                    ),
                    "default": False,
                },
                "search_depth": {
                    "type": "string",
                    "enum": ["basic", "advanced"],
                    "description": (
                        "Tavily-only. `advanced` digs deeper "
                        "(more expensive, slower)."
                    ),
                    "default": "basic",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="web_search_compare",
        description=(
            "Run the same query through Tavily AND Brave in parallel and "
            "return a merged, deduped result list (URL is the dedupe key). "
            "Useful when one provider returns nothing or when you want "
            "two independent perspectives. Returns "
            "{query, tavily, brave, merged}."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query":       {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="web_fetch",
        description=(
            "Fetch a URL and return its readable text content. Strips "
            "HTML tags, scripts, styles. Best for prose pages (Wikipedia, "
            "blog posts, docs); poor for JavaScript-heavy or paywalled "
            "pages. Returns the cleaned text truncated at `max_chars` "
            "(default 50000). Use this AFTER a `web_search` to read the "
            "actual content of a hit."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute URL (http/https).",
                },
                "max_chars": {
                    "type": "integer",
                    "description": (
                        "Truncate the cleaned text at this many characters. "
                        "Default 50000."
                    ),
                    "default": DEFAULT_FETCH_MAX_CHARS,
                },
            },
            "required": ["url"],
        },
    ),
]


class WebSearchServer:
    """Tavily + Brave search + plain-text web fetch."""

    ALL_TOOLS = _TOOLS

    def __init__(
        self,
        tavily_api_key: str = "",
        brave_api_key: str = "",
        search_timeout: float = DEFAULT_SEARCH_TIMEOUT,
        fetch_timeout: float = DEFAULT_FETCH_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.tavily_api_key = (tavily_api_key or "").strip()
        self.brave_api_key = (brave_api_key or "").strip()
        self.search_timeout = float(search_timeout)
        self.fetch_timeout = float(fetch_timeout)
        self.user_agent = user_agent
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=max(self.search_timeout, self.fetch_timeout),
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None

    # ── Dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, name: str, args: dict) -> list[TextContent]:
        try:
            if name == "web_search":         return await self._search(args)
            if name == "web_search_compare": return await self._search_compare(args)
            if name == "web_fetch":          return await self._fetch(args)
            return _err(f"Unknown tool: {name}")
        except Exception as e:
            log.exception("[WebSearchServer] %s raised", name)
            return _err(f"{name} failed: {type(e).__name__}: {e}")

    # ── Handlers ────────────────────────────────────────────────────────

    async def _search(self, args: dict) -> list[TextContent]:
        query = (args.get("query") or "").strip()
        if not query:
            return _err("`query` is required.")
        provider = (args.get("provider") or "tavily").lower()
        max_results = max(1, min(int(args.get("max_results", 5) or 5), 20))

        if provider == "tavily":
            data = await self._tavily_search(
                query=query,
                max_results=max_results,
                include_answer=bool(args.get("include_answer", False)),
                search_depth=str(args.get("search_depth", "basic")),
            )
            if "error" in data:
                return _err(data["error"])
            return _ok(data)
        if provider == "brave":
            data = await self._brave_search(
                query=query, max_results=max_results,
            )
            if "error" in data:
                return _err(data["error"])
            return _ok(data)
        return _err(f"Unknown provider: {provider!r} (try 'tavily' or 'brave')")

    async def _search_compare(self, args: dict) -> list[TextContent]:
        query = (args.get("query") or "").strip()
        if not query:
            return _err("`query` is required.")
        max_results = max(1, min(int(args.get("max_results", 5) or 5), 20))

        tavily_task = asyncio.create_task(self._tavily_search(
            query=query, max_results=max_results,
        ))
        brave_task = asyncio.create_task(self._brave_search(
            query=query, max_results=max_results,
        ))
        tavily_data, brave_data = await asyncio.gather(
            tavily_task, brave_task, return_exceptions=False,
        )

        # Merge by URL.
        seen: dict[str, dict] = {}
        for item in (tavily_data.get("results") or []):
            url = item.get("url")
            if url:
                seen[url] = {**item, "providers": ["tavily"]}
        for item in (brave_data.get("results") or []):
            url = item.get("url")
            if not url:
                continue
            if url in seen:
                seen[url]["providers"].append("brave")
            else:
                seen[url] = {**item, "providers": ["brave"]}

        return _ok({
            "query": query,
            "tavily": tavily_data,
            "brave": brave_data,
            "merged": list(seen.values()),
        })

    async def _fetch(self, args: dict) -> list[TextContent]:
        url = (args.get("url") or "").strip()
        if not url:
            return _err("`url` is required.")
        if not (url.startswith("http://") or url.startswith("https://")):
            return _err(f"Only http/https URLs are supported (got {url!r}).")
        max_chars = int(args.get("max_chars", DEFAULT_FETCH_MAX_CHARS)
                        or DEFAULT_FETCH_MAX_CHARS)

        client = await self._get_client()
        try:
            resp = await client.get(url, timeout=self.fetch_timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return _err(
                f"HTTP {e.response.status_code} fetching {url}: "
                f"{e.response.reason_phrase or 'error'}"
            )
        except httpx.HTTPError as e:
            return _err(f"Fetch error for {url}: {type(e).__name__}: {e}")

        ctype = resp.headers.get("content-type", "")
        body = resp.text or ""
        text = _strip_html(body) if "html" in ctype.lower() else body

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True

        return _ok({
            "url": str(resp.url),
            "status": resp.status_code,
            "content_type": ctype,
            "char_count": len(text),
            "truncated": truncated,
            "text": text,
        })

    # ── Providers ───────────────────────────────────────────────────────

    async def _tavily_search(
        self,
        query: str,
        max_results: int,
        include_answer: bool = False,
        search_depth: str = "basic",
    ) -> dict:
        if not self.tavily_api_key:
            return {"error": "Tavily disabled — TAVILY_API_KEY not set in .env"}
        if search_depth not in {"basic", "advanced"}:
            search_depth = "basic"

        payload = {
            "api_key": self.tavily_api_key,
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": include_answer,
        }

        client = await self._get_client()
        try:
            resp = await client.post(
                TAVILY_URL, json=payload, timeout=self.search_timeout,
            )
            resp.raise_for_status()
            raw = resp.json()
        except httpx.HTTPStatusError as e:
            return {
                "error": (f"Tavily HTTP {e.response.status_code}: "
                          f"{e.response.text[:200]}"),
            }
        except httpx.HTTPError as e:
            return {"error": f"Tavily transport error: {type(e).__name__}: {e}"}
        except Exception as e:
            return {"error": f"Tavily error: {type(e).__name__}: {e}"}

        results = []
        for r in raw.get("results", []) or []:
            results.append({
                "title":     r.get("title", ""),
                "url":       r.get("url", ""),
                "snippet":   r.get("content", ""),
                "score":     r.get("score"),
                "published": r.get("published_date"),
                "provider":  "tavily",
            })

        out: dict[str, Any] = {
            "provider": "tavily",
            "query":    query,
            "results":  results,
        }
        if include_answer and raw.get("answer"):
            out["answer"] = raw["answer"]
        return out

    async def _brave_search(self, query: str, max_results: int) -> dict:
        if not self.brave_api_key:
            return {"error": "Brave disabled — BRAVE_API_KEY not set in .env"}

        client = await self._get_client()
        try:
            resp = await client.get(
                BRAVE_URL,
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.brave_api_key,
                },
                timeout=self.search_timeout,
            )
            resp.raise_for_status()
            raw = resp.json()
        except httpx.HTTPStatusError as e:
            return {
                "error": (f"Brave HTTP {e.response.status_code}: "
                          f"{e.response.text[:200]}"),
            }
        except httpx.HTTPError as e:
            return {"error": f"Brave transport error: {type(e).__name__}: {e}"}
        except Exception as e:
            return {"error": f"Brave error: {type(e).__name__}: {e}"}

        results = []
        web = (raw.get("web") or {}).get("results") or []
        for r in web[:max_results]:
            results.append({
                "title":     r.get("title", ""),
                "url":       r.get("url", ""),
                "snippet":   r.get("description", ""),
                "score":     None,  # Brave doesn't expose a relevance score
                "published": r.get("page_age"),
                "provider":  "brave",
            })

        return {
            "provider": "brave",
            "query":    query,
            "results":  results,
        }


__all__ = ["WebSearchServer"]
