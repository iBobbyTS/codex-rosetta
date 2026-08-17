"""codex-rosetta Gateway — HTTP application and route handlers."""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from codex_rosetta._vendor.httpserver import (
    App,
    JSONResponse,
    Response,
    StreamingResponse,
)
from codex_rosetta.auto_detect import ProviderType
from codex_rosetta.observability.error_dump import dump_error
from codex_rosetta.routing import ResolvedRoute, is_responses_passthrough

from .admin.restart_notice import (
    consume_codex_restart_required,
    reset_codex_restart_required,
)
from .admin_session import load_or_create_admin_session_secret
from .auth import (
    AuthState,
    api_key_label_var,
    api_key_principal_var,
    create_auth_hook,
)
from .config import (
    GatewayConfig,
    ModelGroupConfigurationUnavailable,
    load_config_raw,
    resolve_codex_home,
    write_config,
)
from .codex_auxiliary import handle_codex_auxiliary as _handle_codex_auxiliary
from .codex_search_references import CodexSearchReferenceStore
from .cors import apply_cors_headers, is_admin_origin_allowed, is_admin_path
from .downstream_errors import (
    DownstreamErrorOrigin,
    classify_downstream_exception,
    format_stream_error_event,
    prefix_error_body,
)
from .headers import (
    build_direct_responses_headers,
    build_upstream_extra_headers,
    generate_request_id,
    resolve_request_id,
)
from .health import build_health_payload, build_readiness_payload
from .image_workers import ImageFetchWorkerPool
from .inbound_content_encoding import (
    bind_inbound_wire_request,
    take_inbound_wire_request,
)
from .late_developer_message import rewrite_late_codex_developer_messages
from .logging import (
    BodyLogState,
    UpstreamErrorLogState,
    get_logger,
    record_request_stat,
)
from .search_provider_candidates import search_candidates_capabilities
from .search_provider_chain import SearchProviderChainCoordinator

from .proxy import (
    ProviderMetadataCapacityError,
    ProviderMetadataStore,
    close_resources,
    detect_stream_request,
    error_response_for_source,
    extract_model,
    handle_non_streaming,
    handle_streaming,
    normalize_codex_window_id,
    validate_model_id,
)
from .state_scope import GatewayStateScope
from .chat_tool_surface import (
    ChatToolSurfaceCoordinator,
    InMemoryChatToolSurfaceStore,
)
from .tool_adaptation import CodexToolLocalizationStore
from .tool_profiles import route_tool_state
from .transport._base import UpstreamNetworkError
from .web_run_capabilities import (
    WEB_RUN_BASIC_SEARCH_CAPABILITY,
    WEB_RUN_PROFILE_ITEM_ID,
    WEB_RUN_SIDECAR_CAPABILITY,
)
from .web_run_health import WebRunHealthState

logger = get_logger()

_TOOL_CALL_CACHE_CLEANUP_INTERVAL = 3600
_INBOUND_REQUEST_LINE_TIMEOUT_SECONDS = 15.0
_INBOUND_HEADER_TIMEOUT_SECONDS = 30.0
_INBOUND_BODY_TIMEOUT_SECONDS = 120.0
_INBOUND_MAX_CONCURRENT_REQUEST_PARSES = 64


class GatewayApp(App):
    """HTTP app that applies the Gateway error contract outside route code."""

    async def _handle_error(
        self, request: Any, exc: Exception
    ) -> Response | StreamingResponse:
        response = await super()._handle_error(request, exc)
        if (request.path == "/v1" or request.path.startswith("/v1/")) and isinstance(
            response, Response
        ):
            _prefix_fixed_error_response(response, DownstreamErrorOrigin.ROSETTA)
        return response

    @staticmethod
    async def _send_error_and_close(
        writer: asyncio.StreamWriter,
        response: Response | JSONResponse,
    ) -> None:
        # Parser limits and deadlines are intentional safety/resource guards;
        # syntax and framing failures remain ordinary Rosetta errors.
        origin = (
            DownstreamErrorOrigin.BLOCKED
            if response.status_code in {408, 413, 431, 503}
            else DownstreamErrorOrigin.ROSETTA
        )
        _prefix_fixed_error_response(response, origin)
        await App._send_error_and_close(writer, response)


def _prefix_fixed_error_response(
    response: Response,
    origin: DownstreamErrorOrigin,
) -> None:
    """Prefix one fixed error response in place before any bytes are written."""
    if response.status_code < 400:
        return
    response.body = prefix_error_body(response.body, origin)
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers.pop("Content-Length", None)


def _record_request_log_entry(
    request: Any,
    *,
    model: str,
    source_provider: ProviderType,
    target_provider: ProviderType,
    provider_name: str,
    is_stream: bool,
    status_code: int,
    duration_ms: float,
    error_detail: str | None,
    profile: dict[str, Any] | None = None,
    entry_id_override: str | None = None,
) -> str | None:
    """Safely add one request-log entry without affecting proxy delivery."""
    request_log = getattr(request.app, "request_log", None)
    if request_log is None:
        return None
    try:
        from dataclasses import replace as _dc_replace

        from codex_rosetta.observability import RequestLogEntry

        entry = RequestLogEntry.create(
            model=model,
            source_provider=source_provider,
            target_provider=target_provider,
            target_provider_name=provider_name,
            is_stream=is_stream,
            status_code=status_code,
            duration_ms=duration_ms,
            error_detail=error_detail,
            api_key_label=api_key_label_var.get(),
            client_ip=_extract_client_ip(request),
            profile=profile,
        )
        if entry_id_override:
            entry = _dc_replace(entry, id=entry_id_override)
        request_log.add(entry, response_redaction="protocol_fields")
        return entry.id
    except Exception as exc:
        logger.warning("Failed to record request log entry: %s", exc)
        return None


