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
from urllib.parse import urlsplit, urlunsplit

from .._ordered_failover import OrderedFailoverCoordinator
from ..provider_profiles import (
    RESPONSES_REQUEST_ENCODINGS,
    ResponsesRequestEncoding,
)

# Type alias for auth-header builder callables
AuthHeaderFn = Callable[[str], dict[str, str]]
CurrentBaseUrlRecorder = Callable[[str, str], Awaitable[None]]
CurrentCredentialRecorder = Callable[[str, str], Awaitable[None]]


# ---------------------------------------------------------------------------
# Provider descriptor
# ---------------------------------------------------------------------------


class ProviderInfo:
    """Runtime representation of a single configured provider.

    Encapsulates ordered credential and base-URL rings, auth-header
    construction, and upstream URL building.
    """

    def __init__(
        self,
        name: str,
        *,
        configured_id: str | None = None,
        api_key: str | None = None,
        api_keys: Sequence[tuple[str, str]] | None = None,
        current_api_key: str | None = None,
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
        request_encoding: ResponsesRequestEncoding | None = None,
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
        if api_keys is None:
            if api_key is None:
                raise ValueError("No API keys configured")
            api_keys = (("primary", api_key),)
        elif api_key is not None:
            raise ValueError("api_key and api_keys are mutually exclusive")
        normalized_credentials = tuple(
            (credential_id.strip(), credential.strip())
            for credential_id, credential in api_keys
        )
        if not normalized_credentials or any(
            not credential_id or not credential
            for credential_id, credential in normalized_credentials
        ):
            raise ValueError("No API keys configured")
        credential_ids = tuple(item[0] for item in normalized_credentials)
        if len(set(credential_ids)) != len(credential_ids):
            raise ValueError("Provider credential IDs must be unique")
        selected_credential = current_api_key or credential_ids[0]
        if selected_credential not in credential_ids:
            raise ValueError("current_api_key must be a member of api_keys")
        self._credentials = dict(normalized_credentials)
        self._credential_ring = OrderedFailoverCoordinator(
            credential_ids, selected_credential
        )
        self._record_current_credential: CurrentCredentialRecorder | None = None
        self._auth_header_fn = auth_header_fn
        self._url_template = url_template
        self._stream_url_template = stream_url_template
        self.proxy_url = proxy_url
        self.allow_redirects = allow_redirects
        self.soft_interrupt = soft_interrupt
        self.force_rosetta_compaction = force_rosetta_compaction
        if (
            request_encoding is not None
            and request_encoding not in RESPONSES_REQUEST_ENCODINGS
        ):
            raise ValueError(
                "request_encoding must be one of 'passthrough', 'identity', or 'zstd'"
            )
        self.request_encoding = request_encoding

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

    def base_url_statuses(self) -> tuple[tuple[str, str], ...]:
        """Return each configured URL and its process-local availability."""
        return self._url_ring.status_snapshot()

    async def select_base_url(self, base_url: str) -> None:
        if base_url == self.base_url:
            return
        if self._record_current_base_url is not None:
            await self._record_current_base_url(self.configured_id, base_url)
        self._url_ring.set_current(base_url)

    async def manually_select_base_url(self, base_url: str) -> None:
        """Persist a manual selection, then clear only its cooldown."""
        if base_url not in self.base_urls:
            raise ValueError("current_base_url must be a member of base_urls")
        if base_url != self.base_url and self._record_current_base_url is not None:
            await self._record_current_base_url(self.configured_id, base_url)
        self._url_ring.clear_cooldown(base_url)
        self._url_ring.set_current(base_url)

    def next_available_base_url(self, failed: str) -> str | None:
        return self._url_ring.next_available_after(failed)

    async def publish_url_rotation(self) -> None:
        await self._url_ring.publish()

    @property
    def credential_ids(self) -> tuple[str, ...]:
        """Return stable credential identifiers in configured order."""
        return self._credential_ring.candidates

    @property
    def current_credential_id(self) -> str:
        """Return the selected credential identifier without its secret."""
        return self._credential_ring.current

    def bind_current_credential_recorder(
        self, recorder: CurrentCredentialRecorder | None
    ) -> None:
        """Bind the app-owned persistence callback for credential selection."""
        self._record_current_credential = recorder

    async def wait_for_credential_rotation(self) -> None:
        await self._credential_ring.wait()

    def available_credentials(self) -> tuple[str, ...]:
        return self._credential_ring.available()

    def has_available_credential(self) -> bool:
        return bool(self._credential_ring.available())

    async def claim_credential_rotation(self, observed: str) -> bool:
        return await self._credential_ring.claim(observed)

    def mark_credential_failed(self, credential_id: str) -> None:
        self._credential_ring.mark_failed(credential_id)

    def credential_statuses(self) -> tuple[tuple[str, str], ...]:
        """Return credential IDs with process-local availability."""
        return self._credential_ring.status_snapshot()

    async def select_credential(self, credential_id: str) -> None:
        if credential_id == self.current_credential_id:
            return
        if self._record_current_credential is not None:
            await self._record_current_credential(self.configured_id, credential_id)
        self._credential_ring.set_current(credential_id)

    async def manually_select_credential(self, credential_id: str) -> None:
        """Persist a manual credential selection and clear only its cooldown."""
        if credential_id not in self.credential_ids:
            raise ValueError("current_api_key must be a member of api_keys")
        if (
            credential_id != self.current_credential_id
            and self._record_current_credential is not None
        ):
            await self._record_current_credential(self.configured_id, credential_id)
        self._credential_ring.clear_cooldown(credential_id)
        self._credential_ring.set_current(credential_id)

    def next_available_credential(self, failed: str) -> str | None:
        return self._credential_ring.next_available_after(failed)

    async def publish_credential_rotation(self) -> None:
        await self._credential_ring.publish()

    @property
    def credential_values(self) -> tuple[str, ...]:
        """Return wire credentials in configured order as a read-only view."""
        return tuple(self._credentials[item] for item in self.credential_ids)

    # -- public helpers used by the proxy -----------------------------------

    def auth_headers(self) -> dict[str, str]:
        """Return auth headers using the configured credential."""
        return self._auth_header_fn(self._credentials[self.current_credential_id])

    def upstream_url(self, model: str, *, stream: bool = False) -> str:
        """Build the upstream URL for the given model."""
        tpl = (
            self._stream_url_template
            if (stream and self._stream_url_template)
            else self._url_template
        )
        return tpl.format(base_url=self.base_url, model=model)

    def current_url_for(self, url: str) -> str:
        """Replace this Provider's configured origin with its current origin."""
        parsed = urlsplit(url)
        for candidate in self.base_urls:
            candidate_parts = urlsplit(candidate)
            candidate_path = candidate_parts.path.rstrip("/")
            if (
                parsed.scheme == candidate_parts.scheme
                and parsed.netloc == candidate_parts.netloc
                and (
                    parsed.path == candidate_path
                    or parsed.path.startswith(f"{candidate_path}/")
                )
            ):
                suffix = parsed.path[len(candidate_path) :]
                current = urlsplit(self.base_url)
                return urlunsplit(
                    (
                        current.scheme,
                        current.netloc,
                        f"{current.path.rstrip('/')}{suffix}",
                        parsed.query,
                        parsed.fragment,
                    )
                )
        raise ValueError("Passthrough URL is outside the configured Provider origins")


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
