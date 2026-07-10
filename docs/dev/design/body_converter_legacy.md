# Body-Level Converter (Legacy Design)

> **⚠️ Historical Reference**: This document describes an early design for body-level
> conversion using `UnifiedBody` / `BodyConverter`. This approach has been superseded
> by the current IR (Intermediate Representation) architecture using `IRRequest` /
> `IRResponse` with per-provider converters and the bottom-up Ops pattern.
> Retained here for design evolution context.

Codex-Rosetta's body-level converter provides complete parameter conversion between different LLM provider SDKs. Unlike existing message-level converters, the body converter can handle the complete set of parameters of SDK entry functions, achieving true SDK compatibility.

## Core concepts

### Supported SDK types

- **OpenAI Chat Completions** (`openai_chat`): `openai_client.chat.completions.create()`
- **OpenAI Responses** (`openai_responses`): `openai_responses_client.responses.create()`
- **Anthropic Messages** (`anthropic`): `anthropic_client.messages.create()`
- **Google GenerativeAI** (`google`): `google_client.models.generate_content()`

### UnifiedBody intermediate representation

`UnifiedBody` is a unified intermediate representation of all SDK parameters, including:

- **Core parameters**: `model`, `messages`
- **Generation controls**: `max_tokens`, `temperature`, `top_p`, `top_k`, `frequency_penalty`, `presence_penalty`, `seed`
- **Tool related**: `tools`, `tool_choice`
- **Control parameters**: `stop_sequences`, `stream`, `system_instruction`
- **Response format**: `response_format`, `response_mime_type`, `response_schema`
- **Advanced parameters**: `logprobs`, `top_logprobs`, `n`
- **SDK specific**: `sdk_specific` (save specific parameters that cannot be mapped)

## Basic usage

### Simple conversion

```python
from codex-rosetta import convert_body, SDKType

# OpenAI Chat format
openai_body = {
    "model": "gpt-4",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ],
    "max_completion_tokens": 150,
    "temperature": 0.7
}

# Convert to Anthropic format
anthropic_body = convert_body(
    openai_body,
    SDKType.OPENAI_CHAT,
    SDKType.ANTHROPIC
)

print(anthropic_body)
# {
#     "model": "gpt-4",
#     "messages": [{"role": "user", "content": "What is the capital of France?"}],
#     "max_tokens": 150,
#     "temperature": 0.7,
#     "system": "You are a helpful assistant."
# }
```

### Automatically detect conversion

```python
from codex-rosetta import BodyConverter, SDKType

converter = BodyConverter()

# Automatically detect source SDK type
source_body = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
}

# Automatically detect and convert
result = converter.convert_auto(source_body, SDKType.ANTHROPIC)
```

### Tool call conversion

```python
# OpenAI format tool call
openai_with_tools = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "What's the weather in Paris?"}],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"}
                    },
                    "required": ["city"]
                }
            }
        }
    ],
    "tool_choice": "auto"
}

# Convert to Anthropic format
anthropic_result = convert_body(
    openai_with_tools,
    SDKType.OPENAI_CHAT,
    SDKType.ANTHROPIC
)
```

## Advanced features

### SDK specific parameter processing

Each SDK has some specific parameters, which will be stored in the `sdk_specific` field:

```python
# OpenAI specific parameters
openai_specific = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}],
    "logit_bias": {"50256": -100}, # OpenAI specific
    "user": "user123", # OpenAI specific
    "service_tier": "auto" # OpenAI specific
}

converter = BodyConverter()
unified = converter.from_openai_chat(openai_specific)

# Specific parameters are stored in sdk_specific
print(unified.sdk_specific)
# {"logit_bias": {"50256": -100}, "user": "user123", "service_tier": "auto"}

# Specific parameters will be restored when converting back to OpenAI format
converted_back = converter.to_openai_chat(unified)
print(converted_back["logit_bias"])  # {"50256": -100}
```

### SDK Availability Check

