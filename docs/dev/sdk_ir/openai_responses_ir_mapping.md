# OpenAI Responses API to IR Types Mapping

This document details the mapping relationship between Codex-Rosetta IR types and OpenAI Responses API native types.

## Table of Contents

1. [IR Request Types Mapping](#ir-request-types-mapping)
2. [IR Response Types Mapping](#ir-response-types-mapping)
3. [Detailed Type Mapping Table](#detailed-type-mapping-table)

---

## IR Request Types Mapping

### 1. Core Request Parameters

| IR Type | OpenAI Responses API Type | Notes |
|---------|---------------------------|-------|
| `IRRequest.model` | `ResponseCreateParams.model: ResponsesModel` | Model ID |
| `IRRequest.messages` | `ResponseCreateParams.input: Union[str, ResponseInputParam]` | Input messages |
| `IRRequest.system_instruction` | `ResponseCreateParams.instructions: Optional[str]` | System instruction |

### 2. Tool-Related Types

#### 2.1 ToolDefinition → Tool

| IR Field | OpenAI Type | Mapping |
|----------|-------------|---------|
| `ToolDefinition.type` | `Tool` (discriminated union) | IR type maps to specific OpenAI tool type |
| `ToolDefinition.name` | `FunctionTool.function.name` | Function tool name |
| `ToolDefinition.description` | `FunctionTool.function.description` | Function tool description |
| `ToolDefinition.parameters` | `FunctionTool.function.parameters` | JSON Schema parameters |

**OpenAI Tool Types:**
```python
Tool = Union[
    FunctionTool,           # type="function"
    FileSearchTool,         # type="file_search"
    ComputerTool,          # type="computer"
    WebSearchTool,         # type="web_search"
    Mcp,                   # type="mcp"
    CodeInterpreter,       # type="code_interpreter"
    ImageGeneration,       # type="image_generation"
    LocalShell,            # type="local_shell"
    FunctionShellTool,     # type="shell"
    CustomTool,            # type="custom"
    WebSearchPreviewTool,  # type="web_search_preview"
    ApplyPatchTool,        # type="apply_patch"
]
```

#### 2.2 ToolChoice → ToolChoice

| IR Field | OpenAI Type | Notes |
|----------|-------------|-------|
| `ToolChoice.mode: "none"` | `ToolChoiceOptions: "none"` | No tools |
| `ToolChoice.mode: "auto"` | `ToolChoiceOptions: "auto"` | Auto select |
| `ToolChoice.mode: "any"` | `ToolChoiceOptions: "required"` | Tool use required |
| `ToolChoice.mode: "tool"` | `ToolChoiceFunction/ToolChoiceMcp/...` | Specific tool |

**OpenAI ToolChoice Types:**
```python
ToolChoice = Union[
    ToolChoiceOptions,        # "auto" | "none" | "required"
    ToolChoiceAllowed,        # {"type": "allowed", "allowed_types": [...]}
    ToolChoiceTypes,          # {"type": "types", "types": [...]}
    ToolChoiceFunction,       # {"type": "function", "function": {"name": "..."}}
    ToolChoiceMcp,           # {"type": "mcp", ...}
    ToolChoiceCustom,        # {"type": "custom", ...}
    ToolChoiceApplyPatch,    # {"type": "apply_patch"}
    ToolChoiceShell,         # {"type": "shell"}
]
```

#### 2.3 ToolCallConfig → Request Parameters

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `ToolCallConfig.disable_parallel` | `ResponseCreateParams.parallel_tool_calls: bool` | Disable parallel tool calls (inverted) |
| `ToolCallConfig.max_calls` | `ResponseCreateParams.max_tool_calls: Optional[int]` | Maximum tool calls |

### 3. Generation Control Parameters

#### 3.1 GenerationConfig → ResponseCreateParams

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `temperature` | `temperature: Optional[float]` | Temperature parameter (0-2) |
| `top_p` | `top_p: Optional[float]` | Nucleus sampling |
| `max_tokens` | `max_output_tokens: Optional[int]` | Maximum output tokens |
| `stop_sequences` | ❌ Not supported | OpenAI Responses API does not support stop parameter |
| `truncation` | `truncation: Optional[Literal["auto", "disabled"]]` | Truncation strategy |
| `logprobs` | `top_logprobs: Optional[int]` | Log probabilities (enabled via include parameter) |
| `top_logprobs` | `top_logprobs: Optional[int]` | Top log probabilities count |

**Note:** OpenAI Responses API does not support the following parameters:
- `top_k` (Anthropic/Google only)
- `frequency_penalty` (Chat API only)
- `presence_penalty` (Chat API only)
- `logit_bias` (Chat API only)
- `seed` (Chat API only)
- `n` (Chat API only)

### 4. Response Format Configuration

#### 4.1 ResponseFormatConfig → ResponseTextConfig

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `type: "text"` | `ResponseTextConfig.type: "text"` | Plain text |
| `type: "json_object"` | `ResponseTextConfig.type: "json_object"` | JSON object |
| `type: "json_schema"` | `ResponseTextConfig.type: "json_schema"` | JSON Schema |
| `json_schema` | `ResponseTextConfig.json_schema` | Schema definition |

**OpenAI ResponseTextConfig:**
```python
ResponseTextConfig = Union[
    ResponseFormatTextConfig,           # {"type": "text"}
    ResponseFormatTextJsonSchemaConfig  # {"type": "json_schema", "json_schema": {...}}
]
```

### 5. Reasoning Configuration

#### 5.1 ReasoningConfig → Reasoning

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `effort: "low"` | `Reasoning.effort: "low"` | Low reasoning effort |
| `effort: "medium"` | `Reasoning.effort: "medium"` | Medium reasoning effort |
| `effort: "high"` | `Reasoning.effort: "high"` | High reasoning effort |
| `type: "enabled"` | `Reasoning.type: "enabled"` | Enable reasoning |
| `type: "disabled"` | `Reasoning.type: "disabled"` | Disable reasoning |

**Note:** `budget_tokens` is not directly supported in OpenAI; controlled indirectly via `max_output_tokens`.

### 6. Streaming Configuration

#### 6.1 StreamConfig → stream & StreamOptions

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `enabled: true` | `stream: true` | Enable streaming |
| `enabled: false` | `stream: false` | Disable streaming |
| `include_usage` | `stream_options.include_obfuscation: bool` | Streaming options |

### 7. Cache Configuration

#### 7.1 CacheConfig → Cache Parameters

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `key` | `prompt_cache_key: str` | Cache key |
| `retention: "in-memory"` | `prompt_cache_retention: "in-memory"` | In-memory cache |
| `retention: "24h"` | `prompt_cache_retention: "24h"` | 24-hour cache |

### 8. Provider-Specific Extensions

The following parameters are passed via `IRRequest.provider_extensions`:

| Extension Key | OpenAI Field | Notes |
|---------------|--------------|-------|
| `metadata` | `metadata: Optional[Metadata]` | Metadata (16 key-value pairs) |
| `user` | `user: str` (deprecated) | User identifier |
| `safety_identifier` | `safety_identifier: str` | Safety identifier |
| `service_tier` | `service_tier: Literal[...]` | Service tier |
| `store` | `store: Optional[bool]` | Whether to store response |
| `background` | `background: Optional[bool]` | Background execution |
| `conversation` | `conversation: Union[str, ResponseConversationParam]` | Conversation ID |
| `previous_response_id` | `previous_response_id: Optional[str]` | Previous response ID |
| `prompt` | `prompt: Optional[ResponsePromptParam]` | Prompt template reference |
| `include` | `include: Optional[List[ResponseIncludable]]` | Additional output data |

---

## IR Response Types Mapping

### 1. Top-Level Response Types

#### 1.1 IRResponse → Response

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `id` | `id: str` | Response unique ID |
| `object: "response"` | `object: Literal["response"]` | Object type |
| `created` | `created_at: float` | Unix timestamp |
| `model` | `model: ResponsesModel` | Model ID |
| `choices` | `output: List[ResponseOutputItem]` | Output item list |
| `usage` | `usage: Optional[ResponseUsage]` | Token usage statistics |
| `service_tier` | `service_tier: Optional[str]` | Service tier |
| `system_fingerprint` | ❌ Not available | OpenAI Responses API does not have this field |

**Note:** OpenAI Responses API uses `output` instead of `choices`, and the structure differs.

### 2. Message Types

#### 2.1 Message → ResponseInputItem/ResponseOutputItem

OpenAI Responses API distinguishes between input and output items:

**Input items (ResponseInputItem):**
```python
ResponseInputItem = Union[
    EasyInputMessage,                    # Simplified message
    Message,                             # Standard message
    ResponseOutputMessage,               # Output message (can be used as input)
    ResponseFileSearchToolCall,          # File search tool call
    ResponseComputerToolCall,            # Computer tool call
    ComputerCallOutput,                  # Computer call output
    ResponseFunctionWebSearch,           # Web search
    ResponseFunctionToolCall,            # Function tool call
    FunctionCallOutput,                  # Function call output
    ResponseReasoningItem,               # Reasoning item
    ResponseCompactionItemParam,         # Compaction item
    ImageGenerationCall,                 # Image generation call
    ResponseCodeInterpreterToolCall,     # Code interpreter call
    LocalShellCall,                      # Local shell call
    LocalShellCallOutput,                # Shell call output
    ShellCall,                           # Shell call
    ShellCallOutput,                     # Shell output
    ApplyPatchCall,                      # Patch application call
    ApplyPatchCallOutput,                # Patch output
    McpListTools,                        # MCP tool list
    McpApprovalRequest,                  # MCP approval request
    McpApprovalResponse,                 # MCP approval response
    McpCall,                             # MCP call
    ResponseCustomToolCallOutput,        # Custom tool output
    ResponseCustomToolCall,              # Custom tool call
    ItemReference,                       # Item reference
]
```

**Output items (ResponseOutputItem):**
```python
ResponseOutputItem = Union[
    ResponseOutputMessage,               # Output message
    ResponseFileSearchToolCall,          # File search tool call
    ResponseFunctionToolCall,            # Function tool call
    ResponseFunctionWebSearch,           # Web search
    ResponseComputerToolCall,            # Computer tool call
    ResponseReasoningItem,               # Reasoning item
    ResponseCompactionItem,              # Compaction item
    ImageGenerationCall,                 # Image generation call
    ResponseCodeInterpreterToolCall,     # Code interpreter call
    LocalShellCall,                      # Local shell call
    ResponseFunctionShellToolCall,       # Shell tool call
    ResponseFunctionShellToolCallOutput, # Shell tool output
    ResponseApplyPatchToolCall,          # Patch tool call
    ResponseApplyPatchToolCallOutput,    # Patch tool output
    McpCall,                             # MCP call
    McpListTools,                        # MCP tool list
    McpApprovalRequest,                  # MCP approval request
    ResponseCustomToolCall,              # Custom tool call
]
```

#### 2.2 Message.role Mapping

| IR Role | OpenAI Input Role | OpenAI Output Role |
|---------|-------------------|-------------------|
| `"system"` | `"system"` | ❌ Not available |
| `"user"` | `"user"` | ❌ Not available |
| `"assistant"` | ❌ Not available | `"assistant"` (in ResponseOutputMessage) |

**Note:** OpenAI also supports the `"developer"` role (input).

### 3. Content Part Types

#### 3.1 TextPart → ResponseInputText/ResponseOutputText

| IR Field | OpenAI Input | OpenAI Output | Notes |
|----------|--------------|---------------|-------|
| `type: "text"` | `type: "input_text"` | `type: "output_text"` | Text type |
| `text` | `text: str` | `text: str` | Text content |

**OpenAI ResponseOutputText additional fields:**
```python
class ResponseOutputText:
    text: str
    type: Literal["output_text"]
    annotations: Optional[List[Annotation]] = None  # Annotations (citations, etc.)
    logprobs: Optional[Logprobs] = None            # Log probabilities
```

#### 3.2 ImagePart → ResponseInputImage

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `type: "image"` | `type: "input_image"` | Image type |
| `image_url` | `image_url: str` | Image URL |
| `image_data.data` | `image_url: str` (base64) | Base64 encoded |
| `detail` | `detail: Literal["auto", "low", "high"]` | Detail level |

#### 3.3 FilePart → ResponseInputFile

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `type: "file"` | `type: "input_file"` | File type |
| `file_url` | `file_id: str` | File ID (OpenAI uses ID, not URL) |
| `file_data` | ❌ Not supported | OpenAI requires uploading file first to obtain ID |

#### 3.4 ToolCallPart → ResponseFunctionToolCall

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `type: "tool_call"` | `type: "function_call"` | Tool call type |
| `tool_call_id` | `call_id: str` | Call ID |
| `tool_name` | `name: str` | Tool name |
| `tool_input` | `arguments: str` (JSON string) | Tool parameters |
| `tool_type` | Distinguished by different types | Tool type |

**OpenAI tool call types:**
- `ResponseFunctionToolCall` - Function call
- `ResponseFileSearchToolCall` - File search
- `ResponseComputerToolCall` - Computer use
- `ResponseCodeInterpreterToolCall` - Code interpreter
- `ResponseFunctionWebSearch` - Web search
- `ResponseCustomToolCall` - Custom tool
- `McpCall` - MCP tool

#### 3.5 ToolResultPart → FunctionCallOutput

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `type: "tool_result"` | `type: "function_call_output"` | Tool result type |
| `tool_call_id` | `call_id: str` | Call ID |
| `result` | `output: Union[str, ResponseFunctionCallOutputItemList]` | Result |
| `is_error` | ❌ Indicated via status field | Error flag |

#### 3.6 ReasoningPart → ResponseReasoningItem

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `type: "reasoning"` | `type: "reasoning"` | Reasoning type |
| `reasoning` | `summary: str` | Reasoning summary |
| `status` | `status: Literal["in_progress", "completed", "incomplete"]` | Status |

**OpenAI ResponseReasoningItem additional fields:**
```python
class ResponseReasoningItem:
    type: Literal["reasoning"]
    status: Literal["in_progress", "completed", "incomplete"]
    id: Optional[str] = None
    summary: Optional[str] = None
    encrypted_content: Optional[str] = None  # Encrypted reasoning content
```

#### 3.7 RefusalPart → ResponseOutputRefusal

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `type: "refusal"` | `type: "output_refusal"` | Refusal type |
| `refusal` | `refusal: str` | Refusal reason |

#### 3.8 CitationPart → Annotations

OpenAI handles citations via `ResponseOutputText.annotations`:

```python
# OpenAI annotation types
Annotation = Union[
    URLCitation,      # URL citation
    FileCitation,     # File citation
]

class URLCitation:
    type: Literal["url_citation"]
    text: str
    start_index: int
    end_index: int
    url: str
    title: Optional[str] = None
```

#### 3.9 AudioPart → ResponseInputAudio

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `type: "audio"` | `type: "input_audio"` | Audio type |
| `audio_id` | `audio: str` (base64) | Audio data |

### 4. Usage Statistics

#### 4.1 UsageInfo → ResponseUsage

| IR Field | OpenAI Field | Notes |
|----------|--------------|-------|
| `prompt_tokens` | `input_tokens: int` | Input tokens |
| `completion_tokens` | `output_tokens: int` | Output tokens |
| `reasoning_tokens` | `output_tokens_details.reasoning_tokens: int` | Reasoning tokens |
| `total_tokens` | `total_tokens: int` | Total tokens |
| `cache_read_tokens` | `input_tokens_details.cached_tokens: int` | Cache read tokens |

**OpenAI ResponseUsage structure:**
```python
class ResponseUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_tokens_details: Optional[InputTokensDetails] = None
    output_tokens_details: Optional[OutputTokensDetails] = None

class InputTokensDetails:
    cached_tokens: Optional[int] = None
    text_tokens: Optional[int] = None
    audio_tokens: Optional[int] = None
    image_tokens: Optional[int] = None

class OutputTokensDetails:
    text_tokens: Optional[int] = None
    audio_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
```

### 5. Stop Reasons

#### 5.1 FinishReason → ResponseStatus

| IR Reason | OpenAI Status | Notes |
|-----------|---------------|-------|
| `"stop"` | `"completed"` | Normal completion |
| `"length"` | `"incomplete"` + `incomplete_details.reason: "max_output_tokens"` | Reached length limit |
| `"tool_calls"` | `"completed"` (with tool calls) | Tool calls |
| `"content_filter"` | `"incomplete"` + `incomplete_details.reason: "content_filter"` | Content filter |
| `"error"` | `"failed"` + `error` object | Error |
| `"cancelled"` | `"cancelled"` | Cancelled |

**OpenAI ResponseStatus:**
```python
ResponseStatus = Literal[
    "completed",      # completed
    "failed",         # failed
    "in_progress",    # in progress
    "cancelled",      # cancelled
    "queued",         # queued
    "incomplete",     # incomplete
]
```

---

## Detailed Type Mapping Table

### Complete Request Parameter Mapping

```python
# IR Request
IRRequest = {
    "model": str,                              # → ResponseCreateParams.model
    "messages": IRInput,                       # → ResponseCreateParams.input
    "system_instruction": str | List[Dict],    # → ResponseCreateParams.instructions
    "tools": List[ToolDefinition],             # → ResponseCreateParams.tools
    "tool_choice": ToolChoice,                 # → ResponseCreateParams.tool_choice
    "tool_config": ToolCallConfig,             # → parallel_tool_calls, max_tool_calls
    "generation": GenerationConfig,            # → temperature, top_p, max_output_tokens, etc.
    "response_format": ResponseFormatConfig,   # → ResponseCreateParams.text
    "stream": StreamConfig,                    # → stream, stream_options
    "reasoning": ReasoningConfig,              # → ResponseCreateParams.reasoning
    "cache": CacheConfig,                      # → prompt_cache_key, prompt_cache_retention
    "provider_extensions": Dict[str, Any],     # → other OpenAI-specific parameters
}

# OpenAI ResponseCreateParams
ResponseCreateParams = {
    "model": ResponsesModel,
    "input": Union[str, ResponseInputParam],
    "instructions": Optional[str],
    "tools": Iterable[ToolParam],
    "tool_choice": ToolChoice,
    "parallel_tool_calls": Optional[bool],
    "max_tool_calls": Optional[int],
    "temperature": Optional[float],
    "top_p": Optional[float],
    "max_output_tokens": Optional[int],
    "top_logprobs": Optional[int],
    "truncation": Optional[Literal["auto", "disabled"]],
    "text": ResponseTextConfigParam,
    "stream": Optional[bool],
    "stream_options": Optional[StreamOptions],
    "reasoning": Optional[Reasoning],
    "prompt_cache_key": str,
    "prompt_cache_retention": Optional[Literal["in-memory", "24h"]],
    # provider-specific parameters below
    "metadata": Optional[Metadata],
    "safety_identifier": str,
    "service_tier": Optional[Literal[...]],
    "store": Optional[bool],
    "background": Optional[bool],
    "conversation": Optional[Conversation],
    "previous_response_id": Optional[str],
    "prompt": Optional[ResponsePromptParam],
    "include": Optional[List[ResponseIncludable]],
    "user": str,  # deprecated
}
```

### Complete Response Structure Mapping

```python
# IR Response
IRResponse = {
    "id": str,                                 # → Response.id
    "object": "response",                      # → Response.object
    "created": int,                            # → Response.created_at
    "model": str,                              # → Response.model
    "choices": List[ChoiceInfo],               # → Response.output (different structure)
    "usage": UsageInfo,                        # → Response.usage
    "service_tier": str,                       # → Response.service_tier
}

# OpenAI Response
Response = {
    "id": str,
    "object": Literal["response"],
    "created_at": float,
    "model": ResponsesModel,
    "output": List[ResponseOutputItem],        # not choices!
    "usage": Optional[ResponseUsage],
    "service_tier": Optional[str],
    "status": Optional[ResponseStatus],
    "error": Optional[ResponseError],
    "incomplete_details": Optional[IncompleteDetails],
    # echo of request parameters below
    "instructions": Union[str, List[ResponseInputItem], None],
    "metadata": Optional[Metadata],
    "parallel_tool_calls": bool,
    "temperature": Optional[float],
    "tool_choice": ToolChoice,
    "tools": List[Tool],
    "top_p": Optional[float],
    "background": Optional[bool],
    "conversation": Optional[Conversation],
    "max_output_tokens": Optional[int],
    "max_tool_calls": Optional[int],
    "previous_response_id": Optional[str],
    "prompt": Optional[ResponsePrompt],
    "prompt_cache_key": Optional[str],
    "prompt_cache_retention": Optional[Literal["in-memory", "24h"]],
    "reasoning": Optional[Reasoning],
    "safety_identifier": Optional[str],
    "text": Optional[ResponseTextConfig],
    "top_logprobs": Optional[int],
    "truncation": Optional[Literal["auto", "disabled"]],
    "user": Optional[str],
}
```

---

## Key Differences Summary

### 1. Structural Differences

- **IR**: Uses a `choices` array, where each choice contains a message
- **OpenAI**: Uses an `output` array that directly contains output items (messages, tool calls, etc.)

### 2. Message Role Differences

- **IR**: Three roles: `system`, `user`, `assistant`
- **OpenAI**: Input supports `system`, `user`, `developer`; output has only `assistant`

### 3. Content Type Differences

- **IR**: Unified `ContentPart` type system
- **OpenAI**: Distinguishes between input and output types (`input_text` vs `output_text`)

### 4. Tool Call Differences

- **IR**: Unified `ToolCallPart` type, distinguished by `tool_type`
- **OpenAI**: Different tool call types (`function_call`, `file_search_call`, etc.)

### 5. Parameter Support Differences

**IR supports but OpenAI Responses API does not:**
- `top_k`
- `frequency_penalty`
- `presence_penalty`
- `logit_bias`
- `seed`
- `n` (multiple choices)
- `stop_sequences`

**OpenAI Responses API specific:**
- `conversation` (conversation management)
- `previous_response_id` (multi-turn conversation)
- `prompt` (prompt template)
- `include` (additional output data)
- `background` (background execution)
- `store` (store response)
- `truncation` (truncation strategy)

### 6. File Handling Differences

- **IR**: Supports `file_url` and `file_data` (base64)
- **OpenAI**: Only supports `file_id`; requires uploading file first

---

## Conversion Notes

### Request Conversion

1. **Message conversion**: IR `messages` must be converted to OpenAI `input` format
2. **Tool definitions**: IR `ToolDefinition` must be converted to the corresponding OpenAI tool type based on `type`
3. **Tool choice**: IR `ToolChoice.mode` must be mapped to the specific OpenAI type
4. **Parameter filtering**: Unsupported parameters must be filtered or handled via `provider_extensions`

### Response Conversion

1. **Output structure**: OpenAI's `output` array must be converted to IR's `choices` structure
2. **Content types**: Input/output types must be unified into IR's `ContentPart` type
3. **Status mapping**: OpenAI's `status` and `incomplete_details` must be mapped to IR's `finish_reason`
4. **Usage statistics**: OpenAI's nested `usage` structure must be flattened to IR format

---

## Example Code

### Request Conversion Example

```python
def ir_to_openai_request(ir_request: IRRequest) -> ResponseCreateParams:
    """Convert IR request to OpenAI Responses API request"""
    params = {
        "model": ir_request["model"],
        "input": convert_ir_messages_to_input(ir_request["messages"]),
    }

    # System instruction
    if "system_instruction" in ir_request:
        params["instructions"] = ir_request["system_instruction"]

    # Tools
    if "tools" in ir_request:
        params["tools"] = [
            convert_tool_definition(tool)
            for tool in ir_request["tools"]
        ]

    # Tool choice
    if "tool_choice" in ir_request:
        params["tool_choice"] = convert_tool_choice(ir_request["tool_choice"])

    # Generation parameters
    if "generation" in ir_request:
        gen = ir_request["generation"]
        if "temperature" in gen:
            params["temperature"] = gen["temperature"]
        if "top_p" in gen:
            params["top_p"] = gen["top_p"]
        if "max_tokens" in gen:
            params["max_output_tokens"] = gen["max_tokens"]

    return params
```

### Response Conversion Example

```python
def openai_to_ir_response(openai_response: Response) -> IRResponse:
    """Convert OpenAI response to IR response"""
    # Convert output to choices
    choices = []
    for idx, output_item in enumerate(openai_response.output):
        if output_item.type == "message":
            choice = {
                "index": idx,
                "message": convert_output_message(output_item),
                "finish_reason": determine_finish_reason(openai_response),
            }
            choices.append(choice)

    return {
        "id": openai_response.id,
        "object": "response",
        "created": int(openai_response.created_at),
        "model": openai_response.model,
        "choices": choices,
        "usage": convert_usage(openai_response.usage) if openai_response.usage else None,
    }
```

---

## References

- [OpenAI Responses API Documentation](https://platform.openai.com/docs/api-reference/responses)
- [OpenAI SDK Types](https://github.com/openai/openai-python/tree/main/src/openai/types/responses)
- [Codex-Rosetta IR Types Design](./provider_messages_typing_schemas/ir_design_final.md)
