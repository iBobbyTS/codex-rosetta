"""Profile-backed OpenAI Images API routing for Codex image_gen.imagegen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from codex_rosetta.routing import ResolvedRoute

from .transport import ProviderInfo
from .transport.provider_info import openai_auth

if TYPE_CHECKING:
    from .config import GatewayConfig

IMAGE_ENDPOINTS = frozenset({"images/generations", "images/edits"})
IMAGEGEN_PROFILE_ITEM_ID = "namespace.image_gen.imagegen"
CODEX_IMAGE_MODEL = "gpt-image-2"


class CodexImageConfigurationError(ValueError):
    """Raised when Modified image generation lacks a usable OpenAI endpoint."""


def profile_image_provider(
    route: ResolvedRoute,
    *,
    proxy_url: str | None,
) -> ProviderInfo:
    """Build the OpenAI Images provider declared by the selected Tool Profile."""
    values: dict[str, Any] = route.tool_profile_inputs.get(IMAGEGEN_PROFILE_ITEM_ID, {})
    base_url = str(values.get("base_url", "")).strip()
    token = str(values.get("token", "")).strip()
    if not base_url:
        raise CodexImageConfigurationError(
            "image_gen.imagegen Modified requires a Base URL"
        )
    if not token:
        raise CodexImageConfigurationError(
            "image_gen.imagegen Modified requires a Token"
        )
    try:
        return ProviderInfo(
            "image_gen.imagegen",
            api_key=token,
            base_url=base_url,
            auth_header_fn=openai_auth,
            url_template="{base_url}",
            proxy_url=proxy_url,
        )
    except ValueError as exc:
        raise CodexImageConfigurationError(str(exc)) from exc


def resolve_unique_profile_image_route(
    config: GatewayConfig,
) -> tuple[ResolvedRoute, ProviderInfo] | None:
    """Resolve Codex's fixed image model through one unambiguous profile target.

    Standalone Codex Images requests do not identify the parent LLM route.  A
    fixed image-model request can therefore use Tool Profile routing only when
    every enabled Modified image mapping resolves to the same endpoint and
    credential set.  Conflicting mappings fail closed instead of depending on
    configuration order.
    """
    candidates: dict[
        tuple[str, tuple[str, ...], str | None], tuple[ResolvedRoute, ProviderInfo]
    ] = {}
    for model in sorted(config.models):
        route, _ = config.resolve("openai_responses", model)
        if route.tool_profile.get(IMAGEGEN_PROFILE_ITEM_ID) != "modified":
            continue
        provider = profile_image_provider(route, proxy_url=config.proxy)
        identity = (
            provider.base_url,
            provider.credential_values,
            provider.proxy_url,
        )
        candidates.setdefault(identity, (route, provider))

    if not candidates:
        return None
    if len(candidates) > 1:
        raise CodexImageConfigurationError(
            "Codex fixed image model cannot be routed because multiple distinct "
            "Modified image_gen.imagegen mappings are configured"
        )
    return next(iter(candidates.values()))


def image_trace_summary(upstream_path: str, provider: ProviderInfo) -> dict[str, str]:
    """Return a secret-free Gateway Logs summary for one Images API request."""
    return {
        "endpoint": upstream_path,
        "executor": "openai_images_api",
        "base_url": provider.base_url,
    }
