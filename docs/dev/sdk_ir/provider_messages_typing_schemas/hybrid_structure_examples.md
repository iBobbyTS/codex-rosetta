# Hybrid Approach: Code Examples for Handling Extensible Scenarios

This document shows how the hybrid approach, nested structure first plus extension items, handles a range of complex and future extensibility scenarios.

## Core Type Definitions

```python
from typing import TypedDict, Union, List, Literal, Dict, Any, Optional
from typing_extensions import Required, NotRequired

# Core: nested message structure
class Message(TypedDict):
    role: Required[Literal["system", "user", "assistant"]]
    content: Required[List[ContentPart]]
    metadata: NotRequired[MessageMetadata]

# Content parts
ContentPart = Union[
    TextPart,
    ImagePart,
    FilePart,
    ToolCallPart,
    ToolResultPart,
    ReasoningPart,
]

# Extension items (for special scenarios)
ExtensionItem = Union[
    SystemEvent,
    BatchMarker,
    SessionControl,
    ToolChainNode,
]

# Hybrid input: most items are Message, a small number are ExtensionItem
IRInput = List[Union[Message, ExtensionItem]]

# Simplified version (Message only)
IRInputSimple = List[Message]
```

## Scenario 1: Tool Chains (Complex Cross-Message Interactions)

### Problem Recap

In a tool chain, the output of one tool becomes the input of another tool directly, without assistant intervention.

### Hybrid Approach

```python
# Define a tool chain node (extension item)
class ToolChainNode(TypedDict):
    type: Required[Literal["tool_chain_node"]]
    node_id: Required[str]
    tool_call: Required[ToolCallPart]
    depends_on: NotRequired[List[str]]  # IDs of dependent nodes
    auto_execute: NotRequired[bool]  # Whether to execute automatically

# Example usage
conversation = [
    # Regular message
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Search for AI news and summarize it"}
        ]
    },

    # Assistant plans the tool chain
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I will search first, then summarize the result"}
        ]
    },

    # Tool chain node 1: search (extension item)
    {
        "type": "tool_chain_node",
        "node_id": "node_1",
        "tool_call": {
            "type": "tool_call",
            "tool_call_id": "call_1",
            "tool_name": "web_search",
            "tool_input": {"query": "latest AI news"},
            "tool_type": "web_search"
        },
        "auto_execute": True
    },

    # Tool chain node 2: summarize (extension item, depends on node 1)
    {
        "type": "tool_chain_node",
        "node_id": "node_2",
        "tool_call": {
            "type": "tool_call",
            "tool_call_id": "call_2",
            "tool_name": "summarize",
            "tool_input": {
                "text": "{{node_1.result}}"  # References the result of node 1
            },
            "tool_type": "function"
        },
        "depends_on": ["node_1"],
        "auto_execute": True
    },

    # After tool chain execution completes, return a regular message
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_2",
                "result": "Summary: ..."
            }
        ]
    },

    # Assistant final reply
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Based on the search and summary..."}
        ]
    }
]
```

**Benefits**:

- ✅ The dependency relationship in the tool chain is clear (`depends_on`)
- ✅ Regular messages stay clean
- ✅ Can represent complex DAG structures
- ✅ Backward compatible: systems that do not support tool chains can ignore these extension items

## Scenario 2: System-Level Events

### Problem Recap

System-level events such as session pause, resume, and timeout need to be supported, but they do not belong to any role.

### Hybrid Approach

