"""Input adaptation for model reasoning and preset-defined modalities.

This module handles **platform-level** constraints that apply regardless of
provider dialect. The pipeline adapts the IR request to match the input
modalities declared by the bundled model preset.

This is distinct from **shim transforms** (provider-specific dialect
adaptation) and from **converter logic** (API-standard translation).

Functions follow the ``enforce_*`` naming convention:

- :func:`enforce_reasoning` — configure reasoning output mode (pre-IR)
- :func:`enforce_vision` — strip images for non-vision models (post-IR)

Called by :class:`~codex_rosetta.pipeline.ConversionPipeline` at the
appropriate pipeline stages.
"""

from __future__ import annotations

from typing import Any, cast

from codex_rosetta.converters.base.context import ConversionContext
from codex_rosetta.shims.provider_shim import (
    ProviderShim,
    resolve_shim,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enforce_reasoning(
    ctx: ConversionContext,
    shim: ProviderShim | str | None,
) -> None:
    """Configure reasoning capability in the conversion context.

    Injects ``reasoning_cap`` into *ctx* so converters produce the
    correct thinking/reasoning output for the target provider.

    Must be called **before** source → IR conversion (converters read
    ``ctx.options["reasoning_cap"]`` during parsing).

    Args:
        ctx: Conversion context to mutate.
        shim: ProviderShim instance, registered name, or None (no-op).
    """
    resolved = resolve_shim(shim)
    if resolved is None:
        return

    cap = resolved.reasoning
    if cap is not None:
        ctx.options["reasoning_cap"] = cap


_REASONING_LADDER = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def enforce_reasoning_levels(
    ir_request: dict[str, object],
    *,
    supported_levels: list[str] | None,
    warnings: list[str],
) -> dict[str, object]:
    """Clamp IR reasoning effort to the nearest declared model capability."""
    reasoning = ir_request.get("reasoning")
    if not isinstance(reasoning, dict) or not supported_levels:
        return ir_request
    reasoning_fields = cast(dict[str, object], reasoning)
    requested = reasoning_fields.get("effort")
    if not isinstance(requested, str) or requested in supported_levels:
        return ir_request
    rank = {value: index for index, value in enumerate(_REASONING_LADDER)}
    if requested not in rank:
        return ir_request
    candidates = [value for value in supported_levels if value in rank]
    if not candidates:
        return ir_request
    effective = min(
        candidates,
        key=lambda value: (abs(rank[value] - rank[requested]), rank[value]),
    )
    reasoning_fields["effort"] = effective
    warnings.append(
        f"Reasoning effort '{requested}' is unsupported by the resolved model "
        f"profile; using nearest supported level '{effective}'."
    )
    return ir_request


def enforce_vision(
    ir_request: dict[str, Any],
    *,
    input_modalities: list[str] | None = None,
    model: str = "",
    request_id: str = "-",
) -> dict[str, Any]:
    """Strip images from the IR request if its preset lacks image input.

    Must be called **after** source → IR conversion (operates on the IR
    dict, not the raw provider body).

    No-op when *input_modalities* is ``None`` (unknown) or includes ``"image"``.

    Args:
        ir_request: The IR request dict — **always use the return value**.
        input_modalities: Input modalities declared by the model preset.
        model: Upstream model identifier (for logging).
        request_id: Request identifier (for logging).

    Returns:
        The IR request with images replaced by text placeholders, or
        the original request if the model has vision capability.
    """
    if input_modalities is None or "image" in input_modalities:
        return ir_request

    from codex_rosetta.converters.base.helpers.image_limit import (
        strip_images_for_non_vision,
    )

    return strip_images_for_non_vision(ir_request, model=model, request_id=request_id)
