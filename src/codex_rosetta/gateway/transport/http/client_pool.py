"""HTTP client pool — manages :class:`AsyncClient` instances.

Thin wrapper over :mod:`codex_rosetta._vendor.httpclient` that pools
``AsyncClient`` instances by proxy URL so multiple requests to the
same upstream reuse the same connection pool.
"""

from __future__ import annotations

from codex_rosetta._vendor.httpclient import AsyncClient, DEFAULT_MAX_REDIRECTS


class HttpClientPool:
    """Manages :class:`AsyncClient` instances keyed by proxy URL.

    Each unique ``proxy_url`` (including ``None`` for direct connections)
    gets its own ``AsyncClient`` with connection pooling.
    """

    def __init__(self, *, timeout: float = 300.0) -> None:
        self._clients: dict[tuple[str | None, bool], AsyncClient] = {}
        self._timeout = timeout

    def get(
        self,
        proxy_url: str | None = None,
        *,
        allow_redirects: bool = False,
    ) -> AsyncClient:
        """Get a client isolated by proxy and explicit redirect policy."""
        key = (proxy_url, allow_redirects)
        if key not in self._clients:
            self._clients[key] = AsyncClient(
                timeout=self._timeout,
                max_redirects=DEFAULT_MAX_REDIRECTS if allow_redirects else 0,
                proxy=proxy_url,
            )
        return self._clients[key]

    async def close_all(self) -> None:
        """Close all pooled HTTP clients."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