def _record_telemetry(
    request: Any,
    *,
    model: str,
    source_provider: ProviderType,
    target_provider: ProviderType,
    provider_name: str,
    is_stream: bool,
    status_code: int,
    duration_ms: float,
    error_detail: str | None,
    profile: dict[str, Any] | None = None,
    entry_id_override: str | None = None,
) -> str | None:
    """Record metrics and request log entry after a proxy call completes.

    Args:
        entry_id_override: Pre-generated entry ID for streaming requests.
            When provided, the entry is created with this ID so the
            stream generator can write back profile data by ID.

    Returns:
        The request log entry ID, or ``None`` if no request log is
        configured.
    """
    metrics = getattr(request.app, "metrics", None)
    if metrics:
        try:
            if is_stream:
                metrics.active_streams -= 1
            metrics.record_request(
                model=model,
                source=source_provider,
                target=target_provider,
                status_code=status_code,
                duration_ms=duration_ms,
                is_stream=is_stream,
                provider_name=provider_name,
                error_detail=error_detail,
                response_redaction="protocol_fields",
            )
        except Exception as exc:
            logger.warning("Failed to record request metrics: %s", exc)

    return _record_request_log_entry(
        request,
        model=model,
        source_provider=source_provider,
        target_provider=target_provider,
        provider_name=provider_name,
        is_stream=is_stream,
        status_code=status_code,
        duration_ms=duration_ms,
        error_detail=error_detail,
        profile=profile,
        entry_id_override=entry_id_override,
    )


def _finalize_stream_telemetry(
    request: Any,
    *,
    entry_id: str,
    model: str,
    source_provider: ProviderType,
    target_provider: ProviderType,
    provider_name: str,
    status_code: int,
    duration_ms: float,
    error_detail: str | None,
) -> None:
    """Safely record the one terminal outcome of an open stream."""
    metrics = getattr(request.app, "metrics", None)
    if metrics:
        try:
            metrics.active_streams -= 1
            metrics.record_request(
                model=model,
                source=source_provider,
                target=target_provider,
                status_code=status_code,
                duration_ms=duration_ms,
                is_stream=True,
                provider_name=provider_name,
                error_detail=error_detail,
                response_redaction="protocol_fields",
            )
        except Exception as exc:
            logger.warning("Failed to finalize stream metrics: %s", exc)

    request_log = getattr(request.app, "request_log", None)
    if request_log is not None:
        profile_update: dict[str, Any] = {
            "stream_complete": status_code < 400,
        }
        if error_detail is not None:
            profile_update["stream_error"] = error_detail[:500]
        try:
            request_log.update_result(
                entry_id,
                status_code=status_code,
                duration_ms=duration_ms,
                error_detail=error_detail,
                profile_update=profile_update,
                response_redaction="protocol_fields",
            )
        except Exception as exc:
            logger.warning("Failed to finalize stream request log: %s", exc)


class _InstrumentedStream:
    """Async iterator that finalizes stream telemetry exactly once."""

    def __init__(
        self,
        source: AsyncIterator[bytes | str],
        *,
        source_provider: ProviderType,
        success_status: int,
        finalize: Callable[[int, str | None], None],
    ) -> None:
        self._source = source
        self._iterator = source.__aiter__()
        self._source_provider = source_provider
        self._success_status = success_status
        self._finalize_callback = finalize
        self._finished = False
        self._source_closed = False
        self._terminal_chunk_sent = False

    def __aiter__(self) -> _InstrumentedStream:
        return self

    async def __anext__(self) -> bytes | str:
        if self._terminal_chunk_sent:
            raise StopAsyncIteration
        try:
            return await self._iterator.__anext__()
        except StopAsyncIteration:
            self._source_closed = True
            self._finish(self._success_status, None)
            raise
        except asyncio.CancelledError:
            try:
                await self._close_source()
            except BaseException:
                logger.debug("Failed to close cancelled stream", exc_info=True)
            finally:
                self._finish(499, "Stream cancelled or client disconnected")
            raise
        except Exception as exc:
            try:
                await self._close_source()
            except BaseException:
                logger.debug("Failed to close errored stream", exc_info=True)
            finally:
                self._finish(502, str(exc))
            if isinstance(exc, UpstreamNetworkError):
                logger.error("Upstream stream disconnected: %s", exc)
            self._terminal_chunk_sent = True
            return format_stream_error_event(
                self._source_provider,
                str(exc),
                classify_downstream_exception(exc),
            )

    async def aclose(self) -> None:
        """Close an incomplete stream and record a client-disconnect outcome."""
        if self._finished:
            return
        status_code = 499
        error_detail = "Stream closed before completion"
        try:
            await self._close_source()
        except asyncio.CancelledError:
            error_detail = "Stream cancelled or client disconnected"
            raise
        except Exception as exc:
            status_code = 502
            error_detail = str(exc)
            logger.debug("Failed to close stream source", exc_info=True)
        finally:
            self._finish(status_code, error_detail)

    async def _close_source(self) -> None:
        if self._source_closed:
            return
        self._source_closed = True
        aclose = getattr(self._iterator, "aclose", None)
        if aclose is None and self._iterator is not self._source:
            aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            await aclose()

    def _finish(self, status_code: int, error_detail: str | None) -> None:
        if self._finished:
            return
        self._finished = True
        self._finalize_callback(status_code, error_detail)


def _response_error_detail(response: Response | StreamingResponse) -> str | None:
    """Decode a non-streaming error response body for telemetry."""
    if response.status_code < 400 or not hasattr(response, "body"):
        return None
    body = response.body
    return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else None


