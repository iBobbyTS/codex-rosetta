"""Gateway provider definitions — registry, factory, and defaults.

Transport-level classes (:class:`ProviderInfo`) and auth header builders live
in :mod:`gateway.transport.provider_info`.  This module
keeps the provider *registry* and *factory* that resolve shim config into
runtime :class:`ProviderInfo` instances.
"""

from __future__ import annotations

import logging
from typing import Any

from .transport.provider_info import (
    ProviderInfo,
    anthropic_auth,
    google_auth,
    openai_auth,
)

# Re-export ProviderInfo so existing ``from .providers import ProviderInfo``
# continues to work without changes across the codebase.
__all__ = [
    "ProviderInfo",
    "build_provider_info",
    "normalize_provider_api_key",
    "provider_api_key_values",
]

logger = logging.getLogger("codex-rosetta-gateway")


# ---------------------------------------------------------------------------
# Provider registry — known provider types and their characteristics
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "openai_chat": {
        "default_base_url": "https://api.openai.com/v1",
        "default_api_key_env": "OPENAI_API_KEY",
        "auth_header_fn": openai_auth,
        "url_template": "{base_url}/chat/completions",
    },
    "openai_responses": {
        "default_base_url": "https://api.openai.com/v1",
        "default_api_key_env": "OPENAI_API_KEY",
        "auth_header_fn": openai_auth,
        "url_template": "{base_url}/responses",
    },
    "open_responses": {
        "default_base_url": "https://api.openai.com/v1",
        "default_api_key_env": "OPENAI_API_KEY",
        "auth_header_fn": openai_auth,
        "url_template": "{base_url}/responses",
    },
    "anthropic": {
        "default_base_url": "https://api.anthropic.com",
        "default_api_key_env": "ANTHROPIC_API_KEY",
        "auth_header_fn": anthropic_auth,
        "url_template": "{base_url}/v1/messages",
    },
    "google": {
        "default_base_url": "https://generativelanguage.googleapis.com",
        "default_api_key_env": "GOOGLE_API_KEY",
        "auth_header_fn": google_auth,
        "url_template": "{base_url}/v1beta/models/{model}:generateContent",
        "stream_url_template": "{base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse",
    },
}


def get_default_base_url(provider_type: str) -> str:
    """Return the default base URL for a known provider type, or ``""``."""
    entry = _PROVIDER_REGISTRY.get(provider_type)
    return entry["default_base_url"] if entry else ""


def get_default_api_key_env(provider_type: str) -> str:
    """Return the default env-var name for a provider's API key."""
    entry = _PROVIDER_REGISTRY.get(provider_type)
    return entry["default_api_key_env"] if entry else f"{provider_type.upper()}_API_KEY"


def known_provider_types() -> list[str]:
    """Return the list of built-in provider type names."""
    return list(_PROVIDER_REGISTRY)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def provider_api_key_values(value: Any) -> tuple[str, ...]:
    """Return credentials from the canonical provider credential list."""
    if not isinstance(value, list):
        raise ValueError("config: provider api_keys must be a list")
    values: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise ValueError("config: provider api_keys entries must contain key")
        key = item["key"].strip()
        if key:
            values.append(key)
    return tuple(values)


def normalize_provider_api_key(value: Any) -> str:
    """Return the first non-empty Provider credential from canonical values."""
    values = provider_api_key_values(value)
    return values[0] if values else ""


