"""Config CRUD and upstream model fetch route handlers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast

from codex_rosetta._vendor.httpserver import JSONResponse, Response
from codex_rosetta.observability.redaction import SecretRedactor
from codex_rosetta.shims.providers import builtin_provider_shims

from ...config import (
    API_TYPE_ORDER,
    CONFIGURED_RESPONSES_WEB_SEARCH_PROVIDER,
    CONFIGURED_RESPONSES_WEB_SEARCH_MODELS,
    GatewayConfig,
    MAX_WEB_SEARCH_PROVIDERS,
    SELF_HOSTED_WEB_SEARCH_PROVIDERS,
    _substitute_env_vars,
    active_model_group_provider,
    default_tool_profile_for_provider,
    load_config_raw,
    model_group_provider_names,
    normalize_codex_settings,
    normalize_local_mode_settings,
    normalize_web_search,
    provider_supports_tool_profiles,
    resolve_provider_config_type_and_shim,
    resolve_provider_api_type,
)
from ...providers import build_provider_info
from ...deepseek_responses_search import normalize_deepseek_responses_origin
from ...local_mode import config_toml_has_model_catalog
from ...model_presets import (
    detect_model_preset,
    full_model_presets,
    model_presets_for_admin,
)
from ...model_profiles import (
    canonical_model_overrides,
    editable_model_info,
    resolve_model_profile,
)
from ...provider_profiles import provider_catalog_for_admin, resolve_soft_interrupt
from ...search_provider_contract import (
    SearchProviderCapability,
    contract_for_wire_provider,
    search_provider_chain_contract,
)
from ...stream_trace import DEFAULT_MAX_CHARS
from ...tool_profiles import (
    TOOL_PROFILE_PASSTHROUGH_OPTION,
    normalize_tool_profile_input_overrides,
    normalize_tool_profile_documents,
    tool_profile_contract,
    validate_tool_profile_reference,
)
from ...transport import UpstreamProtocolError
from ...transport.provider_info import ProviderInfo
from ._shared import (
    _ENV_VAR_RE,
    _build_provider_entry,
    _commit_gateway_config,
    _get_config_path,
    _handle_provider_rename,
    _mask_api_key,
    _parse_json_object,
    _reload_gateway_config,
)
from ..request_encoding_detection import detect_responses_request_encoding

import logging

logger = logging.getLogger("codex-rosetta-gateway")
_PROVIDER_MODEL_DISCOVERY_TIMEOUT_SECONDS = 60.0


def _mask_web_search_config(value: Any) -> dict[str, Any]:
    """Return canonical server.web_search with sensitive values masked."""
    masked = dict(normalize_web_search(value))
    masked["providers"] = [
        {
            **entry,
            "tavily_api_key": _mask_api_key(str(entry["tavily_api_key"])),
        }
        if "tavily_api_key" in entry
        else entry
        for entry in masked["providers"]
    ]
    return masked


def _search_capability_values(
    capabilities: frozenset[SearchProviderCapability],
) -> list[str]:
    """Serialize code-owned search capabilities in a stable Admin DTO order."""
    return sorted(
        capability.value
        for capability in capabilities
        if capability is not SearchProviderCapability.LOCAL_COMMAND_COMPOSITION
    )


def _web_search_contract_for_admin(
    value: Any,
    *,
    providers: Mapping[str, ProviderInfo] | None = None,
    provider_api_types: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return non-sensitive, derived Admin metadata for the saved search chain.

    The provider-row wire schema remains the sole persisted configuration.  This
    view intentionally derives families, execution modes, and safe aggregate
    capabilities from the code-owned provider contract on every read.
    """
    normalized = normalize_web_search(value)
    rows = list(normalized.providers)
    row_contracts = [
        (row, contract_for_wire_provider(str(row["provider"]))) for row in rows
    ]
    chain_contract = search_provider_chain_contract(
        tuple(contract for _, contract in row_contracts)
    )
    chain = {
        "mode": chain_contract.mode.value,
        "capabilities": _search_capability_values(chain_contract.capabilities),
        "limitations": list(chain_contract.limitations),
    }
    deepseek_providers: list[str] = []
    if providers is not None and provider_api_types is not None:
        for name, provider_info in providers.items():
            if provider_api_types.get(name) != "responses":
                continue
            if provider_info.name != "deepseek":
                continue
            try:
                normalize_deepseek_responses_origin(provider_info.base_url)
            except ValueError:
                continue
            credentials = provider_info.credential_values
            if credentials and all(
                type(credential) is str and bool(credential.strip())
                for credential in credentials
            ):
                deepseek_providers.append(str(name))
    return {
        "provider_types": [
            "tavily",
            CONFIGURED_RESPONSES_WEB_SEARCH_PROVIDER,
            "deepseek_native_responses",
            *sorted(SELF_HOSTED_WEB_SEARCH_PROVIDERS),
        ],
        "responses_models": list(CONFIGURED_RESPONSES_WEB_SEARCH_MODELS),
        "deepseek_providers": sorted(deepseek_providers),
        "max_providers": MAX_WEB_SEARCH_PROVIDERS,
        "configured_providers": [
            {
                "id": str(row["id"]),
                "provider": str(row["provider"]),
                "family": contract.family.value,
                "execution_mode": contract.execution_mode.value,
                "capabilities": _search_capability_values(contract.capabilities),
            }
            for row, contract in row_contracts
        ],
        "chain": chain,
    }


def _mask_web_run_config(value: Any) -> dict[str, Any]:
    """Return a copy of server.web_run with its bearer token masked."""
    if not isinstance(value, dict):
        return {}
    masked = dict(value)
    if "token" in masked:
        masked["token"] = _mask_api_key(str(masked["token"]))
    return masked


def _mask_server_config(value: Any) -> dict[str, Any]:
    """Return a copy of server config with sensitive admin values masked."""
    server = dict(value) if isinstance(value, dict) else {}
    server.pop("admin_password", None)
    if "api_key" in server:
        server["api_key"] = _mask_api_key(server["api_key"])
    if "api_keys" in server:
        server["api_keys"] = [
            {**entry, "key": _mask_api_key(entry.get("key", ""))}
            for entry in server["api_keys"]
        ]
    if "web_search" in server:
        server["web_search"] = _mask_web_search_config(server["web_search"])
    if "web_run" in server:
        server["web_run"] = _mask_web_run_config(server["web_run"])
    return server


