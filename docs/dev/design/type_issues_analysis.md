# In-Depth Analysis of `ty` Type-Checking Issues

## Overview

This report performs an in-depth analysis of the ty type check results of the codex-rosetta project, classifies 645 diagnoses (644 errors + 1 warning) by root cause, and proposes a systematic repair strategy.

## Error Distribution Overview

| Error type | Quantity | Proportion |
|---------|------|------|
| `invalid-key` | 469 | 72.7% |
| `invalid-return-type` | 72 | 11.2% |
| `invalid-argument-type` | 67 | 10.4% |
| `unresolved-attribute` | 16 | 2.5% |
| `invalid-method-override` | 7 | 1.1% |
| `missing-typed-dict-key` | 6 | 0.9% |
| `invalid-assignment` | 4 | 0.6% |
| `no-matching-overload` | 2 | 0.3% |
| `invalid-type-form` | 1 | 0.2% |

---

## Root-Cause Classification

### Root cause 1: Type narrowing of IRStreamEvent union type failed

**Number of errors**: ~400+ (accounting for the vast majority of `invalid-key` errors)

**Problem description**:

The code uses the `IRStreamEvent` union type (including 10 event types), then determines the specific type through string comparison, and then accesses the fields unique to that type. But ty cannot be type narrowed via string comparison.

**Typical code pattern**:

```python
# converters/anthropic/converter.py:643
event_type = ir_event["type"]
if event_type == "stream_start":
    context.response_id = ir_event["response_id"] # Error: ty thinks ir_event is still a union type
    context.model = ir_event["model"] # Error: other event types have no model field
```

**ty error report example**:

```
error[invalid-key]: Unknown key "response_id" for TypedDict `StreamEndEvent`
error[invalid-key]: Unknown key "response_id" for TypedDict `TextDeltaEvent`
error[invalid-key]: Unknown key "model" for TypedDict `FinishEvent`
...
```

**Scope of influence**:

| Files | Number of Errors |
|------|--------|
| `converters/anthropic/converter.py` | ~100 |
| `converters/google_genai/converter.py` | ~80 |
| `converters/openai_chat/converter.py` | ~80 |
| `converters/openai_responses/converter.py` | ~100 |

**Root Cause**:

1. Type narrowing of TypedDict union type requires special treatment
2. ty does not support type narrowing through `dict["type"] == "xxx"`
3. Need to use TypeGuard or TypeIs function

---

### Root cause 2: The function returns dict[str, Any] instead of the declared TypedDict

**Number of errors**: 72 `invalid-return-type`

**Problem description**:

The function declaration returns a TypedDict (like `GenerationConfig`, `IRRequest`, `IRResponse`), but is actually built with `result: Dict[str, Any] = {}` and then populates the fields step by step. ty cannot treat `dict[str, Any]` as a TypedDict.

**Typical code pattern**:

```python
# converters/anthropic/config_ops.py:102-135
def p_generation_config_to_ir(
    provider_config: Any, **kwargs: Any
) -> GenerationConfig:
    result: Dict[str, Any] = {} #Declared as Dict[str, Any]

    if "max_tokens" in provider_config:
        result["max_tokens"] = provider_config["max_tokens"]
    # ...more conditional filling

    return result # Error: return dict[str, Any] instead of GenerationConfig
```

**ty error report example**:

```
error[invalid-return-type]: Return type does not match returned value
   --> src/codex_rosetta/converters/anthropic/config_ops.py:135:16
    |
135 |         return result
    |                ^^^^^^ expected `GenerationConfig`, found `dict[str, Any]`
```

**Scope of influence**:

| Module | Affected methods |
|------|-------------|
| `config_ops.py` (all providers) | `p_generation_config_to_ir`, `p_stream_config_to_ir`, `p_reasoning_config_to_ir`, `p_cache_config_to_ir`, `p_response_format_to_ir` |
| `converter.py` (all providers) | `request_from_provider`, `response_from_provider` |
| `tool_ops.py` (all providers) | `p_tool_definition_to_ir`, `p_tool_config_to_ir`, `p_tool_choice_to_ir` |

**Root Cause**:

1. Use `Dict[str, Any]` as the intermediate variable type
2. TypedDict’s structured type system requires exact matching
3. Conditionally filled fields make static verification impossible

---

### Root cause 3: Union type parameter passed to function expecting concrete type

**Number of errors**: 67 `invalid-argument-type`

**Problem description**:

The code determines the type through `part.get("type")` and then calls the corresponding conversion function, but ty cannot narrow the type, causing the union type to be passed to a function that expects a specific type.

**Typical code pattern**:

