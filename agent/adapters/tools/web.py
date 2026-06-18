"""Opt-in network tools (--net): web search (DuckDuckGo) and article fetch.
The only tools that leave the machine. Each returns (output, is_error).
"""

import re

import httpx

from ...config import _truncate


def web_search(query: str, max_results: int = 5) -> tuple[str, bool]:
    try:
        from ddgs import DDGS
    except ImportError:
        return "web search unavailable (pip install ddgs)", True
    n = max(1, min(int(max_results or 5), 10))
    results = list(DDGS().text(query, max_results=n))
    if not results:
        return f"no results for {query!r}", False
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('href', '')}\n   {r.get('body', '')}")
    return _truncate("\n\n".join(lines)), False


def web_fetch(url: str) -> tuple[str, bool]:
    try:
        import trafilatura
    except ImportError:
        return "web fetch unavailable (pip install trafilatura)", True
    try:
        resp = httpx.get(
            url, follow_redirects=True, timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (kas agent)"},
        )
        resp.raise_for_status()
    except Exception as exc:
        return f"fetch failed: {type(exc).__name__}: {exc}", True
    text = trafilatura.extract(resp.text, include_links=False) or ""
    if not text.strip():
        # fall back to a crude tag strip if extraction found no article body
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return f"no readable content at {url}", True
    return _truncate(f"[{url}]\n\n{text}"), False
