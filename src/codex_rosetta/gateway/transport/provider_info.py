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

from collections.abc import Callable

# Type alias for auth-header builder callables
AuthHeaderFn = Callable[[str], dict[str, str]]


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
        api_key: str,
        base_url: str,
        auth_header_fn: AuthHeaderFn,
        url_template: str,
        stream_url_template: str | None = None,
        proxy_url: str | None = None,
        allow_redirects: bool = False,
        soft_interrupt: bool = False,
        force_rosetta_compaction: bool = False,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(
                f"Provider '{name}': base_url must start with http:// or https://, "
                f"got '{base_url}'"
            )
        self.name = name
        self.base_url = base_url.rstrip("/")
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
