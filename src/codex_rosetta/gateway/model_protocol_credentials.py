"""Confirmed authentication locations for model-generation protocols."""

from __future__ import annotations

from types import MappingProxyType

from codex_rosetta.auto_detect import ProviderType

JsonFieldPath = tuple[str, ...]

# These paths are intentionally protocol-declared rather than discovered by
# scanning model content. The current supported response protocols do not
# define API authentication fields in successful or streaming response bodies.
MODEL_RESPONSE_AUTH_FIELD_PATHS: MappingProxyType[
    ProviderType, tuple[JsonFieldPath, ...]
] = MappingProxyType(
    {
        "openai_chat": (),
        "openai_responses": (),
        "open_responses": (),
        "anthropic": (),
        "google": (),
    }
)

__all__ = ["MODEL_RESPONSE_AUTH_FIELD_PATHS"]
