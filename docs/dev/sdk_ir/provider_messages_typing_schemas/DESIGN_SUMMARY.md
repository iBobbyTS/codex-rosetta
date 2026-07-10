# LLM Provider Converter - IR Design Summary

This document summarizes the full IR (Intermediate Representation) design process, the key decisions, and the final architecture.

## 📋 Contents

1. [Design Process](#design-process)
2. [Key Documents](#key-documents)
3. [Core Decisions](#core-decisions)
4. [Final Architecture](#final-architecture)
5. [Next Steps](#next-steps)

---

## Design Process

### Phase 1: Research and Analysis (Completed)

We performed a deep analysis of the message typing systems used by three major LLM providers:

1. **OpenAI** - analyzed two APIs (Chat Completions and Responses)
2. **Anthropic** - studied the unified content-block architecture
3. **Google GenAI** - reviewed the adapter pattern and transparent MCP support

**Deliverables**:
- [`openai.md`](openai.md) - detailed analysis of the OpenAI type system
- [`anthropic.md`](anthropic.md) - analysis of the Anthropic content-block architecture
- [`google.md`](google.md) - analysis of the Google GenAI type system
- [`comparison.md`](comparison.md) - comparison of the three providers
- [`mcp_comparison.md`](mcp_comparison.md) - comparison of MCP implementations

### Phase 2: Architecture Exploration (Completed)

Based on the research, we explored several possible IR architecture designs:

1. **Nested vs. flat structure**
2. **Single-layer vs. two-layer type system**
3. **Role system design**
4. **Extensibility mechanisms**

**Deliverables**:
- `ir_design.md` - initial design proposal; historical document not retained in this repository
- `ir_design_revised.md` - revised design; historical document not retained in this repository
- [`thoughts.md`](thoughts.md) - design thought process

### Phase 3: Finalization (Completed)

After extensive discussion, we finalized a **hybrid architecture**:

- **Core**: nested structure (Anthropic style)
- **Extension**: extension-item mechanism (for special cases)

**Deliverables**:
- [`hybrid_structure_examples.md`](hybrid_structure_examples.md) - code examples for the hybrid approach
- [`ir_design_final.md`](ir_design_final.md) - final design document

---

## Key Documents

### 📖 Required Reading

1. **[`ir_design_final.md`](ir_design_final.md)** ⭐⭐⭐
   - **The final IR design specification**
   - Contains the complete type definitions
   - Contains the conversion rules and implementation guidance
   - **This is the primary reference document for implementation**

2. **[`hybrid_structure_examples.md`](hybrid_structure_examples.md)** ⭐⭐
   - Practical code examples for the hybrid approach
   - Demonstrates how to handle complex scenarios
   - Includes six representative use cases

3. **[`comparison.md`](comparison.md)** ⭐
   - Comparative analysis of the three providers
   - Explains the reasoning behind the design decisions

### 📚 Reference Documents

- [`openai.md`](openai.md) - detailed OpenAI type-system reference
- [`anthropic.md`](anthropic.md) - detailed Anthropic type-system reference
- [`google.md`](google.md) - detailed Google type-system reference
- [`mcp_comparison.md`](mcp_comparison.md) - MCP implementation comparison
- `ir_design_revised.md` - design evolution process; historical document not retained in this repository
- [`thoughts.md`](thoughts.md) - design notes and rationale

---

## Core Decisions

### Decision 1: Hybrid Architecture ✅

**Choice**: nested structure (90% of cases) + extension items (10% of cases)

```python
# Simple scenario
IRInputSimple = List[Message]

# Full scenario
IRInput = List[Union[Message, ExtensionItem]]
```

**Reasoning**:
- ✅ Keeps simple scenarios concise
- ✅ Provides enough flexibility for complex scenarios
- ✅ Supports a gradual learning curve
- ✅ Preserves backward compatibility

### Decision 2: Nested Content Structure ✅

**Choice**: adopt an Anthropic-style nested structure

```python
class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: List[ContentPart]  # nested structure
```

**Reasoning**:
- ✅ Clear semantics (tool calls are part of the message content)
- ✅ Atomicity (one message can contain multiple content types)
- ✅ Flexibility (users can add context when returning tool results)

### Decision 3: Two-Layer Type System ✅

**Choice**: use the `tool_type` field to distinguish tool categories

```python
class ToolCallPart(TypedDict):
    type: Literal["tool_call"]
    tool_type: Literal["function", "mcp", "web_search", ...]
```

**Reasoning**:
- ✅ Avoids type explosion
- ✅ Makes it easy to extend with new tool types
- ✅ Preserves type consistency

### Decision 4: Three Roles ✅

**Choice**: system, user, assistant

**Reasoning**:
- ✅ Supported by all three providers
- ✅ Semantically clear
- ✅ Does not introduce extra complexity

### Decision 5: Extension-Item Mechanism ✅

**Choice**: use a Union type to support extension items

```python
ExtensionItem = Union[
    SystemEvent,
    BatchMarker,
    SessionControl,
    ToolChainNode,
]
```

**Reasoning**:
- ✅ Handles special cases (tool chains, system events, and so on)
- ✅ Keeps the core Message type clean
- ✅ Type-safe
- ✅ Easy to filter and ignore

---

## Final Architecture

### Core Type Hierarchy

```
IRInput
├── Message (90% of cases)
│   ├── role: "system" | "user" | "assistant"
│   ├── content: List[ContentPart]
│   │   ├── TextPart
│   │   ├── ImagePart
│   │   ├── FilePart
│   │   ├── ToolCallPart (tool_type distinguishes concrete types)
│   │   ├── ToolResultPart
│   │   └── ReasoningPart
│   └── metadata (optional)
│
└── ExtensionItem (10% of cases)
    ├── SystemEvent (system event)
    ├── BatchMarker (batch marker)
    ├── SessionControl (session control)
    └── ToolChainNode (tool chain)
```

### Design Advantages

#### 1. Simplicity
```python
# Simplest conversation
conversation = [
    {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "Hi!"}]}
]
```

#### 2. Flexibility
```python
# Complex multimodal + tool-call scenario
conversation = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "What's this?"},
            {"type": "image", "image_url": "..."}
        ]
    },
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me analyze it"},
            {"type": "tool_call", "tool_name": "image_analysis", ...}
        ]
    }
]
```

#### 3. Extensibility
```python
# Tool-chain scenario
conversation = [
    {"role": "user", "content": [...]},
    {"type": "tool_chain_node", "node_id": "1", ...},  # extension item
    {"type": "tool_chain_node", "node_id": "2", "depends_on": ["1"], ...},
    {"role": "assistant", "content": [...]}
]
```

#### 4. Type Safety
```python
def process_item(item: Union[Message, ExtensionItem]):
    if "role" in item:
        # TypeScript/mypy knows this is a Message
        print(item["role"])
    elif item.get("type") == "system_event":
        # TypeScript/mypy knows this is a SystemEvent
        print(item["event_type"])
```

### Conversion Strategy

#### IR → Provider

| Provider | Strategy | Complexity |
|----------|----------|------------|
| Anthropic | direct mapping | ⭐ simple |
| OpenAI Responses | extract tool calls to the message level | ⭐⭐ medium |
| Google GenAI | role mapping + content transformation | ⭐⭐ medium |

#### Provider → IR

| Provider | Strategy | Complexity |
|----------|----------|------------|
| Anthropic | direct mapping | ⭐ simple |
| OpenAI Responses | merge tool calls into content | ⭐⭐ medium |
| Google GenAI | role mapping + content transformation | ⭐⭐ medium |

---

## Next Steps

### Phase 1: Core Implementation 🎯

**Priority**: High  
**Estimated time**: 2-3 weeks

1. **Type definitions** (`src/codex-rosetta/types/ir.py`)
   - [ ] Define all core types
   - [ ] Add type-guard helpers
   - [ ] Write type documentation

2. **Base converters** (`src/codex-rosetta/converters/`)
   - [ ] Implement Anthropic conversion (the simplest)
   - [ ] Implement OpenAI conversion
   - [ ] Implement Google conversion

3. **Unit tests** (`tests/unit/`)
   - [ ] Test simple text messages
   - [ ] Test multimodal messages
   - [ ] Test tool calls
   - [ ] Test round-trip conversion

### Phase 2: Extended Features 🚀

**Priority**: Medium  
**Estimated time**: 2-3 weeks

1. **Extension-item support**
   - [ ] Implement SystemEvent
   - [ ] Implement BatchMarker
   - [ ] Implement SessionControl
   - [ ] Implement ToolChainNode

2. **Advanced capabilities**
   - [ ] Streaming support
   - [ ] Batch-operation support
   - [ ] Error handling and validation

3. **Integration tests** (`tests/integration/`)
   - [ ] Test real provider APIs
   - [ ] Test complex scenarios
   - [ ] Performance testing

### Phase 3: Optimization and Documentation 📚

**Priority**: Medium  
**Estimated time**: 1-2 weeks

1. **Performance optimization**
   - [ ] Conversion performance tuning
   - [ ] Memory usage optimization
   - [ ] Caching mechanisms

2. **Documentation improvements**
   - [ ] API documentation
   - [ ] Usage examples
   - [ ] Best-practices guide

3. **Tooling support**
   - [ ] CLI tool
   - [ ] Debugging tool
   - [ ] Visualization tool

---

## Implementation Checklist

### Must Have ✅

- [ ] Core Message type
- [ ] All ContentPart types (Text, Image, File, ToolCall, ToolResult)
- [ ] Conversion to Anthropic
- [ ] Conversion to OpenAI
- [ ] Conversion to Google
- [ ] Reverse conversion from each provider
- [ ] Basic unit tests
- [ ] Type definition documentation

### Should Have ⭐

- [ ] Extension-item support (at least SystemEvent)
- [ ] Streaming support
- [ ] Error handling and validation
- [ ] Integration tests
- [ ] Usage examples

### Nice to Have 💡

- [ ] Full extension-item support
- [ ] Batch operations
- [ ] Session control
- [ ] Tool-chain support
- [ ] Performance optimization
- [ ] CLI tool

---

## Success Criteria

### Functional Completeness

- ✅ Supports bidirectional conversion for the three major providers
- ✅ Supports core content types such as text, image, and tool calls
- ✅ Preserves type safety
- ✅ Provides clear error messages

### Code Quality

- ✅ Test coverage > 80%
- ✅ Type checking passes (mypy/pyright)
- ✅ Consistent code style (black/ruff)
- ✅ Complete documentation

### User Experience

- ✅ Easy to use in simple scenarios
- ✅ Flexible enough for complex scenarios
- ✅ Clear error messages
- ✅ Easy to understand documentation

---

## Risks and Mitigations

### Risk 1: Provider API Changes

**Risk**: Providers may update their APIs, which could break conversion.

**Mitigation**:
- Pin provider SDK versions
- Check for API updates regularly
- Provide a version-compatibility layer

### Risk 2: Performance Issues

**Risk**: The conversion process may affect performance.

**Mitigation**:
- Run performance and benchmark tests
- Optimize hot code paths
- Provide caching mechanisms

### Risk 3: Type Complexity

**Risk**: The type definitions may become too complex.

**Mitigation**:
- Provide simplified type aliases
- Improve documentation and examples
- Offer a gradual learning path

---

## Reference Resources

### Official Documentation

- [Anthropic Messages API](https://docs.anthropic.com/claude/reference/messages_post)
- [OpenAI Chat Completions](https://platform.openai.com/docs/api-reference/chat)
- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses)
- [Google Generative AI](https://ai.google.dev/api/python/google/generativeai)

### Related Projects

- [LangChain](https://github.com/langchain-ai/langchain) - reference for multi-provider support
- [LiteLLM](https://github.com/BerriAI/litellm) - reference for a unified interface
- [Vercel AI SDK](https://github.com/vercel/ai) - TypeScript implementation reference

### Design Patterns

- Adapter Pattern - used for provider conversion
- Strategy Pattern - used for different conversion strategies
- Builder Pattern - used for constructing complex messages

---

## Summary

After extensive research and design work, we settled on a **simple, flexible, and extensible** IR architecture:

1. **Concise core**: the nested Message structure satisfies 90% of cases
2. **Flexible extension**: extension items handle special scenarios
3. **Type safety**: complete TypeScript/Python type definitions
4. **Ease of implementation**: clear conversion rules and implementation guidance

This design balances **simplicity** and **flexibility**, meeting current needs while leaving room for future expansion.

**Next step**: start implementing the core features in Phase 1! 🚀

---

**Document Version**: 1.0  
**Last Updated**: 2024-01-10  
**Maintainer**: LLM Provider Converter Team
