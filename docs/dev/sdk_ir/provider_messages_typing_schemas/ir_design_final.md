# LLM Provider Converter - IR (Intermediate Representation) Design Document

**Version**: 1.0  
**Date**: 2024-01-10  
**Status**: Final Design

## Table of Contents

1. [Design Goals](#design-goals)
2. [Core Architecture](#core-architecture)
3. [Type Definitions](#type-definitions)
4. [Design Decisions](#design-decisions)
5. [Conversion Rules](#conversion-rules)
6. [Extensibility](#extensibility)
7. [Implementation Guide](#implementation-guide)

---

## Design Goals

### Primary Goals

1. **Unified Interface**: Provide a single message format that hides differences between providers
2. **Lossless Conversion**: Preserve as many provider-specific capabilities as possible to avoid information loss
3. **Ease of Use**: Keep simple scenarios simple and complex scenarios flexible
4. **Future-Oriented**: Provide strong extensibility for new content and tool types
5. **Type Safety**: Provide complete TypeScript/Python type definitions

### Non-Goals

- ❌ Do not aim for perfect bidirectional conversion; some features may only be supported in one direction
- ❌ Do not require every provider to support every feature; degradation is allowed
- ❌ Do not invent new message semantics; this layer only converts, it does not enhance

---

## Core Architecture

### Architectural Choice

After analyzing the three providers OpenAI, Anthropic, and Google in depth, we adopted a **hybrid architecture**:

```
Core: nested structure (Anthropic style) + extension items (special scenarios)
```

**Rationale**:
- ✅ **Nested structure**: sufficient for 90% of scenarios, concise and clear
- ✅ **Extension items**: cover the remaining 10% of special scenarios (tool chains, system events, etc.)
- ✅ **Progressive complexity**: simple scenarios do not need to learn about extension items
- ✅ **Backward compatibility**: legacy code can ignore extension items

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    IR Input                             │
│  List[Union[Message, ExtensionItem]]                    │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
        ▼                                   ▼
┌───────────────┐                  ┌──────────────────┐
│    Message    │                  │  ExtensionItem   │
│  (90% cases)  │                  │  (10% cases)     │
└───────────────┘                  └──────────────────┘
        │                                   │
        │                          ┌────────┴────────┐
        │                          │                 │
        ▼                          ▼                 ▼
┌───────────────┐          ┌──────────────┐  ┌──────────────┐
│    Content    │          │ SystemEvent  │  │ToolChainNode │
│     Parts     │          │              │  │              │
└───────────────┘          └──────────────┘  └──────────────┘
        │                          │                 │
┌───────┴────────┐                 ▼                 ▼
│                │          ┌──────────────┐  ┌──────────────┐
▼                ▼          │ BatchMarker  │  │SessionControl│
TextPart    ImagePart       └──────────────┘  └──────────────┘
ToolCallPart ToolResultPart
FilePart    ReasoningPart
```

---

## Type Definitions

### 1. Core Message Types

```python
from typing import TypedDict, Union, List, Literal, Dict, Any, Optional
from typing_extensions import Required, NotRequired

# ============================================================================
# Core Message
# ============================================================================

class Message(TypedDict):
    """
    Core message type representing a single message in a conversation.

    This is the main building block of the IR; 90% of scenarios only need this type.
    """
    role: Required[Literal["system", "user", "assistant"]]
    content: Required[List[ContentPart]]
    metadata: NotRequired[MessageMetadata]

class MessageMetadata(TypedDict, total=False):
    """
    Metadata for a message, used to store additional information.

    Examples:
        - Message ID and timestamp
        - Streaming state
        - Custom tags
    """
    message_id: str
    timestamp: str
    streaming: StreamingMetadata
    custom: Dict[str, Any]

class StreamingMetadata(TypedDict, total=False):
    """Metadata for streaming"""
    is_streaming: bool
    is_final: bool
    chunk_index: int
```

### 2. Content Part Types

```python
# ============================================================================
# Content Parts
# ============================================================================

ContentPart = Union[
    TextPart,
    ImagePart,
    FilePart,
    ToolCallPart,
    ToolResultPart,
    ReasoningPart,
]

# ----------------------------------------------------------------------------
# Text Content
# ----------------------------------------------------------------------------

class TextPart(TypedDict):
    """Plain text content"""
    type: Required[Literal["text"]]
    text: Required[str]

# ----------------------------------------------------------------------------
# Image Content
# ----------------------------------------------------------------------------

class ImagePart(TypedDict):
    """Image content, supports URL or base64"""
    type: Required[Literal["image"]]
    image_url: NotRequired[str]  # URL form
    image_data: NotRequired[ImageData]  # base64 form
    detail: NotRequired[Literal["auto", "low", "high"]]  # OpenAI-specific

class ImageData(TypedDict):
    """Base64-encoded image data"""
    data: Required[str]  # base64-encoded
    media_type: Required[str]  # for example, "image/png"

# ----------------------------------------------------------------------------
# File Content
# ----------------------------------------------------------------------------

class FilePart(TypedDict):
    """
    File content, supports multiple file types.

    Examples:
        - PDF documents
        - Audio files
        - Video files
    """
    type: Required[Literal["file"]]
    file_url: NotRequired[str]  # URL form
    file_data: NotRequired[FileData]  # base64 form
    file_name: NotRequired[str]
    file_type: NotRequired[str]  # MIME type

class FileData(TypedDict):
    """Base64-encoded file data"""
    data: Required[str]  # base64-encoded
    media_type: Required[str]  # for example, "application/pdf"

# ----------------------------------------------------------------------------
# Tool Calls
# ----------------------------------------------------------------------------

class ToolCallPart(TypedDict):
    """
    Tool call content.

    Uses a two-level type system:
    - type: fixed to "tool_call"
    - tool_type: distinguishes tool categories (function, mcp, web_search, etc.)

    This design avoids type explosion while preserving extensibility.
    """
    type: Required[Literal["tool_call"]]
    tool_call_id: Required[str]
    tool_name: Required[str]
    tool_input: Required[Dict[str, Any]]
    tool_type: NotRequired[Literal[
        "function",
        "mcp",
        "web_search",
        "code_interpreter",
        "file_search",
    ]]  # defaults to "function"

# ----------------------------------------------------------------------------
# Tool Results
# ----------------------------------------------------------------------------

class ToolResultPart(TypedDict):
    """
    Result of a tool call.

    Corresponds to a ToolCallPart and is associated via tool_call_id.
    """
    type: Required[Literal["tool_result"]]
    tool_call_id: Required[str]
    result: Required[Any]  # Can be a string, object, etc.
    is_error: NotRequired[bool]  # Whether this is an error result

# ----------------------------------------------------------------------------
# Reasoning Content
# ----------------------------------------------------------------------------

class ReasoningPart(TypedDict):
    """
    Reasoning content (for example, OpenAI reasoning).

    Used to store the model's internal thought process, usually not shown to the user.
    """
    type: Required[Literal["reasoning"]]
    reasoning: Required[str]
```

### 3. Extension Item Types

```python
# ============================================================================
# Extension Items
# ============================================================================

ExtensionItem = Union[
    SystemEvent,
    BatchMarker,
    SessionControl,
    ToolChainNode,
]

# ----------------------------------------------------------------------------
# System Events
# ----------------------------------------------------------------------------

class SystemEvent(TypedDict):
    """
    System-level event used to record conversation state changes.

    Examples:
        - Session start/end
        - Session pause/resume
        - Timeout warnings
        - Error events
    """
    type: Required[Literal["system_event"]]
    event_type: Required[Literal[
        "session_start",
        "session_pause",
        "session_resume",
        "session_timeout",
        "session_end",
        "error",
        "warning",
    ]]
    timestamp: Required[str]  # ISO 8601 format
    event_data: NotRequired[Dict[str, Any]]
    message: NotRequired[str]

# ----------------------------------------------------------------------------
# Batch Marker
# ----------------------------------------------------------------------------

class BatchMarker(TypedDict):
    """
    Batch marker used to mark a group of related operations.

    Examples:
        - Start/end of parallel tool calls
        - Progress tracking for partial results
    """
    type: Required[Literal["batch_marker"]]
    batch_id: Required[str]
    batch_type: Required[Literal["start", "end", "partial"]]
    total_items: NotRequired[int]
    completed_items: NotRequired[int]
    metadata: NotRequired[Dict[str, Any]]

# ----------------------------------------------------------------------------
# Session Control
# ----------------------------------------------------------------------------

class SessionControl(TypedDict):
    """
    Session control instructions used to control tool call execution.

    Examples:
        - Cancel a tool call
        - Modify tool call arguments
        - Pause/resume tool execution
    """
    type: Required[Literal["session_control"]]
    control_type: Required[Literal[
        "cancel_tool",
        "modify_tool",
        "pause_tool",
        "resume_tool",
    ]]
    target_id: Required[str]  # target tool_call_id
    reason: NotRequired[str]
    new_input: NotRequired[Dict[str, Any]]  # used for modify_tool

# ----------------------------------------------------------------------------
# Tool Chain Node
# ----------------------------------------------------------------------------

class ToolChainNode(TypedDict):
    """
    Tool chain node used to represent dependencies between tool calls.

    Supports a DAG structure where the output of one tool can be the input to another.

    Examples:
        - Search -> Summary
        - Data retrieval -> Analysis -> Visualization
    """
    type: Required[Literal["tool_chain_node"]]
    node_id: Required[str]
    tool_call: Required[ToolCallPart]
    depends_on: NotRequired[List[str]]  # List of dependent node IDs
    auto_execute: NotRequired[bool]  # Whether to execute automatically
```

### 4. Top-Level Types

```python
# ============================================================================
# Top-Level Types
# ============================================================================

# Complete IR input (supports extension items)
IRInput = List[Union[Message, ExtensionItem]]

# Simplified IR input (messages only)
IRInputSimple = List[Message]

# Type guards
def is_message(item: Union[Message, ExtensionItem]) -> bool:
    """Determine whether the item is a Message"""
    return "role" in item

def is_extension_item(item: Union[Message, ExtensionItem]) -> bool:
    """Determine whether the item is an ExtensionItem"""
    return "type" in item and item.get("type") in [
        "system_event",
        "batch_marker",
        "session_control",
        "tool_chain_node",
    ]
```

---

## Design Decisions

### Decision 1: Nested Structure vs Flat Structure

**Choice**: Nested structure (Anthropic style)

**Rationale**:
1. ✅ **Clear semantics**: tool calls and results are part of the message content
2. ✅ **Atomicity**: one message can contain multiple content parts (text + tool call)
3. ✅ **Flexibility**: users can add information while returning tool results
4. ✅ **Consistency**: all content types are `ContentPart`

**Tradeoffs**:
- ❌ Converting to the OpenAI Responses API requires extracting tool calls to the message level
- ✅ However, this conversion is mechanical and does not lose information

### Decision 2: Role System

**Choice**: Three roles (`system`, `user`, `assistant`)

**Rationale**:
1. ✅ **General applicability**: all three providers support these three roles
2. ✅ **Simplicity**: no extra roles are introduced (such as OpenAI's `tool` role)
3. ✅ **Clarity**: tool results are placed in `user` messages, making semantics explicit

**Tradeoffs**:
- ❌ OpenAI's `tool` role must be converted to `user`
- ✅ However, this conversion is lossless; only the role name changes

### Decision 3: Two-Level Type System

**Choice**: Use the `tool_type` field to distinguish tool categories

**Rationale**:
1. ✅ **Avoid type explosion**: no need to create a new `ContentPart` for every tool category
2. ✅ **Extensibility**: adding a new tool category only requires extending the `tool_type` literal
3. ✅ **Consistency**: all tool calls are `ToolCallPart`

**Example**:
```python
# Bad design (type explosion)
ContentPart = Union[
    TextPart,
    FunctionCallPart,
    MCPCallPart,
    WebSearchCallPart,
    CodeInterpreterCallPart,
    # ... one type per tool
]

# Good design (two-level type system)
class ToolCallPart(TypedDict):
    type: Literal["tool_call"]
    tool_type: Literal["function", "mcp", "web_search", ...]
```

### Decision 4: Extension Item Mechanism

**Choice**: Use a `Union` type to support extension items

**Rationale**:
1. ✅ **Progressive complexity**: simple scenarios only need `Message`
2. ✅ **Backward compatibility**: legacy code can filter out extension items
3. ✅ **Type safety**: supported by TypeScript/Python type checking
4. ✅ **Flexibility**: can represent complex interaction patterns

**Use Cases**:
- Tool chains (dependencies across messages)
- System events (conversation state changes)
- Batch operations (parallel tool calls)
- Session control (cancel/modify tool calls)

### Decision 5: Metadata vs New Types

**Choice**: Use `metadata` to store non-core information

**Rationale**:
1. ✅ **Keep the core simple**: core types contain only necessary fields
2. ✅ **Extensibility**: `metadata` can store arbitrary information
3. ✅ **Optionality**: `metadata` is optional and does not affect basic functionality

**Example**:
```python
# Streaming state is stored in metadata
{
    "role": "user",
    "content": [...],
    "metadata": {
        "streaming": {
            "is_streaming": True,
            "is_final": False,
            "chunk_index": 0
        }
    }
}
```

---

## Conversion Rules

### 1. IR -> Anthropic

```python
def to_anthropic(ir_input: IRInput) -> tuple[List[MessageParam], List[str]]:
    """
    Convert IR to Anthropic format.

    Returns:
        - messages: list of Anthropic messages
        - warnings: list of conversion warnings
    """
    messages = []
    warnings = []

    for item in ir_input:
        if is_message(item):
            # Normal message: convert directly
            messages.append({
                "role": item["role"],
                "content": convert_content_to_anthropic(item["content"])
            })
        elif item.get("type") == "system_event":
            # System event: not supported by Anthropic, record a warning
            warnings.append(f"System event ignored: {item['event_type']}")
        elif item.get("type") == "tool_chain_node":
            # Tool chain: expand into ordinary tool calls
            warnings.append("Tool chain converted to sequential calls")
            # Can be expanded into multiple messages
        # ... handle other extension items

    return messages, warnings

def convert_content_to_anthropic(content: List[ContentPart]) -> List[ContentBlock]:
    """Convert content parts to Anthropic format"""
    blocks = []
    for part in content:
        if part["type"] == "text":
            blocks.append({"type": "text", "text": part["text"]})
        elif part["type"] == "image":
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64" if "image_data" in part else "url",
                    "data": part.get("image_data", {}).get("data"),
                    "media_type": part.get("image_data", {}).get("media_type"),
                }
            })
        elif part["type"] == "tool_call":
            blocks.append({
                "type": "tool_use",
                "id": part["tool_call_id"],
                "name": part["tool_name"],
                "input": part["tool_input"]
            })
        elif part["type"] == "tool_result":
            blocks.append({
                "type": "tool_result",
                "tool_use_id": part["tool_call_id"],
                "content": part["result"]
            })
        # ... other types
    return blocks
```

### 2. IR -> OpenAI Responses

```python
def to_openai_responses(ir_input: IRInput) -> List[ResponseInputItemParam]:
    """
    Convert IR to OpenAI Responses format.

    Note: OpenAI Responses uses a flat structure, so tool calls need to be extracted.
    """
    items = []

    for item in ir_input:
        if is_message(item):
            # Check whether there are tool calls
            tool_calls = [p for p in item["content"] if p["type"] == "tool_call"]
            other_content = [p for p in item["content"] if p["type"] != "tool_call"]

            if tool_calls and item["role"] == "assistant":
                # Assistant message with tool calls: split it
                if other_content:
                    # Add text content first
                    items.append({
                        "type": "message",
                        "role": "assistant",
                        "content": convert_content_to_openai(other_content)
                    })
                # Add tool calls afterward
                for tc in tool_calls:
                    items.append({
                        "type": "function_call",
                        "name": tc["tool_name"],
                        "call_id": tc["tool_call_id"],
                        "arguments": json.dumps(tc["tool_input"])
                    })
            else:
                # Normal message
                items.append({
                    "type": "message",
                    "role": item["role"],
                    "content": convert_content_to_openai(item["content"])
                })
        elif item.get("type") == "system_event":
            # OpenAI Responses supports system events
            items.append({
                "type": "system_event",
                "event_type": item["event_type"],
                # ... other fields
            })
        # ... handle other extension items

    return items
```

### 3. IR -> Google GenAI

```python
def to_google(ir_input: IRInput) -> List[Content]:
    """
    Convert IR to Google GenAI format.
    """
    contents = []

    for item in ir_input:
        if is_message(item):
            # Google uses the "user" and "model" roles
            role = "model" if item["role"] == "assistant" else "user"

            contents.append({
                "role": role,
                "parts": convert_content_to_google(item["content"])
            })
        elif item.get("type") == "system_event":
            # Google does not support system events; ignore them
            pass
        # ... handle other extension items

    return contents

def convert_content_to_google(content: List[ContentPart]) -> List[Part]:
    """Convert content parts to Google format"""
    parts = []
    for part in content:
        if part["type"] == "text":
            parts.append({"text": part["text"]})
        elif part["type"] == "image":
            parts.append({
                "inline_data": {
                    "mime_type": part.get("image_data", {}).get("media_type"),
                    "data": part.get("image_data", {}).get("data")
                }
            })
        elif part["type"] == "tool_call":
            parts.append({
                "function_call": {
                    "name": part["tool_name"],
                    "args": part["tool_input"]
                }
            })
        elif part["type"] == "tool_result":
            parts.append({
                "function_response": {
                    "name": part["tool_call_id"],  # need to look up the corresponding tool name
                    "response": part["result"]
                }
            })
        # ... other types
    return parts
```

### 4. Reverse Conversion (Provider -> IR)

```python
# Anthropic -> IR
def from_anthropic(messages: List[MessageParam]) -> IRInput:
    """Convert from Anthropic format to IR"""
    ir_input = []
    for msg in messages:
        ir_input.append({
            "role": msg["role"],
            "content": convert_content_from_anthropic(msg["content"])
        })
    return ir_input

# OpenAI -> IR
def from_openai_responses(items: List[ResponseInputItemParam]) -> IRInput:
    """Convert from OpenAI Responses format to IR"""
    ir_input = []
    current_message = None

    for item in items:
        if item["type"] == "message":
            if current_message:
                ir_input.append(current_message)
            current_message = {
                "role": item["role"],
                "content": convert_content_from_openai(item["content"])
            }
        elif item["type"] == "function_call":
            # Merge into the current assistant message
            if current_message and current_message["role"] == "assistant":
                current_message["content"].append({
                    "type": "tool_call",
                    "tool_call_id": item["call_id"],
                    "tool_name": item["name"],
                    "tool_input": json.loads(item["arguments"]),
                    "tool_type": "function"
                })
        # ... other types

    if current_message:
        ir_input.append(current_message)

    return ir_input

# Google -> IR
def from_google(contents: List[Content]) -> IRInput:
    """Convert from Google GenAI format to IR"""
    ir_input = []
    for content in contents:
        # Google uses the "model" role; convert it to "assistant"
        role = "assistant" if content["role"] == "model" else "user"
        ir_input.append({
            "role": role,
            "content": convert_content_from_google(content["parts"])
        })
    return ir_input
```

---

## Extensibility

### 1. Add a New Content Type

```python
# Step 1: define the new content type
class AudioPart(TypedDict):
    """Audio content"""
    type: Required[Literal["audio"]]
    audio_url: NotRequired[str]
    audio_data: NotRequired[AudioData]
    transcript: NotRequired[str]  # optional transcript text

class AudioData(TypedDict):
    """Base64-encoded audio data"""
    data: Required[str]
    media_type: Required[str]  # for example, "audio/mp3"

# Step 2: add it to the ContentPart union
ContentPart = Union[
    TextPart,
    ImagePart,
    FilePart,
    AudioPart,  # newly added
    ToolCallPart,
    ToolResultPart,
    ReasoningPart,
]

# Step 3: update conversion functions
def convert_content_to_anthropic(content: List[ContentPart]) -> List[ContentBlock]:
    blocks = []
    for part in content:
        # ... existing type handling
        if part["type"] == "audio":
            # Handle audio if the provider supports it
            blocks.append({
                "type": "audio",
                "source": {
                    "type": "base64",
                    "data": part.get("audio_data", {}).get("data"),
                    "media_type": part.get("audio_data", {}).get("media_type"),
                }
            })
    return blocks
```

### 2. Add a New Tool Type

```python
# Only extend the tool_type literal
class ToolCallPart(TypedDict):
    type: Required[Literal["tool_call"]]
    tool_call_id: Required[str]
    tool_name: Required[str]
    tool_input: Required[Dict[str, Any]]
    tool_type: NotRequired[Literal[
        "function",
        "mcp",
        "web_search",
        "code_interpreter",
        "file_search",
        "database_query",  # newly added
        "api_call",        # newly added
    ]]
```

### 3. Add a New Extension Item

```python
# Step 1: define the new extension item type
class CustomExtension(TypedDict):
    """Custom extension item"""
    type: Required[Literal["custom_extension"]]
    extension_name: Required[str]
    extension_data: Required[Dict[str, Any]]

# Step 2: add it to the ExtensionItem union
ExtensionItem = Union[
    SystemEvent,
    BatchMarker,
    SessionControl,
    ToolChainNode,
    CustomExtension,  # newly added
]

# Step 3: update conversion functions
def to_anthropic(ir_input: IRInput) -> tuple[List[MessageParam], List[str]]:
    messages = []
    warnings = []

    for item in ir_input:
        # ... existing handling
        if item.get("type") == "custom_extension":
            # Handle custom extension item
            warnings.append(f"Custom extension ignored: {item['extension_name']}")

    return messages, warnings
```

### 4. Version Evolution Strategy

```python
# Use a version field to support backward compatibility
class Message(TypedDict):
    role: Required[Literal["system", "user", "assistant"]]
    content: Required[List[ContentPart]]
    metadata: NotRequired[MessageMetadata]
    ir_version: NotRequired[str]  # for example, "1.0", "1.1"

# Check version during conversion
def convert_message(msg: Message) -> Any:
    version = msg.get("ir_version", "1.0")
    if version == "1.0":
        return convert_v1_0(msg)
    elif version == "1.1":
        return convert_v1_1(msg)
    else:
        raise ValueError(f"Unsupported IR version: {version}")
```

---

## Implementation Guide

### 1. Project Structure

```
src/codex-rosetta/
├── types/
│   ├── __init__.py
│   ├── ir.py              # IR type definitions
│   ├── openai.py          # OpenAI type definitions
│   ├── anthropic.py       # Anthropic type definitions
│   └── google.py          # Google type definitions
├── converters/
│   ├── __init__.py
│   ├── base.py            # base converter
│   ├── to_anthropic.py    # IR -> Anthropic
│   ├── to_openai.py       # IR -> OpenAI
│   ├── to_google.py       # IR -> Google
│   ├── from_anthropic.py  # Anthropic -> IR
│   ├── from_openai.py     # OpenAI -> IR
│   └── from_google.py     # Google -> IR
├── utils/
│   ├── __init__.py
│   ├── validators.py      # type validation
│   └── helpers.py         # helper functions
└── __init__.py
```

### 2. Implementation Priority

**Phase 1: Core Functionality**
1. ✅ Define IR types (`types/ir.py`)
2. ✅ Implement the base converter (`converters/base.py`)
3. ✅ Implement Anthropic conversion (simplest, direct mapping)
4. ✅ Implement OpenAI conversion (requires flattening)
5. ✅ Implement Google conversion (requires role mapping)

**Phase 2: Extended Functionality**
1. ⏳ Support extension items (system events, tool chains, etc.)
2. ⏳ Support streaming
3. ⏳ Support batch operations
4. ⏳ Support session control

**Phase 3: Optimization and Tooling**
1. ⏳ Performance optimization
2. ⏳ Error handling and validation
3. ⏳ Documentation and examples
4. ⏳ Test coverage

### 3. Test Strategy

```python
# Test case structure
tests/
├── unit/
│   ├── test_ir_types.py           # IR type tests
│   ├── test_to_anthropic.py       # conversion tests
│   ├── test_to_openai.py
│   └── test_to_google.py
├── integration/
│   ├── test_round_trip.py         # round-trip conversion tests
│   └── test_real_providers.py     # real provider tests
└── fixtures/
    ├── ir_examples.py             # IR example data
    ├── anthropic_examples.py      # Anthropic example data
    ├── openai_examples.py         # OpenAI example data
    └── google_examples.py         # Google example data

# Test example
def test_simple_text_message():
    """Test conversion of a simple text message"""
    ir_msg = {
        "role": "user",
        "content": [{"type": "text", "text": "Hello"}]
    }

    # Convert to Anthropic
    anthropic_msg = to_anthropic([ir_msg])
    assert anthropic_msg[0]["role"] == "user"
    assert anthropic_msg[0]["content"][0]["type"] == "text"

    # Round-trip conversion
    ir_msg_back = from_anthropic(anthropic_msg)
    assert ir_msg_back == [ir_msg]

def test_tool_call_conversion():
    """Test tool call conversion"""
    ir_msg = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me search for that"},
            {
                "type": "tool_call",
                "tool_call_id": "call_123",
                "tool_name": "web_search",
                "tool_input": {"query": "AI news"},
                "tool_type": "web_search"
            }
        ]
    }

    # Convert to each provider
    anthropic_msg = to_anthropic([ir_msg])
    openai_msg = to_openai_responses([ir_msg])
    google_msg = to_google([ir_msg])

    # Verify conversion results
    # ...
```

### 4. Usage Example

```python
from codex-rosetta import IRInput, to_anthropic, to_openai, to_google

# Create IR messages
ir_input: IRInput = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "What's the weather in Beijing?"}
        ]
    },
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me check that for you."},
            {
                "type": "tool_call",
                "tool_call_id": "call_1",
                "tool_name": "get_weather",
                "tool_input": {"city": "Beijing"},
                "tool_type": "function"
            }
        ]
    },
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_1",
                "result": "Sunny, 25°C"
            }
        ]
    },
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "The weather in Beijing is sunny with a temperature of 25°C."}
        ]
    }
]

# Convert to different providers
anthropic_messages, warnings = to_anthropic(ir_input)
openai_messages = to_openai_responses(ir_input)
google_contents = to_google(ir_input)

# Use the converted messages to call APIs
# anthropic_client.messages.create(messages=anthropic_messages, ...)
# openai_client.chat.completions.create(messages=openai_messages, ...)
# google_model.generate_content(contents=google_contents, ...)
```

---

## Appendix

### A. Summary of Design Principles

1. **Simplicity First**: Simple scenarios should stay simple; avoid over-engineering
2. **Progressive Complexity**: Complex capabilities should be implemented through extension items without affecting the basic path
3. **Type Safety**: Make full use of the TypeScript/Python type systems
4. **Backward Compatibility**: New versions should remain compatible with old versions
5. **Documentation First**: Design decisions should have clear documentation

### B. References

- [Anthropic Messages API](https://docs.anthropic.com/claude/reference/messages_post)
- [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat)
- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses)
- [Google Generative AI](https://ai.google.dev/api/python/google/generativeai)

### C. Change Log

**v1.0 (2024-01-10)**
- Initial design
- Defined core types
- Defined conversion rules
- Defined extension mechanism

---

**Document End**