def _instrument_stream_response(
    request: Any,
    response: StreamingResponse,
    *,
    entry_id: str,
    request_id: str,
    model: str,
    source_provider: ProviderType,
    target_provider: ProviderType,
    provider_name: str,
    profile: dict[str, Any] | None,
    profiler: Any,
    started_at: float,
    on_finish: Callable[[], None] | None = None,
) -> None:
    """Attach request logging and terminal telemetry to an open stream."""
    _record_request_log_entry(
        request,
        model=model,
        source_provider=source_provider,
        target_provider=target_provider,
        provider_name=provider_name,
        is_stream=True,
        status_code=response.status_code,
        duration_ms=(time.monotonic() - started_at) * 1000,
        error_detail=None,
        profile=profile,
        entry_id_override=entry_id,
    )

    def _finalize_stream(status: int, stream_error: str | None) -> None:
        try:
            duration_ms = (time.monotonic() - started_at) * 1000
            _try_stop_profiler(
                profiler,
                request.app,
                request_id=request_id,
                model=model,
                source=source_provider,
                target=target_provider,
                is_stream=True,
                duration_ms=duration_ms,
            )
            _finalize_stream_telemetry(
                request,
                entry_id=entry_id,
                model=model,
                source_provider=source_provider,
                target_provider=target_provider,
                provider_name=provider_name,
                status_code=status,
                duration_ms=duration_ms,
                error_detail=stream_error,
            )
            logger.info("[%s] stream finalized status=%s", request_id, status)
        finally:
            if on_finish is not None:
                on_finish()

    response._generator = _InstrumentedStream(
        response._generator,
        source_provider=source_provider,
        success_status=response.status_code,
        finalize=_finalize_stream,
    )


def _clear_request_local_state(
    scope: GatewayStateScope,
    *,
    metadata_store: ProviderMetadataStore,
    codex_tool_store: CodexToolLocalizationStore,
) -> None:
    """Clear every in-memory store owned by one non-persistent request scope."""
    if scope.persistent:
        return
    for name, store in (
        ("provider metadata", metadata_store),
        ("tool localization", codex_tool_store),
    ):
        try:
            store.scoped(scope).clear()
        except Exception:
            logger.warning(
                "Failed to clear request-local %s state", name, exc_info=True
            )


def _mark_stream_active(request: Any, *, is_stream: bool) -> None:
    """Increment the active-stream gauge for an accepted streaming request."""
    if not is_stream:
        return
    metrics = getattr(request.app, "metrics", None)
    if metrics:
        metrics.active_streams += 1


def _extract_client_ip(request: Any) -> str | None:
    """Return the direct TCP peer address for request attribution.

    Forwarded client-IP headers remain untrusted until the gateway exposes an
    explicit trusted-proxy allowlist.
    """
    addr = getattr(request, "client_addr", None)
    if addr and isinstance(addr, (tuple, list)) and addr[0]:
        return str(addr[0])
    return None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


def _try_start_profiler(app: Any) -> Any | None:
    """Start a per-request deep profiler if profiling is enabled.

    Returns a started DeepProfiler instance, or ``None`` if profiling
    is disabled or pyinstrument is not installed.
    """
    state = getattr(app, "profiler_state", None)
    if state is None or not state.should_profile():
        return None
    try:
        profiler = state.create_profiler()
        profiler.start()
        return profiler
    except RuntimeError:
        # pyinstrument not installed — restore the consumed slot
        state.remaining += 1
        if not state.enabled:
            state.enabled = True
        return None


def _try_stop_profiler(
    profiler: Any,
    app: Any,
    *,
    request_id: str,
    model: str,
    source: str,
    target: str,
    is_stream: bool,
    duration_ms: float,
) -> None:
    """Stop a running deep profiler and store the result."""
    if profiler is None:
        return
    try:
        profiler.stop()
        state = getattr(app, "profiler_state", None)
        if state is not None:
            state.store_result(
                profiler,
                request_id=request_id,
                model=model,
                source=source,
                target=target,
                is_stream=is_stream,
                duration_ms=duration_ms,
            )
    except Exception:
        logger.debug("Failed to store profiling result")


def _proxy_request_id_or_error(
    request: Any, source_provider: ProviderType
) -> str | Response:
    """Resolve a safe request ID or return a source-shaped ingress error."""

    try:
        return resolve_request_id(request.headers.get("x-request-id"))
    except ValueError as exc:
        response = error_response_for_source(source_provider, 400, str(exc))
        response.headers["x-request-id"] = generate_request_id()
        return response


def _proxy_body_or_error(
    request: Any,
    source_provider: ProviderType,
    request_id: str,
) -> tuple[Any, dict[str, Any]] | Response:
    """Parse and bind one proxy body or return a source-shaped ingress error."""

    inbound_wire_request = take_inbound_wire_request()
    try:
        body = request.json()
    except Exception:
        response = error_response_for_source(source_provider, 400, "Invalid JSON body")
        response.headers["x-request-id"] = request_id
        return response
    if not isinstance(body, dict):
        response = error_response_for_source(
            source_provider, 400, "JSON body must be an object"
        )
        response.headers["x-request-id"] = request_id
        return response
    return bind_inbound_wire_request(inbound_wire_request, body)


def _apply_route_model_alias(
    body: dict[str, Any], model: str, upstream_model: str | None
) -> tuple[str, str]:
    """Apply an upstream alias and return log/stat model labels."""

    if upstream_model:
        body["model"] = upstream_model
        return f"{model} (upstream={upstream_model})", upstream_model
    return model, model


