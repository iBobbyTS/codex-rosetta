"""Tests for gateway configuration parsing and validation."""

from __future__ import annotations

import json
import asyncio
import os
import sys
from argparse import Namespace
from uuid import UUID

import pytest

import codex_rosetta.gateway.config as gateway_config
from codex_rosetta.gateway.cli import (
    _cmd_add_provider,
    _cmd_add_model,
    _cmd_add_model_group,
    _cmd_init,
    _empty_config_template,
)
from codex_rosetta.gateway.config import (
    CODEX_HOME_ENV,
    CONFIG_DIRS_TO_TRY,
    DEFAULT_CODEX_HOME,
    DEFAULT_CONFIG_DIR,
    GatewayConfig,
    config_path_for_dir,
    default_tool_profile_for_provider,
    discover_config,
    load_config,
    resolve_codex_home,
)
from codex_rosetta.gateway.app import _rotate_model_group_after_upstream_failure
from codex_rosetta.gateway.search_provider_candidates import (
    DeepSeekNativeResponsesSearchProviderCandidate,
)
from codex_rosetta.gateway.web_run_capabilities import (
    WEB_RUN_BASIC_SEARCH_CAPABILITY,
    WEB_RUN_SIDECAR_CAPABILITY,
)
from codex_rosetta.routing import is_responses_passthrough


_PRIMARY_CREDENTIAL_UUID = "00000000-0000-4000-8000-000000000001"


def test_default_config_search_only_uses_xdg_directory() -> None:
    expected = os.path.expanduser("~/.config/codex-rosetta-gateway")

    assert DEFAULT_CONFIG_DIR == expected
    assert CONFIG_DIRS_TO_TRY == [expected]
    assert config_path_for_dir(expected) == os.path.join(expected, "config.jsonc")


def test_legacy_single_api_key_field_is_rejected() -> None:
    raw = _minimal_raw()
    raw["server"].pop("api_keys")
    raw["server"]["api_key"] = "legacy-key"

    with pytest.raises(ValueError, match="server.api_key is unsupported"):
        GatewayConfig(raw)


@pytest.mark.parametrize(
    "credential_uuid",
    [None, "", "not-a-uuid", "00000000000040008000000000000001"],
)
def test_provider_credential_uuid_must_be_present_and_canonical(
    credential_uuid: str | None,
) -> None:
    raw = _minimal_raw()
    if credential_uuid is None:
        raw["providers"]["test"]["api_keys"][0].pop("uuid")
    else:
        raw["providers"]["test"]["api_keys"][0]["uuid"] = credential_uuid

    with pytest.raises(ValueError, match=r"api_keys\[0\]\.uuid.*canonical UUID"):
        GatewayConfig(raw)


def test_provider_credential_uuids_must_be_unique_within_provider() -> None:
    raw = _minimal_raw()
    raw["providers"]["test"]["api_keys"].append(
        {
            "uuid": _PRIMARY_CREDENTIAL_UUID,
            "id": "secondary",
            "key": "sk-secondary",
        }
    )

    with pytest.raises(ValueError, match="api_keys UUIDs must be unique"):
        GatewayConfig(raw)


def test_responses_provider_requires_explicit_request_encoding() -> None:
    raw = _minimal_raw()
    raw["providers"]["test"]["api_type"] = "responses"

    with pytest.raises(
        ValueError,
        match="request_encoding is required for api_type 'responses'",
    ):
        GatewayConfig(raw)


@pytest.mark.parametrize("request_encoding", ["passthrough", "identity", "zstd"])
def test_responses_provider_propagates_request_encoding(
    request_encoding: str,
) -> None:
    raw = _minimal_raw()
    raw["providers"]["test"].update(
        {
            "api_type": "responses",
            "request_encoding": request_encoding,
        }
    )

    config = GatewayConfig(raw)

    assert config.providers["test"].request_encoding == request_encoding


def test_discover_config_resolves_explicit_directory() -> None:
    assert discover_config("/tmp/gateway") == "/tmp/gateway/config.jsonc"


@pytest.mark.parametrize(
    ("provider", "api_type", "base_url", "expected"),
    [
        (
            "openai",
            "responses",
            "https://api.openai.com/v1",
            "passthrough",
        ),
        (
            "openai",
            "responses",
            "https://relay.example/v1",
            "passthrough",
        ),
        ("custom", "responses", "https://relay.example", "web-run-injection"),
        (
            "qwen",
            "responses",
            "https://qwen.example/v1",
            "web-run-injection",
        ),
        ("custom", "chat", "https://chat.example/v1", "builtin"),
        ("custom", "anthropic", "https://messages.example", None),
        ("custom", "google", "https://generativelanguage.googleapis.com", None),
    ],
)
def test_provider_selection_chooses_expected_builtin_tool_profile(
    provider: str, api_type: str, base_url: str, expected: str | None
) -> None:
    assert (
        default_tool_profile_for_provider(
            {"provider": provider, "api_type": api_type, "base_url": base_url}
        )
        == expected
    )


def test_provider_identity_not_url_selects_profile() -> None:
    assert (
        default_tool_profile_for_provider(
            {
                "provider": "custom",
                "api_type": "responses",
                "request_encoding": "passthrough",
                "base_url": "https://api.openai.com/v1",
            }
        )
        == "web-run-injection"
    )


@pytest.mark.parametrize(
    ("provider", "base_url", "expected_profile"),
    [
        (
            "openai",
            "https://api.openai.com/v1",
            "passthrough",
        ),
        (
            "openai",
            "https://relay.example/v1",
            "passthrough",
        ),
        (
            "custom",
            "https://relay.example",
            "web-run-injection",
        ),
        ("qwen", "https://qwen.example/v1", "web-run-injection"),
    ],
)
def test_unified_responses_protocol_resolves_direct_profile(
    provider: str,
    base_url: str,
    expected_profile: str,
) -> None:
    raw = {
        "providers": {
            "upstream": {
                "api_keys": [
                    {
                        "uuid": _PRIMARY_CREDENTIAL_UUID,
                        "id": "primary",
                        "key": "sk-test",
                    }
                ],
                "current_api_key": "primary",
                "base_urls": [base_url],
                "current_base_url": base_url,
                "provider": provider,
                "api_type": "responses",
                "request_encoding": "passthrough",
            }
        },
        "model_groups": {
            "models": {
                "provider": ["upstream"],
                "type": "llm",
                "models": {"test-model": {"upstream_model": "gpt-5.6-terra"}},
            }
        },
        "server": {
            "admin_password": "test-admin-password",
            "api_keys": [{"id": "test", "label": "Test", "key": "test-key"}],
        },
    }

    route, _provider_info = GatewayConfig(raw).resolve("openai_responses", "test-model")

    assert is_responses_passthrough(route)
    assert route.tool_profile_name == (
        None if expected_profile == "passthrough" else expected_profile
    )
    if expected_profile == "passthrough":
        assert route.tool_profile == {}
        assert route.tool_profile_inputs == {}


def test_passthrough_tool_option_is_rejected_for_non_responses_provider() -> None:
    raw = _minimal_raw()
    raw["model_groups"]["test-llm"]["tool_profile"] = "passthrough"

    with pytest.raises(
        ValueError,
        match="'passthrough'.*only available for provider api_type 'responses'",
    ):
        GatewayConfig(raw)


