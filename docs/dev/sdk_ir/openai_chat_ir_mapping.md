# OpenAI Chat Completion API to IR Types Mapping Reference

This document details the type mapping between Codex-Rosetta IR types and the OpenAI Chat Completion API.

## Table of Contents

- [IR Request Types Mapping](#ir-request-types-mapping)
- [IR Response Types Mapping](#ir-response-types-mapping)

---

## IR Request Types Mapping

### 1. Core Request Parameters

#### IRRequest → CompletionCreateParams

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `IRRequest` | `model` | `Union[str, ChatModel]` | `model` | Model ID; ChatModel is a predefined model name literal type |
| `IRRequest` | `messages` | `Iterable[ChatCompletionMessageParam]` | `messages` | Message list; requires conversion |
| `IRRequest` | `system_instruction` | `ChatCompletionSystemMessageParam` | `messages[0]` | Converted to a role="system" message inserted at the beginning of the array |

**OpenAI Type Definitions:**
```python
# ChatModel is a predefined model name
ChatModel = Literal["gpt-4o", "gpt-4-turbo", "o1", "o3", ...]

# ChatCompletionMessageParam is a union of message types
ChatCompletionMessageParam = Union[
    ChatCompletionDeveloperMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionFunctionMessageParam,
]
```

**Mapping Notes:**
- IR's `messages` field type is `IRInput` (i.e., `List[Union[Message, ExtensionItem]]`)
- OpenAI's `messages` field type is `Iterable[ChatCompletionMessageParam]`
- `system_instruction` is implemented in OpenAI by inserting `ChatCompletionSystemMessageParam` at the beginning of the messages array

---

### 2. Tool-Related Parameters

#### ToolDefinition → ChatCompletionFunctionToolParam

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `ToolDefinition` | `type` | `Literal["function"]` | `type` | IR supports multiple types; OpenAI only supports "function" |
| `ToolDefinition` | `name` | `str` (in `FunctionDefinition`) | `function.name` | Function name |
| `ToolDefinition` | `description` | `str` (in `FunctionDefinition`) | `function.description` | Function description |
| `ToolDefinition` | `parameters` | `FunctionParameters` (in `FunctionDefinition`) | `function.parameters` | Parameter definition in JSON Schema format |

**OpenAI Type Definitions:**
```python
# Tool parameter type
ChatCompletionFunctionToolParam = TypedDict({
    "type": Required[Literal["function"]],
    "function": Required[FunctionDefinition]
}, total=False)

# Function definition type
FunctionDefinition = TypedDict({
    "name": Required[str],
    "description": str,  # optional
    "parameters": FunctionParameters,  # optional, JSON Schema
    "strict": Optional[bool]  # optional, strict mode
}, total=False)
```

**Mapping Notes:**
- IR's `ToolDefinition` is a flat structure
- OpenAI uses a nested structure: `{"type": "function", "function": {...}}`
- IR's `required_parameters` needs to be merged into the `parameters` JSON Schema
- OpenAI's `strict` field can be stored in IR's `metadata`

#### ToolChoice → ChatCompletionToolChoiceOptionParam

| IR Type | IR Field | OpenAI Value | Notes |
|---------|----------|--------------|-------|
| `ToolChoice` | `mode: "none"` | `"none"` | Do not use tools |
| `ToolChoice` | `mode: "auto"` | `"auto"` | Auto decide |
| `ToolChoice` | `mode: "any"` | `"required"` | Must use a tool (OpenAI uses "required") |
| `ToolChoice` | `mode: "tool"` | `ChatCompletionNamedToolChoiceParam` | Specify a specific tool |

**OpenAI tool_choice type:**
```python
ChatCompletionToolChoiceOptionParam = Union[
    Literal["none", "auto", "required"],
    ChatCompletionNamedToolChoiceParam  # {"type": "function", "function": {"name": "..."}}
]
```

**Mapping Notes:**
- IR's `mode: "any"` maps to OpenAI's `"required"`
- IR's `mode: "tool"` needs to be converted to `{"type": "function", "function": {"name": tool_name}}`

#### ToolCallConfig → parallel_tool_calls

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `ToolCallConfig` | `disable_parallel` | `bool` | `parallel_tool_calls` | Needs inversion: IR true → OpenAI false |
| `ToolCallConfig` | `max_calls` | - | - | OpenAI Chat does not support this parameter |

**Mapping Notes:**
- `parallel_tool_calls` is a top-level parameter of type `bool`
- IR's `disable_parallel: true` maps to OpenAI's `parallel_tool_calls: false`

---

### 3. Generation Control Parameters

#### GenerationConfig → Various generation parameters

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `GenerationConfig` | `temperature` | `Optional[float]` | `temperature` | 0.0-2.0 |
| `GenerationConfig` | `top_p` | `Optional[float]` | `top_p` | 0.0-1.0 |
| `GenerationConfig` | `top_k` | - | - | OpenAI does not support |
| `GenerationConfig` | `max_tokens` | `Optional[int]` | `max_completion_tokens` | Recommend using max_completion_tokens |
| `GenerationConfig` | `stop_sequences` | `Union[Optional[str], SequenceNotStr[str], None]` | `stop` | IR is List[str]; OpenAI is str or List[str] |
| `GenerationConfig` | `frequency_penalty` | `Optional[float]` | `frequency_penalty` | -2.0 to 2.0 |
| `GenerationConfig` | `presence_penalty` | `Optional[float]` | `presence_penalty` | -2.0 to 2.0 |
| `GenerationConfig` | `logit_bias` | `Optional[Dict[str, int]]` | `logit_bias` | Mapping from token ID to bias value |
| `GenerationConfig` | `seed` | `Optional[int]` | `seed` | Random seed |
| `GenerationConfig` | `logprobs` | `Optional[bool]` | `logprobs` | Whether to return log probabilities |
| `GenerationConfig` | `top_logprobs` | `Optional[int]` | `top_logprobs` | 0-20 |
| `GenerationConfig` | `n` | `Optional[int]` | `n` | Number of generation choices |

**Mapping Notes:**
- `max_tokens` in OpenAI has two fields: `max_tokens` (deprecated) and `max_completion_tokens` (recommended)
- `stop_sequences` needs conversion: IR is always `List[str]`, OpenAI can be a single string or a list
- All parameters are optional (`Optional`)

---

### 4. Response Format Configuration

#### ResponseFormatConfig → CompletionCreateParams.response_format

| IR Type | IR Field | OpenAI Type | OpenAI Value | Notes |
|---------|----------|-------------|--------------|-------|
| `ResponseFormatConfig` | `type: "text"` | `ResponseFormatText` | `{"type": "text"}` | Plain text |
| `ResponseFormatConfig` | `type: "json_object"` | `ResponseFormatJSONObject` | `{"type": "json_object"}` | JSON object |
| `ResponseFormatConfig` | `type: "json_schema"` | `ResponseFormatJSONSchema` | `{"type": "json_schema", "json_schema": {...}}` | Structured output |

**OpenAI Structure:**
```python
ResponseFormat = Union[
    ResponseFormatText,           # {"type": "text"}
    ResponseFormatJSONObject,     # {"type": "json_object"}
    ResponseFormatJSONSchema      # {"type": "json_schema", "json_schema": {...}}
]
```

---

### 5. Reasoning Configuration

#### ReasoningConfig → reasoning_effort

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `ReasoningConfig` | `effort` | `Optional[ReasoningEffort]` | `reasoning_effort` | Reasoning effort level |
| `ReasoningConfig` | `type` | - | - | OpenAI does not support this field |
| `ReasoningConfig` | `budget_tokens` | - | - | OpenAI does not support this field |

**OpenAI Type Definitions:**
```python
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
```

**Mapping Notes:**
- IR's `effort: Literal["low", "medium", "high"]` can map directly to OpenAI's `reasoning_effort`
- OpenAI supports more levels: `"none"`, `"minimal"`, `"xhigh"`
- IR's `type` and `budget_tokens` fields are not supported in OpenAI

---

### 6. Streaming Output Configuration

#### StreamConfig → stream + stream_options

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `StreamConfig` | `enabled` | `Union[Literal[True], Literal[False], None]` | `stream` | Whether to enable streaming output |
| `StreamConfig` | `include_usage` | `bool` (in `ChatCompletionStreamOptionsParam`) | `stream_options.include_usage` | Whether to include usage statistics |

**OpenAI Type Definitions:**
```python
# stream_options type
ChatCompletionStreamOptionsParam = TypedDict({
    "include_usage": bool
}, total=False)
```

**Mapping Notes:**
- The `stream` parameter determines whether to use streaming output
- `stream_options` is only effective when `stream=True`

---

### 7. Cache Configuration

#### CacheConfig → prompt_cache_*

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `CacheConfig` | `key` | `str` | `prompt_cache_key` | Cache key |
| `CacheConfig` | `retention` | `Optional[Literal["in-memory", "24h"]]` | `prompt_cache_retention` | Cache retention policy |

**Mapping Notes:**
- `prompt_cache_key` is used to optimize cache hit rate
- `prompt_cache_retention` set to `"24h"` enables extended prompt caching

---

### 8. Provider Extension Parameters

The following are OpenAI-specific parameters stored in IR's `provider_extensions`:

| OpenAI Field | Type | Notes |
|--------------|------|-------|
| `audio` | `ChatCompletionAudioParam` | Audio output parameters |
| `metadata` | `Metadata` | Metadata (16 key-value pairs) |
| `modalities` | `List[Literal["text", "audio"]]` | Output modalities |
| `prediction` | `ChatCompletionPredictionContentParam` | Predicted content |
| `safety_identifier` | `str` | Safety identifier |
| `service_tier` | `Literal["auto", "default", "flex", "scale", "priority"]` | Service tier |
| `store` | `bool` | Whether to store for distillation/evaluation |
| `user` | `str` | User identifier (deprecated, replaced by safety_identifier) |
| `verbosity` | `Literal["low", "medium", "high"]` | Response verbosity |
| `web_search_options` | `WebSearchOptions` | Web search options |

---

### 9. Detailed Message Parameter Type Mapping

IR's `Message` needs to be converted to different OpenAI message parameter types based on `role`:

#### Message (role="system") → ChatCompletionSystemMessageParam

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `Message` | `role: "system"` | `Literal["system"]` | `role` | System role |
| `Message` | `content` (TextPart) | `Union[str, Iterable[ChatCompletionContentPartTextParam]]` | `content` | System message content |

**OpenAI Type Definitions:**
```python
ChatCompletionSystemMessageParam = TypedDict({
    "role": Required[Literal["system"]],
    "content": Required[Union[str, Iterable[ChatCompletionContentPartTextParam]]],
    "name": str  # optional
}, total=False)
```

#### Message (role="user") → ChatCompletionUserMessageParam

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `Message` | `role: "user"` | `Literal["user"]` | `role` | User role |
| `Message` | `content` | `Union[str, Iterable[ChatCompletionContentPartParam]]` | `content` | User message content; supports multimodal |

**OpenAI Type Definitions:**
```python
ChatCompletionUserMessageParam = TypedDict({
    "role": Required[Literal["user"]],
    "content": Required[Union[str, Iterable[ChatCompletionContentPartParam]]],
    "name": str  # optional
}, total=False)

# Content part types
ChatCompletionContentPartParam = Union[
    ChatCompletionContentPartTextParam,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartInputAudioParam,
    File
]
```

#### Message (role="assistant") → ChatCompletionAssistantMessageParam

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `Message` | `role: "assistant"` | `Literal["assistant"]` | `role` | Assistant role |
| `Message` | `content` (TextPart) | `Union[str, Iterable[ContentArrayOfContentPart], None]` | `content` | Assistant message content |
| `Message` | `content` (ToolCallPart) | `Iterable[ChatCompletionMessageToolCallUnionParam]` | `tool_calls` | Tool calls |
| `Message` | `content` (RefusalPart) | `Optional[str]` | `refusal` | Refusal message |
| `Message` | `content` (AudioPart) | `Optional[Audio]` | `audio` | Audio data |

**OpenAI Type Definitions:**
```python
ChatCompletionAssistantMessageParam = TypedDict({
    "role": Required[Literal["assistant"]],
    "content": Union[str, Iterable[ContentArrayOfContentPart], None],
    "audio": Optional[Audio],
    "function_call": Optional[FunctionCall],  # deprecated
    "name": str,
    "refusal": Optional[str],
    "tool_calls": Iterable[ChatCompletionMessageToolCallUnionParam]
}, total=False)
```

#### ToolResultPart → ChatCompletionToolMessageParam

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `ToolResultPart` | `tool_call_id` | `str` | `tool_call_id` | Tool call ID |
| `ToolResultPart` | `result` | `Union[str, Iterable[ChatCompletionContentPartTextParam]]` | `content` | Tool execution result |

**OpenAI Type Definitions:**
```python
ChatCompletionToolMessageParam = TypedDict({
    "role": Required[Literal["tool"]],
    "content": Required[Union[str, Iterable[ChatCompletionContentPartTextParam]]],
    "tool_call_id": Required[str]
}, total=False)
```

**Mapping Notes:**
- IR's `Message` maps to different OpenAI message parameter types based on the `role` field
- IR's `content: List[ContentPart]` needs to be dispatched to different OpenAI fields based on content type
- `ToolResultPart` needs to create a separate `ChatCompletionToolMessageParam` message

---

## IR Response Types Mapping

### 1. Top-Level Response Structure

#### IRResponse → ChatCompletion

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `IRResponse` | `id` | `ChatCompletion` | `id` | Unique response ID |
| `IRResponse` | `object` | `ChatCompletion` | `object` | IR: "response", OpenAI: "chat.completion" |
| `IRResponse` | `created` | `ChatCompletion` | `created` | Unix timestamp |
| `IRResponse` | `model` | `ChatCompletion` | `model` | Model used |
| `IRResponse` | `choices` | `ChatCompletion` | `choices` | List of choices |
| `IRResponse` | `usage` | `ChatCompletion` | `usage` | Token usage statistics |
| `IRResponse` | `service_tier` | `ChatCompletion` | `service_tier` | Service tier |
| `IRResponse` | `system_fingerprint` | `ChatCompletion` | `system_fingerprint` | System fingerprint |

---

### 2. Choice Results

#### ChoiceInfo → Choice

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `ChoiceInfo` | `index` | `Choice` | `index` | Choice index |
| `ChoiceInfo` | `message` | `Choice` | `message` | Generated message |
| `ChoiceInfo` | `finish_reason` | `Choice` | `finish_reason` | Finish reason |
| `ChoiceInfo` | `logprobs` | `Choice` | `logprobs` | Log probability information |

---

### 3. Finish Reasons

#### FinishReason → Choice.finish_reason

| IR Value | OpenAI Value | Notes |
|----------|--------------|-------|
| `"stop"` | `"stop"` | Normal stop |
| `"length"` | `"length"` | Reached maximum length |
| `"tool_calls"` | `"tool_calls"` | Tool calls |
| `"content_filter"` | `"content_filter"` | Content filter |
| `"refusal"` | - | OpenAI does not have this value (but has a refusal field) |
| `"error"` | - | OpenAI does not have this value |
| `"cancelled"` | - | OpenAI does not have this value |
| - | `"function_call"` | OpenAI-specific (deprecated) |

---

### 4. Message Structure

#### Message → ChatCompletionMessage

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `Message` | `role` | `Literal["assistant"]` | `role` | IR supports "system"/"user"/"assistant"; OpenAI responses only have "assistant" |
| `Message` | `content` | `Optional[str]` | `content` | IR: List[ContentPart], OpenAI: Optional[str] |
| `Message` | `metadata` | - | - | OpenAI does not support |

**OpenAI Type Definitions:**
```python
ChatCompletionMessage = BaseModel({
    "content": Optional[str],
    "refusal": Optional[str],
    "role": Literal["assistant"],
    "annotations": Optional[List[Annotation]],
    "audio": Optional[ChatCompletionAudio],
    "function_call": Optional[FunctionCall],  # deprecated
    "tool_calls": Optional[List[ChatCompletionMessageToolCallUnion]]
})
```

**Mapping Notes:**
- IR's `content` is `List[ContentPart]`, supporting multimodal
- OpenAI's `content` is `Optional[str]`, supporting only text
- OpenAI's other content types are represented through separate fields (e.g., `tool_calls`, `refusal`, `audio`, `annotations`)

---

### 5. Content Part Mapping

#### TextPart → content

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `TextPart` | `text` | `Optional[str]` | `content` | Text content maps directly |

#### ToolCallPart → tool_calls

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `ToolCallPart` | `tool_call_id` | `str` | `id` | Tool call ID |
| `ToolCallPart` | `tool_name` | `str` (in `Function`) | `function.name` | Function name |
| `ToolCallPart` | `tool_input` | `str` (in `Function`) | `function.arguments` | IR: Dict, OpenAI: JSON string |
| `ToolCallPart` | `tool_type` | `Literal["function"]` | `type` | IR supports multiple; OpenAI only "function" |

**OpenAI Type Definitions:**
```python
# Tool call union type
ChatCompletionMessageToolCallUnion = Union[
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageCustomToolCall
]

# Function tool call
ChatCompletionMessageFunctionToolCall = BaseModel({
    "id": str,
    "type": Literal["function"],
    "function": Function
})

# Function definition
Function = BaseModel({
    "name": str,
    "arguments": str  # JSON string
})
```

**Mapping Notes:**
- IR's `tool_input` is `Dict[str, Any]`
- OpenAI's `arguments` is a JSON string; requires serialization/deserialization
- OpenAI's `tool_calls` is a list: `Optional[List[ChatCompletionMessageToolCallUnion]]`

#### RefusalPart → refusal

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `RefusalPart` | `refusal` | `Optional[str]` | `refusal` | Refusal reason text |

#### ReasoningPart → (no direct mapping)

OpenAI's reasoning content is included in token statistics but is not returned as an independent content part.

**Mapping Notes:**
- IR's `ReasoningPart` is used to store the reasoning process
- OpenAI reports reasoning tokens via `usage.completion_tokens_details.reasoning_tokens`

#### CitationPart → annotations

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `CitationPart` | `url_citation` | `AnnotationURLCitation` (in `Annotation`) | `url_citation` | URL citation |

**OpenAI Type Definitions:**
```python
# Annotation type
Annotation = BaseModel({
    "type": Literal["url_citation"],
    "url_citation": AnnotationURLCitation
})

# URL citation
AnnotationURLCitation = BaseModel({
    "start_index": int,
    "end_index": int,
    "title": str,
    "url": str
})
```

**Mapping Notes:**
- OpenAI's `annotations` is a list: `Optional[List[Annotation]]`

#### AudioPart → audio

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `AudioPart` | `audio_id` | `str` | `id` | Audio ID |

**OpenAI Type Definitions:**
```python
ChatCompletionAudio = BaseModel({
    "id": str,
    "expires_at": int,
    "data": str,  # base64
    "transcript": str
})
```

**Mapping Notes:**
- OpenAI's `audio` field type is `Optional[ChatCompletionAudio]`

---

### 6. Token Usage Statistics

#### UsageInfo → CompletionUsage

| IR Type | IR Field | OpenAI Type | OpenAI Field | Notes |
|---------|----------|-------------|--------------|-------|
| `UsageInfo` | `prompt_tokens` | `int` | `prompt_tokens` | Input token count |
| `UsageInfo` | `completion_tokens` | `int` | `completion_tokens` | Output token count |
| `UsageInfo` | `total_tokens` | `int` | `total_tokens` | Total token count |
| `UsageInfo` | `reasoning_tokens` | `Optional[int]` (in `CompletionTokensDetails`) | `completion_tokens_details.reasoning_tokens` | Reasoning token count |
| `UsageInfo` | `prompt_tokens_details` | `Optional[PromptTokensDetails]` | `prompt_tokens_details` | Input details |
| `UsageInfo` | `completion_tokens_details` | `Optional[CompletionTokensDetails]` | `completion_tokens_details` | Output details |
| `UsageInfo` | `cache_read_tokens` | `Optional[int]` (in `PromptTokensDetails`) | `prompt_tokens_details.cached_tokens` | Cache read token count |

**OpenAI Type Definitions:**
```python
# Usage statistics
CompletionUsage = BaseModel({
    "prompt_tokens": int,
    "completion_tokens": int,
    "total_tokens": int,
    "prompt_tokens_details": Optional[PromptTokensDetails],
    "completion_tokens_details": Optional[CompletionTokensDetails]
})

# Input token details
PromptTokensDetails = BaseModel({
    "cached_tokens": Optional[int],
    "audio_tokens": Optional[int]
})

# Output token details
CompletionTokensDetails = BaseModel({
    "reasoning_tokens": Optional[int],
    "audio_tokens": Optional[int],
    "accepted_prediction_tokens": Optional[int],
    "rejected_prediction_tokens": Optional[int]
})
```

---

## Summary of Key Differences

### 1. Structural Differences

| Aspect | IR | OpenAI |
|------|----|----|
| Tool definition | Flat structure | Nested structure `{"type": "function", "function": {...}}` |
| Message content | `List[ContentPart]` multimodal | `str` text + separate fields (tool_calls, refusal, etc.) |
| Tool call arguments | `Dict[str, Any]` | JSON string |
| System instruction | Separate field `system_instruction` | System message in messages array |

### 2. Functional Differences

| Feature | IR | OpenAI |
|------|----|----|
| Tool types | Supports function, mcp, web_search, code_interpreter, file_search | Only supports function |
| top_k sampling | Supported | Not supported |
| Reasoning budget | Supports `budget_tokens` | Not supported |
| Extension items | Supports SystemEvent, BatchMarker, etc. | Not supported |

### 3. Naming Differences

| IR | OpenAI | Notes |
|----|--------|-------|
| `mode: "any"` | `"required"` | Must use a tool |
| `max_tokens` | `max_completion_tokens` | Maximum generated tokens |
| `stop_sequences` | `stop` | Stop sequences |
| `object: "response"` | `object: "chat.completion"` | Object type |

---

## Conversion Notes

### Request Conversion

1. **System instruction handling**: Convert `system_instruction` to the first message in the messages array
2. **Tool definition nesting**: Convert flat `ToolDefinition` to nested `{"type": "function", "function": {...}}`
3. **Tool choice mapping**: `mode: "any"` → `"required"`
4. **Parallel tool calls**: `disable_parallel` needs inversion to `parallel_tool_calls`
5. **Stop sequences**: Ensure `stop_sequences` is converted to the correct format

### Response Conversion

1. **Content part expansion**: Convert OpenAI's separate fields (content, tool_calls, refusal, etc.) to IR's `List[ContentPart]`
2. **Tool call arguments**: Parse the JSON string `arguments` into `Dict[str, Any]`
3. **Object type**: `"chat.completion"` → `"response"`
4. **Reasoning tokens**: Extract from `completion_tokens_details.reasoning_tokens` to `UsageInfo.reasoning_tokens`

---

## Example Code Snippets

### Request Conversion Example

```python
# IR → OpenAI
ir_request: IRRequest = {...}

openai_params = {
    "model": ir_request["model"],
    "messages": convert_ir_messages_to_openai(ir_request["messages"]),
    "temperature": ir_request.get("generation", {}).get("temperature"),
    "max_completion_tokens": ir_request.get("generation", {}).get("max_tokens"),
    "tools": [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description"),
                "parameters": tool.get("parameters")
            }
        }
        for tool in ir_request.get("tools", [])
    ],
    "tool_choice": convert_tool_choice(ir_request.get("tool_choice"))
}
```

### Response Conversion Example

```python
# OpenAI → IR
openai_response: ChatCompletion = {...}

ir_response: IRResponse = {
    "id": openai_response.id,
    "object": "response",
    "created": openai_response.created,
    "model": openai_response.model,
    "choices": [
        {
            "index": choice.index,
            "message": convert_openai_message_to_ir(choice.message),
            "finish_reason": {"reason": choice.finish_reason},
            "logprobs": choice.logprobs
        }
        for choice in openai_response.choices
    ],
    "usage": convert_usage(openai_response.usage)
}
```

---

## References

- OpenAI SDK source: `/data/pding/miniforge3/envs/codex-rosetta/lib/python3.10/site-packages/openai/types/chat/`
- IR Request Types: `src/codex-rosetta/types/ir_request.py`
- IR Response Types: `src/codex-rosetta/types/ir_response.py`