async def _resolve_request_tool_runtime_capabilities(
    app: Any,
    config: GatewayConfig,
    route: ResolvedRoute,
    body: dict[str, Any],
) -> ResolvedRoute:
    """Add request-time optional executors to an immutable route snapshot."""
    if route.source_provider not in {"openai_responses", "open_responses"}:
        return route
    if route_tool_state(route, WEB_RUN_PROFILE_ITEM_ID) != "modified":
        return route
    if not _request_exposes_web_run(body):
        return route

    browser_ready = False
    if config.web_run_sidecar_url and config.web_run_sidecar_token:
        health_state: WebRunHealthState = app.web_run_health_state
        status = await health_state.status(config.web_run_sidecar_url)
        browser_ready = status.browser_ready is True

    capabilities = set(route.tool_runtime_capabilities)
    if browser_ready:
        capabilities.add(WEB_RUN_SIDECAR_CAPABILITY)
    else:
        capabilities.discard(WEB_RUN_SIDECAR_CAPABILITY)
    candidates = config.web_search_candidates
    coordinator = getattr(app, "search_provider_coordinator", None)
    if isinstance(coordinator, SearchProviderChainCoordinator):
        current = coordinator.current_candidate(candidates)
        candidates = (current,) if current is not None else ()
    search_capabilities = search_candidates_capabilities(
        candidates,
        self_hosted_ready=browser_ready,
    )
    if search_capabilities:
        capabilities.add(WEB_RUN_BASIC_SEARCH_CAPABILITY)
    else:
        capabilities.discard(WEB_RUN_BASIC_SEARCH_CAPABILITY)
    return replace(
        route,
        tool_runtime_capabilities=frozenset(capabilities),
        web_run_search_capabilities=search_capabilities,
    )


def _request_exposes_web_run(body: dict[str, Any]) -> bool:
    """Return whether a Responses request contains direct or nested web.run."""
    containers: list[Any] = [body.get("tools")]
    input_items = body.get("input")
    if isinstance(input_items, list):
        containers.extend(
            item.get("tools")
            for item in input_items
            if isinstance(item, dict) and item.get("type") == "additional_tools"
        )
    for container in containers:
        if not isinstance(container, list):
            continue
        for tool in container:
            if not isinstance(tool, dict):
                continue
            if tool.get("name") == "web__run":
                return True
            if tool.get("type") == "custom" and tool.get("name") == "exec":
                description = tool.get("description")
                if isinstance(description, str) and "### `web__run`" in description:
                    return True
    return False