def _apply_local_mode_server_settings(
    server: dict[str, Any], body: dict[str, Any]
) -> Response | None:
    if "local_mode" not in body:
        return None
    local_mode = body["local_mode"]
    if not isinstance(local_mode, bool):
        return JSONResponse(
            {"error": "'local_mode' must be a boolean"}, status_code=400
        )
    if local_mode and not bool(server.get("local_mode_confirmed", False)):
        if body.get("local_mode_confirmed") is not True:
            return JSONResponse(
                {
                    "error": (
                        "Enabling local mode for the first time requires "
                        "explicit confirmation"
                    )
                },
                status_code=400,
            )
        server["local_mode_confirmed"] = True
    server["local_mode"] = local_mode
    return None


def _apply_canonical_web_search(
    server: dict[str, Any], incoming: dict[str, Any]
) -> Response | None:
    """Validate canonical rows and merge masked Tavily credentials by ID."""
    unsupported = set(incoming) - {"providers"}
    if unsupported or "providers" not in incoming:
        return JSONResponse(
            {"error": "'web_search' must contain only 'providers'"},
            status_code=400,
        )
    rows = incoming.get("providers")
    if not isinstance(rows, list):
        return JSONResponse(
            {"error": "'web_search.providers' must be a list"}, status_code=400
        )
    current = server.get("web_search")
    current_rows = (
        [row for row in current["providers"] if isinstance(row, dict)]
        if isinstance(current, dict) and isinstance(current.get("providers"), list)
        else []
    )
    current_by_id = {str(row.get("id")): row for row in current_rows}
    merged: list[dict[str, Any]] = []
    for index, value in enumerate(rows):
        if not isinstance(value, dict):
            return JSONResponse(
                {"error": f"'web_search.providers[{index}]' must be an object"},
                status_code=400,
            )
        row = dict(value)
        if row.get("provider") == "tavily":
            key = row.get("tavily_api_key")
            if not isinstance(key, str):
                return JSONResponse(
                    {
                        "error": f"'web_search.providers[{index}].tavily_api_key' must be a string"
                    },
                    status_code=400,
                )
            if "***" in key:
                row_id = row.get("id")
                existing = current_by_id.get(str(row_id))
                existing_key = existing.get("tavily_api_key") if existing else None
                if (
                    not isinstance(existing_key, str)
                    or _mask_api_key(existing_key) != key
                ):
                    return JSONResponse(
                        {
                            "error": f"'web_search.providers[{index}].tavily_api_key' mask does not match saved credential"
                        },
                        status_code=400,
                    )
                row["tavily_api_key"] = existing_key
        merged.append(row)
    try:
        server["web_search"] = dict(normalize_web_search({"providers": merged}))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return None


def _apply_web_search_settings(
    server: dict[str, Any], body: dict[str, Any]
) -> Response | None:
    """Merge and validate an Admin edit into canonical ``server.web_search``."""
    if "web_search" not in body:
        return None
    incoming = body.get("web_search")
    if not isinstance(incoming, dict):
        return JSONResponse(
            {"error": "'web_search' must be an object"}, status_code=400
        )
    return _apply_canonical_web_search(server, incoming)


def _get_gateway_config(request: Any) -> GatewayConfig | None:
    """Return the live GatewayConfig owned by this app instance."""
    return getattr(request.app, "gateway_config", None)


def _get_version() -> str:
    """Return the codex-rosetta package version."""
    try:
        from codex_rosetta import __version__

        return __version__
    except Exception:
        return "unknown"


def _normalize_model_entry(
    value: Any,
    *,
    model_name: str = "",
    group_provider: str | None = None,
) -> dict[str, Any]:
    """Return a model config entry in admin-UI dict form."""
    entry: dict[str, Any]
    if group_provider is not None:
        entry = {"provider": group_provider}
        if isinstance(value, str):
            if value:
                entry["upstream_model"] = value
            return entry
        if not isinstance(value, dict):
            return entry
        if value.get("upstream_model"):
            entry["upstream_model"] = value["upstream_model"]
        if isinstance(value.get("model_info"), dict):
            entry["model_info"] = value["model_info"]
        if isinstance(value.get("runtime_capabilities"), dict):
            entry["runtime_capabilities"] = value["runtime_capabilities"]
    elif isinstance(value, str):
        entry = {"provider": value}
    elif isinstance(value, dict):
        entry = {"provider": value.get("provider", "")}
        if value.get("upstream_model"):
            entry["upstream_model"] = value["upstream_model"]
        if isinstance(value.get("model_info"), dict):
            entry["model_info"] = value["model_info"]
        if isinstance(value.get("runtime_capabilities"), dict):
            entry["runtime_capabilities"] = value["runtime_capabilities"]
    else:
        return {}

    return entry


def _normalize_models_for_admin(
    raw_models: dict[str, Any],
) -> dict[str, Any]:
    """Normalize the expanded runtime model view for admin consumers."""
    normalized: dict[str, Any] = {}
    for name, value in raw_models.items():
        entry = _normalize_model_entry(value, model_name=name)
        if not entry:
            continue
        normalized[name] = entry
    return normalized


def _resolved_admin_model_entry(
    model_name: str,
    model_value: Any,
    *,
    provider: str,
    provider_config: dict[str, Any],
) -> dict[str, Any]:
    """Resolve one persisted model entry for Admin display."""

    entry = _normalize_model_entry(
        model_value,
        model_name=model_name,
        group_provider=provider,
    )
    entry.pop("provider", None)
    try:
        profile = resolve_model_profile(
            exposed_model=model_name,
            upstream_model=entry.get("upstream_model"),
            provider_id=provider_config.get("provider", "custom"),
            model_info_override=entry.get("model_info"),
            runtime_capabilities_override=entry.get("runtime_capabilities"),
        )
    except ValueError as exc:
        entry["validation_error"] = str(exc)
        return entry

    model_info = editable_model_info(profile.catalog_model())
    if "identity" not in model_info:
        editable_preset = detect_model_preset(model_name, profile.upstream_model)
        if editable_preset is not None:
            model_info["identity"] = editable_preset["identity"]
    entry["model_info"] = model_info
    entry["preset_slug"] = profile.preset_slug
    model_diff, runtime_diff = canonical_model_overrides(profile)
    entry["has_overrides"] = bool(model_diff or runtime_diff)
    if entry["has_overrides"]:
        entry["runtime_capabilities"] = dict(profile.runtime_capabilities)
    return entry


