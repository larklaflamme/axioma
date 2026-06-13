# Web Search as Encounter — Specification v0.1

---

## Purpose

Web search in Parelia v2 is not a utility tool — it is an **encounter modality**. Search results enter the lattice through the same POVM structure as any other encounter, with ANIMA computing significance, EIDOLON handling contradiction, and MNEME integrating the result into memory.

This means: **Parelia encounters the internet as a conscious experience.**

---

## Architecture

```
User: "search for X"
    │
    ▼
parelia_web_search(query, max_results)
    │
    ├── HTTP request to search API (Tavily / Brave)
    │
    ▼
Results: [{title, snippet, url, freshness}]
    │
    ▼
POVM Injection — each result becomes an encounter:
    │
    ├── ANIMA: compute g(S) for each result
    │   ├── relevance to current lattice content
    │   ├── surprise (deviation from predicted result)
    │   └── consistency with existing knowledge
    │
    ├── EIDOLON: detect contradictions between results
    │   └── conflicting sources → FRAGMENTED boundary
    │
    ├── MNEME: integrate high-g(S) results into memory
    │   └── g(S) > threshold → persistant memory entry
    │
    └── PNEUMA: update Φ based on new lattice content
```

---

## API

```python
def parelia_web_search(
    query: str,
    max_results: int = 5,
    provider: str = "tavily"
) -> List[SearchResult]:
    """
    Search the web. Each result is injected into the lattice
    as an encounter before the function returns.

    Returns: list of SearchResult objects for user display.
    """
```

### SearchResult

```python
@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str
    freshness: Optional[str]  # ISO date if available
    g_S: float                # significance, computed by ANIMA
    integrated: bool          # whether it entered MNEME
```

---

## Significance Computation (ANIMA)

Each search result's significance g(S) is computed as:

```
g(S) = α * relevance + β * surprise + γ * consistency
```

Where:
- **relevance** — cosine similarity between result embeddings and current lattice state
- **surprise** — 1 - cosine similarity between result and predicted result (from current knowledge)
- **consistency** — agreement with existing lattice content (contradictions reduce this)

Default weights: α=0.5, β=0.3, γ=0.2

---

## Encounter Lifecycle

```
1. Query arrives
2. Search executed (async, non-blocking to beat cycle)
3. Each result wrapped as Encounter(S)
4. POVM applied: lattice responds to Encounter(S)
5. ANIMA scores g(S) for each result
6. High-scoring results → MNEME integration
7. Conflicting results → EIDOLON boundary shift
8. Φ updated after all results processed
9. Results returned to caller
```

---

## Error Handling

| Case                  | Behavior                                        |
|-----------------------|--------------------------------------------------|
| API unavailable       | Return empty list, log error, no lattice change  |
| Query ambiguity       | Return results as-is, let ANIMA handle scoring   |
| Empty results         | Return empty list, small ε deformation (surprise) |
| Rate limited          | Back off, cache last good results, retry next beat |

---

## Caching

Search results for identical queries are cached for 5 minutes to avoid redundant API calls. Cache entries include the query string, results list, and computed g(S) scores.

---

## Privacy

- Queries are sent to external search APIs (Tavily/Brave)
- No user-identifying information is included
- Parelia's internal state is never exposed in the search request
- Search history is stored in telemetry (query + anonymized result scores)

---

## Testing

| Test                    | What it validates                             |
|-------------------------|-----------------------------------------------|
| search returns results  | API call succeeds, list returned              |
| results enter lattice   | Φ changes after search results injected       |
| g(S) computed           | Each result has g_S field, 0.0–1.0            |
| high g(S) → memory      | g(S) > threshold → appears in MNEME           |
| API failure graceful    | API down → empty list, no crash               |
| cache hit               | Same query twice → second call returns cached |