async def _proxy_handler(  # noqa: C901
    request: Any,
    source_provider: ProviderType,
    model_override: str | None = None,
    force_stream: bool = False,
) -> Response | StreamingResponse:
    """Handle one ingress and bounded model-group provider attempt lifecycle."""
    config: GatewayConfig = request.app.gateway_config

    request_id = _proxy_request_id_or_error(request, source_provider)
    if isinstance(request_id, Response):
        return request_id
    parsed_body = _proxy_body_or_error(request, source_provider, request_id)
    if isinstance(parsed_body, Response):
        return parsed_body
    inbound_wire_request, parsed_request_body = parsed_body

    try:
        model = (
            validate_model_id(model_override)
            if model_override
            else extract_model(source_provider, parsed_request_body)
        )
        codex_window_id = normalize_codex_window_id(
            request.headers.get("x-codex-window-id")
        )
    except ValueError as exc:
        resp = error_response_for_source(source_provider, 400, str(exc))
        resp.headers["x-request-id"] = request_id
        return resp
    if not model:
        resp = error_response_for_source(
            source_provider, 400, "Missing 'model' in request body"
        )
        resp.headers["x-request-id"] = request_id
        return resp
    if model_override and "model" not in parsed_request_body:
        parsed_request_body["model"] = model_override
    request_body = copy.deepcopy(parsed_request_body)

    principal_id = api_key_principal_var.get()
    group_name = getattr(config, "model_group_names_by_model", {}).get(model)
    ring = (
        getattr(config, "model_group_rings", {}).get(group_name) if group_name else None
    )
    is_stream = force_stream or detect_stream_request(source_provider, request_body)
    store: ProviderMetadataStore = request.app.metadata_store
    codex_tool_store: CodexToolLocalizationStore = request.app.codex_tool_store
    request_log = getattr(request.app, "request_log", None)
    persistence = getattr(request.app, "persistence", None)

    _mark_stream_active(request, is_stream=is_stream)
    t0 = time.monotonic()
    status_code = 500
    error_detail: str | None = None
    profile: dict[str, Any] | None = None
    deep_profiler = _try_start_profiler(request.app)
    pre_entry_id = uuid.uuid4().hex if is_stream else None
    stream_telemetry_deferred = False
    request_state_cleanup_deferred = False
    state_scope: GatewayStateScope | None = None
    route: ResolvedRoute | None = None
    failover_leader = False
    request_stat_recorded = False
    body = copy.deepcopy(request_body)

    try:
        while True:
            observation: tuple[str, int] | None = None
            if ring is not None:
                if failover_leader:
                    observation = ring.observe()
                else:
                    observation, _waited, inherited_leader = await ring.await_attempt()
                    failover_leader = inherited_leader

            try:
                route, provider_info = config.resolve(source_provider, model)
            except ModelGroupConfigurationUnavailable as exc:
                status_code = 503
                error_detail = str(exc)
                response = error_response_for_source(
                    source_provider,
                    503,
                    str(exc),
                    origin=DownstreamErrorOrigin.BLOCKED,
                )
                response.headers["x-request-id"] = request_id
                return response
            except KeyError:
                configured = ", ".join(sorted(config.models.keys()))
                response = error_response_for_source(
                    source_provider,
                    404,
                    f"Unknown model: '{model}'. Configured models: {configured}",
                )
                response.headers["x-request-id"] = request_id
                return response

            if principal_id is None:
                response = error_response_for_source(
                    source_provider, 401, "Authenticated principal is unavailable"
                )
                response.headers["x-request-id"] = request_id
                return response

            body = copy.deepcopy(request_body)
            route = await _resolve_request_tool_runtime_capabilities(
                request.app,
                config,
                route,
                body,
            )
            body, late_developer_rewritten_items = (
                rewrite_late_codex_developer_messages(
                    body,
                    enabled=provider_info.soft_interrupt,
                    source_provider=source_provider,
                    target_provider=route.target_provider,
                )
            )
            model_label, stats_model = _apply_route_model_alias(
                body, model, route.upstream_model
            )
            state_scope = GatewayStateScope.for_request(
                principal_id=principal_id,
                provider_name=route.provider_name,
                model=model,
                window_id=codex_window_id,
            )
            if not request_stat_recorded:
                record_request_stat(stats_model)
                logger.info(
                    "[%s] %s -> %s | model=%s stream=%s",
                    request_id,
                    source_provider,
                    route.target_provider,
                    model_label,
                    is_stream,
                )
                request_stat_recorded = True

            extra_headers = (
                build_direct_responses_headers(
                    request.headers,
                    request_id,
                    preserve_wire=False,
                )
                if is_responses_passthrough(route)
                else build_upstream_extra_headers(request, request_id)
            )
            if is_stream:
                response, profile = await handle_streaming(
                    route,
                    provider_info,
                    body,
                    transport=request.app.transport,
                    metadata_store=store,
                    codex_tool_store=codex_tool_store,
                    chat_tool_surface_coordinator=getattr(
                        request.app, "chat_tool_surface_coordinator", None
                    ),
                    extra_headers=extra_headers,
                    entry_id=pre_entry_id,
                    request_log=request_log,
                    persistence=persistence,
                    state_scope=state_scope,
                    codex_window_id=codex_window_id,
                    stream_trace_state=getattr(request.app, "stream_trace_state", None),
                    upstream_error_log_state=getattr(
                        request.app, "upstream_error_log_state", None
                    ),
                    body_log_state=getattr(request.app, "body_log_state", None),
                    image_fetch_workers=getattr(
                        request.app, "image_fetch_workers", None
                    ),
                    inbound_wire_request=inbound_wire_request,
                    model_group_failover=ring is not None,
                )
            else:
                response, profile = await handle_non_streaming(
                    route,
                    provider_info,
                    body,
                    transport=request.app.transport,
                    metadata_store=store,
                    codex_tool_store=codex_tool_store,
                    chat_tool_surface_coordinator=getattr(
                        request.app, "chat_tool_surface_coordinator", None
                    ),
                    extra_headers=extra_headers,
                    persistence=persistence,
                    state_scope=state_scope,
                    codex_window_id=codex_window_id,
                    upstream_error_log_state=getattr(
                        request.app, "upstream_error_log_state", None
                    ),
                    body_log_state=getattr(request.app, "body_log_state", None),
                    image_fetch_workers=getattr(
                        request.app, "image_fetch_workers", None
                    ),
                    model_group_failover=ring is not None,
                )

            provider_failed = bool(
                ring is not None
                and profile.get("upstream_provider_failure")
                and not isinstance(response, StreamingResponse)
            )
            if provider_failed:
                assert ring is not None
                assert observation is not None
                if not failover_leader:
                    failover_leader, _waited = await ring.claim_observation(observation)
                    if not failover_leader:
                        _clear_request_local_state(
                            state_scope,
                            metadata_store=store,
                            codex_tool_store=codex_tool_store,
                        )
                        state_scope = None
                        continue

                failed_provider = route.provider_name
                next_provider = next(
                    (
                        candidate
                        for candidate in ring.available()
                        if candidate != failed_provider
                    ),
                    None,
                )
                if next_provider is not None:
                    # Persistence succeeds before either runtime current or
                    # cooldown state changes, so recorder failure cannot split
                    # the two authoritative views.
                    await ring.select(next_provider)
                    ring.mark_failed(failed_provider)
                    _clear_request_local_state(
                        state_scope,
                        metadata_store=store,
                        codex_tool_store=codex_tool_store,
                    )
                    state_scope = None
                    continue
                ring.mark_failed(failed_provider)
                await ring.publish()
                failover_leader = False
            elif failover_leader:
                assert ring is not None
                await ring.publish()
                failover_leader = False

            if late_developer_rewritten_items:
                profile["late_developer_rewritten_items"] = (
                    late_developer_rewritten_items
                )
            status_code = response.status_code
            error_detail = _response_error_detail(response)
            if isinstance(response, StreamingResponse):
                assert pre_entry_id is not None
                _instrument_stream_response(
                    request,
                    response,
                    entry_id=pre_entry_id,
                    request_id=request_id,
                    model=model,
                    source_provider=source_provider,
                    target_provider=route.target_provider,
                    provider_name=route.provider_name,
                    profile=profile,
                    profiler=deep_profiler,
                    started_at=t0,
                    on_finish=lambda: _clear_request_local_state(
                        state_scope,
                        metadata_store=store,
                        codex_tool_store=codex_tool_store,
                    ),
                )
                stream_telemetry_deferred = True
                request_state_cleanup_deferred = True
            response.headers["x-request-id"] = request_id
            logger.info("[%s] response status=%s", request_id, status_code)
            return response
    except ProviderMetadataCapacityError as exc:
        error_detail = str(exc)
        status_code = 413
        pre_entry_id = None
        logger.warning("[%s] provider metadata capacity rejected", request_id)
        resp = error_response_for_source(
            source_provider,
            413,
            str(exc),
            origin=DownstreamErrorOrigin.BLOCKED,
        )
        resp.headers["x-request-id"] = request_id
        return resp
    except Exception as exc:
        error_detail = str(exc)
        logger.exception("[%s] unhandled error in proxy handler", request_id)
        status_code = 500
        pre_entry_id = None
        dump_error(
            persistence,
            request_body=body,
            response_text=error_detail,
            model=model,
            source_provider=source_provider,
            target_provider=route.target_provider
            if route is not None
            else source_provider,
            provider_name=route.provider_name if route is not None else "",
            status_code=500,
            error_phase="conversion",
            response_redaction="protocol_fields",
        )
        resp = error_response_for_source(
            source_provider, 500, f"Internal server error: {exc}"
        )
        resp.headers["x-request-id"] = request_id
        return resp
    finally:
        if failover_leader and ring is not None:
            await ring.handoff()
        duration_ms = (time.monotonic() - t0) * 1000
        if not request_state_cleanup_deferred and state_scope is not None:
            _clear_request_local_state(
                state_scope,
                metadata_store=store,
                codex_tool_store=codex_tool_store,
            )
        if not stream_telemetry_deferred:
            target_provider = (
                route.target_provider if route is not None else source_provider
            )
            provider_name = route.provider_name if route is not None else ""
            _try_stop_profiler(
                deep_profiler,
                request.app,
                request_id=request_id,
                model=model,
                source=source_provider,
                target=target_provider,
                is_stream=is_stream,
                duration_ms=duration_ms,
            )
            _record_telemetry(
                request,
                model=model,
                source_provider=source_provider,
                target_provider=target_provider,
                provider_name=provider_name,
                is_stream=is_stream,
                status_code=status_code,
                duration_ms=duration_ms,
                error_detail=error_detail,
                profile=profile,
                entry_id_override=pre_entry_id,
            )