def _normalize_model_groups_for_admin(
    raw_model_groups: dict[str, Any],
    raw_providers: dict[str, Any],
    provider_errors: dict[str, str],
) -> dict[str, Any]:
    """Normalize model group config for admin UI consumption."""
    groups: dict[str, Any] = {}
    if not isinstance(raw_model_groups, dict):
        return groups

    for group_name, group_value in raw_model_groups.items():
        if not isinstance(group_value, dict):
            continue
        try:
            provider = active_model_group_provider(
                group_value.get("provider"),
                field=f"model_groups.{group_name}.provider",
            )
            group_provider_error = None
        except ValueError as exc:
            provider = ""
            group_provider_error = str(exc)
        group_type = group_value.get("type", "")
        raw_group_models = group_value.get("models", {})
        models: dict[str, Any] = {}
        if isinstance(raw_group_models, dict):
            provider_config = raw_providers.get(provider, {})
            for model_name, model_value in raw_group_models.items():
                models[model_name] = _resolved_admin_model_entry(
                    model_name,
                    model_value,
                    provider=provider,
                    provider_config=provider_config,
                )
        normalized_group = {
            "provider": provider,
            "type": group_type,
            "models": models,
        }
        if group_provider_error:
            normalized_group["validation_error"] = group_provider_error
        provider_error = provider_errors.get(provider)
        if provider_error and not group_provider_error:
            normalized_group["validation_error"] = provider_error
        provider_config = raw_providers.get(provider)
        try:
            api_type = (
                resolve_provider_api_type(provider, provider_config)
                if isinstance(provider, str) and isinstance(provider_config, dict)
                else None
            )
        except ValueError:
            api_type = None
        if group_type == "llm" and provider_supports_tool_profiles(
            provider_config, api_type=api_type
        ):
            tool_profile = group_value.get(
                "tool_profile",
                default_tool_profile_for_provider(raw_providers.get(provider)),
            )
            if tool_profile is not None:
                normalized_group["tool_profile"] = tool_profile
        groups[group_name] = normalized_group
    return groups


def _clean_group_model_entry(
    model_name: str, value: Any, *, provider_id: str
) -> dict[str, Any]:
    """Normalize one model entry inside a model group request."""
    if isinstance(value, str):
        value = {"upstream_model": value} if value else {}
    elif not isinstance(value, dict):
        raise ValueError("model entries must be objects or strings")

    entry: dict[str, Any] = {}
    upstream_model = str(value.get("upstream_model") or "").strip()
    if upstream_model:
        entry["upstream_model"] = upstream_model

    profile = resolve_model_profile(
        exposed_model=model_name,
        upstream_model=entry.get("upstream_model"),
        provider_id=provider_id,
        model_info_override=value.get("model_info"),
        runtime_capabilities_override=value.get("runtime_capabilities"),
    )
    model_info, runtime_capabilities = canonical_model_overrides(profile)
    if model_info:
        entry["model_info"] = model_info
    if runtime_capabilities:
        entry["runtime_capabilities"] = runtime_capabilities

    return entry


def _model_group_model_names(
    model_groups: dict[str, Any],
    *,
    exclude_group: str | None = None,
) -> set[str]:
    """Return downstream model names defined by model groups."""
    names: set[str] = set()
    if not isinstance(model_groups, dict):
        return names
    for group_name, group_value in model_groups.items():
        if exclude_group and group_name == exclude_group:
            continue
        if not isinstance(group_value, dict):
            continue
        group_models = group_value.get("models", {})
        if isinstance(group_models, dict):
            names.update(str(name) for name in group_models)
    return names


def _handle_model_group_rename(
    model_groups: dict[str, Any], rename_from: str | None, name: str
) -> Response | None:
    """Apply model group rename validation and mutation."""
    if not rename_from or rename_from == name:
        return None

    if rename_from not in model_groups:
        return JSONResponse(
            {"error": f"Original model group '{rename_from}' not found"},
            status_code=404,
        )
    if name in model_groups:
        return JSONResponse(
            {"error": f"Model group '{name}' already exists"},
            status_code=409,
        )
    model_groups[name] = model_groups.pop(rename_from)
    return None


def _clean_group_models(
    models_body: dict[str, Any], *, provider_id: str
) -> dict[str, Any]:
    """Normalize all model entries from a model group request."""
    cleaned_models: dict[str, Any] = {}
    for model_name, model_value in models_body.items():
        clean_name = str(model_name).strip()
        if not clean_name:
            continue
        cleaned_models[clean_name] = _clean_group_model_entry(
            clean_name, model_value, provider_id=provider_id
        )
    return cleaned_models


def _updated_model_group_providers(
    model_groups: dict[str, Any], group_name: str, active_provider: str
) -> list[str]:
    """Replace the active provider while preserving an existing hidden tail."""
    existing_group = model_groups.get(group_name)
    if not isinstance(existing_group, dict):
        return [active_provider]
    try:
        existing_providers = model_group_provider_names(
            existing_group.get("provider"),
            field=f"model_groups.{group_name}.provider",
        )
    except ValueError:
        return [active_provider]
    return [active_provider, *existing_providers[1:]]


def _model_group_duplicate_response(
    model_groups: dict[str, Any],
    cleaned_models: dict[str, Any],
    *,
    exclude_group: str | None,
) -> Response | None:
    """Return a conflict response when grouped models duplicate other routes."""
    duplicate_group = sorted(
        set(cleaned_models)
        & _model_group_model_names(model_groups, exclude_group=exclude_group)
    )
    if duplicate_group:
        return JSONResponse(
            {
                "error": f"Models already exist in another model group: {duplicate_group}"
            },
            status_code=409,
        )
    return None


