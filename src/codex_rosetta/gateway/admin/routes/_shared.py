"""Shared helpers used by multiple admin route modules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, overload

from codex_rosetta._vendor.httpserver import JSONResponse, Response

from ...config import (
    ConfigConflictError,
    GatewayConfig,
    load_config,
    write_config,
)
from ...local_mode import (
    CodexLocalModeTransaction,
    codex_api_key_value,
    ensure_codex_api_key,
)
from ..restart_notice import (
    mark_codex_restart_required,
    reset_codex_restart_required,
)

_ENV_VAR_RE = re.compile(r"^\$\{.+\}$")


@overload
def _qp(request: Any, key: str) -> str | None: ...


@overload
def _qp(request: Any, key: str, default: str) -> str: ...


def _qp(request: Any, key: str, default: str | None = None) -> str | None:
    """Extract a single query param value (httpserver convenience)."""
    vals = request.query_params.get(key)
    if vals:
        return vals[0]
    return default


def _bounded_int_qp(
    request: Any,
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int | Response:
    """Parse one bounded integer query parameter or return a 400 response."""
    values = request.query_params.get(key)
    if not values:
        return default
    if len(values) != 1:
        return JSONResponse(
            {"error": f"'{key}' must appear exactly once"},
            status_code=400,
        )
    try:
        value = int(values[0])
    except TypeError, ValueError:
        return JSONResponse(
            {"error": f"'{key}' must be an integer"},
            status_code=400,
        )
    if value < minimum or value > maximum:
        return JSONResponse(
            {"error": f"'{key}' must be between {minimum} and {maximum}"},
            status_code=400,
        )
    return value


def _mask_api_key(value: str) -> str:
    """Mask a literal API key, leaving env-var placeholders intact."""
    if _ENV_VAR_RE.match(value):
        return value
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def _parse_json_object(request: Any) -> dict[str, Any] | Response:
    """Parse one Admin request body and require a JSON object at the root."""
    try:
        value = request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(value, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    return value


def _get_config_path(request: Any) -> str | None:
    """Return the config file path stored on the app object."""
    return getattr(request.app, "config_path", None)


def _reload_gateway_config(request: Any, config_path: str) -> GatewayConfig:
    """Re-read config from disk, rebuild GatewayConfig, swap into app state."""
    raw = load_config(config_path)
    new_config = GatewayConfig(raw)
    _activate_gateway_config(request, new_config)
    return new_config


@dataclass(frozen=True)
class _PreparedGatewayActivation:
    """All runtime state prepared before a config swap begins."""

    auth: tuple[Any, Any] | None
    stream_trace: tuple[Any, Any] | None
    upstream_error_log: tuple[Any, Any] | None
    body_log: tuple[Any, Any] | None
    persistence: tuple[Any, Any] | None
    metrics: tuple[Any, Any] | None
    admin_cors_origins: tuple[str, ...]
    max_body_size: int


@dataclass
class _GatewayActivationRollback:
    """Old runtime state plus committed persistence compensation data."""

    gateway_config: Any
    admin_cors_origins: tuple[str, ...]
    max_body_size: int
    auth: tuple[Any, dict[str, str], dict[str, str], Any, Any] | None
    stream_trace: tuple[Any, Any, Any] | None
    upstream_error_log: tuple[Any, Any] | None
    body_log: tuple[Any, Any, Any] | None
    persistence: tuple[Any, Any] | None
    metrics: tuple[Any, Any] | None


def _prepare_admin_cors_origins(config: GatewayConfig) -> tuple[str, ...]:
    """Prepare the immutable live Admin CORS allowlist."""
    return tuple(config.admin_cors_origins)


def _prepare_gateway_activation(
    request: Any, new_config: GatewayConfig
) -> _PreparedGatewayActivation:
    """Build all dependent runtime state before config persistence begins."""
    app = request.app
    token_values = _runtime_token_values(app, new_config)

    auth_state = getattr(app, "auth_state", None)
    prepared_auth = None
    if auth_state is not None:
        prepared_auth = (
            auth_state,
            auth_state.prepare_update(
                dict(new_config.api_key_principals),
                dict(new_config.api_key_labels),
                new_config.admin_password,
            ),
        )

    stream_trace_state = getattr(app, "stream_trace_state", None)
    prepared_trace = None
    if stream_trace_state is not None:
        prepared_trace = (
            stream_trace_state,
            stream_trace_state.prepare_update(
                new_config.stream_trace,
                token_values=token_values,
            ),
        )

    upstream_error_log_state = getattr(app, "upstream_error_log_state", None)
    prepared_upstream_error_log = None
    if upstream_error_log_state is not None:
        prepared_upstream_error_log = (
            upstream_error_log_state,
            upstream_error_log_state.prepare_update(token_values),
        )

    body_log_state = getattr(app, "body_log_state", None)
    prepared_body_log = None
    if body_log_state is not None:
        prepared_body_log = (
            body_log_state,
            body_log_state.prepare_update(
                enabled=new_config.log_bodies,
                token_values=token_values,
            ),
        )

    persistence = getattr(app, "persistence", None)
    prepared_persistence = None
    if persistence is not None:
        from .. import _resolve_log_caps

        success_max, error_max = _resolve_log_caps(new_config)
        prepared_persistence = (
            persistence,
            persistence.prepare_update(
                token_values,
                success_max=success_max,
                error_max=error_max,
            ),
        )

    metrics = getattr(app, "metrics", None)
    prepared_metrics = None
    if metrics is not None:
        prepared_metrics = (
            metrics,
            metrics.prepare_token_values(token_values),
        )

    return _PreparedGatewayActivation(
        auth=prepared_auth,
        stream_trace=prepared_trace,
        upstream_error_log=prepared_upstream_error_log,
        body_log=prepared_body_log,
        persistence=prepared_persistence,
        metrics=prepared_metrics,
        admin_cors_origins=_prepare_admin_cors_origins(new_config),
        max_body_size=new_config.request_body_limit_bytes,
    )


def _activate_gateway_config(
    request: Any,
    new_config: GatewayConfig,
    prepared: _PreparedGatewayActivation | None = None,
) -> _GatewayActivationRollback:
    """Commit prepared state and return compensation for later write failure."""
    activation = prepared or _prepare_gateway_activation(request, new_config)
    app = request.app
    auth_state = activation.auth[0] if activation.auth is not None else None
    trace_state = (
        activation.stream_trace[0] if activation.stream_trace is not None else None
    )
    upstream_error_log_state = (
        activation.upstream_error_log[0]
        if activation.upstream_error_log is not None
        else None
    )
    body_log_state = activation.body_log[0] if activation.body_log is not None else None
    metrics_state = activation.metrics[0] if activation.metrics is not None else None
    rollback = _GatewayActivationRollback(
        gateway_config=app.gateway_config,
        admin_cors_origins=tuple(getattr(app, "admin_cors_origins", ())),
        max_body_size=getattr(
            app,
            "max_body_size",
            app.gateway_config.request_body_limit_bytes,
        ),
        auth=(
            auth_state,
            auth_state.principals,
            auth_state.labels,
            auth_state.admin_password,
            auth_state.admin_token,
        )
        if auth_state is not None
        else None,
        stream_trace=(trace_state, trace_state.config, trace_state._redactor)
        if trace_state is not None
        else None,
        upstream_error_log=(
            upstream_error_log_state,
            upstream_error_log_state._redactor,
        )
        if upstream_error_log_state is not None
        else None,
        body_log=(
            body_log_state,
            body_log_state.enabled,
            body_log_state._redactor,
        )
        if body_log_state is not None
        else None,
        persistence=None,
        metrics=(metrics_state, metrics_state._redactor)
        if metrics_state is not None
        else None,
    )

    try:
        # Persistence is the only mutating/fallible commit. Apply it first so
        # every later assignment can be compensated using its returned token.
        if activation.persistence is not None:
            state, value = activation.persistence
            rollback.persistence = (state, state.commit_update(value))
        if activation.auth is not None:
            state, value = activation.auth
            state.principals = value.principals
            state.labels = value.labels
            state.admin_password = value.admin_password
            state.admin_token = value.admin_token
        if activation.stream_trace is not None:
            state, value = activation.stream_trace
            state.config = value.config
            state._redactor = value.redactor
        if activation.upstream_error_log is not None:
            state, value = activation.upstream_error_log
            state.commit_update(value)
        if activation.body_log is not None:
            state, value = activation.body_log
            state.commit_update(value)
        if activation.metrics is not None:
            state, value = activation.metrics
            state._redactor = value
        from ...app import _bind_provider_current_recorders

        _bind_provider_current_recorders(new_config, getattr(app, "config_path", None))
        app.admin_cors_origins = activation.admin_cors_origins
        app.max_body_size = activation.max_body_size
        app.gateway_config = new_config
        web_run_health_state = getattr(app, "web_run_health_state", None)
        if web_run_health_state is not None:
            web_run_health_state.invalidate()
    except BaseException:
        _rollback_gateway_activation(request, rollback)
        raise
    return rollback


def _rollback_gateway_activation(
    request: Any,
    rollback: _GatewayActivationRollback,
) -> None:
    """Restore a previously committed gateway activation."""
    app = request.app
    if rollback.auth is not None:
        state, principals, labels, admin_password, admin_token = rollback.auth
        state.principals = principals
        state.labels = labels
        state.admin_password = admin_password
        state.admin_token = admin_token
    if rollback.stream_trace is not None:
        state, config, redactor = rollback.stream_trace
        state.config = config
        state._redactor = redactor
    if rollback.upstream_error_log is not None:
        state, redactor = rollback.upstream_error_log
        state._redactor = redactor
    if rollback.body_log is not None:
        state, enabled, redactor = rollback.body_log
        state.enabled = enabled
        state._redactor = redactor
    if rollback.metrics is not None:
        state, redactor = rollback.metrics
        state._redactor = redactor
    app.admin_cors_origins = rollback.admin_cors_origins
    app.max_body_size = rollback.max_body_size
    app.gateway_config = rollback.gateway_config
    web_run_health_state = getattr(app, "web_run_health_state", None)
    if web_run_health_state is not None:
        web_run_health_state.invalidate()
    if rollback.persistence is not None:
        state, value = rollback.persistence
        state.rollback_update(value)


def _prepare_local_mode_transaction(
    request: Any,
    new_config: GatewayConfig,
    data: dict[str, Any],
) -> CodexLocalModeTransaction | None:
    codex_home = getattr(request.app, "codex_home", None)
    if not codex_home:
        return None
    if new_config.local_mode and new_config.local_mode_confirmed:
        gateway_port = getattr(request.app, "gateway_port", new_config.port)
        return CodexLocalModeTransaction.sync(
            codex_home,
            data,
            gateway_port=gateway_port,
            api_key=codex_api_key_value(new_config.api_keys),
        )
    if not new_config.local_mode:
        return CodexLocalModeTransaction.clear(codex_home)
    return None


def _rollback_config_updates(
    request: Any,
    activation_rollback: _GatewayActivationRollback | None,
    local_mode_transaction: CodexLocalModeTransaction | None,
) -> list[str]:
    errors: list[str] = []
    if activation_rollback is not None:
        try:
            _rollback_gateway_activation(request, activation_rollback)
        except Exception as exc:
            errors.append(f"config activation rollback failed: {exc}")
    if local_mode_transaction is not None:
        try:
            local_mode_transaction.rollback()
        except Exception as exc:
            errors.append(f"Codex local-mode rollback failed: {exc}")
    return errors


def _mark_codex_restart_if_changed(
    transaction: CodexLocalModeTransaction | None,
) -> None:
    if transaction is not None and transaction.changed:
        mark_codex_restart_required()


def _commit_gateway_config(
    request: Any,
    config_path: str,
    data: dict[str, Any],
) -> tuple[GatewayConfig | None, Response | None]:
    """Validate, persist, and activate one complete Admin config candidate.

    Caller-controlled validation failures return 400, duplicate conflicts and
    concurrent file changes return 409, and the config file is never left on a
    candidate that failed validation or runtime activation.
    """
    reset_codex_restart_required()
    try:
        server = data.get("server")
        if (
            isinstance(server, dict)
            and server.get("local_mode", True) is True
            and server.get("local_mode_confirmed", False) is True
        ):
            ensure_codex_api_key(data)
        new_config = GatewayConfig.from_raw_with_env(data)
    except (KeyError, TypeError, ValueError) as exc:
        status_code = 409 if "duplicate" in str(exc).lower() else 400
        return None, JSONResponse(
            {"error": f"Invalid config: {exc}"},
            status_code=status_code,
        )

    try:
        prepared = _prepare_gateway_activation(request, new_config)
    except Exception as exc:
        return None, JSONResponse(
            {"error": f"Failed to prepare config: {exc}"}, status_code=500
        )

    try:
        local_mode_transaction = _prepare_local_mode_transaction(
            request, new_config, data
        )
    except Exception as exc:
        return None, JSONResponse(
            {"error": f"Failed to prepare Codex local mode: {exc}"},
            status_code=500,
        )

    server = data.get("server")
    if isinstance(server, dict) and "admin_cors_origins" in server:
        server["admin_cors_origins"] = list(new_config.admin_cors_origins)

    activation_started = False
    activation_rollback: _GatewayActivationRollback | None = None

    def _activate() -> None:
        nonlocal activation_rollback, activation_started
        activation_started = True
        if local_mode_transaction is not None:
            local_mode_transaction.apply()
        try:
            activation_rollback = _activate_gateway_config(
                request, new_config, prepared
            )
        except BaseException:
            if local_mode_transaction is not None:
                local_mode_transaction.rollback()
            raise

    try:
        write_config(config_path, data, activate=_activate)
    except ConfigConflictError as exc:
        rollback_errors = _rollback_config_updates(
            request, activation_rollback, local_mode_transaction
        )
        if rollback_errors:
            return None, JSONResponse(
                {"error": "Failed to rollback: " + "; ".join(rollback_errors)},
                status_code=500,
            )
        return None, JSONResponse({"error": str(exc)}, status_code=409)
    except Exception as exc:
        rollback_errors = _rollback_config_updates(
            request, activation_rollback, local_mode_transaction
        )
        if rollback_errors:
            return None, JSONResponse(
                {"error": "Failed to rollback: " + "; ".join(rollback_errors)},
                status_code=500,
            )
        action = "activate" if activation_started else "write"
        return None, JSONResponse(
            {"error": f"Failed to {action} config: {exc}"}, status_code=500
        )

    _mark_codex_restart_if_changed(local_mode_transaction)
    return new_config, None


def _sync_auth_middleware(app: Any, config: GatewayConfig) -> None:
    """Update the auth hook's state for hot-reload."""
    auth_state = getattr(app, "auth_state", None)
    if auth_state is not None:
        auth_state.update_config(
            dict(config.api_key_principals),
            dict(config.api_key_labels),
            config.admin_password,
        )