def build_provider_info(
    provider_type: str,
    cfg: dict[str, Any],
    *,
    configured_id: str | None = None,
    global_proxy: str | None = None,
    credential_inventory: set[str] | None = None,
) -> ProviderInfo:
    """Create a :class:`ProviderInfo` from a provider config dict.

    *provider_type* may be a base converter type (e.g. ``"openai_chat"``)
    or a registered shim name (e.g. ``"deepseek"``).  When a shim is
    found, its ``default_base_url`` and ``default_api_key_env`` are used
    as fallbacks when the config does not specify them.

    *cfg* is the dict from the JSONC config, e.g.
    ``{"api_keys": [{"id": "primary", "key": "sk-..."}],
    "base_urls": ["https://..."]}``

    *global_proxy* is the server-level proxy URL (from ``server.proxy``).
    A per-provider ``"proxy"`` key in *cfg* takes precedence.

    For known provider types the auth and URL logic is looked up from the
    registry.  Unknown types fall back to Bearer-token auth and a simple
    ``{base_url}/`` URL template.
    """
    import os

    from codex_rosetta.shims import get_shim

    # Resolve through shim registry for defaults
    shim = get_shim(provider_type)
    if shim is not None:
        base_type = shim.base
        # Apply shim defaults where config is missing
        if "base_urls" not in cfg and "base_url" not in cfg and shim.default_base_url:
            cfg = {**cfg, "base_urls": [shim.default_base_url]}
        if "api_keys" not in cfg and shim.default_api_key_env:
            env_val = os.environ.get(shim.default_api_key_env, "")
            if env_val:
                cfg = {**cfg, "api_keys": [{"id": "primary", "key": env_val}]}
    else:
        base_type = provider_type

    reg = _PROVIDER_REGISTRY.get(base_type)

    if reg:
        auth_fn = reg["auth_header_fn"]
        url_tpl = reg["url_template"]
        stream_tpl = reg.get("stream_url_template")
    else:
        # Unknown / custom provider — best-effort defaults
        auth_fn = openai_auth
        url_tpl = "{base_url}/"
        stream_tpl = None
        logger.warning(
            "Unknown provider type '%s'; using Bearer auth and generic URL template",
            base_type,
        )

    # Fall back to base-type defaults if still missing
    if "base_urls" not in cfg and "base_url" not in cfg:
        default_url = get_default_base_url(base_type)
        if default_url:
            cfg = {**cfg, "base_urls": [default_url]}
    if "api_keys" not in cfg:
        default_env = get_default_api_key_env(base_type)
        env_val = os.environ.get(default_env, "")
        if env_val:
            cfg = {**cfg, "api_keys": [{"id": "primary", "key": env_val}]}

    # Per-provider proxy overrides global proxy
    proxy_url = cfg.get("proxy") or global_proxy or None
    allow_redirects = cfg.get("allow_redirects", False)
    if not isinstance(allow_redirects, bool):
        raise ValueError("config: provider allow_redirects must be a boolean")
    soft_interrupt = cfg.get("soft_interrupt", False)
    if not isinstance(soft_interrupt, bool):
        raise ValueError("config: provider soft_interrupt must be a boolean")
    force_rosetta_compaction = cfg.get("force_rosetta_compaction", False)
    if not isinstance(force_rosetta_compaction, bool):
        raise ValueError("config: provider force_rosetta_compaction must be a boolean")

    raw_credentials = cfg.get("api_keys")
    if not isinstance(raw_credentials, list):
        raise ValueError("config: provider api_keys must be a list")
    credential_values = provider_api_key_values(raw_credentials)
    if credential_inventory is not None:
        credential_inventory.update(credential_values)
    credential_entries = tuple(
        (item["id"], item["key"])
        for item in raw_credentials
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("key"), str)
    )

    return ProviderInfo(
        name=provider_type,
        configured_id=configured_id,
        api_keys=credential_entries,
        current_api_key=cfg.get("current_api_key"),
        **(
            {
                "base_urls": cfg["base_urls"],
                "current_base_url": cfg.get("current_base_url"),
            }
            if "base_urls" in cfg
            else {"base_url": cfg["base_url"]}
        ),
        auth_header_fn=auth_fn,
        url_template=url_tpl,
        stream_url_template=stream_tpl,
        proxy_url=proxy_url,
        allow_redirects=allow_redirects,
        soft_interrupt=soft_interrupt,
        force_rosetta_compaction=force_rosetta_compaction,
    )