# --- Endpoint handlers ---


async def handle_openai_chat(request: Any) -> Response | StreamingResponse:
    return await _proxy_handler(request, source_provider="openai_chat")


async def handle_codex_search(request: Any) -> Response:
    config: GatewayConfig = request.app.gateway_config
    return await _handle_codex_auxiliary(request, config, "alpha/search")


async def handle_image_generation(request: Any) -> Response:
    config: GatewayConfig = request.app.gateway_config
    return await _handle_codex_auxiliary(request, config, "images/generations")


async def handle_image_edit(request: Any) -> Response:
    config: GatewayConfig = request.app.gateway_config
    return await _handle_codex_auxiliary(request, config, "images/edits")


async def handle_anthropic(request: Any) -> Response | StreamingResponse:
    return await _proxy_handler(request, source_provider="anthropic")


async def handle_openai_responses(request: Any) -> Response | StreamingResponse:
    return await _proxy_handler(request, source_provider="openai_responses")


async def handle_google_genai(
    request: Any, model_path: str = ""
) -> Response | StreamingResponse:
    if model_path.endswith(":streamGenerateContent"):
        model = model_path.removesuffix(":streamGenerateContent")
        return await _proxy_handler(
            request,
            source_provider="google",
            model_override=model,
            force_stream=True,
        )
    elif model_path.endswith(":generateContent"):
        model = model_path.removesuffix(":generateContent")
        return await _proxy_handler(
            request, source_provider="google", model_override=model
        )
    else:
        return error_response_for_source("google", 404, "Unknown Google GenAI method")


async def handle_list_models(request: Any) -> Response:
    """List configured models in a format compatible with OpenAI and Anthropic SDKs."""
    config: GatewayConfig = request.app.gateway_config
    models = sorted(config.models.keys())
    data = []
    for name in models:
        provider_name = config.models[name]
        api_standard = config.provider_types.get(provider_name, "unknown")
        input_modalities = config.model_input_modalities.get(name)
        data.append(
            {
                "id": name,
                "object": "model",
                "created": 0,
                "owned_by": provider_name,
                "api_standard": api_standard,
                "input_modalities": input_modalities,
                "type": "model",
                "display_name": name,
                "created_at": "1970-01-01T00:00:00Z",
            }
        )
    return JSONResponse(
        {
            "object": "list",
            "data": data,
            "has_more": False,
            "first_id": models[0] if models else None,
            "last_id": models[-1] if models else None,
        }
    )


async def handle_list_models_google(request: Any) -> Response:
    """List configured models in Google GenAI SDK format."""
    config: GatewayConfig = request.app.gateway_config
    models_list = [
        {
            "name": f"models/{name}",
            "displayName": name,
            "supportedGenerationMethods": [
                "generateContent",
                "streamGenerateContent",
            ],
        }
        for name in sorted(config.models.keys())
    ]
    return JSONResponse({"models": models_list})


async def handle_health(request: Any) -> Response:
    """Return operational metrics and per-provider health status.

    Always returns HTTP 200. Use ``status: "degraded"`` in the payload
    to signal provider issues without breaking existing monitors.
    For a 503-on-unhealthy probe use ``/health/ready``.
    """
    metrics = getattr(request.app, "metrics", None)
    if metrics is None:
        return JSONResponse({"status": "ok"})

    return JSONResponse(build_health_payload(metrics), status_code=200)


async def handle_health_live(request: Any) -> Response:
    """Kubernetes liveness probe — always 200 while the process is up."""
    return JSONResponse({"status": "ok"})


async def handle_health_ready(request: Any) -> Response:
    """Kubernetes readiness probe — 200 if all providers are operational, 503 if not."""
    metrics = getattr(request.app, "metrics", None)
    if metrics is None:
        return JSONResponse({"status": "ok"})

    payload, status_code = build_readiness_payload(metrics)
    return JSONResponse(payload, status_code=status_code)


# ---------------------------------------------------------------------------
# Persistence flush helpers
# ---------------------------------------------------------------------------

_FLUSH_METRICS_INTERVAL = 30  # seconds


