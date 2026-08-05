"""Tests for pure web-search candidate construction."""

from dataclasses import FrozenInstanceError

import pytest

from codex_rosetta.gateway.search_provider_candidates import (
    ConfiguredResponsesSearchProviderCandidate,
    SelfHostedSearchProviderCandidate,
    TavilySearchProviderCandidate,
    build_search_provider_candidates,
)
from codex_rosetta.gateway.transport.provider_info import ProviderInfo, openai_auth

ALLOWED_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")


def _provider(
    name: str,
    keys: str,
    *,
    base_url: str = "https://upstream.example/v1",
    proxy_url: str | None = None,
    allow_redirects: bool = False,
) -> ProviderInfo:
    return ProviderInfo(
        name,
        api_key=keys,
        base_url=base_url,
        auth_header_fn=openai_auth,
        url_template="{base_url}/responses",
        proxy_url=proxy_url,
        allow_redirects=allow_redirects,
    )


def _build(rows, providers=None, api_types=None):
    return build_search_provider_candidates(
        rows,
        providers or {},
        api_types or {},
        allowed_responses_models=ALLOWED_MODELS,
    )


def test_builds_mixed_candidates_in_exact_order_and_empty_is_immutable():
    upstream = _provider("responses", "responses-key")
    rows = [
        {"id": "tavily", "provider": "tavily", "tavily_api_key": "tvly-key"},
        {
            "id": "responses",
            "provider": "configured_responses_provider",
            "responses_provider": "upstream",
            "responses_model": "gpt-5.6-terra",
        },
        {"id": "google", "provider": "self_hosted_google"},
        {"id": "bing", "provider": "self_hosted_bing"},
        {"id": "browser", "provider": "self_hosted_bing_browser"},
    ]

    candidates = _build(rows, {"upstream": upstream}, {"upstream": "responses"})

    assert isinstance(candidates, tuple)
    assert [candidate.row_id for candidate in candidates] == [
        "tavily",
        "responses",
        "google",
        "bing",
        "browser",
    ]
    assert isinstance(candidates[0], TavilySearchProviderCandidate)
    assert isinstance(candidates[1], ConfiguredResponsesSearchProviderCandidate)
    assert all(
        isinstance(candidate, SelfHostedSearchProviderCandidate)
        for candidate in candidates[2:]
    )
    assert candidates[1].provider_info is upstream
    assert _build([]) == ()
    with pytest.raises(FrozenInstanceError):
        candidates[0].row_id = "changed"


@pytest.mark.parametrize(
    ("providers", "api_types", "message"),
    [
        ({}, {}, "enabled Responses provider"),
        ({"upstream": _provider("responses", "key")}, {"upstream": "chat"}, "api_type"),
    ],
)
def test_rejects_missing_disabled_or_non_responses_dependencies(
    providers, api_types, message
):
    row = {
        "id": "responses-row",
        "provider": "configured_responses_provider",
        "responses_provider": "upstream",
        "responses_model": "gpt-5.6-sol",
    }

    with pytest.raises(ValueError, match=message) as exc_info:
        _build([row], providers, api_types)

    assert "responses-row" in str(exc_info.value)


def test_rejects_model_outside_shared_allowlist():
    row = {
        "id": "responses-row",
        "provider": "configured_responses_provider",
        "responses_provider": "upstream",
        "responses_model": "gpt-unsupported",
    }

    with pytest.raises(ValueError, match="unsupported Responses model"):
        _build(
            [row],
            {"upstream": _provider("responses", "key")},
            {"upstream": "responses"},
        )


@pytest.mark.parametrize(
    "rows,providers,api_types",
    [
        (
            [
                {"id": "first", "provider": "tavily", "tavily_api_key": "shared"},
                {"id": "second", "provider": "tavily", "tavily_api_key": "shared"},
            ],
            {},
            {},
        ),
        (
            [
                {"id": "first", "provider": "tavily", "tavily_api_key": "shared"},
                {
                    "id": "second",
                    "provider": "configured_responses_provider",
                    "responses_provider": "upstream",
                    "responses_model": "gpt-5.6-sol",
                },
            ],
            {"upstream": _provider("responses", "other,shared")},
            {"upstream": "responses"},
        ),
        (
            [
                {
                    "id": "first",
                    "provider": "configured_responses_provider",
                    "responses_provider": "one",
                    "responses_model": "gpt-5.6-sol",
                },
                {
                    "id": "second",
                    "provider": "configured_responses_provider",
                    "responses_provider": "two",
                    "responses_model": "gpt-5.6-terra",
                },
            ],
            {
                "one": _provider("responses", "first,shared"),
                "two": _provider("responses", "shared,second"),
            },
            {"one": "responses", "two": "responses"},
        ),
    ],
)
def test_rejects_every_remote_credential_overlap_without_leaking_secret(
    rows, providers, api_types
):
    with pytest.raises(ValueError, match="first.*second") as exc_info:
        _build(rows, providers, api_types)

    message = str(exc_info.value)
    assert "shared" not in message
    assert "hmac-sha256" not in message


