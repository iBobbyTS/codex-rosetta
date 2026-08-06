"""Codex Search and Images endpoint pass-through handlers."""

from __future__ import annotations

import time
from typing import Any

from codex_rosetta._vendor.httpserver import JSONResponse, Response
from codex_rosetta.routing import ResolvedRoute, is_responses_passthrough

from .auth import api_key_principal_var
from .codex_images import (
    CODEX_IMAGE_MODEL,
    IMAGE_ENDPOINTS,
    IMAGEGEN_PROFILE_ITEM_ID,
    CodexImageConfigurationError,
    image_trace_summary,
    profile_image_provider,
    resolve_unique_profile_image_route,
)
from .codex_page import StaticPageClient
from .codex_search import (
    CodexSearchBridgeResult,
    CodexSearchExecutionError,
    CodexSearchInvalidRequest,
    CodexSearchNotImplemented,
    codex_search_request_summary,
    execute_local_codex_search,
    should_use_local_codex_search,
)
from .codex_search_references import CodexSearchReferenceStore
from .search_provider_chain import (
    SearchProviderBudgetExceeded,
    SearchProviderChainUnavailable,
    SearchProviderChainUnavailableReason,
    SearchProviderChainCoordinator,
)
from .search_provider_executor import (
    SearchProviderExecutor,
    SearchProviderTerminalError,
)
from .config import GatewayConfig
from .downstream_errors import (
    DownstreamErrorOrigin,
    classify_downstream_exception,
    format_downstream_error,
    prefix_error_body,
)
from .headers import build_upstream_extra_headers, resolve_request_id
from .logging import record_request_stat
from .proxy import error_response_for_source, extract_model
from .stream_trace import StreamTraceLogger, StreamTraceState
from .tool_profiles import route_tool_state
from .transport import ProviderInfo, UpstreamConnectionError, UpstreamTransport
from .transport.credential_redaction import CredentialRedactingTransport
from .web_run_sidecar import (
    WebRunBrowserClient,
    WebRunSearchClient,
    WebRunSidecarHTTPClient,
)
from .web_run_capabilities import (
    web_run_capability_trace_summary,
    web_run_search_projection_capabilities,
)

_BROWSER_USE_HINT = 'Consider "Browser Use" skill'


def _native_auxiliary_endpoint_available(
    *,
    native_passthrough: bool,
    upstream_path: str,
    web_run_state: str,
    image_tool_state: str,
) -> bool:
    if upstream_path in IMAGE_ENDPOINTS:
        return native_passthrough and image_tool_state == "passthrough"
    return native_passthrough and (
        upstream_path != "alpha/search" or web_run_state == "passthrough"
    )


def _apply_auxiliary_model_alias(
    body: dict[str, Any],
    route: ResolvedRoute,
    *,
    fixed_image_route_fallback: bool,
    override_model: str | None,
) -> None:
    """Apply model routing only when the effective endpoint owns that alias."""
    if override_model is not None:
        body["model"] = override_model
    elif route.upstream_model and not fixed_image_route_fallback:
        body["model"] = route.upstream_model


def _unavailable_auxiliary_message(
    upstream_path: str,
    *,
    profile_selected: bool,
    web_run_state: str,
    image_tool_state: str,
) -> str:
    if (
        profile_selected
        and upstream_path == "alpha/search"
        and web_run_state == "disabled"
    ):
        return "web.run is disabled by the selected Tool Profile"
    if (
        profile_selected
        and upstream_path in IMAGE_ENDPOINTS
        and image_tool_state == "disabled"
    ):
        return "image_gen.imagegen is disabled by the selected Tool Profile"
    return (
        f"POST /v1/{upstream_path} is only implemented for OpenAI Responses providers"
    )


def _log_profile_image_request(
    trace: StreamTraceLogger | None,
    *,
    enabled: bool,
    upstream_path: str,
    provider_info: Any,
) -> None:
    if enabled and trace is not None:
        trace.log(
            "codex_image_request",
            image_trace_summary(upstream_path, provider_info),
        )