async def _periodic_flush(app: App) -> None:
    """Periodically flush metrics counters to disk."""
    while True:
        await asyncio.sleep(_FLUSH_METRICS_INTERVAL)
        persistence = getattr(app, "persistence", None)
        if persistence is None:
            continue
        metrics = getattr(app, "metrics", None)
        if metrics is not None:
            try:
                persistence.save_metrics(metrics.export_counters())
            except Exception as exc:
                logger.warning("Failed to flush metrics: %s", exc)


async def _periodic_tool_call_mapping_cleanup(app: App) -> None:
    """Periodically delete expired persistent tool-call mappings."""
    while True:
        await asyncio.sleep(_TOOL_CALL_CACHE_CLEANUP_INTERVAL)
        persistence = getattr(app, "persistence", None)
        if persistence is None:
            continue
        try:
            now = datetime.now(timezone.utc).isoformat()
            persistence.cleanup_expired_tool_history_translations(now)
            persistence.cleanup_expired_codex_compaction_mappings(now)
        except Exception as exc:
            logger.warning("Failed to clean up tool-call mapping cache: %s", exc)


def _flush_now(app: App) -> None:
    """Final synchronous flush on shutdown."""
    persistence = getattr(app, "persistence", None)
    if persistence is None:
        return

    metrics = getattr(app, "metrics", None)
    if metrics is not None:
        try:
            persistence.save_metrics(metrics.export_counters())
        except Exception as exc:
            logger.warning("Shutdown: failed to flush metrics: %s", exc)

    persistence.close()
    logger.info("Persistence flushed and closed on shutdown")