```python
# Define system events (extension items)
class SystemEvent(TypedDict):
    type: Required[Literal["system_event"]]
    event_type: Required[Literal[
        "session_start",
        "session_pause",
        "session_resume",
        "session_timeout",
        "session_end",
        "error",
        "warning"
    ]]
    timestamp: Required[str]
    event_data: NotRequired[Dict[str, Any]]
    message: NotRequired[str]

# Example usage
conversation = [
    # Session start event
    {
        "type": "system_event",
        "event_type": "session_start",
        "timestamp": "2024-01-01T10:00:00Z",
        "event_data": {"session_id": "sess_123"}
    },

    # Regular conversation
    {
        "role": "user",
        "content": [{"type": "text", "text": "Help me calculate..."}]
    },
    {
        "role": "assistant",
        "content": [
            {
                "type": "tool_call",
                "tool_call_id": "call_1",
                "tool_name": "calc",
                "tool_input": {"expression": "2+2"},
                "tool_type": "function"
            }
        ]
    },

    # Session pause event
    {
        "type": "system_event",
        "event_type": "session_pause",
        "timestamp": "2024-01-01T10:05:00Z",
        "message": "User requested pause"
    },

    # ... some time later ...

    # Session resume event
    {
        "type": "system_event",
        "event_type": "session_resume",
        "timestamp": "2024-01-01T10:15:00Z"
    },

    # Continue conversation
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_1",
                "result": "4"
            }
        ]
    },

    # Timeout warning
    {
        "type": "system_event",
        "event_type": "warning",
        "timestamp": "2024-01-01T10:25:00Z",
        "message": "Tool execution took longer than expected",
        "event_data": {"tool_call_id": "call_1", "duration_ms": 600000}
    },

    # Session end event
    {
        "type": "system_event",
        "event_type": "session_end",
        "timestamp": "2024-01-01T10:30:00Z",
        "event_data": {"total_messages": 10, "total_tokens": 1500}
    }
]
```

**Benefits**:

- ✅ System events do not pollute role semantics
- ✅ Clear timeline
- ✅ Can be inserted anywhere
- ✅ Easy to filter (messages only or events only)

## Scenario 3: Partial Results from Parallel Tool Calls

### Problem Recap

Multiple tools are called in parallel, results return in different orders, and we do not want to wait for all results before continuing.

### Hybrid Approach

```python
# Define batch markers (extension items)
class BatchMarker(TypedDict):
    type: Required[Literal["batch_marker"]]
    batch_id: Required[str]
    batch_type: Required[Literal["start", "end", "partial"]]
    total_items: NotRequired[int]
    completed_items: NotRequired[int]
    metadata: NotRequired[Dict[str, Any]]

# Example usage
conversation = [
    {
        "role": "user",
        "content": [{"type": "text", "text": "Check the weather in 3 cities"}]
    },

    # Assistant starts 3 parallel tool calls
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I will query all 3 cities at the same time"},
            {
                "type": "tool_call",
                "tool_call_id": "call_1",
                "tool_name": "get_weather",
                "tool_input": {"city": "Beijing"},
                "tool_type": "function"
            },
            {
                "type": "tool_call",
                "tool_call_id": "call_2",
                "tool_name": "get_weather",
                "tool_input": {"city": "Shanghai"},
                "tool_type": "function"
            },
            {
                "type": "tool_call",
                "tool_call_id": "call_3",
                "tool_name": "get_weather",
                "tool_input": {"city": "Guangzhou"},
                "tool_type": "function"
            }
        ]
    },

    # Batch start marker
    {
        "type": "batch_marker",
        "batch_id": "batch_weather",
        "batch_type": "start",
        "total_items": 3,
        "metadata": {"description": "Weather queries for 3 cities"}
    },

    # First result returns (call_3 is fastest)
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_3",
                "result": "Guangzhou: Sunny, 28°C"
            }
        ]
    },

    # Partial completion marker
    {
        "type": "batch_marker",
        "batch_id": "batch_weather",
        "batch_type": "partial",
        "total_items": 3,
        "completed_items": 1
    },

    # Second result returns (call_1)
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_1",
                "result": "Beijing: Cloudy, 15°C"
            }
        ]
    },

    # Partial completion marker
    {
        "type": "batch_marker",
        "batch_id": "batch_weather",
        "batch_type": "partial",
        "total_items": 3,
        "completed_items": 2
    },

    # Third result returns (call_2)
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_2",
                "result": "Shanghai: Rainy, 20°C"
            }
        ]
    },

    # Batch end marker
    {
        "type": "batch_marker",
        "batch_id": "batch_weather",
        "batch_type": "end",
        "total_items": 3,
        "completed_items": 3
    },

    # Assistant summary reply
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "The weather for the three cities is as follows: ..."}
        ]
    }
]
```

**Benefits**:

- ✅ Partial results can be returned immediately
- ✅ Clear batch boundaries
- ✅ Progress tracking
- ✅ No need to wait for all results

## Scenario 4: Streaming Tool Calls

### Problem Recap

Tool calls support streaming output, such as live output from code execution.