```python
# converters/anthropic/converter.py:357-365
for part in message.get("content", []):
    part_type = part.get("type")
    if part_type == "text":
        anthropic_content.append(self.content_ops.ir_text_to_p(part))
        # Error: part is still TextPart | ImagePart | ToolCallPart | ...
    elif part_type == "tool_call":
        anthropic_content.append(self.tool_ops.ir_tool_call_to_p(part))
        # Error: part is still a union type
```

**ty error report example**:

```
error[invalid-argument-type]: Argument to function `ir_text_to_p` is incorrect
   --> src/codex_rosetta/converters/anthropic/converter.py:359:80
    |
359 |     anthropic_content.append(self.content_ops.ir_text_to_p(part))
    |                                                            ^^^^ Expected `TextPart`, found `TextPart | ImagePart | ToolCallPart | ...`
```

**Scope of influence**:

- All `response_to_provider` methods of `converter.py`
- All message conversion methods of `message_ops.py`
- All `_ir_message_to_p` and `_p_content_part_to_ir` methods

**Root Cause**:

1. Same type of narrowing problem as Root Cause 1
2. TypeGuard function needs to be used for type narrowing

---

### Root cause 4: TypedDict definition does not match actual usage

**Number of Errors**: ~30 (spread across multiple error types)

#### Sub-problem 4a: ImagePart/FilePart/AudioPart field access methods are inconsistent

**Problem description**:

The code accesses `ir_image["data"]` and `ir_image["media_type"]` directly, but the TypedDict definition uses the nested structure `image_data: ImageData`.

**TypedDict definition**:

```python
# types/ir/parts.py
class ImagePart(TypedDict):
    type: Required[Literal["image"]]
    image_url: NotRequired[str]
    image_data: NotRequired[ImageData] # Nested structure
    detail: NotRequired[Literal["auto", "low", "high"]]
```

**Actual code**:

```python
# converters/google_genai/content_ops.py:88-90
return {
    "inline_data": {
        "mime_type": ir_image["media_type"], # Error: ImagePart has no media_type
        "data": ir_image["data"], # Error: ImagePart has no data
    }
}
```

#### Sub-issue 4b: The dictionary type definition of CitationPart is too strict

**Problem description**:

The `url_citation` field of `CitationPart` is defined as `Dict[Literal["start_index", "end_index", "title", "url"], Any]`, but when actually constructed, an ordinary dict is used, and ty cannot be matched.

**TypedDict definition**:

```python
class CitationPart(TypedDict):
    type: Required[Literal["citation"]]
    url_citation: NotRequired[
        Dict[Literal["start_index", "end_index", "title", "url"], Any]
    ]
```

**Actual code**:

```python
# converters/openai_chat/content_ops.py:277-282
return CitationPart(
    type="citation",
    url_citation={
        "start_index": provider_citation.get("start_index", 0),
        "end_index": provider_citation.get("end_index", 0),
        "title": provider_citation.get("title", ""),
        "url": provider_citation.get("url", ""),
    }, # Error: dict[str, Any] does not match Dict[Literal[...], Any]
)
```

#### Sub-issue 4c: AudioPart return value is missing required fields

**Problem description**:

The AudioPart returned by the code is missing the required `audio_id` field.

```python
# converters/google_genai/content_ops.py:231-235
return {
    "type": "audio",
    "url": None, # Error: AudioPart has no url field
    "media_type": inline_data["mime_type"], # Error: AudioPart has no media_type field
} # Error: Required audio_id field is missing
```

---

### Root cause 5: Method rewriting signature is incompatible

**Number of errors**: 7 `invalid-method-override`

**Problem description**:

The parameter names of subclass methods are different from those of the parent class, which violates the Liskov substitution principle.

**Parent class definition**:

```python
# converters/base/converter.py:169-173
@abstractmethod
def stream_response_from_provider(
    self,
    chunk: Dict[str, Any], #The parameter name is chunk
    context: Optional[StreamContext] = None,
) -> List[IRStreamEvent]:
```

**Subclass implementation**:

```python
# converters/anthropic/converter.py:435-439
def stream_response_from_provider(
    self,
    event: Dict[str, Any], #The parameter name is event, which is different from the parent class
    context: Optional[StreamContext] = None,
) -> List[IRStreamEvent]:
```

**Scope of influence**:

- `AnthropicConverter.stream_response_from_provider`
- `AnthropicConverter.stream_response_to_provider`
- `GoogleGenAIConverter.stream_response_to_provider`
- Similar methods for other converters

---

### Root cause 6: TypedDict is missing required keys

**Number of errors**: 6 `missing-typed-dict-key`

**Problem description**:

When creating a TypedDict using `**kwargs` unpacking, ty was unable to verify that all required keys were present.

**Typical code**:

```python
# converters/google_genai/tool_ops.py:246
return ToolCallPart(**tool_call_kwargs)
# Error: tool_call_id, tool_input, tool_name, type may be missing
```

---

### Root cause 7: Type expression format error

**Number of errors**: 1 `invalid-type-form`