def _bind_provider_current_recorders(  # noqa: C901
    config: GatewayConfig,
    config_path: str | None,
) -> None:
    """Bind config-path-aware URL and credential recorders per provider row."""
    write_lock = asyncio.Lock()

    async def record(configured_id: str, base_url: str) -> None:
        if config_path is None:
            raise RuntimeError("Provider base URL state cannot be persisted")
        async with write_lock:
            try:
                document = load_config_raw(config_path)
                providers = document.get("providers")
                if not isinstance(providers, dict):
                    raise ValueError
                provider = providers.get(configured_id)
                if not isinstance(provider, dict):
                    raise ValueError
                provider["current_base_url"] = base_url
                write_config(config_path, document)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise RuntimeError(
                    "Provider base URL state could not be persisted"
                ) from None

    async def record_credential(configured_id: str, credential_id: str) -> None:
        if config_path is None:
            raise RuntimeError("Provider credential state cannot be persisted")
        async with write_lock:
            try:
                document = load_config_raw(config_path)
                providers = document.get("providers")
                if not isinstance(providers, dict):
                    raise ValueError
                provider = providers.get(configured_id)
                if not isinstance(provider, dict):
                    raise ValueError
                provider["current_api_key"] = credential_id
                write_config(config_path, document)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise RuntimeError(
                    "Provider credential state could not be persisted"
                ) from None

    async def record_model_group(group_name: str, provider_name: str) -> None:
        if config_path is None:
            raise RuntimeError("Model group provider state cannot be persisted")
        async with write_lock:
            try:
                document = load_config_raw(config_path)
                groups = document.get("model_groups")
                if not isinstance(groups, dict):
                    raise ValueError
                group = groups.get(group_name)
                if not isinstance(group, dict):
                    raise ValueError
                names = group.get("provider")
                if not isinstance(names, list) or provider_name not in names:
                    raise ValueError
                group["provider"] = [
                    provider_name,
                    *[item for item in names if item != provider_name],
                ]
                write_config(config_path, document)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise RuntimeError(
                    "Model group provider state could not be persisted"
                ) from None

    for provider_info in config.providers.values():
        provider_info.bind_current_base_url_recorder(record)
        provider_info.bind_current_credential_recorder(record_credential)
    for ring in config.model_group_rings.values():
        ring.bind_recorder(record_model_group)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    config: GatewayConfig,
    config_path: str | None = None,
    *,
    codex_home: str | None = None,
    gateway_port: int | None = None,
) -> App:
    """Create the httpserver application."""
    from .transport import HttpTransport

    metadata_store = ProviderMetadataStore()
    codex_tool_store = CodexToolLocalizationStore()
    chat_tool_surface_coordinator = ChatToolSurfaceCoordinator(
        InMemoryChatToolSurfaceStore()
    )
    codex_search_reference_store = CodexSearchReferenceStore()
    from .search_usage import TavilyUsageState

    tavily_usage_state = TavilyUsageState()
    image_fetch_workers = ImageFetchWorkerPool()
    web_run_health_state = WebRunHealthState()
    transport = HttpTransport()
    _bind_provider_current_recorders(config, config_path)

    app = GatewayApp(
        max_body_size=config.request_body_limit_bytes,
        request_line_timeout=_INBOUND_REQUEST_LINE_TIMEOUT_SECONDS,
        header_timeout=_INBOUND_HEADER_TIMEOUT_SECONDS,
        body_timeout=_INBOUND_BODY_TIMEOUT_SECONDS,
        max_concurrent_request_parses=_INBOUND_MAX_CONCURRENT_REQUEST_PARSES,
    )
    setattr(app, "gateway_config", config)
    setattr(app, "web_run_health_state", web_run_health_state)
    setattr(app, "codex_home", resolve_codex_home(codex_home))
    setattr(app, "gateway_port", config.port if gateway_port is None else gateway_port)
    app.admin_cors_origins = tuple(config.admin_cors_origins)  # type: ignore

    # --- Routes ---
    app.route("/v1/alpha/search", methods=["POST"])(handle_codex_search)
    app.route("/v1/images/generations", methods=["POST"])(handle_image_generation)
    app.route("/v1/images/edits", methods=["POST"])(handle_image_edit)
    app.route("/v1/responses", methods=["POST"])(handle_openai_responses)
    app.route("/v1/models", methods=["GET"])(handle_list_models)
    app.route("/health", methods=["GET"])(handle_health)
    app.route("/health/live", methods=["GET"])(handle_health_live)
    app.route("/health/ready", methods=["GET"])(handle_health_ready)

    # --- Auth ---
    import secrets

    internal_token = f"rsk-internal-{secrets.token_hex(16)}"
    admin_session_secret = load_or_create_admin_session_secret(config_path)
    auth_state = AuthState(
        config.api_key_principals,
        config.api_key_labels,
        internal_token,
        admin_password=config.admin_password,
        admin_session_secret=admin_session_secret,
    )
    upstream_error_log_state = UpstreamErrorLogState(
        {*config.token_values, internal_token}
    )
    body_log_state = BodyLogState(
        enabled=config.log_bodies,
        token_values={*config.token_values, internal_token},
    )
    auth_hook = create_auth_hook(auth_state)

    async def reset_admin_restart_notice(_request: Any) -> None:
        reset_codex_restart_required()

    app.before_body(reset_admin_restart_notice)
    app.before_body(auth_hook)
    app.before_request(reset_admin_restart_notice)
    app.before_request(auth_hook)

    # Decode Codex's optional request compression only after authentication.
    # The HTTP parser has already applied app.max_body_size to compressed bytes;
    # this hook applies the same live limit to decoded bytes before JSON parsing.
    from .inbound_content_encoding import decode_inbound_zstd

    app.before_request(decode_inbound_zstd)

    # --- CORS ---
    # Admin API endpoints are restricted to same-origin by default.
    # /v1/* proxy endpoints remain open (Access-Control-Allow-Origin: *).
    # The list of allowed origins for admin can be overridden via
    # server.admin_cors_origins in config (default [] = same-origin only).
    @app.after_request
    async def add_cors_headers(request: Any, response: Any) -> Any:
        apply_cors_headers(request, response)
        restart_required = consume_codex_restart_required()
        if restart_required and response.status_code < 400:
            response.headers["X-Codex-Restart-Required"] = "true"
        if is_admin_path(request.path):
            # Restricted CORS for admin endpoints: same-origin only by default,
            # or explicit allow-list via server.admin_cors_origins.
            # Prevent reverse-proxy caching of admin API responses (e.g. Caddy/Souin).
            # Uses the full directive set that Souin recognises as NO-STORE-DIRECTIVE.
            if request.path.startswith("/admin/api/"):
                response.headers.setdefault(
                    "Cache-Control", "no-cache, no-store, must-revalidate"
                )
        return response

    @app.route("/<path:_path>", methods=["OPTIONS"])
    async def cors_preflight(request: Any, _path: str = "") -> Response:
        if is_admin_path(request.path) and not is_admin_origin_allowed(request):
            return JSONResponse(
                {"error": "Admin CORS origin is not allowed"}, status_code=403
            )
        resp = Response(body=b"", status_code=204)
        return apply_cors_headers(request, resp)

    @app.errorhandler(404)
    async def handle_404(request: Any, exc: Any) -> Response:
        resp = JSONResponse({"error": "Not Found"}, status_code=404)
        return apply_cors_headers(request, resp)

    @app.errorhandler(405)
    async def handle_405(request: Any, exc: Any) -> Response:
        resp = JSONResponse({"error": "Method Not Allowed"}, status_code=405)
        return apply_cors_headers(request, resp)

    # --- Admin routes ---
    from .admin import setup_admin
    from .admin.routes import register_admin_routes

    register_admin_routes(app)

    # --- App-level state ---
    app.transport = transport  # type: ignore
    app.metadata_store = metadata_store  # type: ignore
    app.codex_tool_store = codex_tool_store  # type: ignore
    app.chat_tool_surface_coordinator = chat_tool_surface_coordinator  # type: ignore
    app.codex_search_reference_store = codex_search_reference_store  # type: ignore
    app.tavily_usage_state = tavily_usage_state  # type: ignore
    app.image_fetch_workers = image_fetch_workers  # type: ignore
    app.internal_token = internal_token  # type: ignore
    app.auth_state = auth_state  # type: ignore
    app.upstream_error_log_state = upstream_error_log_state  # type: ignore
    app.body_log_state = body_log_state  # type: ignore

    setup_admin(app, config, config_path)
    app.search_provider_coordinator = SearchProviderChainCoordinator(  # type: ignore
        persistence=app.persistence,  # type: ignore
        tavily_usage_state=tavily_usage_state,
    )

    return app


async def run_gateway(
    app: App, host: str, port: int, *, socket: str | None = None
) -> None:
    """Start the gateway with lifecycle management."""
    # Expose bind address so admin test tasks can self-call.
    setattr(app, "_bind_host", host)
    setattr(app, "_bind_port", port)
    flush_task = asyncio.create_task(_periodic_flush(app))
    tool_cache_cleanup_task = asyncio.create_task(
        _periodic_tool_call_mapping_cleanup(app)
    )
    try:
        await app._serve(host, port, socket=socket)
    finally:
        for task in (flush_task, tool_cache_cleanup_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        admin_runtime_state = getattr(app, "admin_runtime_state", None)
        if admin_runtime_state is not None:
            await admin_runtime_state.aclose()
        _flush_now(app)
        await close_resources(
            transport=app.transport,  # type: ignore
            metadata_store=app.metadata_store,  # type: ignore
            codex_tool_store=app.codex_tool_store,  # type: ignore
            codex_search_reference_store=app.codex_search_reference_store,  # type: ignore
            image_fetch_workers=app.image_fetch_workers,  # type: ignore
        )
