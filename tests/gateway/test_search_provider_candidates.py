"""Tests for pure web-search candidate construction."""

from dataclasses import FrozenInstanceError

import pytest

from codex_rosetta.gateway.search_provider_candidates import (
    ConfiguredResponsesSearchProviderCandidate,
    SelfHostedSearchProviderCandidate,
    TavilySearchProviderCandidate,
    build_search_provider_candidates,
)
from codex_rosetta.gateway.search_provider_contract import (
    GPT_PASSTHROUGH_CONTRACT,
    SELF_HOSTED_LOCAL_CONTRACT,
    TAVILY_LOCAL_CONTRACT,
    SearchProviderCapability,
    SearchProviderContract,
    SearchProviderExecutionMode,
    SearchProviderFamily,
    contract_for_wire_provider,
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
    assert [candidate.contract for candidate in candidates] == [
        TAVILY_LOCAL_CONTRACT,
        GPT_PASSTHROUGH_CONTRACT,
        SELF_HOSTED_LOCAL_CONTRACT,
        SELF_HOSTED_LOCAL_CONTRACT,
        SELF_HOSTED_LOCAL_CONTRACT,
    ]
    assert candidates[1].safe_view() == {
        "id": "responses",
        "provider": "configured_responses_provider",
        "family": "gpt_passthrough",
        "execution_mode": "alpha_search_passthrough",
    }
    assert candidates[1].provider_info is upstream
    assert _build([]) == ()
    with pytest.raises(FrozenInstanceError):
        candidates[0].row_id = "changed"


@pytest.mark.parametrize(
    ("wire_provider", "contract"),
    [
        ("configured_responses_provider", GPT_PASSTHROUGH_CONTRACT),
        ("tavily", TAVILY_LOCAL_CONTRACT),
        ("self_hosted_google", SELF_HOSTED_LOCAL_CONTRACT),
        ("self_hosted_bing", SELF_HOSTED_LOCAL_CONTRACT),
        ("self_hosted_bing_browser", SELF_HOSTED_LOCAL_CONTRACT),
    ],
)
def test_persisted_wire_provider_maps_to_one_typed_contract(wire_provider, contract):
    assert contract_for_wire_provider(wire_provider) is contract


def test_provider_contracts_declare_only_their_supported_semantics():
    assert GPT_PASSTHROUGH_CONTRACT.family is SearchProviderFamily.GPT_PASSTHROUGH
    assert (
        GPT_PASSTHROUGH_CONTRACT.execution_mode
        is SearchProviderExecutionMode.ALPHA_SEARCH_PASSTHROUGH
    )
    assert GPT_PASSTHROUGH_CONTRACT.capabilities == {
        SearchProviderCapability.FULL_WEB_RUN_PASSTHROUGH
    }

    local_capabilities = {
        SearchProviderCapability.SEARCH_QUERY,
        SearchProviderCapability.DOMAIN_FILTER,
        SearchProviderCapability.MULTI_QUERY,
        SearchProviderCapability.NORMALIZED_RESULTS,
        SearchProviderCapability.REFERENCE_STORAGE,
    }
    for contract, family in (
        (TAVILY_LOCAL_CONTRACT, SearchProviderFamily.TAVILY_LOCAL),
        (SELF_HOSTED_LOCAL_CONTRACT, SearchProviderFamily.SELF_HOSTED_LOCAL),
    ):
        assert contract.family is family
        assert (
            contract.execution_mode is SearchProviderExecutionMode.LOCAL_QUERY_ADAPTER
        )
        assert contract.capabilities == local_capabilities


@pytest.mark.parametrize(
    "factory",
    [
        lambda: contract_for_wire_provider("self_hosted_unknown"),
        lambda: SearchProviderContract.create(
            "unknown", "local_query_adapter", ["search_query"]
        ),
        lambda: SearchProviderContract.create(
            "tavily_local", "unknown", ["search_query"]
        ),
        lambda: SearchProviderContract.create(
            "tavily_local", "local_query_adapter", ["unknown"]
        ),
        lambda: SearchProviderContract.create(
            "tavily_local", "local_query_adapter", []
        ),
    ],
)
def test_invalid_provider_contract_inputs_fail_closed(factory):
    with pytest.raises(ValueError):
        factory()


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
            {"upstream": _provider("responses", "shared")},
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
                "one": _provider("responses", "shared"),
                "two": _provider("responses", "shared"),
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


def test_candidate_build_keeps_single_credential_stable_without_runtime_state():
    upstream = _provider("responses", "first")
    row = {
        "id": "responses",
        "provider": "configured_responses_provider",
        "responses_provider": "upstream",
        "responses_model": "gpt-5.6-luna",
    }

    candidates = _build([row], {"upstream": upstream}, {"upstream": "responses"})

    assert len(candidates) == 1
    assert upstream.auth_headers() == {"Authorization": "Bearer first"}
    assert upstream.auth_headers() == {"Authorization": "Bearer first"}
    rebuilt = _build(
        [row],
        {"upstream": _provider("responses", "first")},
        {"upstream": "responses"},
    )
    assert candidates[0].identity == rebuilt[0].identity


def test_rejects_duplicate_configured_responses_provider_by_row_id_only():
    rows = [
        {
            "id": row_id,
            "provider": "configured_responses_provider",
            "responses_provider": "upstream",
            "responses_model": "gpt-5.6-sol",
        }
        for row_id in ("first", "second")
    ]

    with pytest.raises(ValueError, match="repeat Responses provider.*second") as exc:
        _build(
            rows, {"upstream": _provider("responses", "key")}, {"upstream": "responses"}
        )

    assert "first" not in str(exc.value)


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
                {"upstream": _provider("responses", "one")},
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