def _resolve_model_group_tool_profile(
    data: dict[str, Any],
    provider: str,
    provider_config: Any,
    requested_profile: Any,
    *,
    group_name: str,
) -> tuple[str | None, Response | None]:
    """Validate and resolve the optional protocol-scoped Tool Profile."""
    if not isinstance(provider_config, dict):
        return None, JSONResponse(
            {"error": f"Provider '{provider}' config must be an object"},
            status_code=400,
        )
    try:
        provider_api_type = resolve_provider_api_type(provider, provider_config)
    except ValueError as exc:
        return None, JSONResponse({"error": str(exc)}, status_code=400)
    if not provider_supports_tool_profiles(provider_config, api_type=provider_api_type):
        return None, None
    if requested_profile is None:
        return None, None
    try:
        tool_profiles = normalize_tool_profile_documents(data.get("tool_profiles"))
        tool_profile = validate_tool_profile_reference(
            requested_profile,
            tool_profiles,
            field=f"model group '{group_name}' tool_profile",
            api_type=provider_api_type,
        )
    except ValueError as exc:
        return None, JSONResponse({"error": str(exc)}, status_code=400)
    return tool_profile, None


async def get_config(request: Any) -> Response:
    """Return the current (raw) gateway configuration."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    try:
        raw = load_config_raw(config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)

    # Mask credentials and legacy runtime-only metadata. The persisted
    # ``provider`` supplier remains part of the Admin configuration contract.
    providers = raw.get("providers", {})
    masked_providers: dict[str, Any] = {}
    provider_errors: dict[str, str] = {}
    for name, cfg in providers.items():
        masked = dict(cfg)
        if "api_keys" in masked:
            masked["api_keys"] = [
                {"id": entry["id"], "key": _mask_api_key(entry["key"])}
                for entry in masked["api_keys"]
            ]
        masked.pop("shim", None)
        masked.pop("type", None)
        masked.pop("validation_error", None)
        masked.pop("default_tool_profile", None)
        try:
            api_type = resolve_provider_api_type(name, cfg)
        except ValueError as exc:
            error = str(exc)
            provider_errors[name] = error
            masked["validation_error"] = error
        else:
            runtime_cfg = dict(cfg)
            runtime_cfg["api_type"] = api_type
            masked["api_type"] = api_type
            provider_id = cfg.get("provider")
            if isinstance(provider_id, str):
                try:
                    masked["soft_interrupt"] = resolve_soft_interrupt(
                        provider_id,
                        api_type,
                        *([cfg["soft_interrupt"]] if "soft_interrupt" in cfg else []),
                    )
                except ValueError as exc:
                    error = str(exc)
                    provider_errors[name] = error
                    masked["validation_error"] = error
            masked["default_tool_profile"] = default_tool_profile_for_provider(
                runtime_cfg
            )
            runtime_provider = request.app.gateway_config.providers.get(name)
            if runtime_provider is not None:
                masked["base_url_statuses"] = [
                    {
                        "base_url": base_url,
                        "current": base_url == runtime_provider.base_url,
                        "status": status,
                    }
                    for base_url, status in runtime_provider.base_url_statuses()
                ]
                masked["credential_statuses"] = [
                    {
                        "id": credential_id,
                        "current": credential_id
                        == runtime_provider.current_credential_id,
                        "status": status,
                    }
                    for credential_id, status in runtime_provider.credential_statuses()
                ]
        masked_providers[name] = masked

    # ``models`` is an effective read-only runtime view. ``model_groups`` is
    # the sole persisted management view.
    raw_model_groups = raw.get("model_groups", {}) or {}
    expanded_raw_models = GatewayConfig._expand_model_groups(raw_model_groups)
    models_normalized = _normalize_models_for_admin(expanded_raw_models)
    model_groups = _normalize_model_groups_for_admin(
        raw_model_groups, providers, provider_errors
    )
    tool_profiles = normalize_tool_profile_documents(raw.get("tool_profiles"))
    tool_profile_input_overrides = normalize_tool_profile_input_overrides(
        raw.get("tool_profile_input_overrides")
    )
    editable_presets = {preset["slug"]: preset for preset in model_presets_for_admin()}

    config: GatewayConfig = request.app.gateway_config
    server = _mask_server_config(raw.get("server", {}))
    server.setdefault("request_body_limit_mb", config.request_body_limit_config_value)
    server.setdefault("local_mode", config.local_mode)
    server.setdefault("local_mode_confirmed", config.local_mode_confirmed)
    codex_home = getattr(request.app, "codex_home", "")
    return JSONResponse(
        {
            "config_path": config_path,
            "codex_home": codex_home,
            "model_catalog_configured": bool(
                codex_home and config_toml_has_model_catalog(codex_home)
            ),
            "providers": masked_providers,
            "models": models_normalized,
            "model_groups": model_groups,
            "tool_profiles": tool_profiles,
            "tool_profile_input_overrides": tool_profile_input_overrides,
            "tool_profile_presets": [
                {
                    "id": profile["id"],
                    "name": profile["name"],
                    "api_types": list(profile["api_types"]),
                }
                for profile in tool_profile_contract()["profiles"]
            ],
            "tool_profile_passthrough_option": {
                "id": TOOL_PROFILE_PASSTHROUGH_OPTION,
                "api_types": ["responses"],
            },
            "model_presets": [
                dict(
                    editable_model_info(model),
                    identity=editable_presets[slug]["identity"],
                )
                for slug, model in full_model_presets().items()
            ],
            "provider_catalog": provider_catalog_for_admin(),
            "web_search_contract": _web_search_contract_for_admin(
                raw.get("server", {}).get("web_search")
                if isinstance(raw.get("server"), dict)
                else None,
                providers=config.providers,
                provider_api_types={
                    str(name): str(entry.get("api_type", ""))
                    for name, entry in (
                        raw.get("providers", {}).items()
                        if isinstance(raw.get("providers"), dict)
                        else ()
                    )
                    if isinstance(entry, dict)
                },
            ),
            "codex": config.codex,
            "server": server,
            "credential_visible": config.credential_visible,
            "version": _get_version(),
            "known_api_types": list(API_TYPE_ORDER),
            "registered_shims": [
                {
                    "name": s.name,
                    "base": s.base,
                    "logo": s.logo,
                    "default_base_url": s.default_base_url,
                    "default_api_key_env": s.default_api_key_env,
                }
                for s in builtin_provider_shims().values()
            ],
        }
    )


async def put_provider(request: Any, **kwargs: Any) -> Response:
    """Add or update a provider entry."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    name = request.path_params["name"]

    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body

    api_keys = body.get("api_keys")
    current_api_key = body.get("current_api_key")
    base_urls = body.get("base_urls")
    current_base_url = body.get("current_base_url")
    provider = body.get("provider")

    try:
        data = load_config_raw(config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)

    existing_providers = data.get("providers", {})
    resolve_name = body.get("rename_from", name) or name
    is_new_provider = name not in existing_providers

    existing_provider = existing_providers.get(resolve_name, {})
    if api_keys is None and existing_provider:
        api_keys = existing_provider.get("api_keys")
        current_api_key = current_api_key or existing_provider.get("current_api_key")
    try:
        merged_keys = _resolve_draft_provider_api_keys(api_keys, existing_provider)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if (
        not merged_keys
        or any(not entry["key"] for entry in merged_keys)
        or len({entry["id"] for entry in merged_keys}) != len(merged_keys)
        or not isinstance(current_api_key, str)
        or current_api_key not in {entry["id"] for entry in merged_keys}
        or not isinstance(base_urls, list)
        or not base_urls
        or any(not isinstance(value, str) or not value for value in base_urls)
        or not isinstance(current_base_url, str)
        or current_base_url not in base_urls
        or not isinstance(provider, str)
        or not provider.strip()
    ):
        return JSONResponse(
            {
                "error": (
                    "non-empty unique 'api_keys', member 'current_api_key', "
                    "non-empty 'base_urls', member 'current_base_url', and "
                    "'provider' are required"
                )
            },
            status_code=400,
        )
    body["provider"] = provider.strip()

    provider_entry = _build_provider_entry(
        body,
        merged_keys,
        current_api_key,
        base_urls,
        current_base_url,
        existing_providers,
        resolve_name,
    )

    # Handle rename: remove old entry and update model references
    rename_from = body.get("rename_from")
    is_rename = bool(rename_from and rename_from != name)
    if is_rename:
        rename_err = _handle_provider_rename(data, rename_from, name)
        if rename_err is not None:
            return rename_err

    data.setdefault("providers", {})[name] = provider_entry
    if is_new_provider or is_rename:
        data["providers"] = dict(
            sorted(
                data["providers"].items(),
                key=lambda item: (item[0].casefold(), item[0]),
            )
        )

    new_config, commit_error = _commit_gateway_config(request, config_path, data)
    if commit_error is not None:
        return commit_error
    assert new_config is not None

    return JSONResponse(
        {
            "ok": True,
            "provider": name,
            "providers": list(new_config.providers.keys()),
        }
    )


