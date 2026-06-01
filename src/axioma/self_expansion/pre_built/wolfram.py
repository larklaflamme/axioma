"""WolframServer — Wolfram|Alpha tool server (5 tools, async httpx).

Five tools spanning four Wolfram|Alpha API endpoints:

  - ``wolfram_full_query``    Full Results API (all pods, XML parsed → dict
                              + a `readable` plaintext rollup)
  - ``wolfram_short_answer``  Short Answers API (one-line factoid)
  - ``wolfram_spoken_answer`` Spoken Results API (a natural-language
                              sentence; good for explanations)
  - ``wolfram_math_verify``   Math verification (full_query + structured
                              extraction of result / numeric / alternate
                              forms / step-by-step solution when available)
  - ``wolfram_llm_query``     LLM-optimised endpoint (clean structured
                              plaintext; no XML overhead). General-purpose
                              for LLM-integrated queries.

Configuration: pass the Wolfram AppID at construction time, typically read
from the ``WOLFRAM_APPID`` env var in shell wiring. Missing AppID returns
a structured ``[ERROR] ...`` envelope on every dispatch — the rest of the
executor continues to work.

Port of /home/ubuntu/thea/data/thea/generated/wolfram_alpha.py (which is
in turn adapted from skye_v2's wolfram_mcp.py). The Thea version is async
via httpx and uses HTTPS directly so we don't pay for a 308 redirect;
both invariants preserved here.
"""
from __future__ import annotations

import contextlib
import json
import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..types import TextContent, Tool

log = logging.getLogger(__name__)


# Wolfram redirects http → https with 308; use https directly to skip the
# redirect round-trip on every call.
BASE_FULL   = "https://api.wolframalpha.com/v2/query"
BASE_SHORT  = "https://api.wolframalpha.com/v1/result"
BASE_SPOKEN = "https://api.wolframalpha.com/v1/spoken"
BASE_LLM    = "https://www.wolframalpha.com/api/v1/llm-api"


def _ok(data: Any) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=f"[ERROR] {msg}")]


# ── XML parsing helpers (Full Results API) ─────────────────────────────