**Problem description**:

```python
T = TypeVar("T", bound=TypedDict) # TypedDict cannot be used as a type boundary
```

**Location**: `types/ir/helpers.py`

---

### Root cause 8: Other minor issues

#### 8a: Unused type: ignore annotation

**Number of errors**: 1 warning

#### 8b: dict.get() overload matching problem

**Number of Errors**: 2 `no-matching-overload`

```python
# converters/anthropic/converter.py:290
reason_map.get(stop_reason_val, "stop")
# Error: stop_reason_val type mismatch
```

#### 8c: Incompatible dictionary assignment types

**Number of errors**: 4 `invalid-assignment`

```python
# converters/anthropic/converter.py:724
result["index"] = context.current_block_index
# Error: Expected str | dict[str, str | Unknown], got int
```

---

## Repair priority

### P0: Type issues that may cause runtime errors

| Question | Quantity | Description |
|------|------|------|
| Root cause 4c: AudioPart is missing a required field | 2 | May cause runtime KeyError |
| Root cause 6: TypedDict is missing a required key | 6 | May cause runtime KeyError |

### P1: Type issues affecting API correctness

| Question | Quantity | Description |
|------|------|------|
| Root cause 4a: Inconsistent field access methods | ~10 | TypedDict definition does not match actual use |
| Root cause 4b: CitationPart type definition is too strict | ~5 | Type definition needs to be adjusted |
| Root cause 5: Method rewriting signature is incompatible | 7 | Violation of LSP, which may lead to polymorphic calling problems |
| Root cause 7: TypeVar bound error | 1 | Basic problem of type system |

### P2: Issue where the type system cannot be inferred correctly but is correct at runtime

| Question | Quantity | Description |
|------|------|------|
| Root cause 1: Union type narrowing failed | ~400 | TypeGuard needs to be added |
| Root cause 2: Returning dict instead of TypedDict | 72 | Need to refactor the build method |
| Root cause 3: Union type parameter passing | 67 | Need to add TypeGuard |

### P3: Coding style/best practice issues

| Question | Quantity | Description |
|------|------|------|
| Root cause 8a: Unused type: ignore | 1 | Just clean |
| Root cause 8b/8c: Other minor issues | 6 | Partial fix |

---

## Repair strategy

### Strategy 1: Add TypeGuard function for IRStreamEvent (solve root causes 1, 3)

**Goal**: Resolve ~470 bugs

**Implementation plan**:

Add event type guard function in `types/ir/type_guards.py`:

```python
from typing import TypeGuard

def is_stream_start_event(event: IRStreamEvent) -> TypeGuard[StreamStartEvent]:
    return event.get("type") == "stream_start"

def is_text_delta_event(event: IRStreamEvent) -> TypeGuard[TextDeltaEvent]:
    return event.get("type") == "text_delta"

def is_tool_call_start_event(event: IRStreamEvent) -> TypeGuard[ToolCallStartEvent]:
    return event.get("type") == "tool_call_start"

# ...add for each event type
```

**How to use**:

```python
# Before modification
event_type = ir_event["type"]
if event_type == "stream_start":
    context.response_id = ir_event["response_id"]

# After modification
if is_stream_start_event(ir_event):
    context.response_id = ir_event["response_id"] # Now ty knows this is a StreamStartEvent
```

### Strategy 2: Add TypeGuard function for ContentPart (solve root cause 3)

**Goal**: Resolve ~50 bugs

**Implementation plan**:

```python
def is_text_part(part: ContentPart) -> TypeGuard[TextPart]:
    return isinstance(part, dict) and part.get("type") == "text"

def is_image_part(part: ContentPart) -> TypeGuard[ImagePart]:
    return isinstance(part, dict) and part.get("type") == "image"

def is_tool_call_part(part: ContentPart) -> TypeGuard[ToolCallPart]:
    return isinstance(part, dict) and part.get("type") == "tool_call"

# ... add for each content type
```

### Strategy 3: Refactor the TypedDict construction method (solve root cause 2)

**Goal**: Resolve 72 bugs

**Option A: Use TypedDict constructor**

```python
# Before modification
def p_generation_config_to_ir(...) -> GenerationConfig:
    result: Dict[str, Any] = {}
    if "max_tokens" in provider_config:
        result["max_tokens"] = provider_config["max_tokens"]
    return result

# After modification
def p_generation_config_to_ir(...) -> GenerationConfig:
    return GenerationConfig(
        max_tokens=provider_config.get("max_tokens"),
        temperature=provider_config.get("temperature"),
        # ...explicitly list all fields
    )
```

**Option B: Use cast (not recommended, but fast)**

```python
from typing import cast

def p_generation_config_to_ir(...) -> GenerationConfig:
    result: Dict[str, Any] = {}
    # ...fill logic
    return cast(GenerationConfig, result)
```