def _log_profile_image_response(
    trace: StreamTraceLogger | None,
    *,
    enabled: bool,
    status_code: int,
) -> None:
    if enabled and trace is not None:
        trace.log("codex_image_response", {"status_code": status_code})


def _resolve_auxiliary_route(
    config: GatewayConfig,
    *,
    model: str,
    upstream_path: str,
) -> tuple[ResolvedRoute, ProviderInfo, bool] | Response:
    """Resolve a normal route or Codex's unambiguous fixed-image fallback."""
    try:
        route, provider_info = config.resolve("openai_responses", model)
        return route, provider_info, False
    except KeyError:
        resolved_image_route = None
        if upstream_path in IMAGE_ENDPOINTS and model == CODEX_IMAGE_MODEL:
            try:
                resolved_image_route = resolve_unique_profile_image_route(config)
            except CodexImageConfigurationError as exc:
                return error_response_for_source("openai_responses", 400, str(exc))
        if resolved_image_route is not None:
            route, provider_info = resolved_image_route
            return route, provider_info, True

    configured = ", ".join(sorted(config.models.keys()))
    return JSONResponse(
        {
            "error": {
                "message": format_downstream_error(
                    f"Unknown model: '{model}'. Configured models: {configured}",
                    DownstreamErrorOrigin.ROSETTA,
                ),
                "type": "model_not_found",
                "code": None,
            }
        },
        status_code=404,
    )