def _sync_stream_trace_state(app: Any, config: GatewayConfig) -> None:
    """Update stream trace settings for hot-reload."""
    stream_trace_state = getattr(app, "stream_trace_state", None)
    if stream_trace_state is not None:
        stream_trace_state.update(
            config.stream_trace,
            token_values=_runtime_token_values(app, config),
        )


def _runtime_token_values(app: Any, config: GatewayConfig) -> set[str]:
    values = set(config.token_values)
    internal_token = getattr(app, "internal_token", None)
    if internal_token:
        values.add(internal_token)
    return values


def _sync_persistence_redaction(app: Any, config: GatewayConfig) -> None:
    persistence = getattr(app, "persistence", None)
    if persistence is not None:
        persistence.update_token_values(_runtime_token_values(app, config))


def _build_provider_entry(
    body: dict[str, Any],
    api_keys: list[dict[str, str]],
    current_api_key: str | None,
    base_urls: list[str],
    current_base_url: str,
    existing_providers: dict[str, Any],
    resolve_name: str,
) -> dict[str, Any]:
    """Build one canonical provider entry from validated Admin input."""
    entry: dict[str, Any] = {
        "api_keys": api_keys,
        "auto_rotate_credentials": body["auto_rotate_credentials"],
        "base_urls": base_urls,
        "current_base_url": current_base_url,
    }
    if current_api_key is not None:
        entry["current_api_key"] = current_api_key

    provider = body.get("provider")
    if provider:
        entry["provider"] = provider

    api_type = body.get("api_type")
    if api_type:
        entry["api_type"] = api_type

    if "request_encoding" in body:
        entry["request_encoding"] = body["request_encoding"]

    if "sub2api_account_id" in body:
        entry["sub2api_account_id"] = body["sub2api_account_id"]

    if "proxy" in body:
        proxy = body["proxy"]
        if proxy:
            entry["proxy"] = proxy

    allow_redirects = body.get("allow_redirects", False)
    if allow_redirects is not False:
        entry["allow_redirects"] = allow_redirects

    if "soft_interrupt" in body:
        entry["soft_interrupt"] = body["soft_interrupt"]

    force_rosetta_compaction = body.get("force_rosetta_compaction", False)
    if force_rosetta_compaction is not False:
        entry["force_rosetta_compaction"] = force_rosetta_compaction

    if resolve_name in existing_providers:
        existing_enabled = existing_providers[resolve_name].get("enabled")
        if existing_enabled is not None:
            entry["enabled"] = existing_enabled

    return entry