def _parse_pods(xml_text: str) -> dict:
    """Parse Wolfram Full Results XML into a structured dict."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return {
            "error": f"XML parse error: {e}",
            "raw": xml_text[:500],
            "success": False,
            "pods": [],
        }

    result: dict[str, Any] = {
        "success":     root.attrib.get("success", "false") == "true",
        "error":       root.attrib.get("error", "false") == "true",
        "numpods":     int(root.attrib.get("numpods", 0)),
        "timing":      root.attrib.get("timing"),
        "pods":        [],
        "warnings":    [],
        "assumptions": [],
    }

    for w in root.findall(".//warning"):
        result["warnings"].append(dict(w.attrib))

    for a in root.findall(".//assumption"):
        result["assumptions"].append({
            "type":  a.attrib.get("type"),
            "word":  a.attrib.get("word"),
            "count": a.attrib.get("count"),
        })

    for pod in root.findall("pod"):
        pod_data: dict[str, Any] = {
            "title":   pod.attrib.get("title"),
            "scanner": pod.attrib.get("scanner"),
            "id":      pod.attrib.get("id"),
            "primary": pod.attrib.get("primary", "false") == "true",
            "subpods": [],
        }
        for subpod in pod.findall("subpod"):
            sp: dict[str, Any] = {"title": subpod.attrib.get("title", "")}
            pt = subpod.find("plaintext")
            if pt is not None and pt.text:
                sp["plaintext"] = pt.text.strip()
            img = subpod.find("img")
            if img is not None:
                sp["image_src"] = img.attrib.get("src")
                sp["image_alt"] = img.attrib.get("alt")
            pod_data["subpods"].append(sp)
        result["pods"].append(pod_data)

    return result


def _format_pods_readable(parsed: dict) -> str:
    if not parsed.get("success"):
        return "Wolfram Alpha could not interpret this query."
    lines: list[str] = []
    for pod in parsed.get("pods", []):
        title = pod.get("title", "")
        texts = [
            sp.get("plaintext", "")
            for sp in pod.get("subpods", [])
            if sp.get("plaintext")
        ]
        if texts:
            lines.append(f"=== {title} ===")
            for t in texts:
                lines.append(f"  {t}")
            lines.append("")
    return "\n".join(lines) if lines else (
        "Query succeeded but returned no plaintext results."
    )


# ── Tool definitions ───────────────────────────────────────────────────


_TOOLS: list[Tool] = [
    Tool(
        name="wolfram_full_query",
        description=(
            "Query the Wolfram|Alpha Full Results API. Returns all pods "
            "with plaintext content as a structured dict (success, pods, "
            "assumptions, warnings, plus a `readable` plaintext rollup). "
            "Use for complex multi-part queries where you want comprehensive "
            "information: definitions, alternate forms, properties, numeric "
            "approximations, plot descriptions, etc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query":      {"type": "string",  "description": "Natural-language or math query."},
                "assumption": {"type": "string",  "description": "Assumption string to resolve ambiguity."},
                "units":      {"type": "string",  "description": "'metric' or 'nonmetric'.", "default": "metric"},
                "timeout":    {"type": "integer", "description": "HTTP timeout seconds.",   "default": 12},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="wolfram_short_answer",
        description=(
            "Get a single short plaintext answer from Wolfram|Alpha. "
            "Best for quick factual lookups, simple arithmetic, and unit "
            "conversions. Returns a single line of text."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query":   {"type": "string",  "description": "Question or calculation."},
                "units":   {"type": "string",  "description": "'metric' or 'nonmetric'."},
                "timeout": {"type": "integer", "description": "HTTP timeout seconds."},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="wolfram_spoken_answer",
        description=(
            "Get a natural-language spoken-style answer from Wolfram|Alpha. "
            "Returns a sentence suitable for reading aloud. Good for "
            "explanations and narrative answers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query":   {"type": "string",  "description": "Question to answer in natural language."},
                "units":   {"type": "string",  "description": "'metric' or 'nonmetric'."},
                "timeout": {"type": "integer", "description": "HTTP timeout seconds."},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="wolfram_math_verify",
        description=(
            "Verify or evaluate a mathematical expression, equation, or "
            "identity using Wolfram|Alpha. Returns simplified result, "
            "numeric value, alternate forms, and step-by-step solution "
            "when available. Essential for rigorous mathematical work — "
            "verifying theorems, checking algebraic identities, solving "
            "equations symbolically, computing integrals/derivatives, "
            "validating statistical calculations."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "Math expression, equation, or query. E.g. "
                        "'solve x^2 - x - 1 = 0', "
                        "'integral of e^(-x^2) from -inf to inf', "
                        "'eigenvalues of {{1,1},{1,0}}', "
                        "'verify 1/phi^2 + 1/phi = 1'."
                    ),
                },
                "timeout": {"type": "integer", "description": "HTTP timeout seconds.", "default": 15},
            },
            "required": ["expression"],
        },
    ),
    Tool(
        name="wolfram_llm_query",
        description=(
            "Query Wolfram|Alpha via the LLM-optimised API endpoint. "
            "Returns clean structured plaintext with no XML overhead. "
            "Best general-purpose tool for LLM-integrated Wolfram queries. "
            "Use when you want a clean readable response without pod XML "
            "structure."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query":     {"type": "string",  "description": "Any natural-language or math query."},
                "max_chars": {"type": "integer", "description": "Max characters returned.", "default": 6800},
                "timeout":   {"type": "integer", "description": "HTTP timeout seconds.",    "default": 15},
            },
            "required": ["query"],
        },
    ),
]


# ── Server ──────────────────────────────────────────────────────────────


class WolframServer:
    """Wolfram|Alpha tool server — 5 tools across 4 API endpoints, async."""

    ALL_TOOLS = _TOOLS

    def __init__(
        self,
        appid: str = "",
        default_timeout_seconds: float = 20.0,
    ) -> None:
        self.appid = (appid or "").strip()
        self.default_timeout_seconds = float(default_timeout_seconds)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.default_timeout_seconds,
                follow_redirects=True,  # belt-and-suspenders with https BASE_*
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None

    # ── Dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, name: str, args: dict) -> list[TextContent]:
        if not self.appid:
            return _err("Wolfram disabled — WOLFRAM_APPID not set in .env")
        try:
            client = self._get_client()
            if name == "wolfram_full_query":   return await self._full_query(client, args)
            if name == "wolfram_short_answer": return await self._short_answer(client, args)
            if name == "wolfram_spoken_answer": return await self._spoken_answer(client, args)
            if name == "wolfram_math_verify":  return await self._math_verify(client, args)
            if name == "wolfram_llm_query":    return await self._llm_query(client, args)
            return _err(f"Unknown tool: {name}")
        except httpx.HTTPError as e:
            return _err(f"Wolfram API request failed: {type(e).__name__}: {e}")
        except Exception as e:
            log.exception("[WolframServer] %s raised", name)
            return _err(f"{name} failed unexpectedly: {type(e).__name__}: {e}")

    # ── Endpoint wrappers ───────────────────────────────────────────────

    async def _do_full_query(
        self,
        client: httpx.AsyncClient,
        query: str,
        *,
        assumption: str | None = None,
        units: str = "metric",
        timeout: int = 12,
    ) -> dict:
        params: dict[str, Any] = {
            "appid":  self.appid,
            "input":  query,
            "format": "plaintext",
            "output": "xml",
            "units":  units,
        }
        if assumption:
            params["assumption"] = assumption
        resp = await client.get(BASE_FULL, params=params, timeout=timeout)
        resp.raise_for_status()
        parsed = _parse_pods(resp.text)
        parsed["readable"] = _format_pods_readable(parsed)
        return parsed

    async def _full_query(
        self, client: httpx.AsyncClient, args: dict,
    ) -> list[TextContent]:
        query = (args.get("query") or "").strip()
        if not query:
            return _err("Parameter 'query' is required.")
        return _ok(await self._do_full_query(
            client, query,
            assumption=args.get("assumption"),
            units=args.get("units", "metric"),
            timeout=int(args.get("timeout", 12)),
        ))

    async def _short_answer(
        self, client: httpx.AsyncClient, args: dict,
    ) -> list[TextContent]:
        query = (args.get("query") or "").strip()
        if not query:
            return _err("Parameter 'query' is required.")
        params = {"appid": self.appid, "i": query,
                  "units": args.get("units", "metric")}
        resp = await client.get(
            BASE_SHORT, params=params, timeout=int(args.get("timeout", 10)),
        )
        if resp.status_code == 501:
            return _ok("Wolfram Alpha could not compute a short answer for this query.")
        resp.raise_for_status()
        return _ok(resp.text.strip())

    async def _spoken_answer(
        self, client: httpx.AsyncClient, args: dict,
    ) -> list[TextContent]:
        query = (args.get("query") or "").strip()
        if not query:
            return _err("Parameter 'query' is required.")
        params = {"appid": self.appid, "i": query,
                  "units": args.get("units", "metric")}
        resp = await client.get(
            BASE_SPOKEN, params=params, timeout=int(args.get("timeout", 10)),
        )
        if resp.status_code == 501:
            return _ok("Wolfram Alpha could not generate a spoken answer for this query.")
        resp.raise_for_status()
        return _ok(resp.text.strip())

    async def _math_verify(
        self, client: httpx.AsyncClient, args: dict,
    ) -> list[TextContent]:
        expression = (args.get("expression") or "").strip()
        if not expression:
            return _err("Parameter 'expression' is required.")
        parsed = await self._do_full_query(
            client, expression, timeout=int(args.get("timeout", 15)),
        )
        out: dict[str, Any] = {
            "result":          None,
            "numeric":         None,
            "alternate_forms": [],
            "solution":        None,
            "success":         parsed.get("success", False),
            "readable":        parsed.get("readable", ""),
        }
        for pod in parsed.get("pods", []):
            title = (pod.get("title") or "").lower()
            texts = [
                sp.get("plaintext", "")
                for sp in pod.get("subpods", [])
                if sp.get("plaintext")
            ]
            if not texts:
                continue
            if pod.get("primary") or title in (
                "result", "results", "solution", "value",
                "exact result", "decimal approximation",
            ):
                if out["result"] is None:
                    out["result"] = texts[0]
            if "decimal" in title or "numeric" in title or "approximation" in title:
                out["numeric"] = texts[0]
            if "alternate" in title or "form" in title:
                out["alternate_forms"].extend(texts)
            if "step" in title or "solution" in title:
                out["solution"] = "\n".join(texts)
        # Fallback: if no labelled result, grab the first non-empty plaintext.
        if out["result"] is None:
            for pod in parsed.get("pods", []):
                for sp in pod.get("subpods", []):
                    if sp.get("plaintext"):
                        out["result"] = sp["plaintext"]
                        break
                if out["result"]:
                    break
        return _ok(out)

    async def _llm_query(
        self, client: httpx.AsyncClient, args: dict,
    ) -> list[TextContent]:
        query = (args.get("query") or "").strip()
        if not query:
            return _err("Parameter 'query' is required.")
        params = {
            "appid":    self.appid,
            "input":    query,
            "maxchars": int(args.get("max_chars", 6800)),
        }
        resp = await client.get(
            BASE_LLM, params=params, timeout=int(args.get("timeout", 15)),
        )
        if resp.status_code == 501:
            return _ok("Wolfram Alpha could not process this query.")
        resp.raise_for_status()
        return _ok(resp.text.strip())


__all__ = ["WolframServer"]
