"""Cross-format behavior for Responses computer calls."""

from __future__ import annotations

from typing import Any, cast

import pytest

from codex_rosetta.converters.anthropic.tool_ops import AnthropicToolOps
from codex_rosetta.converters.google_genai.tool_ops import GoogleGenAIToolOps
from codex_rosetta.converters.openai_chat.tool_ops import OpenAIChatToolOps
from codex_rosetta.types.ir import ToolCallPart


@pytest.mark.parametrize(
    "tool_ops",
    [OpenAIChatToolOps, AnthropicToolOps, GoogleGenAIToolOps],
)
def test_non_responses_converters_reject_computer_use_explicitly(
    tool_ops: type[Any],
) -> None:
    computer_call = cast(
        ToolCallPart,
        {
            "type": "tool_call",
            "tool_call_id": "call_comp_123",
            "tool_name": "computer",
            "tool_input": {"action": {"type": "click", "x": 100, "y": 200}},
            "tool_type": "computer_use",
        },
    )

    with pytest.raises(NotImplementedError, match="computer_use"):
        tool_ops.ir_tool_call_to_p(computer_call)
