# IR Design Architecture Discussion Notes

This document records the deeper discussion and key observations about the design of the LLM Provider Converter intermediate representation (IR).

## Discussion Context

When designing a unified intermediate representation (IR) to support message conversion among OpenAI, Anthropic, and Google GenAI, we needed to decide:

1. Which provider's architecture should we study and follow?
2. Do we need a separate `tool` role?
3. Should the message structure be flattened or nested?

## Core Observations

### Observation 1: Anthropic's content-block architecture is the most elegant

**Reasons to recommend it**:

1. **Minimal role system**: Only `user` and `assistant` roles
2. **Unified content-block architecture**: All capabilities are expressed through content blocks
3. **High consistency**: No matter the content type, the same structural pattern is followed

```python
# Anthropic's unified pattern
{
    "role": "user" | "assistant",
    "content": [
        {"type": "text", "text": "..."},
        {"type": "image", "source": {...}},
        {"type": "tool_use", "id": "...", "name": "...", "input": {...}},
        {"type": "tool_result", "tool_use_id": "...", "content": "..."},
        {"type": "thinking", "thinking": "..."}
    ]
}
```

**Advantages**:

- It is easier to convert from Anthropic's architecture to other providers
- The content-block architecture is flexible enough to express many complex scenarios
- It matches real-world usage: a single message may contain multiple content types

### Observation 2: Anthropic's `web_search` tool design reveals a key principle

Anthropic uses **special content-block types** for internal tools such as `web_search`:

```python
# Server-side tool call
class ServerToolUseBlockParam(TypedDict, total=False):
    type: Required[Literal["server_tool_use"]]  # special type
    name: Required[Literal["web_search"]]
    id: Required[str]
    input: Required[Dict[str, object]]

# Server-side tool result
class WebSearchToolResultBlockParam(TypedDict, total=False):
    type: Required[Literal["web_search_tool_result"]]  # special type
    tool_use_id: Required[str]
    content: Required[...]
```

**Key insight**:

- Distinguish tool origins by using different `type` values (ordinary tools vs. server tools)
- Even when everything is inside the `user` role, the `type` field can clearly distinguish content semantics
- **A `tool` role is not required to preserve clarity**

**Tool results and user input can be mixed**:

```python
{
    "role": "user",
    "content": [
        {"type": "tool_result", "tool_use_id": "...", "result": "..."},
        {"type": "web_search_tool_result", "tool_use_id": "...", "content": {...}},
        {"type": "text", "text": "By the way, I also want to know..."}
    ]
}
```

### Observation 3: OpenAI Responses API introduces a major architectural shift

OpenAI's new Responses API adopts a design philosophy similar to Anthropic's, which is an **important signal of industry direction**.

#### 3.1 From role-oriented to type-oriented

**The old Chat Completions API**:

```python
# Role-based design
{"role": "user", "content": "..."}
{"role": "assistant", "content": "..."}
{"role": "tool", "tool_call_id": "...", "content": "..."}  # separate tool role
```

**The new Responses API**:

```python
# Type-based design
ResponseInputItemParam = Union[
    EasyInputMessageParam,          # type: "message"
    ResponseFunctionToolCallParam,  # type: "function_call"
    FunctionCallOutput,             # type: "function_call_output"
    ShellCall,                      # type: "shell_call"
    McpCall,                        # type: "mcp_call"
    # ... more types
]
```

**Key changes**:

- **There is no longer a separate `tool` role**
- Tool calls and tool outputs are **independent types**, distinguished by the `type` field
- Each type is an equal input item rather than being nested inside a message role

#### 3.2 Flattened input structure

**Old API (nested)**:

```python
messages = [
    {"role": "user", "content": "..."},
    {"role": "assistant", "tool_calls": [...]},  # tool calls nested in the assistant message
    {"role": "tool", "content": "..."}
]
```

**New API (flat)**:

```python
input_items = [
    {"type": "message", "role": "user", "content": "..."},
    {"type": "function_call", "name": "...", "arguments": "..."},  # independent input item
    {"type": "function_call_output", "call_id": "...", "output": "..."}  # independent input item
]
```

#### 3.3 Redefining roles

**EasyInputMessageParam** (simplified message):

```python
role: Required[Literal["user", "assistant", "system", "developer"]]
```

- 4 roles for simple scenarios
- Backward compatible

**Message** (structured message):

```python
role: Required[Literal["user", "system", "developer"]]
```

- **Only 3 roles, excluding `assistant`**
- Assistant behavior is represented by other types:
  - `type: "function_call"` - tool call
  - `type: "reasoning"` - reasoning trace
  - `type: "text_response"` - text reply

**Design philosophy**:

- Roles are used only for explicit "input messages"
- Assistant behavior is split into separate types
- More fine-grained control and type safety

#### 3.4 Native support for MCP tools

```python
class McpCall(TypedDict, total=False):
    type: Required[Literal["mcp_call"]]
    id: Required[str]
    name: Required[str]
    server_label: Required[str]  # MCP server label
    arguments: Required[str]
    approval_request_id: Optional[str]  # approval request
    status: Literal["in_progress", "completed", "incomplete", "calling", "failed"]
```

**Key points**:

- MCP tools are **first-class citizens** with dedicated types
- Approval workflows are supported
- Independent state tracking is available