### Hybrid Approach

```python
# Use regular messages plus metadata to mark streaming state
conversation = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Run this Python code"}
        ]
    },

    {
        "role": "assistant",
        "content": [
            {
                "type": "tool_call",
                "tool_call_id": "call_1",
                "tool_name": "code_interpreter",
                "tool_input": {"code": "for i in range(10): print(i)"},
                "tool_type": "code_interpreter"
            }
        ]
    },

    # Streaming result 1
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_1",
                "result": "0\n1\n2\n"
            }
        ],
        "metadata": {
            "streaming": {
                "is_streaming": True,
                "is_final": False,
                "chunk_index": 0
            }
        }
    },

    # Streaming result 2
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_1",
                "result": "3\n4\n5\n"
            }
        ],
        "metadata": {
            "streaming": {
                "is_streaming": True,
                "is_final": False,
                "chunk_index": 1
            }
        }
    },

    # Streaming result 3 (final)
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_1",
                "result": "6\n7\n8\n9\n"
            }
        ],
        "metadata": {
            "streaming": {
                "is_streaming": True,
                "is_final": True,
                "chunk_index": 2
            }
        }
    },

    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Code execution completed"}
        ]
    }
]
```

**Benefits**:

- ✅ Uses metadata instead of a new content type
- ✅ Keeps the message structure consistent
- ✅ Can use `is_final` to determine completion
- ✅ Can merge all chunks into the full result

## Scenario 5: Canceling and Modifying Tool Calls

### Problem Recap

The user wants to cancel or modify a tool call that is currently executing.

### Hybrid Approach

```python
# Define session control (extension item)
class SessionControl(TypedDict):
    type: Required[Literal["session_control"]]
    control_type: Required[Literal[
        "cancel_tool",
        "modify_tool",
        "pause_tool",
        "resume_tool"
    ]]
    target_id: Required[str]  # Target tool_call_id
    reason: NotRequired[str]
    new_input: NotRequired[Dict[str, Any]]  # Used for modify_tool

# Example usage
conversation = [
    {
        "role": "user",
        "content": [{"type": "text", "text": "Search the latest AI news"}]
    },

    {
        "role": "assistant",
        "content": [
            {
                "type": "tool_call",
                "tool_call_id": "call_1",
                "tool_name": "web_search",
                "tool_input": {"query": "latest AI news"},
                "tool_type": "web_search"
            }
        ]
    },

    # User cancels the tool call
    {
        "type": "session_control",
        "control_type": "cancel_tool",
        "target_id": "call_1",
        "reason": "user_cancelled"
    },

    # User revises the query
    {
        "role": "user",
        "content": [{"type": "text", "text": "No, search for AI safety-related news"}]
    },

    {
        "role": "assistant",
        "content": [
            {
                "type": "tool_call",
                "tool_call_id": "call_2",
                "tool_name": "web_search",
                "tool_input": {"query": "AI safety news"},
                "tool_type": "web_search"
            }
        ]
    },

    # Or directly modify the tool call
    {
        "type": "session_control",
        "control_type": "modify_tool",
        "target_id": "call_2",
        "new_input": {"query": "AI safety and ethics news"}
    },

    # Continue the normal flow
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_2",
                "result": "..."
            }
        ]
    }
]
```

**Benefits**:

- ✅ Control operations do not pollute user messages
- ✅ Clear control semantics
- ✅ Supports multiple control types
- ✅ Operation history is traceable

## Scenario 6: Complex Multimodal plus Tool Hybrid

### Problem Recap

A user sends text and an image in the same message, and also requests a tool call, while expecting both tool results and follow-up information.

### Hybrid Approach

```python
conversation = [
    # User's complex input
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "What animal is this?"},
            {"type": "image", "image_url": "https://example.com/animal.jpg"},
            {"type": "text", "text": "Also, please search for its habits"}
        ]
    },

    # Assistant identifies the animal and calls a tool
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "This is a panda. Let me search for its habits"},
            {
                "type": "tool_call",
                "tool_call_id": "call_1",
                "tool_name": "web_search",
                "tool_input": {"query": "panda habits"},
                "tool_type": "web_search"
            }
        ]
    },

    # User returns tool results and adds follow-up information (advantage of nested structure)
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_call_id": "call_1",
                "result": "Pandas mainly eat bamboo..."
            },
            {"type": "text", "text": "Thanks! Are they endangered as well?"}
        ]
    },

    # Assistant continues the reply
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Yes, pandas are an endangered species..."}
        ]
    }
]
```