async def handle_codex_auxiliary(  # noqa: C901
    request: Any,
    config: GatewayConfig,
    upstream_path: str,
    *,
    search_client: WebRunSearchClient | None = None,
    page_client: StaticPageClient | None = None,
    browser_client: WebRunBrowserClient | None = None,
) -> Response:
    """Handle Codex Search locally when configured, or pass auxiliaries through."""

    try:
        request_id = resolve_request_id(request.headers.get("x-request-id"))
    except ValueError as exc:
        return error_response_for_source("openai_responses", 400, str(exc))

    try:
        body: dict[str, Any] = request.json()
    except Exception:
        return error_response_for_source("openai_responses", 400, "Invalid JSON body")
    if not isinstance(body, dict):
        return error_response_for_source(
            "openai_responses", 400, "JSON body must be an object"
        )

    try:
        model = extract_model("openai_responses", body)
    except ValueError as exc:
        return error_response_for_source("openai_responses", 400, str(exc))
    if not model:
        return error_response_for_source(
            "openai_responses", 400, "Missing 'model' in request body"
        )

    resolved_route = _resolve_auxiliary_route(
        config,
        model=model,
        upstream_path=upstream_path,
    )
    if isinstance(resolved_route, Response):
        return resolved_route
    route, provider_info, fixed_image_route_fallback = resolved_route

    native_passthrough = is_responses_passthrough(route)
    web_run_state = route_tool_state(route, "namespace.web.run", "modified")
    image_tool_state = route_tool_state(route, IMAGEGEN_PROFILE_ITEM_ID, "disabled")
    web_run_mapping = web_run_state == "modified"
    web_run_config = config.web_search
    search_candidates = tuple(getattr(config, "web_search_candidates", ()))
    search_coordinator = getattr(request.app, "search_provider_coordinator", None)
    if not isinstance(search_coordinator, SearchProviderChainCoordinator):
        search_coordinator = SearchProviderChainCoordinator()
        if hasattr(request.app, "__dict__"):
            setattr(request.app, "search_provider_coordinator", search_coordinator)
    use_chain_search = (
        upstream_path == "alpha/search"
        and web_run_mapping
        and not (
            isinstance(body.get("commands"), dict) and body["commands"].get("weather")
        )
        and not isinstance(
            getattr(request.app, "search_provider_coordinator", None), type(None)
        )
        and isinstance(body.get("commands"), dict)
        and bool(body["commands"].get("search_query"))
    )
    configured_sidecar_client = _configured_sidecar_client(config)
    resolved_browser_client = browser_client or configured_sidecar_client
    resolved_search_client = search_client or configured_sidecar_client
    use_profile_images = (
        upstream_path in IMAGE_ENDPOINTS and image_tool_state == "modified"
    )
    use_local_search = (
        upstream_path == "alpha/search"
        and not use_chain_search
        and web_run_mapping
        and should_use_local_codex_search(
            body,
            web_run_config,
            native_passthrough_available=False,
            browser_available=resolved_browser_client is not None,
        )
    )
    native_endpoint_available = (
        use_chain_search
        or _native_auxiliary_endpoint_available(
            native_passthrough=native_passthrough,
            upstream_path=upstream_path,
            web_run_state=web_run_state,
            image_tool_state=image_tool_state,
        )
    )
    if (
        not native_endpoint_available
        and not use_local_search
        and not use_profile_images
    ):
        message = _unavailable_auxiliary_message(
            upstream_path,
            profile_selected=route.tool_profile_name is not None,
            web_run_state=web_run_state,
            image_tool_state=image_tool_state,
        )
        return error_response_for_source(
            "openai_responses",
            501,
            _with_browser_use_hint(message),
            origin=(
                DownstreamErrorOrigin.BLOCKED
                if "disabled by the selected Tool Profile" in message
                else DownstreamErrorOrigin.ROSETTA
            ),
        )

    active_provider_name = route.provider_name
    active_target_provider = route.target_provider
    active_provider_info = provider_info
    if use_profile_images:
        try:
            active_provider_info = profile_image_provider(
                route,
                proxy_url=config.proxy,
            )
        except CodexImageConfigurationError as exc:
            return error_response_for_source("openai_responses", 400, str(exc))
    _apply_auxiliary_model_alias(
        body,
        route,
        fixed_image_route_fallback=fixed_image_route_fallback,
        override_model=None,
    )

    resolved_model = str(body.get("model") or route.upstream_model or model)
    telemetry_model = model
    upstream_url = f"{active_provider_info.base_url}/{upstream_path}"
    transport: UpstreamTransport = CredentialRedactingTransport.wrap(
        request.app.transport
    )
    extra_headers = build_upstream_extra_headers(request, request_id)
    trace = _create_auxiliary_trace(
        request,
        request_id=request_id,
        model=model,
        route=route,
        target_provider=active_target_provider,
        provider_name=active_provider_name,
    )
    started_at = time.monotonic()
    status_code = 500
    error_detail: str | None = None

    try:
        if use_local_search or use_chain_search:
            reference_store, principal_id = _search_reference_context(request)
            (
                response,
                status_code,
                error_detail,
                search_result,
            ) = await _handle_local_search(
                trace,
                body,
                web_run_config,
                resolved_search_client,
                page_client,
                resolved_browser_client,
                reference_store,
                principal_id,
                search_candidates=search_candidates
                if (upstream_path == "alpha/search" and web_run_mapping)
                else None,
                search_coordinator=search_coordinator if use_chain_search else None,
                search_executor=_search_executor(
                    request,
                    injected_search_client=search_client,
                    configured_sidecar_client=configured_sidecar_client,
                    transport=transport,
                    extra_headers=extra_headers,
                ),
                capability_trace_route=route,
            )
            if search_result is not None:
                attribution = search_result.attribution
                if attribution is not None:
                    active_provider_name = attribution.provider_name
                    active_target_provider = attribution.target_provider
                    resolved_model = attribution.model
                    telemetry_model = attribution.model
                success_trace = _create_auxiliary_trace(
                    request,
                    request_id=request_id,
                    model=telemetry_model,
                    route=route,
                    target_provider=active_target_provider,
                    provider_name=active_provider_name,
                )
                if success_trace is not None:
                    success_trace.log(
                        "codex_search_request", codex_search_request_summary(body)
                    )
                    success_trace.log(
                        "codex_search_capability_projection",
                        web_run_capability_trace_summary(
                            web_run_search_projection_capabilities(route),
                            body.get("commands", {}).keys()
                            if isinstance(body.get("commands"), dict)
                            else (),
                        ),
                    )
                    success_trace.log(
                        "codex_search_response", search_result.trace_summary()
                    )
            return response

        _log_profile_image_request(
            trace,
            enabled=use_profile_images,
            upstream_path=upstream_path,
            provider_info=active_provider_info,
        )

        response = await transport.send_passthrough(
            active_provider_info,
            upstream_url,
            body,
            extra_headers=extra_headers,
        )
        status_code = response.status_code
        if response.is_error:
            error_detail = response.error_text
        _log_profile_image_response(
            trace,
            enabled=use_profile_images,
            status_code=response.status_code,
        )
        response_body = (
            prefix_error_body(
                response.raw_content,
                DownstreamErrorOrigin.UPSTREAM,
                fallback=(
                    f"HTTP {response.status_code} error response did not include a message"
                ),
            )
            if response.is_error
            else response.raw_content
        )
        return Response(
            body=response_body,
            status_code=response.status_code,
            content_type="application/json",
        )
    except UpstreamConnectionError as exc:
        error_detail = str(exc)
        status_code = 502
        return error_response_for_source(
            "openai_responses",
            502,
            str(exc),
            origin=classify_downstream_exception(exc),
        )
    except Exception as exc:
        error_detail = str(exc)
        raise
    finally:
        from .app import _record_telemetry

        record_request_stat(resolved_model)
        _record_telemetry(
            request,
            model=telemetry_model,
            source_provider="openai_responses",
            target_provider=active_target_provider,
            provider_name=active_provider_name,
            is_stream=False,
            status_code=status_code,
            duration_ms=(time.monotonic() - started_at) * 1000,
            error_detail=error_detail,
        )