def _renamed_model_group_candidate(value: Any, old_name: str, new_name: str) -> Any:
    """Rewrite one model-group candidate for a Provider rename."""
    if value == old_name:
        return new_name
    if isinstance(value, dict) and value.get("provider") == old_name:
        return {**value, "provider": new_name}
    return value


def _handle_provider_rename(
    data: dict[str, Any], rename_from: str, name: str
) -> Response | None:
    """Handle provider rename and update model-group references."""
    providers = data.get("providers", {})
    if rename_from not in providers:
        return JSONResponse(
            {"error": f"Original provider '{rename_from}' not found"},
            status_code=404,
        )
    if name in providers:
        return JSONResponse(
            {"error": f"Provider '{name}' already exists"},
            status_code=409,
        )
    del providers[rename_from]
    model_groups = data.get("model_groups", {})
    if isinstance(model_groups, dict):
        for group_val in model_groups.values():
            if not isinstance(group_val, dict):
                continue
            provider_names = group_val.get("provider")
            if isinstance(provider_names, list):
                group_val["provider"] = [
                    _renamed_model_group_candidate(item, rename_from, name)
                    for item in provider_names
                ]
            if "current_provider" in group_val:
                group_val["current_provider"] = _renamed_model_group_candidate(
                    group_val["current_provider"], rename_from, name
                )
    server = data.get("server")
    web_search = server.get("web_search") if isinstance(server, dict) else None
    if isinstance(web_search, dict):
        if isinstance(web_search.get("providers"), list):
            for row in web_search["providers"]:
                if isinstance(row, dict):
                    if row.get("responses_provider") == rename_from:
                        row["responses_provider"] = name
                    if row.get("deepseek_provider") == rename_from:
                        row["deepseek_provider"] = name
        elif web_search.get("responses_provider") == rename_from:
            web_search["responses_provider"] = name
    return None
