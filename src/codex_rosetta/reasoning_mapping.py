"""Migration guards for the removed model-specific reasoning mapper.

Request reasoning is now owned by the selected Provider Profile and standard
converter.  These names remain temporarily importable so older integrations
receive an actionable validation error instead of silently changing the wire
format.
"""

from __future__ import annotations

from typing import Any, NoReturn

REMOVED_REASONING_MAPPING_ERROR = (
    "model-specific reasoning_mapping was removed; select an explicit provider "
    "+ api_type and configure supported_reasoning_levels in model_info or "
    "runtime_capabilities"
)


def _removed() -> NoReturn:
    raise ValueError(REMOVED_REASONING_MAPPING_ERROR)


def normalize_reasoning_mapping(value: Any) -> NoReturn:
    """Reject the removed configuration entry with migration guidance."""

    del value
    _removed()


def resolve_reasoning_mapping(**kwargs: Any) -> NoReturn:
    """Reject the removed model-name routing API with migration guidance."""

    del kwargs
    _removed()


def normalize_reasoning_effort(
    raw_effort: Any,
    *,
    mode: Any = None,
    warnings: list[str] | None = None,
) -> NoReturn:
    """Reject the removed mapper-owned effort normalization API."""

    del raw_effort, mode, warnings
    _removed()


def apply_reasoning_mapping_to_provider_request(
    target_body: dict[str, Any],
    **kwargs: Any,
) -> NoReturn:
    """Reject the removed raw request mutation API."""

    del target_body, kwargs
    _removed()