## In-Depth Analysis of the Key Questions

### Question 1: Do we need a separate `tool` role?

#### Reasons to keep the `tool` role

1. **Semantic clarity**: The role makes it obvious at a glance
2. **Readability**: Conversation history is intuitive
3. **Debuggability**: Error sources are clear
4. **OpenAI compatibility**: Matches the legacy OpenAI API

#### Reasons to remove the `tool` role

1. **Structural simplicity**: Fewer role types
2. **Industry trend**:
   - Anthropic has never used a `tool` role
   - Google does not use a `tool` role
   - **OpenAI Responses API also does not use a `tool` role**
3. **More flexibility**: Tool results can be mixed with user input
4. **Extensibility**: Different tool types can be distinguished through `type` (for example, `server_tool_use`, `mcp_call`)

#### Practical scenario comparison

**Option A: With a `tool` role**

```python
[
    {"role": "user", "content": [{"type": "text", "text": "How is the weather in Beijing?"}]},
    {"role": "assistant", "content": [{"type": "tool_use", ...}]},
    {"role": "tool", "content": [{"type": "tool_result", ...}]},  # separate role
    {"role": "assistant", "content": [{"type": "text", "text": "..."}]}
]
```

**Option B: Without a `tool` role**

```python
[
    {"role": "user", "content": [{"type": "text", "text": "How is the weather in Beijing?"}]},
    {"role": "assistant", "content": [{"type": "tool_use", ...}]},
    {"role": "user", "content": [{"type": "tool_result", ...}]},  # user role
    {"role": "assistant", "content": [{"type": "text", "text": "..."}]}
]
```

**Option C: Flattened structure (OpenAI Responses style)**

```python
[
    {"type": "message", "role": "user", "content": [{"type": "text", "text": "..."}]},
    {"type": "tool_call", "call_id": "...", "tool_name": "...", ...},  # independent item
    {"type": "tool_result", "call_id": "...", "result": "..."},  # independent item
    {"type": "message", "role": "assistant", "content": [{"type": "text", "text": "..."}]}
]
```

### Question 2: Flattened vs. nested structure?

#### Flattened structure (OpenAI Responses style)

**Pros**:

- Each item is independent and explicitly typed
- New item types are easy to add
- State tracking is clearer
- Consistent with the OpenAI Responses API

**Cons**:

- Inconsistent with Anthropic/Google nested structures
- Requires splitting and merging during conversion

#### Nested structure (Anthropic style)

**Pros**:

- Consistent with Anthropic/Google
- A single message can contain multiple content types
- More aligned with the concept of a "conversation"

**Cons**:

- Tool calls are nested inside assistant messages
- Less clear than a flat structure

## Summary of the Three Providers' Architectures

| Feature | OpenAI Chat Completions | OpenAI Responses | Anthropic | Google |
| --- | --- | --- | --- | --- |
| **Number of roles** | 6 | 3-4 | 2 | 2 |
| **`tool` role** | ✓ | ✗ | ✗ | ✗ |
| **Structure** | Nested | Flat | Nested | Nested |
| **`type` field** | Partial | Comprehensive | Comprehensive | Comprehensive |
| **Tool-call location** | Nested in assistant | Independent input item | Content block | Part field |
| **MCP support** | ✗ | ✓ Native | ✗ | ✗ |
| **Design philosophy** | Role-oriented | Type-oriented | Content-block oriented | Part-oriented |

## Initial Recommendation

Based on the observations and analysis above, our initial recommendation is:

### 1. Core architecture: adopt Anthropic's content-block design

- Use the content-block architecture as the core
- Distinguish different content types through the `type` field
- Preserve structural consistency and extensibility

### 2. Role system: keep 3 roles

```python
RoleType = Literal["system", "user", "assistant"]
```

- Do not use a separate `tool` role
- Place tool results in the content blocks of `user` messages
- Align with Anthropic, Google, and OpenAI Responses

### 3. Structure choice: needs further discussion

Both options have advantages:

**Option A: Nested structure (Anthropic style)**

```python
Message = {
    "role": "user" | "assistant" | "system",
    "content": List[ContentPart]
}
```

**Option B: Flat structure (OpenAI Responses style)**

```python
InputItem = Union[
    Message,
    ToolCall,
    ToolResult,
    McpCall,
    ...
]
```

### 4. MCP tools: provide first-class support

- Dedicated `mcp_call` and `mcp_result` types
- Support approval workflows
- Align with the OpenAI Responses API

## Questions Still to Be Decided

1. **Flattened vs. nested**: Which structure is better for our use case?
2. **Use of the `assistant` role**:
   - Should it be used only for text messages?
   - Do tool calls need a role?
3. **Conversion strategy**:
   - How should we convert between flat and nested forms?
   - How should incompatible features be handled?

## Next Steps

1. Decide on the final structural choice (flat vs. nested)
2. Define the detailed types
3. Establish conversion rules
4. Write conversion examples

## Reference Documents

- [comparison.md](comparison.md) - Detailed comparison of the three providers
- [anthropic.md](anthropic.md) - Anthropic type definitions
- [openai_responses.md](openai_responses.md) - OpenAI Responses API type definitions
- `ir_design.md` - historical document not retained in this repository
- `ir_design_revised.md` - historical document not retained in this repository