def test_resolve_codex_home_uses_cli_environment_and_default_precedence(
    tmp_path, monkeypatch
) -> None:
    env_home = tmp_path / "from-env"
    cli_home = tmp_path / "from-cli"
    monkeypatch.setenv(CODEX_HOME_ENV, str(env_home))

    assert resolve_codex_home() == str(env_home)
    assert resolve_codex_home(str(cli_home)) == str(cli_home)

    monkeypatch.delenv(CODEX_HOME_ENV)
    assert resolve_codex_home() == DEFAULT_CODEX_HOME


def test_resolve_codex_home_rejects_empty_value(monkeypatch) -> None:
    monkeypatch.setenv(CODEX_HOME_ENV, "")

    with pytest.raises(ValueError, match="must not be empty"):
        resolve_codex_home()


def test_discover_config_checks_config_jsonc_inside_default_directory(
    tmp_path, monkeypatch
) -> None:
    config_dir = tmp_path / "gateway"
    config_dir.mkdir()
    config_path = config_dir / "config.jsonc"
    monkeypatch.setattr(gateway_config, "CONFIG_DIRS_TO_TRY", [str(config_dir)])

    assert discover_config() is None
    config_path.write_text("{}", encoding="utf-8")
    assert discover_config() == str(config_path)


def test_init_uses_the_single_default_config_directory(
    tmp_path, monkeypatch, capsys
) -> None:
    config_dir = tmp_path / "xdg"
    config_path = config_dir / "config.jsonc"
    monkeypatch.setattr("codex_rosetta.gateway.cli.DEFAULT_CONFIG_DIR", str(config_dir))

    _cmd_init(Namespace(config=None))

    assert config_path.is_file()
    assert load_config(str(config_path))["tool_profiles"] == {}
    assert "Default Admin password: columbina" in capsys.readouterr().out


def _secure_server(**overrides) -> dict:
    server = {
        "admin_password": "test-admin-password",
        "api_keys": [{"id": "test-client", "key": "test-gateway-key", "label": "Test"}],
    }
    server.update(overrides)
    return server


def _minimal_raw(**server_overrides) -> dict:
    """Return a minimal valid config dict with optional server overrides."""
    raw = {
        "providers": {
            "test": {
                "api_keys": [
                    {
                        "uuid": _PRIMARY_CREDENTIAL_UUID,
                        "id": "primary",
                        "key": "sk-test",
                    }
                ],
                "current_api_key": "primary",
                "base_urls": ["https://api.example.com"],
                "current_base_url": "https://api.example.com",
                "provider": "custom",
                "api_type": "chat",
            }
        },
        "model_groups": {
            "test-llm": {
                "provider": ["test"],
                "type": "llm",
                "models": {"gpt-test": {"upstream_model": "gpt-5.6-terra"}},
            }
        },
        "server": _secure_server(),
    }
    raw["server"].update(server_overrides)
    return raw


def test_local_mode_defaults_to_enabled_and_unconfirmed() -> None:
    config = GatewayConfig(_minimal_raw())

    assert config.local_mode is True
    assert config.local_mode_confirmed is False


def test_codex_task_model_settings_are_normalized() -> None:
    raw = _minimal_raw()
    raw["codex"] = {
        "auto_review_model_override": " review-alias ",
        "memories": {
            "extract_model": " extract-alias ",
            "consolidation_model": " consolidation-alias ",
        },
    }

    config = GatewayConfig(raw)

    assert config.codex == {
        "auto_review_model_override": "review-alias",
        "memories": {
            "extract_model": "extract-alias",
            "consolidation_model": "consolidation-alias",
        },
    }


@pytest.mark.parametrize(
    "codex",
    [
        "review-alias",
        {"unknown": "review-alias"},
        {"auto_review_model_override": ""},
        {"memories": "extract-alias"},
        {"memories": {"unknown": "extract-alias"}},
        {"memories": {"extract_model": ""}},
    ],
)
def test_invalid_codex_task_model_settings_are_rejected(codex) -> None:
    raw = _minimal_raw()
    raw["codex"] = codex

    with pytest.raises(ValueError, match="config: codex"):
        GatewayConfig(raw)


def test_web_run_sidecar_is_disabled_by_default() -> None:
    config = GatewayConfig(_minimal_raw())

    assert config.web_run_sidecar_url is None
    assert config.web_run_sidecar_token is None
    assert config.web_run_sidecar_timeout == 300.0
    route, _provider = config.resolve("openai_responses", "gpt-test")
    assert WEB_RUN_SIDECAR_CAPABILITY not in route.tool_runtime_capabilities


def test_web_run_sidecar_config_does_not_claim_browser_readiness() -> None:
    config = GatewayConfig(
        _minimal_raw(
            web_run={
                "base_url": "http://web-run:8080/",
                "token": "sidecar-secret-token-for-tests",
                "timeout_seconds": 12,
            }
        )
    )

    assert config.web_run_sidecar_url == "http://web-run:8080"
    assert config.web_run_sidecar_token == "sidecar-secret-token-for-tests"
    assert config.web_run_sidecar_timeout == 12.0
    assert "sidecar-secret-token-for-tests" in config.token_values
    route, _provider = config.resolve("openai_responses", "gpt-test")
    assert WEB_RUN_SIDECAR_CAPABILITY not in route.tool_runtime_capabilities


def test_web_search_key_enables_basic_route_capability() -> None:
    config = GatewayConfig(
        _minimal_raw(
            web_search={
                "providers": [
                    {
                        "id": "tavily",
                        "provider": "tavily",
                        "tavily_api_key": "tvly-test-key",
                    }
                ],
            }
        )
    )

    route, _provider = config.resolve("openai_responses", "gpt-test")

    assert WEB_RUN_BASIC_SEARCH_CAPABILITY in route.tool_runtime_capabilities


@pytest.mark.parametrize("later_provider", ["configured_responses_provider", "tavily"])
def test_later_external_candidate_enables_basic_route_capability(
    later_provider: str,
) -> None:
    later_row = (
        {
            "id": "responses",
            "provider": "configured_responses_provider",
            "responses_provider": "test",
            "responses_model": "gpt-5.6-terra",
        }
        if later_provider == "configured_responses_provider"
        else {
            "id": "tavily",
            "provider": "tavily",
            "tavily_api_key": "tvly-test-key",
        }
    )
    raw = _minimal_raw(
        web_search={
            "providers": [
                {"id": "local", "provider": "self_hosted_google"},
                later_row,
            ]
        }
    )
    if later_provider == "configured_responses_provider":
        raw["providers"]["test"]["api_type"] = "responses"
        raw["providers"]["test"]["request_encoding"] = "passthrough"

    route, _provider = GatewayConfig(raw).resolve("openai_responses", "gpt-test")

    assert WEB_RUN_BASIC_SEARCH_CAPABILITY in route.tool_runtime_capabilities


