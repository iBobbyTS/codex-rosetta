"""Argo OpenAI Chat schema transforms.

Request-side (to_transforms) — body-level
-------------------------------------------
- ``rename_field("max_tokens", "max_completion_tokens")``: converts the
  deprecated ``max_tokens`` parameter for newer OpenAI models.
- ``replace_message_field("role", "developer", "system")``: downgrades
  the ``developer`` role (OpenAI 2024-12-17+) to ``system`` for upstream
  gateways that don't support it.
- ``default_message_field("content", "")``: replaces ``content: null``
  with an empty string — upstream gateways (e.g. Argo Gemini) crash on
  null content when iterating message bodies.
Model-specific request and IR behavior is intentionally excluded. Model
identity never selects provider wire behavior.
"""

from codex_rosetta.shims.transforms import (
    default_message_field,
    rename_field,
    replace_message_field,
)

to_transforms = (
    rename_field("max_tokens", "max_completion_tokens"),
    replace_message_field("role", "developer", "system"),
    default_message_field("content", ""),
)
from_transforms = ()
ir_transforms = ()