def _search_reference_context(
    request: Any,
) -> tuple[CodexSearchReferenceStore | None, str | None]:
    store = getattr(request.app, "codex_search_reference_store", None)
    return (
        store if isinstance(store, CodexSearchReferenceStore) else None,
        api_key_principal_var.get(),
    )


def _configured_sidecar_client(config: GatewayConfig) -> WebRunSidecarHTTPClient | None:
    if not config.web_run_sidecar_url or not config.web_run_sidecar_token:
        return None
    return WebRunSidecarHTTPClient(
        config.web_run_sidecar_url,
        config.web_run_sidecar_token,
        timeout=config.web_run_sidecar_timeout,
    )


def _search_executor(
    request: Any,
    *,
    injected_search_client: WebRunSearchClient | None,
    configured_sidecar_client: WebRunSidecarHTTPClient | None,
    transport: UpstreamTransport,
    extra_headers: dict[str, str],
) -> SearchProviderExecutor:
    configured = getattr(request.app, "search_provider_executor", None)
    if isinstance(configured, SearchProviderExecutor):
        return configured
    return SearchProviderExecutor(
        tavily_client=injected_search_client,
        self_hosted_client=injected_search_client,
        candidate_self_hosted_client=(
            configured_sidecar_client if injected_search_client is None else None
        ),
        responses_transport=transport,
        responses_extra_headers=extra_headers,
    )