def test_unready_self_hosted_only_chain_does_not_enable_basic_route_capability() -> (
    None
):
    config = GatewayConfig(
        _minimal_raw(
            web_search={
                "providers": [{"id": "local", "provider": "self_hosted_google"}]
            }
        )
    )

    route, _provider = config.resolve("openai_responses", "gpt-test")

    assert WEB_RUN_BASIC_SEARCH_CAPABILITY not in route.tool_runtime_capabilities


def test_web_run_sidecar_environment_overrides_config(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_ROSETTA_WEB_RUN_URL", "http://browser.internal:9090")
    monkeypatch.setenv(
        "CODEX_ROSETTA_WEB_RUN_TOKEN", "environment-sidecar-secret-token"
    )

    config = GatewayConfig(_minimal_raw())

    assert config.web_run_sidecar_url == "http://browser.internal:9090"
    assert config.web_run_sidecar_token == "environment-sidecar-secret-token"


def test_empty_web_run_sidecar_environment_preserves_config(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_ROSETTA_WEB_RUN_URL", "")
    monkeypatch.setenv("CODEX_ROSETTA_WEB_RUN_TOKEN", "")

    config = GatewayConfig(
        _minimal_raw(
            web_run={
                "base_url": "http://web-run:8080",
                "token": "configured-sidecar-secret-token",
            }
        )
    )

    assert config.web_run_sidecar_url == "http://web-run:8080"
    assert config.web_run_sidecar_token == "configured-sidecar-secret-token"


@pytest.mark.parametrize(
    "web_run",
    [
        "http://web-run:8080",
        {"base_url": "http://web-run:8080"},
        {"token": "sidecar-secret-token-for-tests"},
        {
            "base_url": "file:///tmp/socket",
            "token": "sidecar-secret-token-for-tests",
        },
        {
            "base_url": "http://web-run:8080/path",
            "token": "sidecar-secret-token-for-tests",
        },
        {
            "base_url": "http://web-run:8080",
            "token": "sidecar-secret-token-for-tests",
            "timeout_seconds": 0,
        },
        {
            "base_url": "http://web-run:8080",
            "token": "sidecar-secret-token-for-tests",
            "timeout_seconds": 601,
        },
    ],
)
def test_invalid_web_run_sidecar_config_is_rejected(web_run) -> None:
    with pytest.raises(ValueError, match="server.web_run"):
        GatewayConfig(_minimal_raw(web_run=web_run))


def test_web_run_sidecar_accepts_extended_timeout_ceiling() -> None:
    config = GatewayConfig(
        _minimal_raw(
            web_run={
                "base_url": "http://web-run:8080",
                "token": "sidecar-secret-token-for-tests",
                "timeout_seconds": 600,
            }
        )
    )

    assert config.web_run_sidecar_timeout == 600.0


@pytest.mark.parametrize("field", ["local_mode", "local_mode_confirmed"])
def test_local_mode_config_fields_require_booleans(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        GatewayConfig(_minimal_raw(**{field: "yes"}))


class TestAdminPasswordUnresolvedEnvVar:
    """admin_password must not contain unresolved ${...} placeholders."""

    def test_reject_unresolved_placeholder(self):
        raw = _minimal_raw(admin_password="${ADMIN_PASSWORD}")
        with pytest.raises(ValueError, match="unresolved"):
            GatewayConfig(raw)

    def test_reject_partial_placeholder(self):
        raw = _minimal_raw(admin_password="prefix-${SOME_VAR}-suffix")
        with pytest.raises(ValueError, match="unresolved"):
            GatewayConfig(raw)

    def test_accept_literal_password(self):
        raw = _minimal_raw(admin_password="my-secret-password")
        cfg = GatewayConfig(raw)
        assert cfg.admin_password == "my-secret-password"

    def test_reject_missing_password(self):
        raw = _minimal_raw()
        raw["server"].pop("admin_password")
        with pytest.raises(ValueError, match="admin_password"):
            GatewayConfig(raw)

    def test_reject_non_string_password(self):
        raw = _minimal_raw(admin_password=12345)
        with pytest.raises(ValueError, match="admin_password"):
            GatewayConfig(raw)


class TestEnvironmentSubstitution:
    """Environment placeholders are resolved as string data after JSON parsing."""

    def test_load_config_preserves_special_characters_without_structure_injection(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        special = 'admin","credential_visible":true,"injected":"\\line\nrest'
        monkeypatch.setenv("SPECIAL_ADMIN_PASSWORD", special)
        raw = _minimal_raw(
            admin_password="${SPECIAL_ADMIN_PASSWORD}",
            credential_visible=False,
        )
        raw["providers"]["test"]["api_keys"] = [
            {
                "uuid": "d98eafb7-2306-5c8b-98cb-3c3d3f780453",
                "id": "primary",
                "key": "prefix-${SPECIAL_ADMIN_PASSWORD}-suffix",
            }
        ]
        raw["providers"]["test"].pop("current_api_key", None)
        path = tmp_path / "config.jsonc"
        path.write_text(json.dumps(raw), encoding="utf-8")

        loaded = load_config(str(path))

        assert loaded["server"]["admin_password"] == special
        assert loaded["server"]["credential_visible"] is False
        assert "injected" not in loaded["server"]
        assert loaded["providers"]["test"]["api_keys"][0]["key"] == (
            f"prefix-{special}-suffix"
        )
        assert GatewayConfig(loaded).admin_password == special

    def test_admin_candidate_substitution_keeps_special_value_as_data(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        special = 'quote"backslash\\newline\nrest'
        monkeypatch.setenv("SPECIAL_ADMIN_PASSWORD", special)
        raw = _minimal_raw(
            admin_password="${SPECIAL_ADMIN_PASSWORD}",
            credential_visible=False,
        )

        config = GatewayConfig.from_raw_with_env(raw)

        assert config.admin_password == special
        assert config.credential_visible is False


class TestGatewayAccessKeys:
    """Gateway access keys require stable, unique principal IDs."""

    def test_reject_missing_access_keys(self):
        raw = _minimal_raw()
        raw["server"].pop("api_keys")
        with pytest.raises(ValueError, match="at least one"):
            GatewayConfig(raw)

    @pytest.mark.parametrize("principal", ["", "   ", None])
    def test_reject_empty_principal_id(self, principal):
        raw = _minimal_raw()
        raw["server"]["api_keys"][0]["id"] = principal
        with pytest.raises(ValueError, match="id must be a non-empty"):
            GatewayConfig(raw)

    def test_reject_duplicate_principal_ids(self):
        raw = _minimal_raw()
        raw["server"]["api_keys"].append(
            {"id": "test-client", "key": "other-key", "label": "Other"}
        )
        with pytest.raises(ValueError, match="duplicate.*id"):
            GatewayConfig(raw)

    def test_maps_raw_keys_to_stable_principals(self):
        cfg = GatewayConfig(_minimal_raw())
        assert cfg.api_key_principals == {"test-gateway-key": "test-client"}

    @pytest.mark.parametrize("label", [{"nested": True}, ["label"], "x" * 129])
    def test_rejects_invalid_access_key_label(self, label):
        raw = _minimal_raw()
        raw["server"]["api_keys"][0]["label"] = label
        with pytest.raises(ValueError, match="label must"):
            GatewayConfig(raw)

    def test_allows_empty_access_key_label(self):
        raw = _minimal_raw()
        raw["server"]["api_keys"][0]["label"] = ""
        assert GatewayConfig(raw).api_key_labels == {"test-gateway-key": ""}

    def test_secure_defaults(self):
        cfg = GatewayConfig(_minimal_raw())
        assert cfg.host == "127.0.0.1"
        assert cfg.credential_visible is False

    def test_cli_scaffold_uses_fixed_default_admin_password_and_unique_access_keys(
        self,
    ):
        first = _empty_config_template()
        second = _empty_config_template()

        first_config = GatewayConfig(first)
        second_config = GatewayConfig(second)
        assert first_config.admin_password == "columbina"
        assert second_config.admin_password == "columbina"
        assert first_config.api_keys[0]["key"] != second_config.api_keys[0]["key"]
        assert first_config.host == "127.0.0.1"
        assert first_config.credential_visible is False
        assert first["server"]["request_body_limit_mb"] == 128


class TestAdminCorsOrigins:
    """Admin CORS accepts only canonical HTTP(S) origin allowlists."""

    @pytest.mark.parametrize("value", [None, "https://admin.example", {}])
    def test_rejects_non_list_allowlist(self, value):
        with pytest.raises(ValueError, match="admin_cors_origins must be a list"):
            GatewayConfig(_minimal_raw(admin_cors_origins=value))

    @pytest.mark.parametrize(
        "origin",
        [
            123,
            "ftp://admin.example",
            "https://user:password@admin.example",
            "https://admin.example/path",
            "https://admin.example?query=1",
            "https://admin.example#fragment",
            "https://admin.example:invalid",
        ],
    )
    def test_rejects_non_origin_entries(self, origin):
        with pytest.raises(ValueError, match=r"admin_cors_origins\[0\]"):
            GatewayConfig(_minimal_raw(admin_cors_origins=[origin]))

    def test_normalizes_default_ports_trailing_slashes_and_duplicates(self):
        config = GatewayConfig(
            _minimal_raw(
                admin_cors_origins=[
                    " HTTPS://ADMIN.EXAMPLE:443/ ",
                    "https://admin.example",
                    "http://localhost:80/",
                    "http://localhost:8765",
                ]
            )
        )

        assert config.admin_cors_origins == [
            "https://admin.example",
            "http://localhost",
            "http://localhost:8765",
        ]


class TestRequestBodyLimit:
    """Inbound request body limits use fixed, validated size tiers."""

    def test_defaults_to_128_mb(self):
        config = GatewayConfig(_minimal_raw())

        assert config.request_body_limit_mb == 128
        assert config.request_body_limit_config_value == 128
        assert config.request_body_limit_bytes == 128 * 1024 * 1024

    @pytest.mark.parametrize("value", [64, 128, 256, 512, 1024])
    def test_accepts_supported_size_tiers(self, value):
        config = GatewayConfig(_minimal_raw(request_body_limit_mb=value))

        assert config.request_body_limit_mb == value
        assert config.request_body_limit_config_value == value
        assert config.request_body_limit_bytes == value * 1024 * 1024

    def test_accepts_unlimited(self):
        config = GatewayConfig(_minimal_raw(request_body_limit_mb="unlimited"))

        assert config.request_body_limit_mb is None
        assert config.request_body_limit_config_value == "unlimited"
        assert config.request_body_limit_bytes == sys.maxsize

    @pytest.mark.parametrize(
        "value", [None, True, False, 0, 63, 129, 2048, "128", "none", {}]
    )
    def test_rejects_unsupported_values(self, value):
        with pytest.raises(ValueError, match="request_body_limit_mb must be one of"):
            GatewayConfig(_minimal_raw(request_body_limit_mb=value))


class TestWebSearchConfig:
    """Global Rosetta web search settings are validated and redacted."""

    def test_defaults_to_empty_provider_list(self):
        config = GatewayConfig(_minimal_raw())

        assert config.web_search == {"providers": []}
        assert "provider" not in config.web_search
        assert "tavily_api_key" not in config.web_search

    def test_canonical_providers_are_normalized_redacted_and_ordered(self):
        raw = _minimal_raw(
            web_search={
                "providers": [
                    {
                        "id": "primary_tavily",
                        "provider": "tavily",
                        "tavily_api_key": " tvly-primary ",
                    },
                    {
                        "id": "responses-2",
                        "provider": "configured_responses_provider",
                        "responses_provider": " test ",
                        "responses_model": " gpt-5.6-terra ",
                    },
                    {"id": "local", "provider": "self_hosted_google"},
                ]
            }
        )
        raw["providers"]["test"]["api_type"] = "responses"
        raw["providers"]["test"]["request_encoding"] = "passthrough"

        config = GatewayConfig(raw)

        assert config.web_search == {
            "providers": [
                {
                    "id": "primary_tavily",
                    "provider": "tavily",
                    "tavily_api_key": "tvly-primary",
                },
                {
                    "id": "responses-2",
                    "provider": "configured_responses_provider",
                    "responses_provider": "test",
                    "responses_model": "gpt-5.6-terra",
                },
                {"id": "local", "provider": "self_hosted_google"},
            ]
        }
        assert "tvly-primary" in config.token_values
        assert list(config.web_search) == ["providers"]
        assert json.loads(json.dumps(config.web_search)) == config.web_search

    def test_accepts_canonical_deepseek_native_responses_row(self):
        raw = _minimal_raw(
            web_search={
                "providers": [
                    {
                        "id": "deepseek-row",
                        "provider": "deepseek_native_responses",
                        "deepseek_provider": "official-deepseek",
                    }
                ]
            }
        )
        raw["providers"]["official-deepseek"] = {
            "api_keys": [
                {
                    "uuid": "f45d720f-7d38-5874-8ab2-7594194e2729",
                    "id": "primary",
                    "key": "deepseek-secret",
                }
            ],
            "current_api_key": "primary",
            "base_urls": ["https://api.deepseek.com"],
            "current_base_url": "https://api.deepseek.com",
            "provider": "deepseek",
            "api_type": "responses",
            "request_encoding": "passthrough",
        }

        config = GatewayConfig(raw)

        assert config.web_search == {
            "providers": [
                {
                    "id": "deepseek-row",
                    "provider": "deepseek_native_responses",
                    "deepseek_provider": "official-deepseek",
                }
            ]
        }
        candidate = config.web_search_candidates[0]
        assert isinstance(candidate, DeepSeekNativeResponsesSearchProviderCandidate)
        assert candidate.model == "deepseek-v4-flash"

    @pytest.mark.parametrize(
        "provider",
        ["self_hosted_google", "self_hosted_bing", "self_hosted_bing_browser"],
    )
    def test_accepts_each_self_hosted_provider(self, provider):
        config = GatewayConfig(
            _minimal_raw(
                web_search={"providers": [{"id": "local", "provider": provider}]}
            )
        )
        assert config.web_search == {
            "providers": [{"id": "local", "provider": provider}]
        }
        assert "provider" not in config.web_search
        assert "tavily_api_key" not in config.web_search

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            ("tavily", "must be an object"),
            ({"providers": {}}, "providers must be a list"),
            ({"providers": [], "provider": "tavily"}, "unsupported fields"),
            ({"providers": ["tavily"]}, r"providers\[0\] must be an object"),
            ({"providers": [{"id": "one"}]}, "provider must be one of"),
            (
                {"providers": [{"id": "one", "provider": "other"}]},
                "provider must be one of",
            ),
            (
                {"providers": [{"id": "one", "provider": "tavily"}]},
                "missing fields",
            ),
            (
                {
                    "providers": [
                        {
                            "id": "one",
                            "provider": "tavily",
                            "tavily_api_key": "key",
                            "responses_model": "gpt-5.6-sol",
                        }
                    ]
                },
                "unsupported fields",
            ),
            (
                {
                    "providers": [
                        {
                            "id": "one",
                            "provider": "configured_responses_provider",
                            "responses_provider": "upstream",
                        }
                    ]
                },
                "missing fields",
            ),
            (
                {
                    "providers": [
                        {
                            "id": "one",
                            "provider": "configured_responses_provider",
                            "responses_provider": "upstream",
                            "responses_model": "gpt-6",
                        }
                    ]
                },
                "responses_model must be one of",
            ),
            (
                {"providers": [{"id": "one", "provider": "deepseek_native_responses"}]},
                "missing fields",
            ),
            (
                {
                    "providers": [
                        {
                            "id": "one",
                            "provider": "deepseek_native_responses",
                            "deepseek_provider": "official",
                            "model": "deepseek-v4-flash",
                        }
                    ]
                },
                "unsupported fields",
            ),
            (
                {
                    "providers": [
                        {"id": "one", "provider": "self_hosted_google", "token": "x"}
                    ]
                },
                "unsupported fields",
            ),
        ],
    )
    def test_rejects_invalid_shapes_and_field_combinations(self, value, message):
        with pytest.raises(ValueError, match=message):
            GatewayConfig(_minimal_raw(web_search=value))

    @pytest.mark.parametrize(
        "value",
        [
            "tavily",
            {},
            {"provider": "tavily", "tavily_api_key": "key"},
            {
                "provider": "configured_responses_provider",
                "responses_provider": "test",
                "responses_model": "gpt-5.6-sol",
            },
            {"provider": "self_hosted_google"},
        ],
    )
    def test_rejects_removed_single_provider_shapes(self, value):
        with pytest.raises(ValueError):
            GatewayConfig(_minimal_raw(web_search=value))

    @pytest.mark.parametrize("provider_id", ["", "has space", "dot.id", "a" * 65, 42])
    def test_rejects_invalid_provider_ids(self, provider_id):
        value = {
            "providers": [
                {
                    "id": provider_id,
                    "provider": "tavily",
                    "tavily_api_key": "key",
                }
            ]
        }
        with pytest.raises(ValueError, match="id must match"):
            GatewayConfig(_minimal_raw(web_search=value))

    def test_rejects_duplicate_ids_and_more_than_32_providers(self):
        duplicate = [
            {"id": "same", "provider": "self_hosted_google"},
            {"id": "same", "provider": "self_hosted_bing"},
        ]
        with pytest.raises(ValueError, match="duplicate.*id"):
            GatewayConfig(_minimal_raw(web_search={"providers": duplicate}))

        too_many = [
            {"id": f"provider-{index}", "provider": "self_hosted_google"}
            for index in range(33)
        ]
        with pytest.raises(ValueError, match="at most 32"):
            GatewayConfig(_minimal_raw(web_search={"providers": too_many}))

    @pytest.mark.parametrize(
        "row",
        [
            {"id": "one", "provider": "tavily", "tavily_api_key": "   "},
            {
                "id": "one",
                "provider": "configured_responses_provider",
                "responses_provider": "",
                "responses_model": "gpt-5.6-sol",
            },
            {
                "id": "one",
                "provider": "configured_responses_provider",
                "responses_provider": "upstream",
                "responses_model": " ",
            },
            {
                "id": "one",
                "provider": "deepseek_native_responses",
                "deepseek_provider": " ",
            },
        ],
    )
    def test_rejects_empty_provider_values(self, row):
        with pytest.raises(ValueError, match="must be a non-empty string"):
            GatewayConfig(_minimal_raw(web_search={"providers": [row]}))

    def test_canonical_responses_provider_requires_enabled_registry_entry(self):
        with pytest.raises(ValueError, match="responses.*enabled Responses provider"):
            GatewayConfig(
                _minimal_raw(
                    web_search={
                        "providers": [
                            {
                                "id": "responses",
                                "provider": "configured_responses_provider",
                                "responses_provider": "not-yet-resolved",
                                "responses_model": "gpt-5.6-luna",
                            }
                        ]
                    }
                )
            )


class TestStreamTraceConfig:
    """server.stream_trace is parsed into runtime trace settings."""

    def test_defaults_disabled(self):
        cfg = GatewayConfig(_minimal_raw())

        assert cfg.stream_trace.enabled is False
        assert cfg.stream_trace.filter == ""
        assert cfg.stream_trace.path == ""
        assert cfg.stream_trace.max_string_chars == 20_000

    def test_parses_config_values(self):
        cfg = GatewayConfig(
            _minimal_raw(
                stream_trace={
                    "enabled": True,
                    "filter": "glm,opencode",
                    "path": "~/trace/log.jsonl",
                    "max_string_chars": "5000",
                }
            )
        )

        assert cfg.stream_trace.enabled is True
        assert cfg.stream_trace.filter == "glm,opencode"
        assert cfg.stream_trace.path == "~/trace/log.jsonl"
        assert cfg.stream_trace.max_string_chars == 5000


class TestProviderApiTypeResolution:
    """Provider entries can use provider/api_type instead of legacy type."""

    def test_legacy_type_is_rejected_even_with_api_type(self):
        raw = {
            "providers": {
                "DeepSeek": {
                    "api_keys": [
                        {
                            "uuid": _PRIMARY_CREDENTIAL_UUID,
                            "id": "primary",
                            "key": "sk-test",
                        }
                    ],
                    "current_api_key": "primary",
                    "base_urls": ["https://api.deepseek.com"],
                    "current_base_url": "https://api.deepseek.com",
                    "provider": "deepseek",
                    "api_type": "chat",
                    "type": "anthropic",
                }
            },
            "model_groups": {
                "DeepSeek": {
                    "provider": ["DeepSeek"],
                    "type": "llm",
                    "models": {"deepseek-test": {}},
                }
            },
            "server": _secure_server(),
        }

        with pytest.raises(ValueError, match="shim/type options are unsupported"):
            GatewayConfig(raw)

    def test_provider_api_type_can_derive_mixed_shim(self):
        raw = {
            "providers": {
                "MiniMax": {
                    "api_keys": [
                        {
                            "uuid": _PRIMARY_CREDENTIAL_UUID,
                            "id": "primary",
                            "key": "sk-test",
                        }
                    ],
                    "current_api_key": "primary",
                    "base_urls": ["https://api.minimaxi.com/anthropic"],
                    "current_base_url": "https://api.minimaxi.com/anthropic",
                    "provider": "minimax",
                    "api_type": "anthropic",
                }
            },
            "model_groups": {
                "MiniMax": {
                    "provider": ["MiniMax"],
                    "type": "llm",
                    "models": {"minimax-test": {"upstream_model": "minimax-m3"}},
                }
            },
            "server": _secure_server(),
        }

        cfg = GatewayConfig(raw)
        route, _provider = cfg.resolve("openai_responses", "minimax-test")

        assert cfg.provider_types["MiniMax"] == "anthropic"
        assert cfg.provider_shim_names["MiniMax"] == "minimax--anthropic"
        assert route.target_provider == "anthropic"
        assert route.shim_name == "minimax--anthropic"

    def test_custom_responses_api_type_has_no_shim(self):
        raw = {
            "providers": {
                "Pixel": {
                    "api_keys": [
                        {
                            "uuid": _PRIMARY_CREDENTIAL_UUID,
                            "id": "primary",
                            "key": "sk-test",
                        }
                    ],
                    "current_api_key": "primary",
                    "base_urls": ["https://api.example.com"],
                    "current_base_url": "https://api.example.com",
                    "provider": "custom",
                    "api_type": "responses",
                    "request_encoding": "passthrough",
                }
            },
            "model_groups": {
                "Pixel": {
                    "provider": ["Pixel"],
                    "type": "llm",
                    "models": {"pixel-test": {"upstream_model": "gpt-5.6-terra"}},
                }
            },
            "server": _secure_server(),
        }

        cfg = GatewayConfig(raw)
        route, _provider = cfg.resolve("openai_chat", "pixel-test")

        assert cfg.provider_types["Pixel"] == "openai_responses"
        assert cfg.provider_shim_names["Pixel"] is None
        assert route.target_provider == "openai_responses"
        assert route.shim_name is None
        assert not is_responses_passthrough(route)
        assert route.tool_profile_name == "web-run-injection"
        assert route.tool_profile["namespace.web.run"] == "modified"

    def test_missing_provider_identity_fails_closed_even_for_known_url(self):
        raw = {
            "providers": {
                "DeepSeek": {
                    "api_keys": [
                        {
                            "uuid": _PRIMARY_CREDENTIAL_UUID,
                            "id": "primary",
                            "key": "sk-test",
                        }
                    ],
                    "current_api_key": "primary",
                    "base_urls": ["https://api.deepseek.com/"],
                    "current_base_url": "https://api.deepseek.com/",
                    "api_type": "chat",
                }
            },
            "model_groups": {
                "DeepSeek": {
                    "provider": ["DeepSeek"],
                    "type": "llm",
                    "models": {"deepseek-test": {}},
                }
            },
            "server": _secure_server(),
        }

        with pytest.raises(
            ValueError, match="requires an explicit provider main identity"
        ):
            GatewayConfig(raw)

    def test_custom_url_without_persisted_provider_option_fails_closed(self):
        raw = {
            "providers": {
                "Relay": {
                    "api_keys": [
                        {
                            "uuid": _PRIMARY_CREDENTIAL_UUID,
                            "id": "primary",
                            "key": "sk-test",
                        }
                    ],
                    "current_api_key": "primary",
                    "base_urls": ["https://relay.example/v1"],
                    "current_base_url": "https://relay.example/v1",
                    "api_type": "chat",
                }
            },
            "model_groups": {
                "Relay": {
                    "provider": ["Relay"],
                    "type": "llm",
                    "models": {"relay-test": {}},
                }
            },
            "server": _secure_server(),
        }

        with pytest.raises(
            ValueError, match="requires an explicit provider main identity"
        ):
            GatewayConfig(raw)

    def test_listed_responses_provider_uses_direct_mode(self):
        raw = {
            "providers": {
                "Qwen": {
                    "api_keys": [
                        {
                            "uuid": _PRIMARY_CREDENTIAL_UUID,
                            "id": "primary",
                            "key": "sk-test",
                        }
                    ],
                    "current_api_key": "primary",
                    "base_urls": ["https://api.example.com"],
                    "current_base_url": "https://api.example.com",
                    "provider": "qwen",
                    "api_type": "responses",
                    "request_encoding": "passthrough",
                }
            },
            "model_groups": {
                "Qwen": {
                    "provider": ["Qwen"],
                    "type": "llm",
                    "models": {"qwen-test": {"upstream_model": "qwen3.7-plus"}},
                }
            },
            "server": _secure_server(),
        }

        cfg = GatewayConfig(raw)
        route, _provider = cfg.resolve("openai_responses", "qwen-test")

        assert cfg.provider_types["Qwen"] == "openai_responses"
        assert route.target_provider == "openai_responses"
        assert is_responses_passthrough(route)

    @pytest.mark.parametrize(
        "api_type",
        [
            "responses_passthrough",
            "responses_rosetta",
            "unknown",
            " responses ",
            "",
            None,
            False,
            True,
            0,
            [],
            {},
        ],
    )
    def test_unrecognized_api_types_fail_closed(self, api_type, caplog):
        raw = _minimal_raw()
        raw["providers"]["test"]["api_type"] = api_type

        with pytest.raises(ValueError, match="requires api_type"):
            GatewayConfig(raw)

    def test_legacy_type_config_is_rejected(self):
        raw = _minimal_raw()
        raw["providers"]["test"].pop("api_type")
        raw["providers"]["test"]["type"] = "openai"

        with pytest.raises(ValueError, match="shim/type options are unsupported"):
            GatewayConfig(raw)

    def test_custom_url_without_explicit_protocol_fails_closed(self, caplog):
        raw = _minimal_raw()
        raw["providers"]["test"] = {
            "api_keys": [
                {"uuid": _PRIMARY_CREDENTIAL_UUID, "id": "primary", "key": "sk-test"}
            ],
            "current_api_key": "primary",
            "base_urls": ["https://provider.example"],
            "current_base_url": "https://provider.example",
            "provider": "custom",
        }
        with pytest.raises(ValueError, match="requires api_type"):
            GatewayConfig(raw)

    def test_preset_url_without_explicit_protocol_fails_closed(self, caplog):
        raw = _minimal_raw()
        raw["providers"]["openai"] = {
            "api_keys": [
                {"uuid": _PRIMARY_CREDENTIAL_UUID, "id": "primary", "key": "sk-test"}
            ],
            "current_api_key": "primary",
            "base_urls": ["https://api.openai.com/v1"],
            "current_base_url": "https://api.openai.com/v1",
            "provider": "openai",
        }
        with pytest.raises(ValueError, match="requires api_type"):
            GatewayConfig(raw)

    def test_deepseek_preset_url_without_explicit_protocol_fails_closed(self):
        raw = _minimal_raw()
        raw["providers"]["test"].pop("api_type")
        raw["providers"]["test"]["base_urls"] = ["https://api.deepseek.com"]
        raw["providers"]["test"]["current_base_url"] = "https://api.deepseek.com"
        raw["providers"]["test"]["provider"] = "deepseek"

        with pytest.raises(ValueError, match="requires api_type"):
            GatewayConfig(raw)


class TestModelGroups:
    """Model groups are the only persisted routing definition."""

    def test_top_level_models_are_ignored(self):
        raw = _minimal_raw()
        raw["models"] = {"ignored": "test"}
        cfg = GatewayConfig(raw)
        assert "ignored" not in cfg.models
        assert cfg.models == {"gpt-test": "test"}

    def test_unadapted_provider_profile_records_config_warning(self, caplog):
        GatewayConfig(_minimal_raw())

        assert "selects unadapted profile custom:chat" in caplog.text

    def test_provider_list_uses_only_first_entry(self):
        raw = _minimal_raw()
        raw["providers"]["secondary"] = {
            **raw["providers"]["test"],
            "base_urls": ["https://secondary.example.com"],
            "current_base_url": "https://secondary.example.com",
        }
        raw["model_groups"]["test-llm"]["provider"] = ["test", "secondary"]

        config = GatewayConfig(raw)

        assert config.models == {"gpt-test": "test"}
        route, _provider = config.resolve("openai_responses", "gpt-test")
        assert route.provider_name == "test"

    def test_provider_list_builds_isolated_runtime_ring(self):
        raw = _minimal_raw()
        raw["providers"]["secondary"] = {
            **raw["providers"]["test"],
            "base_urls": ["https://secondary.example.com"],
            "current_base_url": "https://secondary.example.com",
        }
        raw["model_groups"]["test-llm"]["provider"] = ["test", "secondary"]
        cfg = GatewayConfig(raw)

        assert cfg.model_group_provider_names["test-llm"] == ("test", "secondary")
        assert cfg.model_group_provider_statuses("test-llm") == (
            ("test", "available"),
            ("secondary", "available"),
        )
        ring = cfg.model_group_rings["test-llm"]
        ring.mark_failed("test")
        assert cfg.resolve("openai_responses", "gpt-test")[0].provider_name == "secondary"
        assert ring.next_available("test") == "secondary"

    def test_provider_list_rejects_duplicate_or_mixed_api_types(self):
        raw = _minimal_raw()
        raw["providers"]["secondary"] = {
            **raw["providers"]["test"],
            "base_urls": ["https://secondary.example.com"],
            "current_base_url": "https://secondary.example.com",
        }
        raw["model_groups"]["test-llm"]["provider"] = ["test", "test"]
        with pytest.raises(ValueError, match="provider names must be unique"):
            GatewayConfig(raw)

        raw["model_groups"]["test-llm"]["provider"] = ["test", "secondary"]
        raw["providers"]["secondary"]["api_type"] = "responses"
        raw["providers"]["secondary"]["request_encoding"] = "identity"
        with pytest.raises(ValueError, match="same api_type"):
            GatewayConfig(raw)

    def test_provider_failure_entrypoint_rotates_once_and_is_group_scoped(self):
        raw = _minimal_raw()
        raw["providers"]["secondary"] = {
            **raw["providers"]["test"],
            "base_urls": ["https://secondary.example.com"],
            "current_base_url": "https://secondary.example.com",
        }
        raw["model_groups"]["test-llm"]["provider"] = ["test", "secondary"]
        raw["model_groups"]["other-llm"] = {
            "provider": ["test", "secondary"],
            "type": "llm",
            "models": {"gpt-5.6-terra": {}},
        }
        cfg = GatewayConfig(raw)
        writes: list[tuple[str, str]] = []

        async def record(group: str, provider: str) -> None:
            writes.append((group, provider))

        for ring in cfg.model_group_rings.values():
            ring.bind_recorder(record)

        async def scenario() -> None:
            assert await _rotate_model_group_after_upstream_failure(
                object(), cfg, "gpt-test", "test"
            )
            assert cfg.resolve("openai_responses", "gpt-test")[0].provider_name == "secondary"
            assert cfg.resolve("openai_responses", "gpt-5.6-terra")[0].provider_name == "test"
            assert writes == [("test-llm", "secondary")]
            assert not await _rotate_model_group_after_upstream_failure(
                object(), cfg, "gpt-test", "secondary"
            )

        asyncio.run(scenario())

    @pytest.mark.parametrize(
        ("provider", "message"),
        [
            ("test", "must be a non-empty list"),
            ([], "must be a non-empty list"),
            ([""], "entries must be non-empty provider names"),
            ([" test"], "entries must be non-empty provider names"),
            (["test "], "entries must be non-empty provider names"),
            ([1], "entries must be non-empty provider names"),
        ],
    )
    def test_provider_list_rejects_invalid_values(self, provider, message):
        raw = _minimal_raw()
        raw["model_groups"]["test-llm"]["provider"] = provider

        with pytest.raises(ValueError, match=message):
            GatewayConfig(raw)

    def test_llm_group_uses_compact_preset_modalities(self):
        raw = _minimal_raw()
        raw["model_groups"] = {
            "OpenAI": {
                "provider": ["test"],
                "type": "llm",
                "models": {"qwen-public": {"upstream_model": "qwen3.7-plus"}},
            }
        }
        cfg = GatewayConfig(raw)
        route, _provider = cfg.resolve("openai_responses", "qwen-public")
        assert cfg.models == {"qwen-public": "test"}
        assert route.upstream_model == "qwen3.7-plus"
        assert route.input_modalities == ["text", "image"]
        assert route.provider_profile is not None
        assert route.provider_profile.provider_id == "custom"
        assert route.provider_profile.api_type == "chat"
        assert route.resolved_model_profile is cfg.model_profiles["qwen-public"]

    def test_full_codex_catalog_supplies_runtime_modalities(self):
        raw = _minimal_raw()
        raw["model_groups"]["test-llm"]["models"] = {
            "gpt-public": {"upstream_model": "gpt-5.6-sol"}
        }

        route, _provider = GatewayConfig(raw).resolve("openai_responses", "gpt-public")

        assert route.input_modalities == ["text", "image"]

    def test_embedding_group_is_rejected(self):
        raw = _minimal_raw()
        raw["model_groups"] = {
            "Embeddings": {
                "provider": ["test"],
                "type": "embedding",
                "models": {"embed-public": "embed-upstream"},
            }
        }
        with pytest.raises(ValueError, match="type must be 'llm'"):
            GatewayConfig(raw)

    @pytest.mark.parametrize("group_type", [None, "chat", "", "embedding"])
    def test_group_requires_supported_type(self, group_type):
        raw = _minimal_raw()
        raw["model_groups"]["test-llm"]["type"] = group_type
        with pytest.raises(ValueError, match="type must be"):
            GatewayConfig(raw)

    def test_rejects_advanced_model_fields(self):
        raw = _minimal_raw()
        raw["model_groups"]["test-llm"]["models"]["gpt-test"] = {
            "reasoning_mapping": "auto"
        }
        with pytest.raises(ValueError, match="unsupported fields"):
            GatewayConfig(raw)

    def test_removed_capabilities_field_is_rejected(self):
        raw = _minimal_raw()
        raw["model_groups"]["test-llm"]["models"]["gpt-test"] = {
            "capabilities": ["text", "audio"]
        }
        with pytest.raises(ValueError, match="unsupported fields.*capabilities"):
            GatewayConfig(raw)

    def test_duplicate_names_across_groups_are_rejected(self):
        raw = _minimal_raw()
        raw["model_groups"]["second"] = {
            "provider": ["test"],
            "type": "llm",
            "models": {"gpt-test": {}},
        }
        with pytest.raises(ValueError, match="defined more than once"):
            GatewayConfig(raw)

    def test_models_from_disabled_group_provider_are_skipped(self):
        raw = _minimal_raw()
        raw["providers"]["test"]["enabled"] = False
        cfg = GatewayConfig(raw)
        assert cfg.models == {}

    @pytest.mark.parametrize("value", [1, "true", None, []])
    def test_provider_allow_redirects_requires_boolean(self, value):
        raw = _minimal_raw()
        raw["providers"]["test"]["allow_redirects"] = value

        with pytest.raises(ValueError, match="allow_redirects must be a boolean"):
            GatewayConfig(raw)

    def test_provider_redirects_default_disabled(self):
        cfg = GatewayConfig(_minimal_raw())

        assert cfg.providers["test"].allow_redirects is False

    def test_deepseek_chat_soft_interrupt_defaults_enabled(self):
        raw = _minimal_raw()
        raw["providers"]["test"]["provider"] = "deepseek"

        cfg = GatewayConfig(raw)

        assert cfg.providers["test"].soft_interrupt is True

    def test_deepseek_chat_soft_interrupt_can_be_disabled(self):
        raw = _minimal_raw()
        raw["providers"]["test"].update(
            {"provider": "deepseek", "soft_interrupt": False}
        )

        cfg = GatewayConfig(raw)

        assert cfg.providers["test"].soft_interrupt is False

    @pytest.mark.parametrize("value", [1, "true", None, []])
    def test_provider_soft_interrupt_requires_boolean(self, value):
        raw = _minimal_raw()
        raw["providers"]["test"]["soft_interrupt"] = value

        with pytest.raises(ValueError, match="soft_interrupt must be a boolean"):
            GatewayConfig(raw)

    def test_provider_soft_interrupt_rejects_non_chat_protocol(self):
        raw = _minimal_raw()
        raw["providers"]["test"].update(
            {
                "api_type": "responses",
                "request_encoding": "passthrough",
                "soft_interrupt": True,
            }
        )

        with pytest.raises(ValueError, match="supported only.*chat"):
            GatewayConfig(raw)

    def test_provider_force_rosetta_compaction_defaults_disabled(self):
        cfg = GatewayConfig(_minimal_raw())

        assert cfg.providers["test"].force_rosetta_compaction is False

    def test_responses_provider_force_rosetta_compaction_is_propagated(self):
        raw = _minimal_raw()
        raw["providers"]["test"].update(
            {
                "api_type": "responses",
                "request_encoding": "passthrough",
                "force_rosetta_compaction": True,
            }
        )

        cfg = GatewayConfig(raw)

        assert cfg.providers["test"].force_rosetta_compaction is True

    @pytest.mark.parametrize("value", [1, "true", None, []])
    def test_provider_force_rosetta_compaction_requires_boolean(self, value):
        raw = _minimal_raw()
        raw["providers"]["test"].update(
            {
                "api_type": "responses",
                "request_encoding": "passthrough",
                "force_rosetta_compaction": value,
            }
        )

        with pytest.raises(
            ValueError, match="force_rosetta_compaction must be a boolean"
        ):
            GatewayConfig(raw)

    def test_provider_force_rosetta_compaction_rejects_non_responses_protocol(self):
        raw = _minimal_raw()
        raw["providers"]["test"]["force_rosetta_compaction"] = True

        with pytest.raises(ValueError, match="supported only.*responses"):
            GatewayConfig(raw)


def test_cli_add_model_group_then_grouped_model(tmp_path):
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "test": {
                        "api_keys": [
                            {
                                "uuid": _PRIMARY_CREDENTIAL_UUID,
                                "id": "primary",
                                "key": "sk-test",
                            }
                        ],
                        "current_api_key": "primary",
                        "base_urls": ["https://api.example.test"],
                        "current_base_url": "https://api.example.test",
                        "api_type": "chat",
                    }
                },
                "model_groups": {},
                "server": _secure_server(),
            }
        ),
        encoding="utf-8",
    )

    _cmd_add_model_group(
        Namespace(
            config=str(tmp_path),
            name="Test LLMs",
            provider="test",
        )
    )
    _cmd_add_model(
        Namespace(
            config=str(tmp_path),
            name="gpt-test",
            group="Test LLMs",
        )
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["model_groups"]["Test LLMs"] == {
        "provider": ["test"],
        "type": "llm",
        "tool_profile": "builtin",
        "models": {"gpt-test": {}},
    }


def test_cli_add_provider_persists_explicit_protocol(tmp_path):
    _cmd_add_provider(
        Namespace(
            config=str(tmp_path),
            name="relay",
            api_key="sk-test",
            base_url="https://relay.example/v1",
            api_type="responses",
        )
    )

    saved = json.loads((tmp_path / "config.jsonc").read_text(encoding="utf-8"))
    credential_uuid = saved["providers"]["relay"]["api_keys"][0].pop("uuid")
    assert UUID(credential_uuid).version == 4
    assert saved["providers"]["relay"] == {
        "api_keys": [{"id": "primary", "key": "sk-test"}],
        "current_api_key": "primary",
        "base_urls": ["https://relay.example/v1"],
        "current_base_url": "https://relay.example/v1",
        "api_type": "responses",
        "request_encoding": "passthrough",
    }


def test_cli_add_custom_responses_model_group_selects_injection_profile(tmp_path):
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "test": {
                        "api_keys": [
                            {
                                "uuid": _PRIMARY_CREDENTIAL_UUID,
                                "id": "primary",
                                "key": "sk-test",
                            }
                        ],
                        "current_api_key": "primary",
                        "base_urls": ["https://api.example.test"],
                        "current_base_url": "https://api.example.test",
                        "provider": "custom",
                        "api_type": "responses",
                        "request_encoding": "passthrough",
                    }
                },
                "tool_profiles": {},
                "model_groups": {},
                "server": _secure_server(),
            }
        ),
        encoding="utf-8",
    )

    _cmd_add_model_group(
        Namespace(
            config=str(tmp_path),
            name="Test Rosetta",
            provider="test",
        )
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["model_groups"]["Test Rosetta"]["tool_profile"] == (
        "web-run-injection"
    )


def test_cli_add_custom_responses_group_selects_injection_profile(tmp_path):
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "test": {
                        "api_keys": [
                            {
                                "uuid": _PRIMARY_CREDENTIAL_UUID,
                                "id": "primary",
                                "key": "sk-test",
                            }
                        ],
                        "current_api_key": "primary",
                        "base_urls": ["https://api.example.test"],
                        "current_base_url": "https://api.example.test",
                        "provider": "custom",
                        "api_type": "responses",
                        "request_encoding": "passthrough",
                    }
                },
                "tool_profiles": {},
                "model_groups": {},
                "server": _secure_server(),
            }
        ),
        encoding="utf-8",
    )

    _cmd_add_model_group(
        Namespace(
            config=str(tmp_path),
            name="Test Responses",
            provider="test",
        )
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["model_groups"]["Test Responses"]["tool_profile"] == (
        "web-run-injection"
    )
