"""Migration coverage for the removed model-specific reasoning mapper."""

from __future__ import annotations

import pytest

from codex_rosetta.reasoning_mapping import (
    apply_reasoning_mapping_to_provider_request,
    normalize_reasoning_effort,
    normalize_reasoning_mapping,
    resolve_reasoning_mapping,
)


@pytest.mark.parametrize(
    "call",
    [
        lambda: normalize_reasoning_mapping("auto"),
        lambda: normalize_reasoning_effort("high"),
        lambda: resolve_reasoning_mapping(
            target_provider="openai_chat", upstream_model="glm-5.2"
        ),
        lambda: apply_reasoning_mapping_to_provider_request(
            {"model": "glm-5.2"},
            ir_request={"reasoning": {"effort": "high"}},
            target_provider="openai_chat",
        ),
    ],
)
def test_removed_reasoning_mapping_apis_return_migration_error(call):
    with pytest.raises(
        ValueError,
        match=r"select an explicit provider \+ api_type",
    ):
        call()