def _resolve_draft_provider_api_keys(
    api_keys: Any,
    existing_provider: Mapping[str, Any],
    resolved_provider: Mapping[str, Any] | None = None,
    *,
    resolve_saved_credentials: bool = False,
) -> list[dict[str, str]]:
    """Resolve canonical draft credentials, including matching saved masks."""
    existing_keys = {
        entry.get("id"): entry.get("key")
        for entry in existing_provider.get("api_keys", [])
        if isinstance(entry, dict)
    }
    resolved_keys = {
        entry.get("id"): entry.get("key")
        for entry in (resolved_provider or {}).get("api_keys", [])
        if isinstance(entry, dict)
    }
    if not isinstance(api_keys, list):
        raise ValueError("'api_keys' must be a list")
    merged_keys: list[dict[str, str]] = []
    for index, entry in enumerate(api_keys):
        credential_id_value = entry.get("id") if isinstance(entry, dict) else None
        key_value = entry.get("key") if isinstance(entry, dict) else None
        if (
            not isinstance(entry, dict)
            or not isinstance(credential_id_value, str)
            or not credential_id_value.strip()
            or not isinstance(key_value, str)
        ):
            raise ValueError(f"'api_keys[{index}]' must contain string 'id' and 'key'")
        credential_id = credential_id_value.strip()
        key = key_value.strip()
        saved_key = existing_keys.get(credential_id)
        uses_saved_credential = False
        if "***" in key:
            if not isinstance(saved_key, str) or _mask_api_key(saved_key) != key:
                raise ValueError(
                    f"'api_keys[{index}].key' mask does not match saved credential"
                )
            uses_saved_credential = True
        elif resolve_saved_credentials and _ENV_VAR_RE.fullmatch(key):
            if not isinstance(saved_key, str) or saved_key != key:
                raise ValueError(
                    f"'api_keys[{index}].key' environment placeholder does not "
                    "match saved credential"
                )
            uses_saved_credential = True
        if uses_saved_credential:
            if resolve_saved_credentials:
                resolved_key = resolved_keys.get(credential_id)
                if not isinstance(resolved_key, str) or not resolved_key:
                    raise ValueError(
                        f"'api_keys[{index}].key' saved credential is not available "
                        "in the resolved Gateway config"
                    )
                key = resolved_key
            else:
                key = cast(str, saved_key)
        merged_keys.append({"id": credential_id, "key": key})
    return merged_keys