**Option C: Use TypedDict with total=False**

If most fields are optional, consider defining TypedDict as `total=False`.

### Strategy 4: Fix TypedDict definition (addresses root cause 4)

**4a: Unify the field access methods of ImagePart/FilePart/AudioPart**

Option 1: Modify TypedDict definition to add top-level fields

```python
class ImagePart(TypedDict):
    type: Required[Literal["image"]]
    image_url: NotRequired[str]
    image_data: NotRequired[ImageData]
    # Add top-level fields as convenient access
    data: NotRequired[str]
    media_type: NotRequired[str]
```

Option 2: Modify the code to use nested access

```python
# Before modification
ir_image["data"]

# After modification
ir_image.get("image_data", {}).get("data")
```

**4b: Fix CitationPart type definition**

```python
# Before modification
url_citation: NotRequired[Dict[Literal["start_index", "end_index", "title", "url"], Any]]

# After modification - use more relaxed types
url_citation: NotRequired[Dict[str, Any]]

# Or define a special TypedDict
class UrlCitation(TypedDict):
    start_index: int
    end_index: int
    title: str
    url: str

class CitationPart(TypedDict):
    type: Required[Literal["citation"]]
    url_citation: NotRequired[UrlCitation]
```

**4c: Fix AudioPart return value**

```python
# Modify the code to ensure that the correct fields are returned
return AudioPart(
    type="audio",
    audio_id=generate_audio_id(), # Add required fields
)
```

### Strategy 5: Unify method signatures (solve root cause 5)

**Implementation plan**:

Unify the parameter names of all subclasses to the names defined by the parent class:

```python
# Parent class
def stream_response_from_provider(
    self,
    chunk: Dict[str, Any],
    context: Optional[StreamContext] = None,
) -> List[IRStreamEvent]:

# Subclass - use the same parameter names
def stream_response_from_provider(
    self,
    chunk: Dict[str, Any], # Change to chunk instead of event
    context: Optional[StreamContext] = None,
) -> List[IRStreamEvent]:
```

### Strategy 6: Fix TypedDict construct (addresses root cause 6)

**Implementation plan**:

Avoid using `**kwargs` to unpack and construct TypedDict explicitly:

```python
# Before modification
return ToolCallPart(**tool_call_kwargs)

# After modification
return ToolCallPart(
    type="tool_call",
    tool_call_id=tool_call_kwargs["tool_call_id"],
    tool_name=tool_call_kwargs["tool_name"],
    tool_input=tool_call_kwargs["tool_input"],
)
```

### Strategy 7: Fix TypeVar bound (address root cause 7)

**Implementation plan**:

```python
# Before modification
T = TypeVar("T", bound=TypedDict)

# After modification - use Mapping or concrete base class
from typing import Mapping
T = TypeVar("T", bound=Mapping[str, Any])
```

---

## Recommended repair sequence

### Phase 1: Infrastructure (Estimated impact ~500 bugs)

1. **Add TypeGuard function** - Add all required type guards in `types/ir/type_guards.py`
2. **Fix TypedDict definition** - Adjust the definitions of `ImagePart`, `FilePart`, `AudioPart`, `CitationPart`

### Phase 2: Core Converter (expected to impact ~100 bugs)

1. **Refactor config_ops.py** - use TypedDict constructor or cast
2. **Unified method signature** - fix all `invalid-method-override` errors

### Phase 3: Apply TypeGuard (expected to impact ~400 bugs)

1. **Modify converter.py** - Use TypeGuard in streaming event processing
2. **Modify message_ops.py** - Use TypeGuard in content part processing

### Phase 4: Cleanup (expected to affect ~10 bugs)

1. **Fix minor issues** - `no-matching-overload`, `invalid-assignment`, etc.
2. **Remove unused type: ignore**

---

## Risk Assessment

### Low risk fix

- Added TypeGuard function (does not change runtime behavior)
- Unified method signature (changes in parameter names do not affect calls)
- Remove unused type: ignore

### Medium risk fix

- Modify TypedDict definition (may affect other code using this type)
- Use cast (hide potential type issues)

### High risk fixes

- Refactor the way TypedDict is built (requires a lot of code modifications)
- Modify field access method (may introduce runtime errors)

---

## Summary

The 645 type errors in codex-rosetta mainly stem from the following core issues:

1. **Union type narrowing** - ty cannot narrow TypedDict union type via string comparison (~470 errors)
2. **TypedDict construction method** - build with `Dict[str, Any]` and return (72 errors)
3. **TypedDict definition inconsistency** - definition does not match actual usage (~30 errors)

Most problems can be solved by adding TypeGuard functions and adjusting TypedDict definitions. It is recommended that fixes be carried out in the order of the stages above, prioritizing infrastructure issues and then gradually applying them to individual modules.