**Benefits**:

- ✅ Tool results and user follow-up are in the same message, which preserves atomicity
- ✅ Clear semantics: this is one complete user input
- ✅ No need to split into multiple items

## Conversion Example: Hybrid Approach -> Providers

### Convert to Anthropic

```python
def to_anthropic(ir_input: IRInput) -> tuple[List[MessageParam], List[str]]:
    """Convert IR to Anthropic format"""
    messages = []
    warnings = []

    for item in ir_input:
        if isinstance(item, dict) and item.get("role"):
            # Regular message: convert directly
            messages.append({
                "role": item["role"],
                "content": convert_content_parts(item["content"])
            })
        elif isinstance(item, dict) and item.get("type") == "system_event":
            # System event: record a warning, Anthropic does not support it
            warnings.append(f"System event ignored: {item['event_type']}")
        elif isinstance(item, dict) and item.get("type") == "tool_chain_node":
            # Tool chain: convert to regular tool calls
            warnings.append("Tool chain converted to sequential calls")
            # Can be expanded into multiple messages
        # ... handle other extension items

    return messages, warnings
```

### Convert to OpenAI Responses

```python
def to_openai_responses(ir_input: IRInput) -> List[ResponseInputItemParam]:
    """Convert IR to OpenAI Responses format"""
    items = []

    for item in ir_input:
        if isinstance(item, dict) and item.get("role"):
            # Regular message
            items.append({
                "type": "message",
                "role": item["role"],
                "content": convert_content_parts(item["content"])
            })
        elif isinstance(item, dict) and item.get("type") == "system_event":
            # System event: can be preserved (OpenAI Responses supports it)
            items.append({
                "type": "system_event",
                "event_type": item["event_type"],
                "timestamp": item["timestamp"]
            })
        elif isinstance(item, dict) and item.get("type") == "tool_chain_node":
            # Tool chain: can be expanded or preserved
            items.append({
                "type": "function_call",
                "name": item["tool_call"]["tool_name"],
                "arguments": item["tool_call"]["tool_input"]
            })
        # ... handle other extension items

    return items
```

## Summary: Advantages of the Hybrid Approach

### 1. Progressive Complexity

```python
# Simple scenario: Message only
simple_conversation: List[Message] = [
    {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]}
]

# Complex scenario: use extension items
complex_conversation: IRInput = [
    {"role": "user", "content": [...]},
    {"type": "system_event", "event_type": "pause", ...},
    {"type": "tool_chain_node", ...},
    {"role": "assistant", "content": [...]}
]
```

### 2. Backward Compatibility

```python
# Legacy code handles Message only
def process_messages(messages: List[Message]):
    for msg in messages:
        print(msg["role"], msg["content"])

# New code can filter out extension items
def process_ir_input(ir_input: IRInput):
    messages = [item for item in ir_input if "role" in item]
    process_messages(messages)
```

### 3. Type Safety

```python
def handle_item(item: Union[Message, ExtensionItem]):
    if "role" in item:
        # TypeScript/mypy knows this is a Message
        print(item["role"])
    elif item.get("type") == "system_event":
        # TypeScript/mypy knows this is a SystemEvent
        print(item["event_type"])
```

### 4. Easy to Extend

```python
# Adding a new extension item type does not affect existing code
class NewExtensionType(TypedDict):
    type: Required[Literal["new_extension"]]
    # ... new fields

ExtensionItem = Union[
    SystemEvent,
    BatchMarker,
    SessionControl,
    ToolChainNode,
    NewExtensionType,  # Added
]
```

## Conclusion

The hybrid approach provides:

- ✅ **Simplicity for simple scenarios**: 90% of cases use Message only
- ✅ **Flexibility for complex scenarios**: 10% of cases use extension items
- ✅ **Good extensibility**: adding new features does not break the existing structure
- ✅ **Backward compatibility**: legacy code can ignore extension items
- ✅ **Type safety**: supported by TypeScript/Python type checking
- ✅ **Easy conversion**: conversion logic to each provider remains clear