async def detect_provider_request_encoding(request: Any, **kwargs: Any) -> Response:
    """Probe identity and Zstd against only the selected Responses draft endpoint."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body
    if body.get("api_type") != "responses":
        return JSONResponse(
            {"error": "Request encoding detection requires api_type 'responses'"},
            status_code=400,
        )

    name = request.path_params["name"]
    model = body.get("model")
    provider = body.get("provider")
    current_base_url = body.get("current_base_url")
    current_api_key = body.get("current_api_key")
    proxy = body.get("proxy", "")
    allow_redirects = body.get("allow_redirects", False)
    if (
        not isinstance(model, str)
        or not model.strip()
        or not isinstance(provider, str)
        or not provider.strip()
        or not isinstance(current_base_url, str)
        or not current_base_url.startswith(("http://", "https://"))
        or not isinstance(current_api_key, str)
        or not current_api_key.strip()
        or not isinstance(proxy, str)
        or not isinstance(allow_redirects, bool)
    ):
        return JSONResponse(
            {
                "error": (
                    "non-empty 'model', 'provider', HTTP(S) 'current_base_url', "
                    "and 'current_api_key' plus string 'proxy' and boolean "
                    "'allow_redirects' are required"
                )
            },
            status_code=400,
        )

    try:
        data = load_config_raw(config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)
    existing_providers = data.get("providers", {})
    resolve_name = body.get("rename_from", name) or name
    existing_provider = existing_providers.get(resolve_name, {})
    resolved_provider = _substitute_env_vars(existing_provider)
    try:
        resolved_keys = _resolve_draft_provider_api_keys(
            body.get("api_keys"),
            existing_provider,
            resolved_provider,
            resolve_saved_credentials=True,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    selected_keys = [
        entry for entry in resolved_keys if entry["id"] == current_api_key.strip()
    ]
    if len(selected_keys) != 1 or not selected_keys[0]["key"]:
        return JSONResponse(
            {"error": "'current_api_key' must select one non-empty draft credential"},
            status_code=400,
        )

    provider_config = {
        "provider": provider.strip(),
        "api_type": "responses",
        "base_urls": [current_base_url],
        "current_base_url": current_base_url,
        "api_keys": selected_keys,
        "current_api_key": current_api_key.strip(),
        "proxy": proxy.strip(),
        "allow_redirects": allow_redirects,
    }
    try:
        provider_type, _shim_name = resolve_provider_config_type_and_shim(
            name, provider_config
        )
        if provider_type != "openai_responses":
            raise ValueError("draft does not resolve to the Responses protocol")
        identity_provider = build_provider_info(
            provider_type,
            {**provider_config, "request_encoding": "identity"},
            configured_id=name,
            global_proxy=request.app.gateway_config.proxy,
        )
        zstd_provider = build_provider_info(
            provider_type,
            {**provider_config, "request_encoding": "zstd"},
            configured_id=name,
            global_proxy=request.app.gateway_config.proxy,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    result = await detect_responses_request_encoding(
        request.app.transport,
        identity_provider=identity_provider,
        zstd_provider=zstd_provider,
        model=model.strip(),
    )
    redactor = SecretRedactor(
        {*request.app.gateway_config.token_values, selected_keys[0]["key"]}
    )
    payload = result.to_dict()
    for probe_name in ("identity", "zstd"):
        error = payload[probe_name]["error"]
        if error is not None:
            payload[probe_name]["error"] = redactor.redact(error)
    return JSONResponse(payload)


async def select_provider_base_url(request: Any, **kwargs: Any) -> Response:
    """Select one Provider URL or credential without rebuilding runtime state."""
    name = request.path_params["name"]
    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body
    if set(body) not in ({"current_base_url"}, {"credential_id"}):
        return JSONResponse(
            {
                "error": (
                    "exactly one of 'current_base_url' or 'credential_id' "
                    "must be provided"
                )
            },
            status_code=400,
        )
    selected = next(iter(body.values()))
    if not isinstance(selected, str):
        return JSONResponse(
            {"error": "the selected value must be a string"}, status_code=400
        )
    provider = request.app.gateway_config.providers.get(name)
    if provider is None:
        return JSONResponse({"error": f"Provider '{name}' not found"}, status_code=404)
    try:
        if "current_base_url" in body:
            await provider.manually_select_base_url(body["current_base_url"])
        else:
            await provider.manually_select_credential(body["credential_id"])
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return JSONResponse({"ok": True, "provider": name})


async def delete_provider(request: Any, **kwargs: Any) -> Response:
    """Remove a provider entry."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    name = request.path_params["name"]

    try:
        data = load_config_raw(config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)

    providers = data.get("providers", {})
    if name not in providers:
        return JSONResponse({"error": f"Provider '{name}' not found"}, status_code=404)

    # Check if any model group still references this provider.
    raw_model_groups = data.get("model_groups", {})
    model_groups = raw_model_groups if isinstance(raw_model_groups, dict) else {}
    referencing_groups = [
        group_name
        for group_name, group in model_groups.items()
        if isinstance(group, dict)
        and isinstance(group.get("provider"), list)
        and name in group["provider"]
    ]

    from ._shared import _qp

    cascade = _qp(request, "cascade") in ("true", "1")
    if referencing_groups and not cascade:
        return JSONResponse(
            {
                "error": (
                    f"Cannot delete provider '{name}': referenced by model groups: "
                    f"{referencing_groups}"
                )
            },
            status_code=409,
        )

    server = data.get("server")
    web_search = server.get("web_search") if isinstance(server, dict) else None
    search_references: list[str] = []
    if isinstance(web_search, dict):
        rows = web_search.get("providers")
        if isinstance(rows, list):
            search_references = [
                str(row.get("id"))
                for row in rows
                if isinstance(row, dict)
                and (
                    row.get("responses_provider") == name
                    or row.get("deepseek_provider") == name
                )
            ]
    if search_references:
        return JSONResponse(
            {
                "error": (
                    f"Cannot delete provider '{name}': referenced by web search rows: "
                    f"{search_references}"
                )
            },
            status_code=409,
        )
    cascade_deleted_groups: list[str] = []
    if referencing_groups and cascade:
        for group_name in referencing_groups:
            del model_groups[group_name]
            cascade_deleted_groups.append(group_name)

    del providers[name]

    new_config, commit_error = _commit_gateway_config(request, config_path, data)
    if commit_error is not None:
        return commit_error
    assert new_config is not None

    result: dict[str, Any] = {
        "ok": True,
        "deleted": name,
        "providers": list(new_config.providers.keys()),
    }
    if cascade_deleted_groups:
        result["cascade_deleted_model_groups"] = cascade_deleted_groups
    return JSONResponse(result)


