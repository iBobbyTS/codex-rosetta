"""Bounded Google Search executor for the ``web-run`` sidecar."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote_plus, urlsplit

GOOGLE_SEARCH_ORIGIN = "https://www.google.com"
_MAX_RESULTS = 10
_MAX_QUERY_CHARS = 4_000
_MAX_DOMAIN_CHARS = 253
_MAX_TITLE_CHARS = 500
_MAX_URL_CHARS = 8_192
_MAX_CONTENT_CHARS = 1_200
_SEARCH_TIMEOUT_MS = 30_000

_RESULT_EXTRACTION_SCRIPT = r"""
() => {
  const output = [];
  const seen = new Set();
  for (const heading of document.querySelectorAll('#search a h3, a h3')) {
    const anchor = heading.closest('a');
    if (!anchor) continue;
    let href = anchor.href || '';
    try {
      const parsed = new URL(href, document.baseURI);
      if (parsed.hostname.endsWith('google.com') && parsed.pathname === '/url') {
        href = parsed.searchParams.get('q') || parsed.searchParams.get('url') || '';
      }
    } catch (_) {
      continue;
    }
    if (!href.startsWith('http://') && !href.startsWith('https://')) continue;
    if (seen.has(href)) continue;
    seen.add(href);

    const container = heading.closest('.MjjYud, .g, [data-snhf]')
      || anchor.parentElement?.parentElement?.parentElement;
    const title = (heading.innerText || heading.textContent || '').trim();
    let content = container
      ? (container.innerText || container.textContent || '').trim()
      : '';
    if (content.startsWith(title)) content = content.slice(title.length).trim();
    output.push({title, url: href, content});
  }
  return output;
}
"""


class GoogleSearchError(RuntimeError):
    """Stable failure returned by the self-hosted Google executor."""


def build_google_search_url(
    query: str,
    *,
    max_results: int,
    include_domains: tuple[str, ...] = (),
) -> str:
    """Build one bounded Google result URL with optional site restrictions."""
    normalized_query = query.strip()
    if not normalized_query or len(normalized_query) > _MAX_QUERY_CHARS:
        raise ValueError(f"query must contain 1-{_MAX_QUERY_CHARS} characters")
    if isinstance(max_results, bool) or not 1 <= max_results <= _MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {_MAX_RESULTS}")

    domains = tuple(_normalize_domain(value) for value in include_domains)
    effective_query = normalized_query
    if domains:
        sites = " OR ".join(f"site:{domain}" for domain in domains)
        effective_query = f"({normalized_query}) ({sites})"
    return (
        f"{GOOGLE_SEARCH_ORIGIN}/search?hl=en&filter=1"
        f"&num={max(10, max_results)}&q={quote_plus(effective_query)}"
    )


async def execute_google_search(
    browser: Any,
    *,
    query: str,
    max_results: int,
    include_domains: tuple[str, ...],
    route_handler: Callable[[Any, Any], Awaitable[None]],
) -> dict[str, Any]:
    """Search Google in an isolated browser context and normalize its results."""
    search_url = build_google_search_url(
        query,
        max_results=max_results,
        include_domains=include_domains,
    )
    allowed_domains = tuple(_normalize_domain(value) for value in include_domains)
    context = await browser.new_context(
        accept_downloads=False,
        service_workers="block",
        locale="en-US",
    )
    try:
        await context.route("**/*", route_handler)
        page = await context.new_page()
        response = await page.goto(
            search_url,
            wait_until="domcontentloaded",
            timeout=_SEARCH_TIMEOUT_MS,
        )
        if response is not None and response.status >= 400:
            raise GoogleSearchError(f"Google Search returned HTTP {response.status}")
        try:
            await page.wait_for_load_state("networkidle", timeout=3_000)
        except Exception:
            pass
        raw_results = await page.evaluate(_RESULT_EXTRACTION_SCRIPT)
        if not isinstance(raw_results, list):
            raise GoogleSearchError("Google Search returned an invalid result page")
        results = _normalize_results(
            raw_results,
            max_results=max_results,
            include_domains=allowed_domains,
        )
        if not results:
            body_text = (await page.locator("body").inner_text()).casefold()
            if any(
                marker in body_text
                for marker in (
                    "unusual traffic",
                    "not a robot",
                    "our systems have detected",
                    "before you continue to google",
                )
            ):
                raise GoogleSearchError(
                    "Google Search blocked the automated request; retry later or use Tavily"
                )
        return {"results": results}
    except asyncio.CancelledError:
        raise
    except GoogleSearchError:
        raise
    except Exception as exc:
        message = str(exc).replace("\n", " ")[:500]
        raise GoogleSearchError(f"Google Search request failed: {message}") from exc
    finally:
        await context.close()


def _normalize_results(
    raw_results: list[Any],
    *,
    max_results: int,
    include_domains: tuple[str, ...],
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = _bounded_text(item.get("title"), _MAX_TITLE_CHARS)
        url = _bounded_text(item.get("url"), _MAX_URL_CHARS)
        content = _bounded_text(item.get("content"), _MAX_CONTENT_CHARS)
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not hostname or not title:
            continue
        if hostname == "google.com" or hostname.endswith(".google.com"):
            continue
        if include_domains and not any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in include_domains
        ):
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append({"title": title, "url": url, "content": content})
        if len(results) >= max_results:
            break
    return results


def _normalize_domain(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("include_domains entries must be strings")
    domain = value.strip().lower().rstrip(".")
    labels = domain.split(".")
    if (
        not domain
        or len(domain) > _MAX_DOMAIN_CHARS
        or "://" in domain
        or "/" in domain
        or "@" in domain
        or any(not part or len(part) > 63 for part in labels)
        or any(part.startswith("-") or part.endswith("-") for part in labels)
        or any(
            not all(char.isalnum() or char == "-" for char in part) for part in labels
        )
    ):
        raise ValueError(f"invalid include_domains entry: {value!r}")
    return domain


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


__all__ = [
    "GoogleSearchError",
    "build_google_search_url",
    "execute_google_search",
]
