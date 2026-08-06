"""Pure construction of validated web-search provider candidates."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from codex_rosetta.observability.redaction import secret_fingerprint

if TYPE_CHECKING:
    from .transport.provider_info import ProviderInfo

CONFIGURED_RESPONSES_PROVIDER = "configured_responses_provider"
SELF_HOSTED_PROVIDERS = frozenset(
    {"self_hosted_google", "self_hosted_bing", "self_hosted_bing_browser"}
)


def _safe_view(row_id: str, provider: str) -> dict[str, str]:
    return {"id": row_id, "provider": provider}


@dataclass(frozen=True, slots=True)
class TavilySearchProviderCandidate:
    """One Tavily row with its bound credential hidden from representation."""

    row_id: str
    provider: Literal["tavily"] = "tavily"
    api_key: str = field(repr=False, compare=False, default="")
    identity: str = field(repr=False, default="")

    def safe_view(self) -> dict[str, str]:
        """Return the candidate fields safe for diagnostic serialization."""
        return _safe_view(self.row_id, self.provider)


@dataclass(frozen=True, slots=True)
class ConfiguredResponsesSearchProviderCandidate:
    """One configured Responses row bound to an enabled runtime provider."""

    row_id: str
    responses_provider: str
    responses_model: str
    provider_info: ProviderInfo = field(repr=False, compare=False)
    provider: Literal["configured_responses_provider"] = "configured_responses_provider"
    identity: str = field(repr=False, default="")

    def safe_view(self) -> dict[str, str]:
        """Return the candidate fields safe for diagnostic serialization."""
        return _safe_view(self.row_id, self.provider)


@dataclass(frozen=True, slots=True)
class SelfHostedSearchProviderCandidate:
    """One credential-free self-hosted provider row."""

    row_id: str
    provider: Literal[
        "self_hosted_google", "self_hosted_bing", "self_hosted_bing_browser"
    ]
    identity: str = field(repr=False, default="")

    def safe_view(self) -> dict[str, str]:
        """Return the candidate fields safe for diagnostic serialization."""
        return _safe_view(self.row_id, self.provider)


type SearchProviderCandidate = (
    TavilySearchProviderCandidate
    | ConfiguredResponsesSearchProviderCandidate
    | SelfHostedSearchProviderCandidate
)
type SelfHostedProviderType = Literal[
    "self_hosted_google", "self_hosted_bing", "self_hosted_bing_browser"
]


def _identity_domain(
    row: Mapping[str, Any],
    *,
    provider_info: ProviderInfo | None = None,
) -> str:
    public_config = {
        key: value for key, value in row.items() if key != "tavily_api_key"
    }
    transport_config = (
        {
            "name": provider_info.name,
            "base_url": provider_info.base_url,
            "proxy_url": provider_info.proxy_url,
            "allow_redirects": provider_info.allow_redirects,
        }
        if provider_info is not None
        else None
    )
    return json.dumps(
        ["codex-rosetta.web-search-candidate.v1", public_config, transport_config],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _overlap_error(first_row_id: str, second_row_id: str) -> ValueError:
    return ValueError(
        "config: web search provider rows "
        f"{first_row_id!r} and {second_row_id!r} use overlapping credentials"
    )


def _configured_responses_candidate(
    row: Mapping[str, Any],
    row_id: str,
    providers: Mapping[str, ProviderInfo],
    provider_api_types: Mapping[str, str],
    allowed_responses_models: Collection[str],
    seen_providers: set[str],
) -> tuple[ConfiguredResponsesSearchProviderCandidate, tuple[str, ...]]:
    """Build one configured Responses candidate and validate its dependency."""
    provider_name = str(row["responses_provider"])
    if provider_name in seen_providers:
        raise ValueError(
            "config: web search provider rows must not repeat Responses "
            f"provider {provider_name!r}; duplicate row {row_id!r}"
        )
    seen_providers.add(provider_name)
    provider_info = providers.get(provider_name)
    if provider_info is None:
        raise ValueError(
            "config: web search provider row "
            f"{row_id!r} must name an enabled Responses provider"
        )
    if provider_api_types.get(provider_name) != "responses":
        raise ValueError(
            "config: web search provider row "
            f"{row_id!r} must name a provider with api_type 'responses'"
        )
    responses_model = str(row["responses_model"])
    if responses_model not in allowed_responses_models:
        raise ValueError(
            "config: web search provider row "
            f"{row_id!r} has an unsupported Responses model"
        )
    credentials = provider_info.credential_values
    if len(credentials) != 1:
        raise ValueError(
            "config: web search provider row "
            f"{row_id!r} must resolve exactly one provider credential"
        )
    return (
        ConfiguredResponsesSearchProviderCandidate(
            row_id=row_id,
            responses_provider=provider_name,
            responses_model=responses_model,
            provider_info=provider_info,
            identity=secret_fingerprint(
                _identity_domain(row, provider_info=provider_info), credentials
            ),
        ),
        credentials,
    )


def _self_hosted_candidate(
    row: Mapping[str, Any],
    row_id: str,
    provider_type: str,
    seen_provider_types: set[str],
) -> SelfHostedSearchProviderCandidate:
    """Build one credential-free candidate and enforce type uniqueness."""
    if provider_type not in SELF_HOSTED_PROVIDERS:
        raise ValueError(
            f"config: web search provider row {row_id!r} has an unknown type"
        )
    if provider_type in seen_provider_types:
        raise ValueError(
            "config: web search provider rows must not repeat self-hosted "
            f"type {provider_type!r}; duplicate row {row_id!r}"
        )
    seen_provider_types.add(provider_type)
    return SelfHostedSearchProviderCandidate(
        row_id=row_id,
        provider=cast(SelfHostedProviderType, provider_type),
        identity=secret_fingerprint(_identity_domain(row), ()),
    )


def build_search_provider_candidates(
    rows: Sequence[Mapping[str, Any]],
    providers: Mapping[str, ProviderInfo],
    provider_api_types: Mapping[str, str],
    *,
    allowed_responses_models: Collection[str],
) -> tuple[SearchProviderCandidate, ...]:
    """Build ordered immutable candidates and reject invalid dependencies.

    Args:
        rows: Canonical web-search provider rows in configured order.
        providers: Enabled, fully resolved runtime provider registry.
        provider_api_types: Enabled provider names mapped to configured API types.
        allowed_responses_models: Canonical Responses search model allowlist.

    Returns:
        Candidates in the exact input order.

    Raises:
        ValueError: If a dependency, model, provider uniqueness, or credential
            overlap constraint is violated.
    """
    candidates: list[SearchProviderCandidate] = []
    credential_owners: dict[str, str] = {}
    seen_self_hosted: set[str] = set()
    seen_responses_providers: set[str] = set()

    for row in rows:
        row_id = str(row["id"])
        provider_type = str(row["provider"])
        credentials: tuple[str, ...] = ()

        if provider_type == "tavily":
            api_key = str(row["tavily_api_key"])
            credentials = (api_key,)
            candidate: SearchProviderCandidate = TavilySearchProviderCandidate(
                row_id=row_id,
                api_key=api_key,
                identity=secret_fingerprint(_identity_domain(row), credentials),
            )
        elif provider_type == CONFIGURED_RESPONSES_PROVIDER:
            candidate, credentials = _configured_responses_candidate(
                row,
                row_id,
                providers,
                provider_api_types,
                allowed_responses_models,
                seen_responses_providers,
            )
        else:
            candidate = _self_hosted_candidate(
                row, row_id, provider_type, seen_self_hosted
            )

        for credential in credentials:
            owner = credential_owners.get(credential)
            if owner is not None and owner != row_id:
                raise _overlap_error(owner, row_id)
            credential_owners[credential] = row_id
        candidates.append(candidate)

    return tuple(candidates)