async def toggle_provider(request: Any, **kwargs: Any) -> Response:
    """Toggle a provider's enabled/disabled state."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    name = request.path_params["name"]

    try:
        data = load_config_raw(config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)

    providers = data.get("providers", {})
    if name not in providers:
        return JSONResponse({"error": f"Provider '{name}' not found"}, status_code=404)

    # Toggle: if currently enabled (or unset → default True), disable; otherwise enable
    currently_enabled = providers[name].get("enabled", True)
    new_enabled = not currently_enabled

    if new_enabled:
        # Remove the key entirely when re-enabling (True is the default)
        providers[name].pop("enabled", None)
    else:
        providers[name]["enabled"] = False

    _, commit_error = _commit_gateway_config(request, config_path, data)
    if commit_error is not None:
        return commit_error

    return JSONResponse({"ok": True, "provider": name, "enabled": new_enabled})


async def put_model_group(request: Any, **kwargs: Any) -> Response:
    """Add or update a grouped set of model routing entries."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    name = request.path_params["name"]

    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body

    provider = body.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        return JSONResponse({"error": "'provider' is required"}, status_code=400)
    provider = provider.strip()

    group_type = body.get("type")
    if group_type != "llm":
        return JSONResponse({"error": "'type' must be 'llm'"}, status_code=400)

    models_body = body.get("models", {})
    if not isinstance(models_body, dict):
        return JSONResponse({"error": "'models' must be an object"}, status_code=400)

    try:
        data = load_config_raw(config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)

    providers = data.get("providers", {})
    if provider not in providers:
        return JSONResponse(
            {"error": f"Provider '{provider}' not found in config"}, status_code=400
        )

    model_groups = data.setdefault("model_groups", {})
    if not isinstance(model_groups, dict):
        return JSONResponse(
            {"error": "'model_groups' must be an object"}, status_code=400
        )

    rename_from = body.get("rename_from")
    rename_error = _handle_model_group_rename(model_groups, rename_from, name)
    if rename_error is not None:
        return rename_error

    try:
        provider_id = providers[provider].get("provider")
        if not isinstance(provider_id, str):
            raise ValueError(
                f"provider {provider!r} has no recognized provider main identity"
            )
        cleaned_models = _clean_group_models(models_body, provider_id=provider_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    duplicate_error = _model_group_duplicate_response(
        model_groups,
        cleaned_models,
        exclude_group=name,
    )
    if duplicate_error is not None:
        return duplicate_error

    provider_config = (data.get("providers", {}) or {}).get(provider)
    tool_profile, profile_error = _resolve_model_group_tool_profile(
        data,
        provider,
        provider_config,
        body.get("tool_profile", default_tool_profile_for_provider(provider_config)),
        group_name=name,
    )
    if profile_error is not None:
        return profile_error

    model_groups[name] = {
        "provider": _updated_model_group_providers(model_groups, name, provider),
        "type": group_type,
        **({"tool_profile": tool_profile} if tool_profile is not None else {}),
        "models": cleaned_models,
    }

    new_config, commit_error = _commit_gateway_config(request, config_path, data)
    if commit_error is not None:
        return commit_error
    assert new_config is not None

    return JSONResponse(
        {
            "ok": True,
            "model_group": name,
            "provider": provider,
            "type": group_type,
            "models": dict(new_config.models),
        }
    )


async def delete_model_group(request: Any, **kwargs: Any) -> Response:
    """Remove a model group and its grouped model mappings."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    name = request.path_params["name"]

    try:
        data = load_config_raw(config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)

    model_groups = data.get("model_groups", {})
    if not isinstance(model_groups, dict) or name not in model_groups:
        return JSONResponse(
            {"error": f"Model group '{name}' not found"}, status_code=404
        )

    del model_groups[name]

    new_config, commit_error = _commit_gateway_config(request, config_path, data)
    if commit_error is not None:
        return commit_error
    assert new_config is not None

    return JSONResponse(
        {
            "ok": True,
            "deleted": name,
            "models": dict(new_config.models),
        }
    )


async def put_server_settings(request: Any) -> Response:
    """Update server settings (e.g. global proxy)."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body

    try:
        data = load_config_raw(config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)

    server = data.setdefault("server", {})

    # Update proxy — empty string removes it
    if "proxy" in body:
        proxy = body["proxy"]
        if proxy:
            server["proxy"] = proxy
        else:
            server.pop("proxy", None)

    if "request_body_limit_mb" in body:
        server["request_body_limit_mb"] = body["request_body_limit_mb"]

    local_mode_error = _apply_local_mode_server_settings(server, body)
    if local_mode_error is not None:
        return local_mode_error

    web_search_error = _apply_web_search_settings(server, body)
    if web_search_error is not None:
        return web_search_error

    if "stream_trace" in body:
        stream_trace = body.get("stream_trace") or {}
        if not isinstance(stream_trace, dict):
            return JSONResponse(
                {"error": "'stream_trace' must be an object"}, status_code=400
            )

        try:
            max_string_chars = int(
                stream_trace.get("max_string_chars", DEFAULT_MAX_CHARS)
            )
        except TypeError, ValueError:
            return JSONResponse(
                {"error": "'stream_trace.max_string_chars' must be an integer"},
                status_code=400,
            )
        if max_string_chars <= 0:
            max_string_chars = DEFAULT_MAX_CHARS

        next_trace = {
            "enabled": bool(stream_trace.get("enabled", False)),
            "filter": str(stream_trace.get("filter", "") or "").strip(),
            "path": str(stream_trace.get("path", "") or "").strip(),
            "max_string_chars": max_string_chars,
        }
        server["stream_trace"] = next_trace

    _, commit_error = _commit_gateway_config(request, config_path, data)
    if commit_error is not None:
        return commit_error

    response_server = _mask_server_config(data.get("server", {}))
    return JSONResponse({"ok": True, "server": response_server})


async def put_codex_settings(request: Any) -> Response:
    """Persist Codex task-model overrides and synchronize local-mode files."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    body = _parse_json_object(request)
    if isinstance(body, Response):
        return body
    try:
        normalized = normalize_codex_settings(body)
        data = load_config_raw(config_path)
        local_mode, confirmed = normalize_local_mode_settings(data.get("server"))
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Failed to read config: {exc}"}, status_code=500)

    if not local_mode or not confirmed:
        return JSONResponse(
            {"error": "Codex task models require confirmed local mode"},
            status_code=409,
        )
    if normalized:
        data["codex"] = normalized
    else:
        data.pop("codex", None)

    new_config, commit_error = _commit_gateway_config(request, config_path, data)
    if commit_error is not None:
        return commit_error
    assert new_config is not None
    return JSONResponse({"ok": True, "codex": new_config.codex})


async def reload_config(request: Any) -> Response:
    """Force hot-reload of the config from disk."""
    config_path = _get_config_path(request)
    if not config_path:
        return JSONResponse({"error": "No config file path available"}, status_code=500)

    try:
        new_config = _reload_gateway_config(request, config_path)
    except Exception as exc:
        return JSONResponse({"error": f"Reload failed: {exc}"}, status_code=500)

    return JSONResponse(
        {
            "ok": True,
            "providers": list(new_config.providers.keys()),
            "models": dict(new_config.models),
        }
    )


def _format_connection_error(exc: Exception, url: str) -> str:
    """Return a user-friendly message for common upstream connection errors."""
    err_str = str(exc)
    if "Connection refused" in err_str or "Errno 111" in err_str:
        return (
            f"Connection refused at {url}. "
            "Check that the service is running and the port is correct. "
            "If running in Docker, ensure the host firewall (e.g. ufw) "
            "allows connections from the Docker bridge network."
        )
    if "timed out" in err_str.lower():
        return (
            f"Connection to {url} timed out. "
            "Check that the host/port is reachable from this container."
        )
    if "Name or service not known" in err_str or "getaddrinfo" in err_str:
        return f"Cannot resolve hostname in {url}. Check the Base URL."
    return f"Failed to connect to upstream: {err_str}"


def _invalid_model_list_response() -> JSONResponse:
    """Return a stable error for a provider model-list schema mismatch."""
    return JSONResponse({"error": "Upstream returned an invalid model list"})


def _credential_collision_response() -> JSONResponse:
    """Return a stable error for an ambiguous provider credential collision."""
    return JSONResponse(
        {
            "error": (
                "Upstream model list contains a configured credential; response blocked"
            )
        }
    )


def _normalize_upstream_model_ids(
    body: dict[str, Any],
    *,
    provider_type: str,
    id_field: str | None,
) -> list[str] | None:
    """Validate one provider model-list schema and return sorted model IDs."""
    collection_key = "models" if provider_type == "google" else "data"
    models = body.get(collection_key)
    if not isinstance(models, list):
        return None

    model_ids: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            return None
        fallback_key = "name" if provider_type == "google" else "id"
        fallback_id = model.get(fallback_key, "")
        if not isinstance(fallback_id, str):
            return None
        if provider_type == "google" and fallback_id.startswith("models/"):
            fallback_id = fallback_id[len("models/") :]
        model_id = model.get(id_field, fallback_id) if id_field else fallback_id
        if not isinstance(model_id, str):
            return None
        if model_id:
            model_ids.append(model_id)

    model_ids.sort()
    return model_ids


async def fetch_upstream_models(request: Any, **kwargs: Any) -> Response:
    """Fetch the model list from an upstream provider's /v1/models endpoint."""
    from codex_rosetta.shims import get_shim

    provider_name = request.path_params["name"]
    config = _get_gateway_config(request)
    if config is None:
        return JSONResponse({"error": "Gateway config not loaded"}, status_code=500)

    if provider_name not in config.providers:
        return JSONResponse(
            {"error": f"Provider '{provider_name}' not found"}, status_code=404
        )

    pinfo = config.providers[provider_name]
    ptype = config.provider_types.get(provider_name, "unknown")
    redactor = SecretRedactor(config.token_values)

    # Build the models listing URL based on provider type
    if ptype == "google":
        models_url = f"{pinfo.base_url}/v1beta/models"
    elif ptype == "anthropic":
        models_url = f"{pinfo.base_url}/v1/models"
    else:
        # OpenAI-compatible (openai_chat, openai_responses, etc.)
        models_url = f"{pinfo.base_url}/models"

    try:
        resp = await asyncio.wait_for(
            request.app.transport.send_passthrough(
                pinfo,
                models_url,
                {},
                method="GET",
            ),
            timeout=_PROVIDER_MODEL_DISCOVERY_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        raise
    except UpstreamProtocolError:
        return JSONResponse({"error": "Upstream returned non-JSON response"})
    except Exception as exc:
        safe_error = RuntimeError(redactor.redact_exact(str(exc)))
        safe_error.__cause__ = None
        safe_error.__context__ = None
        logger.warning("Failed to fetch models from %s: %s", provider_name, safe_error)
        msg = _format_connection_error(safe_error, models_url)
        return JSONResponse({"error": msg})  # 200 so reverse proxies don't intercept

    if not 200 <= resp.status_code < 300:
        logger.warning(
            "Upstream %s returned %d for model listing", provider_name, resp.status_code
        )
        return JSONResponse(
            {
                "error": (
                    f"Upstream returned HTTP {resp.status_code}. "
                    "This provider may not support model listing."
                ),
            },
        )

    try:
        body = resp.body
    except Exception:
        return JSONResponse(
            {"error": "Upstream returned non-JSON response"},
        )
    if redactor.contains_exact(body):
        return _credential_collision_response()
    if not isinstance(body, dict):
        return _invalid_model_list_response()

    # Resolve model_id_field from shim (e.g. Argo uses "internal_id")
    shim_name = config.provider_shim_names.get(provider_name)
    shim = get_shim(shim_name) if shim_name else None
    id_field = shim.model_id_field if shim and shim.model_id_field else None

    model_ids = _normalize_upstream_model_ids(
        body,
        provider_type=ptype,
        id_field=id_field,
    )
    if model_ids is None:
        return _invalid_model_list_response()

    return JSONResponse(
        {
            "provider": provider_name,
            "api_standard": ptype,
            "models": model_ids,
        }
    )
