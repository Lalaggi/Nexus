"""SearXNG-backed web search."""

from __future__ import annotations

import httpx

from ..config import CONFIG
from .base import Tool, ToolContext, ToolResult, register

PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The search query."},
        "num_results": {
            "type": "integer",
            "description": "How many results to return (1-10).",
            "minimum": 1,
            "maximum": 10,
        },
        "time_range": {
            "type": "string",
            "enum": ["day", "week", "month", "year"],
            "description": "Optional recency filter.",
        },
    },
    "required": ["query"],
}


async def search(ctx: ToolContext, args: dict) -> ToolResult:
    query = str(args.get("query", "")).strip()
    if not query:
        return ToolResult(content="A search query is required.", ok=False)
    limit = int(args.get("num_results") or CONFIG.max_search_results)
    limit = max(1, min(10, limit))
    params: dict[str, str] = {
        "q": query,
        "format": "json",
        "language": "en",
        "safesearch": "0",
        "categories": "general",
    }
    if args.get("time_range") in {"day", "week", "month", "year"}:
        params["time_range"] = str(args["time_range"])

    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            response = await client.get(f"{CONFIG.searxng_url.rstrip('/')}/search", params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        return ToolResult(
            content=f"Web search is unavailable right now ({exc}). Try again or use web_fetch on a known URL.",
            summary="Search unavailable",
            ok=False,
        )
    except ValueError:
        return ToolResult(content="Web search returned an invalid response.", ok=False)

    results = []
    for item in payload.get("results", []):
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        snippet = " ".join((item.get("content") or "").split())
        if not url or not title:
            continue
        results.append(
            {
                "title": title[:200],
                "url": url,
                "snippet": snippet[:400],
                "engine": item.get("engine", ""),
            }
        )
        if len(results) >= limit:
            break

    if not results:
        return ToolResult(
            content=f"No results found for {query!r}. Try a broader query.",
            summary="No results",
            data={"results": []},
        )

    lines = [f"Search results for {query!r}:"]
    for index, result in enumerate(results, 1):
        lines.append(f"{index}. {result['title']}\n   {result['url']}\n   {result['snippet']}")
    lines.append("\nUse web_fetch on the most relevant URLs when you need full detail.")
    return ToolResult(
        content="\n".join(lines),
        summary=f"{len(results)} results",
        data={"results": results, "query": query},
    )


register(
    Tool(
        name="web_search",
        description=(
            "Search the live web via a local SearXNG instance. Use this for current events, "
            "recent releases, prices, or any fact that may have changed. Returns titles, URLs, "
            "and snippets."
        ),
        parameters=PARAMETERS,
        handler=search,
    )
)