def test_deduplicates_one_provider_key_ring_without_advancing_or_expanding_rows():
    upstream = _provider("responses", "first,second,first")
    row = {
        "id": "responses",
        "provider": "configured_responses_provider",
        "responses_provider": "upstream",
        "responses_model": "gpt-5.6-luna",
    }

    candidates = _build([row], {"upstream": upstream}, {"upstream": "responses"})

    assert len(candidates) == 1
    assert upstream.auth_headers() == {"Authorization": "Bearer first"}
    assert upstream.auth_headers() == {"Authorization": "Bearer second"}
    deduplicated = _provider("responses", "first,second")
    rebuilt = _build([row], {"upstream": deduplicated}, {"upstream": "responses"})
    assert candidates[0].identity == rebuilt[0].identity


@pytest.mark.parametrize(
    "changed_provider",
    [
        _provider("responses", "key", base_url="https://other.example/v1"),
        _provider("responses", "key", proxy_url="http://proxy.example:8080"),
        _provider("responses", "key", allow_redirects=True),
    ],
)
def test_responses_identity_binds_effective_transport_configuration(changed_provider):
    row = {
        "id": "responses",
        "provider": "configured_responses_provider",
        "responses_provider": "upstream",
        "responses_model": "gpt-5.6-sol",
    }
    baseline = _build(
        [row],
        {"upstream": _provider("responses", "key")},
        {"upstream": "responses"},
    )[0]
    equivalent = _build(
        [row],
        {"upstream": _provider("responses", "key")},
        {"upstream": "responses"},
    )[0]
    changed = _build([row], {"upstream": changed_provider}, {"upstream": "responses"})[
        0
    ]

    assert baseline.identity == equivalent.identity
    assert baseline.identity != changed.identity


def test_allows_disjoint_remote_credentials_and_distinct_self_hosted_types():
    rows = [
        {"id": "tavily", "provider": "tavily", "tavily_api_key": "tvly"},
        {
            "id": "responses",
            "provider": "configured_responses_provider",
            "responses_provider": "upstream",
            "responses_model": "gpt-5.6-sol",
        },
        {"id": "google", "provider": "self_hosted_google"},
        {"id": "bing", "provider": "self_hosted_bing"},
    ]

    assert (
        len(
            _build(
                rows,
                {"upstream": _provider("responses", "one,two")},
                {"upstream": "responses"},
            )
        )
        == 4
    )


def test_rejects_duplicate_self_hosted_type_by_row_id_only():
    rows = [
        {"id": "first", "provider": "self_hosted_google"},
        {"id": "second", "provider": "self_hosted_google"},
    ]

    with pytest.raises(ValueError, match="second") as exc_info:
        _build(rows)

    assert "first" not in str(exc_info.value)


def test_repr_and_safe_view_do_not_expose_secrets_identity_or_provider_details():
    tavily_secret = "tvly-sensitive"
    provider_secret = "responses-sensitive"
    rows = [
        {"id": "tavily", "provider": "tavily", "tavily_api_key": tavily_secret},
        {
            "id": "responses",
            "provider": "configured_responses_provider",
            "responses_provider": "private-upstream",
            "responses_model": "gpt-5.6-sol",
        },
    ]
    candidates = _build(
        rows,
        {"private-upstream": _provider("responses", provider_secret)},
        {"private-upstream": "responses"},
    )

    for candidate in candidates:
        public = repr(candidate) + repr(candidate.safe_view())
        assert tavily_secret not in public
        assert provider_secret not in public
        assert candidate.identity not in public
        assert "private-upstream" not in repr(candidate.safe_view())
