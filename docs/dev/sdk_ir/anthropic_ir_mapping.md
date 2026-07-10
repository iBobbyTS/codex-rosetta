# Anthropic Messages API and IR Types Mapping Document

This document details the type mapping relationship between Codex-Rosetta's IR types and the Anthropic Messages API.

## Table of Contents

- [IR Request Types Mapping](#ir-request-types-mapping)
- [IR Response Types Mapping](#ir-response-types-mapping)

---

## IR Request Types Mapping

### 1. Core Request Parameters

#### IRRequest → MessageCreateParams

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `IRRequest` | `model` | `ModelParam` | `model` | Model ID, e.g. "claude-3-5-sonnet-20241022" |
| `IRRequest` | `messages` | `Iterable[MessageParam]` | `messages` | Message list, requires conversion |
| `IRRequest` | `system_instruction` | `Union[str, Iterable[TextBlockParam]]` | `system` | System prompt, independent field |

**Anthropic type definitions:**
```python
# MessageCreateParams base type
class MessageCreateParamsBase(TypedDict, total=False):
    max_tokens: Required[int]  # Required parameter
    messages: Required[Iterable[MessageParam]]  # Required parameter
    model: Required[ModelParam]  # Required parameter

    system: Union[str, Iterable[TextBlockParam]]  # System prompt
    # ... Other optional parameters
```

**Mapping notes:**
- IR's `messages` field type is `IRInput` (i.e. `List[Union[Message, ExtensionItem]]`)
- Anthropic's `messages` field type is `Iterable[MessageParam]`
- `system_instruction` is an independent top-level parameter `system` in Anthropic
- Anthropic's `max_tokens` is a **required parameter**, while it is optional in IR

---

### 2. Tool-related Parameters

#### ToolDefinition → ToolParam

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `ToolDefinition` | `type` | `Optional[Literal["custom"]]` | `type` | IR supports multiple types, Anthropic mainly uses "custom" |
| `ToolDefinition` | `name` | `str` | `name` | Tool name |
| `ToolDefinition` | `description` | `str` | `description` | Tool description (optional but strongly recommended) |
| `ToolDefinition` | `parameters` | `InputSchema` | `input_schema` | Parameter definition in JSON Schema format |

**Anthropic type definitions:**
```python
# Tool parameter type
class ToolParam(TypedDict, total=False):
    input_schema: Required[InputSchema]  # JSON Schema
    name: Required[str]

    cache_control: Optional[CacheControlEphemeralParam]
    description: str  # Optional but strongly recommended
    type: Optional[Literal["custom"]]

# InputSchema type
InputSchema: TypeAlias = Union[InputSchemaTyped, Dict[str, object]]

class InputSchemaTyped(TypedDict, total=False):
    type: Required[Literal["object"]]
    properties: Optional[Dict[str, object]]
    required: Optional[SequenceNotStr[str]]
```

**Mapping notes:**
- IR's `ToolDefinition` is a flat structure
- Anthropic also uses a flat structure, but with different field names: `parameters` → `input_schema`
- IR's `required_parameters` needs to be merged into the JSON Schema of `input_schema`
- Anthropic supports `cache_control` for prompt caching

#### ToolChoice → ToolChoiceParam

| IR Type | IR Field | Anthropic Value | Notes |
|---------|----------|-----------------|-------|
| `ToolChoice` | `mode: "none"` | `ToolChoiceNoneParam` | Do not use tools |
| `ToolChoice` | `mode: "auto"` | `ToolChoiceAutoParam` | Auto-decide |
| `ToolChoice` | `mode: "any"` | `ToolChoiceAnyParam` | Must use a tool |
| `ToolChoice` | `mode: "tool"` | `ToolChoiceToolParam` | Specify a specific tool |

**Anthropic's tool_choice types:**
```python
ToolChoiceParam: TypeAlias = Union[
    ToolChoiceAutoParam,  # {"type": "auto"}
    ToolChoiceAnyParam,   # {"type": "any"}
    ToolChoiceToolParam,  # {"type": "tool", "name": "..."}
    ToolChoiceNoneParam   # {"type": "none", "disable_parallel_tool_use": bool}
]
```

**Mapping notes:**
- IR's `mode` values directly correspond to Anthropic's `type` field
- IR's `mode: "tool"` needs to be converted to `{"type": "tool", "name": tool_name}`
- Anthropic's naming is more intuitive: uses "any" instead of "required"

#### ToolCallConfig → disable_parallel_tool_use

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `ToolCallConfig` | `disable_parallel` | `bool` (in `ToolChoiceNoneParam`) | `disable_parallel_tool_use` | Disable parallel tool use |
| `ToolCallConfig` | `max_calls` | - | - | Anthropic does not support this parameter |

**Mapping notes:**
- `disable_parallel_tool_use` is part of `ToolChoiceNoneParam` in Anthropic
- IR's `disable_parallel: true` maps directly to Anthropic's `disable_parallel_tool_use: true`

---

### 3. Generation Control Parameters

#### GenerationConfig → various generation parameters

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `GenerationConfig` | `temperature` | `float` | `temperature` | 0.0-1.0 (Anthropic's range is narrower) |
| `GenerationConfig` | `top_p` | `float` | `top_p` | 0.0-1.0 |
| `GenerationConfig` | `top_k` | `int` | `top_k` | Anthropic supports this |
| `GenerationConfig` | `max_tokens` | `int` | `max_tokens` | **Required parameter** |
| `GenerationConfig` | `stop_sequences` | `SequenceNotStr[str]` | `stop_sequences` | List of stop sequences |
| `GenerationConfig` | `frequency_penalty` | - | - | Anthropic does not support this |
| `GenerationConfig` | `presence_penalty` | - | - | Anthropic does not support this |
| `GenerationConfig` | `logit_bias` | - | - | Anthropic does not support this |
| `GenerationConfig` | `seed` | - | - | Anthropic does not support this |
| `GenerationConfig` | `logprobs` | - | - | Anthropic does not support this |
| `GenerationConfig` | `n` | - | - | Anthropic does not support this |

**Mapping notes:**
- Anthropic's `temperature` range is 0.0-1.0, while OpenAI's is 0.0-2.0
- `max_tokens` is a **required parameter** in Anthropic
- Anthropic supports `top_k` sampling
- Anthropic does not support penalty, logit_bias, seed, etc. parameters

---

### 4. Reasoning Configuration

#### ReasoningConfig → thinking

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `ReasoningConfig` | `type` | `Literal["enabled", "disabled"]` | `thinking.type` | Reasoning type |
| `ReasoningConfig` | `budget_tokens` | `int` | `thinking.budget_tokens` | Reasoning budget token count |
| `ReasoningConfig` | `effort` | - | - | Anthropic does not support this field |

**Anthropic type definitions:**
```python
# ThinkingConfig union type
ThinkingConfigParam: TypeAlias = Union[
    ThinkingConfigEnabledParam,   # {"type": "enabled", "budget_tokens": int}
    ThinkingConfigDisabledParam   # {"type": "disabled"}
]
```

**Mapping notes:**
- Anthropic uses `thinking` configuration instead of `reasoning_effort`
- `budget_tokens` minimum value is 1024
- IR's `effort` field is not supported in Anthropic

---

### 5. Streaming Output Configuration

#### StreamConfig → stream

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `StreamConfig` | `enabled` | `Union[Literal[True], Literal[False]]` | `stream` | Whether to enable streaming output |
| `StreamConfig` | `include_usage` | - | - | Anthropic always includes usage in streaming output |

**Anthropic type definitions:**
```python
# Non-streaming
class MessageCreateParamsNonStreaming(MessageCreateParamsBase, total=False):
    stream: Literal[False]

# Streaming
class MessageCreateParamsStreaming(MessageCreateParamsBase):
    stream: Required[Literal[True]]
```

**Mapping notes:**
- Anthropic's streaming output is controlled by the `stream` parameter
- Anthropic always includes usage information in streaming output, no additional configuration needed

---

### 6. Response Format Configuration

#### ResponseFormatConfig → (Not directly supported)

Anthropic does not directly support the `response_format` parameter, but it can be achieved through:
- Specifying the output format in the `system` prompt
- Using tool calls to obtain structured output

---

### 7. Cache Configuration

#### CacheConfig → cache_control

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `CacheConfig` | - | `CacheControlEphemeralParam` | `cache_control` | Cache control |

**Anthropic type definitions:**
```python
# Cache control parameter (at the content block level)
class CacheControlEphemeralParam(TypedDict, total=False):
    type: Required[Literal["ephemeral"]]
```

**Mapping notes:**
- Anthropic's cache control is set at the **content block level**, not the request level
- Caching is enabled by adding `cache_control` fields to messages, tool definitions, etc.
- IR's cache configuration needs to be converted to content-block-level `cache_control`

---

### 8. Provider Extension Parameters

The following are Anthropic-specific parameters, stored in IR's `provider_extensions`:

| Anthropic Field | Type | Notes |
|-----------------|------|-------|
| `metadata` | `MetadataParam` | Request metadata |
| `service_tier` | `Literal["auto", "standard_only"]` | Service tier |

---

### 9. Message Parameter Type Detailed Mapping

IR's `Message` needs to be converted to Anthropic's `MessageParam` based on `role`:

#### Message → MessageParam

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `Message` | `role` | `Literal["user", "assistant"]` | `role` | Anthropic does not support "system" role |
| `Message` | `content` | `Union[str, Iterable[ContentBlockParam]]` | `content` | Message content |

**Anthropic type definitions:**
```python
class MessageParam(TypedDict, total=False):
    content: Required[Union[str, Iterable[ContentBlockParam]]]
    role: Required[Literal["user", "assistant"]]

# ContentBlockParam includes:
ContentBlockParam = Union[
    TextBlockParam,
    ImageBlockParam,
    DocumentBlockParam,
    SearchResultBlockParam,
    ThinkingBlockParam,
    RedactedThinkingBlockParam,
    ToolUseBlockParam,
    ToolResultBlockParam,
    ServerToolUseBlockParam,
    WebSearchToolResultBlockParam,
    ContentBlock,  # Content blocks from responses can also be used as input
]
```

**Mapping notes:**
- Anthropic's messages only support `"user"` and `"assistant"` roles
- The `"system"` role needs to use the top-level `system` parameter
- IR's `content: List[ContentPart]` needs to be converted to Anthropic's content block format

---

## IR Response Types Mapping

### 1. Top-level Response Structure

#### IRResponse → Message

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `IRResponse` | `id` | `str` | `id` | Response unique ID |
| `IRResponse` | `object` | `Literal["message"]` | `type` | IR: "response", Anthropic: "message" |
| `IRResponse` | `created` | - | - | Anthropic does not provide a timestamp |
| `IRResponse` | `model` | `Model` | `model` | Model used |
| `IRResponse` | `choices` | - | - | Anthropic does not use the choices structure |
| `IRResponse` | `usage` | `Usage` | `usage` | Token usage statistics |

**Anthropic type definitions:**
```python
class Message(BaseModel):
    id: str
    content: List[ContentBlock]
    model: Model
    role: Literal["assistant"]
    stop_reason: Optional[StopReason] = None
    stop_sequence: Optional[str] = None
    type: Literal["message"]
    usage: Usage
```

**Mapping notes:**
- Anthropic's response is a single `Message` object, not a `choices` list
- IR's `choices[0].message` corresponds to Anthropic's entire `Message`
- Anthropic does not provide a `created` timestamp
- Anthropic's `role` is always `"assistant"`

---

### 2. Stop Reason

#### FinishReason → stop_reason

| IR Value | Anthropic Value | Notes |
|----------|-----------------|-------|
| `"stop"` | `"end_turn"` | Normal stop |
| `"length"` | `"max_tokens"` | Reached maximum length |
| `"tool_calls"` | `"tool_use"` | Tool call |
| `"content_filter"` | - | Anthropic does not have this value |
| `"refusal"` | `"refusal"` | Refusal to answer |
| - | `"stop_sequence"` | Encountered a stop sequence (Anthropic-specific) |
| - | `"pause_turn"` | Pause long-running operation (Anthropic-specific) |

**Anthropic type definitions:**
```python
StopReason: TypeAlias = Literal[
    "end_turn",      # Normal stop
    "max_tokens",    # Reached maximum length
    "stop_sequence", # Encountered a stop sequence
    "tool_use",      # Tool call
    "pause_turn",    # Pause long-running operation
    "refusal"        # Refusal to answer
]
```

---

### 3. Content Part Mapping

#### TextPart → TextBlock

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `TextPart` | `text` | `str` | `text` | Text content |
| - | - | `Optional[List[TextCitation]]` | `citations` | Anthropic supports citations |

**Anthropic type definitions:**
```python
class TextBlock(BaseModel):
    citations: Optional[List[TextCitation]] = None
    text: str
    type: Literal["text"]
```

#### ToolCallPart → ToolUseBlock

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `ToolCallPart` | `tool_call_id` | `str` | `id` | Tool call ID |
| `ToolCallPart` | `tool_name` | `str` | `name` | Tool name |
| `ToolCallPart` | `tool_input` | `Dict[str, object]` | `input` | IR: Dict, Anthropic: Dict (not a string) |

**Anthropic type definitions:**
```python
class ToolUseBlock(BaseModel):
    id: str
    input: Dict[str, object]  # Directly a dict, not a JSON string
    name: str
    type: Literal["tool_use"]
```

**Mapping notes:**
- Anthropic's `input` is `Dict[str, object]`, while OpenAI uses a JSON string
- No serialization/deserialization needed

#### ReasoningPart → ThinkingBlock

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `ReasoningPart` | `reasoning` | `str` | `thinking` | Reasoning content |
| - | - | `str` | `signature` | Anthropic-specific signature field |

**Anthropic type definitions:**
```python
class ThinkingBlock(BaseModel):
    signature: str  # Reasoning signature
    thinking: str   # Reasoning content
    type: Literal["thinking"]
```

**Mapping notes:**
- Anthropic uses `thinking` instead of `reasoning`
- Anthropic provides a `signature` field to verify reasoning content

#### CitationPart → TextBlock.citations

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `CitationPart` | `text_citation` | `TextCitation` | `citations` | Text citation |

**Anthropic type definitions:**
```python
class TextCitation(BaseModel):
    cited_text: str
    type: Literal["text_citation"]
```

**Mapping notes:**
- Anthropic's citations are part of `TextBlock`, not independent content blocks
- Supports multiple citation types: `char_location`, `page_location`, `content_block_location`

---

### 4. Token Usage Statistics

#### UsageInfo → Usage

| IR Type | IR Field | Anthropic Type | Anthropic Field | Notes |
|---------|----------|----------------|-----------------|-------|
| `UsageInfo` | `prompt_tokens` | `int` | `input_tokens` | Input token count |
| `UsageInfo` | `completion_tokens` | `int` | `output_tokens` | Output token count |
| `UsageInfo` | `total_tokens` | - | - | Anthropic does not provide total (needs computation) |
| `UsageInfo` | `cache_read_tokens` | `Optional[int]` | `cache_read_input_tokens` | Cache read token count |
| - | `Optional[int]` | `cache_creation_input_tokens` | Cache creation token count (Anthropic-specific) |

**Anthropic type definitions:**
```python
class Usage(BaseModel):
    cache_creation: Optional[CacheCreation] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    input_tokens: int
    output_tokens: int
    server_tool_use: Optional[ServerToolUsage] = None
    service_tier: Optional[Literal["standard", "priority", "batch"]] = None
```

**Mapping notes:**
- Anthropic uses `input_tokens` and `output_tokens` instead of `prompt_tokens` and `completion_tokens`
- Anthropic does not provide `total_tokens`; it needs to be computed: `input_tokens + output_tokens`
- Anthropic provides detailed cache statistics: `cache_creation_input_tokens` and `cache_read_input_tokens`

---

## Key Differences Summary

### 1. Structural Differences

| Aspect | IR | Anthropic |
|--------|----|----|
| System instruction | Independent field `system_instruction` | Top-level parameter `system` |
| Tool definition | Flat structure | Flat structure, but different field names |
| Tool call parameters | `Dict[str, Any]` | `Dict[str, object]` (not a string) |
| Response structure | `choices` list | Single `Message` object |
| Token statistics | `prompt_tokens`, `completion_tokens` | `input_tokens`, `output_tokens` |

### 2. Functional Differences

| Feature | IR | Anthropic |
|---------|----|----|
| Required parameters | `model`, `messages` | `model`, `messages`, `max_tokens` |
| Temperature range | 0.0-2.0 | 0.0-1.0 |
| top_k sampling | Supported | Supported |
| Reasoning configuration | `reasoning_effort` | `thinking` (type + budget_tokens) |
| Cache control | Request level | Content block level |
| Citation support | Independent content block | Part of TextBlock |

### 3. Naming Differences

| IR | Anthropic | Notes |
|----|-----------|-------|
| `mode: "any"` | `type: "any"` | Must use a tool |
| `stop_sequences` | `stop_sequences` | Same |
| `object: "response"` | `type: "message"` | Object type |
| `finish_reason: "stop"` | `stop_reason: "end_turn"` | Stop reason |
| `finish_reason: "length"` | `stop_reason: "max_tokens"` | Reached maximum length |
| `finish_reason: "tool_calls"` | `stop_reason: "tool_use"` | Tool call |

---

## Conversion Notes

### Request Conversion

1. **Required parameter handling**: Ensure `max_tokens` has a value (required in Anthropic)
2. **System instruction handling**: Convert `system_instruction` to the top-level `system` parameter
3. **Temperature range**: Ensure `temperature` is within the 0.0-1.0 range
4. **Tool definition**: `parameters` → `input_schema`
5. **Cache control**: Convert from request level to content block level

### Response Conversion

1. **Response structure**: Convert a single `Message` to a `choices` list
2. **Stop reason mapping**: `end_turn` → `stop`, `max_tokens` → `length`, `tool_use` → `tool_calls`
3. **Token statistics**: `input_tokens` → `prompt_tokens`, `output_tokens` → `completion_tokens`
4. **Compute total**: `total_tokens = input_tokens + output_tokens`
5. **Reasoning content**: `thinking` → `reasoning`
6. **Citation handling**: Extract from `TextBlock.citations` into independent `CitationPart`

---

## Example Code Snippets

### Request Conversion Example

```python
# IR → Anthropic
ir_request: IRRequest = {...}

anthropic_params = {
    "model": ir_request["model"],
    "max_tokens": ir_request.get("generation", {}).get("max_tokens", 4096),  # Required
    "messages": convert_ir_messages_to_anthropic(ir_request["messages"]),
    "system": ir_request.get("system_instruction"),  # Independent parameter
    "temperature": min(ir_request.get("generation", {}).get("temperature", 1.0), 1.0),
    "top_p": ir_request.get("generation", {}).get("top_p"),
    "top_k": ir_request.get("generation", {}).get("top_k"),
    "stop_sequences": ir_request.get("generation", {}).get("stop_sequences"),
    "tools": [
        {
            "name": tool["name"],
            "description": tool.get("description"),
            "input_schema": tool.get("parameters")
        }
        for tool in ir_request.get("tools", [])
    ],
    "tool_choice": convert_tool_choice(ir_request.get("tool_choice"))
}
```

### Response Conversion Example

```python
# Anthropic → IR
anthropic_response: Message = {...}

ir_response: IRResponse = {
    "id": anthropic_response.id,
    "object": "response",
    "created": int(time.time()),  # Anthropic does not provide this, generate it yourself
    "model": anthropic_response.model,
    "choices": [
        {
            "index": 0,
            "message": convert_anthropic_message_to_ir(anthropic_response),
            "finish_reason": {
                "reason": convert_stop_reason(anthropic_response.stop_reason)
            },
        }
    ],
    "usage": {
        "prompt_tokens": anthropic_response.usage.input_tokens,
        "completion_tokens": anthropic_response.usage.output_tokens,
        "total_tokens": anthropic_response.usage.input_tokens + anthropic_response.usage.output_tokens,
        "cache_read_tokens": anthropic_response.usage.cache_read_input_tokens,
    }
}
```

---

## References

- Anthropic SDK source: `/data/pding/miniforge3/envs/codex-rosetta/lib/python3.10/site-packages/anthropic/types/`
- IR Request Types: `src/codex-rosetta/types/ir_request.py`
- IR Response Types: `src/codex-rosetta/types/ir_response.py`
