"""Provider runtime configuration — connection info and authentication.

This module contains the data classes that describe *how* to talk to an
upstream provider at the transport level:

* :class:`ProviderInfo` — base URL, auth headers, URL templates.
* Auth header builder functions (``openai_auth``, ``anthropic_auth``,
  ``google_auth``).

Higher-level factory logic (shim resolution, config parsing) stays in
``gateway.providers``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from .._ordered_failover import OrderedFailoverCoordinator

# Type alias for auth-header builder callables
AuthHeaderFn = Callable[[str], dict[str, str]]
CurrentBaseUrlRecorder = Callable[[str, str], Awaitable[None]]


# ---------------------------------------------------------------------------
# Provider descriptor
# ---------------------------------------------------------------------------


class ProviderInfo:
    """Runtime representation of a single configured provider.

    Encapsulates one credential, base URL, auth-header construction, and
    upstream URL building.
    """

    def __init__(
        self,
        name: str,
        *,
        configured_id: str | None = None,
        api_key: str,
        base_url: str | None = None,
        base_urls: Sequence[str] | None = None,
        current_base_url: str | None = None,
        auth_header_fn: AuthHeaderFn,
        url_template: str,
        stream_url_template: str | None = None,
        proxy_url: str | None = None,
        allow_redirects: bool = False,
        soft_interrupt: bool = False,
        force_rosetta_compaction: bool = False,
    ) -> None:
        if base_urls is None:
            if base_url is None:
                raise ValueError(f"Provider '{name}': base_urls must not be empty")
            base_urls = (base_url,)
        elif base_url is not None:
            raise ValueError("base_url and base_urls are mutually exclusive")
        normalized_urls = tuple(
            self._normalize_base_url(name, url) for url in base_urls
        )
        if not normalized_urls:
            raise ValueError(f"Provider '{name}': base_urls must not be empty")
        if len(set(normalized_urls)) != len(normalized_urls):
            raise ValueError(f"Provider '{name}': base_urls must be unique")
        normalized_current = self._normalize_base_url(
            name, current_base_url or normalized_urls[0]
        )
        if normalized_current not in normalized_urls:
            raise ValueError(
                f"Provider '{name}': current_base_url must be a member of base_urls"
            )
        self.name = name
        self.configured_id = configured_id or name
        self._url_ring = OrderedFailoverCoordinator(normalized_urls, normalized_current)
        self._record_current_base_url: CurrentBaseUrlRecorder | None = None
        self._credential = api_key.strip()
        if not self._credential:
            raise ValueError("No API keys configured")
        self._auth_header_fn = auth_header_fn
        self._url_template = url_template
        self._stream_url_template = stream_url_template
        self.proxy_url = proxy_url
        self.allow_redirects = allow_redirects
        self.soft_interrupt = soft_interrupt
        self.force_rosetta_compaction = force_rosetta_compaction

    @staticmethod
    def _normalize_base_url(name: str, value: str) -> str:
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            raise ValueError(
                f"Provider '{name}': base URL must start with http:// or https://"
            )
        return value.rstrip("/")

    @property
    def base_urls(self) -> tuple[str, ...]:
        """Return the configured base-URL ring in stable order."""
        return self._url_ring.candidates

    @property
    def base_url(self) -> str:
        """Return the currently selected base URL."""
        return self._url_ring.current

    def bind_current_base_url_recorder(
        self, recorder: CurrentBaseUrlRecorder | None
    ) -> None:
        """Bind the app-owned persistence callback for automatic selection."""
        self._record_current_base_url = recorder

    async def wait_for_url_rotation(self) -> None:
        await self._url_ring.wait()

    def available_base_urls(self) -> tuple[str, ...]:
        return self._url_ring.available()

    def has_available_base_url(self) -> bool:
        return bool(self._url_ring.available())

    async def claim_url_rotation(self, observed: str) -> bool:
        return await self._url_ring.claim(observed)

    def mark_base_url_failed(self, base_url: str) -> None:
        self._url_ring.mark_failed(base_url)

    async def select_base_url(self, base_url: str) -> None:
        if base_url == self.base_url:
            return
        if self._record_current_base_url is not None:
            await self._record_current_base_url(self.configured_id, base_url)
        self._url_ring.set_current(base_url)

    def next_available_base_url(self, failed: str) -> str | None:
        return self._url_ring.next_available_after(failed)

    async def publish_url_rotation(self) -> None:
        await self._url_ring.publish()

    @property
    def credential_values(self) -> tuple[str, ...]:
        """Return the provider's single wire credential as a read-only view."""
        return (self._credential,)

    # -- public helpers used by the proxy -----------------------------------

    def auth_headers(self) -> dict[str, str]:
        """Return auth headers using the configured credential."""
        return self._auth_header_fn(self._credential)

    def upstream_url(self, model: str, *, stream: bool = False) -> str:
        """Build the upstream URL for the given model."""
        tpl = (
            self._stream_url_template
            if (stream and self._stream_url_template)
            else self._url_template
        )
        return tpl.format(base_url=self.base_url, model=model)


# ---------------------------------------------------------------------------
# Per-provider auth header builders
# ---------------------------------------------------------------------------


def openai_auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def anthropic_auth(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


def google_auth(api_key: str) -> dict[str, str]:
    return {"x-goog-api-key": api_key}