async def _handle_local_search(
    trace: StreamTraceLogger | None,
    body: dict[str, Any],
    web_search_config: dict[str, Any],
    search_client: WebRunSearchClient | None,
    page_client: StaticPageClient | None,
    browser_client: WebRunBrowserClient | None,
    reference_store: CodexSearchReferenceStore | None,
    principal_id: str | None,
    *,
    search_candidates: tuple[Any, ...] | None = None,
    search_coordinator: Any | None = None,
    search_executor: SearchProviderExecutor | None = None,
    capability_trace_route: ResolvedRoute | None = None,
) -> tuple[Response, int, str | None, CodexSearchBridgeResult | None]:
    request_summary = codex_search_request_summary(body)

    def log_failure(
        stage: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if trace is None:
            return
        trace.log("codex_search_request", request_summary)
        if capability_trace_route is not None:
            trace.log(
                "codex_search_capability_projection",
                web_run_capability_trace_summary(
                    web_run_search_projection_capabilities(capability_trace_route),
                    body.get("commands", {}).keys()
                    if isinstance(body.get("commands"), dict)
                    else (),
                ),
            )
        if stage is not None:
            trace.log(stage, data or {})

    try:
        result = await execute_local_codex_search(
            body,
            web_search_config,
            client=search_client,
            page_client=page_client,
            browser_client=browser_client,
            reference_store=reference_store,
            principal_id=principal_id,
            search_candidates=search_candidates,
            search_coordinator=search_coordinator,
            search_executor=search_executor,
        )
    except CodexSearchNotImplemented as exc:
        error = str(exc)
        log_failure("codex_search_not_implemented", {"error": error})
        return _not_implemented_response(error), 501, error, None
    except SearchProviderBudgetExceeded:
        error = "Search provider request budget exceeded"
        log_failure()
        return (
            error_response_for_source("openai_responses", 504, error),
            504,
            error,
            None,
        )
    except SearchProviderChainUnavailable as exc:
        if exc.reason is SearchProviderChainUnavailableReason.EMPTY_CHAIN:
            error = "未配置搜索能力"
            log_failure()
            return (
                error_response_for_source("openai_responses", 501, error),
                501,
                error,
                None,
            )
        error = "搜索能力全部无效"
        log_failure()
        return (
            error_response_for_source("openai_responses", 502, error),
            502,
            error,
            None,
        )
    except SearchProviderTerminalError:
        error = "Search request rejected"
        log_failure()
        return (
            error_response_for_source("openai_responses", 422, error),
            422,
            error,
            None,
        )
    except CodexSearchInvalidRequest as exc:
        error = str(exc)
        log_failure("codex_search_invalid_request", {"error": error})
        return (
            error_response_for_source(
                "openai_responses",
                400,
                error,
                origin=classify_downstream_exception(exc),
            ),
            400,
            error,
            None,
        )
    except CodexSearchExecutionError as exc:
        error = str(exc)
        log_failure("codex_search_execution_error", {"error": error})
        origin = classify_downstream_exception(exc)
        if origin is DownstreamErrorOrigin.ROSETTA:
            origin = DownstreamErrorOrigin.UPSTREAM
        return (
            error_response_for_source("openai_responses", 502, error, origin=origin),
            502,
            error,
            None,
        )
    except Exception:
        log_failure()
        raise

    return JSONResponse(result.response_body()), 200, None, result


def _not_implemented_response(message: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "message": format_downstream_error(
                    _with_browser_use_hint(message), DownstreamErrorOrigin.ROSETTA
                ),
                "type": "not_implemented_error",
                "code": "not_implemented",
            }
        },
        status_code=501,
    )


def _with_browser_use_hint(message: str) -> str:
    return f"{message.rstrip('.')}. {_BROWSER_USE_HINT}"


def _create_auxiliary_trace(
    request: Any,
    *,
    request_id: str,
    model: str,
    route: Any,
    target_provider: str | None = None,
    provider_name: str | None = None,
) -> StreamTraceLogger | None:
    state = getattr(request.app, "stream_trace_state", None)
    if not isinstance(state, StreamTraceState):
        return None
    return state.create_logger(
        request_id=request_id,
        request_log_id=None,
        model=model,
        source_provider=route.source_provider,
        target_provider=target_provider or route.target_provider,
        provider_name=provider_name or route.provider_name,
    )