```python
from codex-rosetta import is_sdk_available, get_available_providers

# Check if a specific SDK is available
if is_sdk_available("openai_chat"):
    print("OpenAI SDK is available")

# Get all available providers
available = get_available_providers()
print(available)
# {"openai_chat": True, "anthropic": False, ...}
```

### Parameter verification

```python
from codex-rosetta import validate_provider_body

body = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
}

# Verify whether the body conforms to the OpenAI Chat format
is_valid = validate_provider_body("openai_chat", body)
print(is_valid)  # True
```

## Parameter mapping rules

### General parameter mapping

| UnifiedBody          | OpenAI Chat                 | OpenAI Responses        | Anthropic        | Google                      |
| -------------------- | --------------------------- | ----------------------- | ---------------- | --------------------------- |
| `max_tokens`         | `max_completion_tokens`     | `max_completion_tokens` | `max_tokens`     | `config.max_output_tokens`  |
| `system_instruction` | `messages[0]` (role=system) | `instructions`          | `system`         | `config.system_instruction` |
| `stop_sequences`     | `stop`                      | -                       | `stop_sequences` | `config.stop_sequences`     |
| `tools`              | `tools`                     | `tools`                 | `tools`          | `config.tools`              |
| `tool_choice`        | `tool_choice`               | -                       | `tool_choice`    | `config.tool_config`        |

### SDK specific parameters

#### OpenAI Chat specific

- `audio`, `logit_bias`, `service_tier`, `user`

#### OpenAI Responses specific

- `modalities`

#### Anthropic specific

- `metadata`, `service_tier`, `thinking`

#### Google specific

- `safety_settings`, `cached_content`, `response_modalities`, `thinking_config`

## Type support

### Optional dependencies

The body converter supports optional dependencies and works even if some SDKs are not installed:

```python
# Type checking can be performed even if the anthropopic package is not installed
from codex-rosetta.types.anthropic_types import AnthropicBody # Use TypedDict fallback
```

### Type checking

```python
from codex-rosetta.types.provider_types import OpenAIChatBody, AnthropicBody

def process_openai_request(body: OpenAIChatBody) -> AnthropicBody:
    return convert_body(body, SDKType.OPENAI_CHAT, SDKType.ANTHROPIC)
```

## Error handling

```python
from codex-rosetta import BodyConverter, SDKType

converter = BodyConverter()

try:
    # Invalid body
    invalid_body = {"model": "gpt-4"} # Missing messages

    # Automatic detection will return None
    detected = converter.detect_source_sdk(invalid_body)
    if detected is None:
        print("Unable to detect SDK type")

    # Conversion may throw exception
    result = converter.convert_auto(invalid_body, SDKType.ANTHROPIC)

except ValueError as e:
    print(f"Conversion failed: {e}")
```

## Performance considerations

- The body converter reuses existing message and tool converters to remain efficient
- The conversion process is stateless and can be used safely concurrently
- `UnifiedBody` uses dataclass, which is memory efficient

## Limitations and Notes

1. **Parameter Compatibility**: Not all parameters can be mapped perfectly between SDKs
2. **SDK specific features**: Some SDK specific features may be lost after conversion
3. **Validation Limitations**: Parameter validation is basic and cannot replace complete schema validation.
4. **Version Compatibility**: Depends on the current version of each SDK, API changes may affect conversion

## Sample code

For complete usage examples, please refer to `examples/body_converter_example.py`.

## API Reference

### Main classes and functions

- `BodyConverter`: main converter class
- `UnifiedBody`: unified parameter representation
- `SDKType`: SDK type enumeration
- `convert_body()`: Convenient conversion function
- `detect_provider_from_body()`: automatic detection function
- `validate_provider_body()`: validation function
- `is_sdk_available()`: SDK availability check

### Type definition

- `OpenAIChatBody`, `OpenAIResponsesBody`: OpenAI type
- `AnthropicBody`: Anthropic type
- `GoogleBody`: Google type
- `ProviderBody`: union type of all provider types
