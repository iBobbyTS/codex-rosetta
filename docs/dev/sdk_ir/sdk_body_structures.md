# SDK Body-Level Parameter Structure Analysis

Based on analysis of four major SDK entry functions, we identified the complete "body" parameter structures. These structures represent the full set of API call parameters for each SDK.

## Classification Notes

- **Core Input Content Parameters**: user/system/developer message, conversation history, content input, etc.
- **Tool-Related Parameters**: tools, tool_choice, tool_use, etc.
- **Generation Control Parameters**: temperature, top_p, max_tokens, and other generation quality controls
- **Runtime Control Parameters**: stream, stop_sequences, metadata, and other runtime controls
- **Miscellaneous**: SDK-specific parameters, system parameters, etc.

---

## 1. OpenAI Chat Completions

**Entry function**: `openai_client.chat.completions.create()`  
**Total parameters**: 37

### 1.1 Core Input Content Parameters

| Parameter | Type | Required | Description |
|--------|------|------|------|
| `messages` | `Iterable[ChatCompletionMessageParam]` | ✅ | Conversation message list, type: `Union[ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam, ChatCompletionAssistantMessageParam, ...]` |
| `model` | `Union[str, ChatModel]` | ✅ | Model ID, e.g. `gpt-4o`, `o3`, etc. |

### 1.2 Tool-Related Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `tools` | `Iterable[ChatCompletionToolUnionParam]` | `omit` | List of available tools, type: `Union[Function, CodeInterpreter, FileSearch]` |
| `tool_choice` | `ChatCompletionToolChoiceOptionParam` | `omit` | Tool selection strategy, type: `Union[Literal["auto", "none", "required"], ChatCompletionToolChoiceFunction]` |
| `parallel_tool_calls` | `bool` | `omit` | Whether to allow parallel tool calls |

### 1.3 Generation Control Parameters

| Parameter | Type | Default | Range/Description |
|--------|------|--------|-----------|
| `temperature` | `Optional[float]` | `omit` | Range: `0.0-2.0`, lower values = more deterministic |
| `top_p` | `Optional[float]` | `omit` | Nucleus sampling, range: `0.0-1.0` |
| `max_completion_tokens` | `Optional[int]` | `omit` | Maximum number of tokens to generate |
| `max_tokens` | `Optional[int]` | `omit` | Maximum number of tokens (alias, same as max_completion_tokens) |
| `n` | `Optional[int]` | `omit` | Number of completions to generate |
| `frequency_penalty` | `Optional[float]` | `omit` | Frequency penalty, range: `-2.0` to `2.0` |
| `presence_penalty` | `Optional[float]` | `omit` | Presence penalty, range: `-2.0` to `2.0` |
| `logit_bias` | `Optional[Dict[str, int]]` | `omit` | Logit bias, key = token ID, value = bias value |
| `seed` | `Optional[int]` | `omit` | Random seed for reproducible output |
| `top_logprobs` | `Optional[int]` | `omit` | Return log probabilities for the top k tokens |

### 1.4 Runtime Control Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `stop` | `Union[Optional[str], SequenceNotStr[str], None]` | `omit` | Stop sequence, a string or list of strings |
| `stream` | `Optional[Literal[False]]` | `omit` | Whether to stream output, true by default |
| `stream_options` | `Optional[ChatCompletionStreamOptionsParam]` | `omit` | Streaming output options, includes `include_usage`, etc. |
| `response_format` | `completion_create_params.ResponseFormat` | `omit` | Response format, e.g. JSON mode |
| `logprobs` | `Optional[bool]` | `omit` | Whether to return log probabilities |
| `user` | `str` | `omit` | User identifier |
| `metadata` | `Optional[Metadata]` | `omit` | Metadata, type: `Dict[str, str]` |

### 1.5 Miscellaneous Parameters

| Parameter | Type | Description |
|--------|------|------|
| `audio` | `Optional[ChatCompletionAudioParam]` | Audio output configuration, requires `modalities: ["audio"]` |
| `modalities` | `Optional[List[Literal["text", "audio"]]]` | Supported modality types |
| `prediction` | `Optional[ChatCompletionPredictionContentParam]` | Prediction content configuration |
| `prompt_cache_key` | `str` | Prompt cache key |
| `prompt_cache_retention` | `Optional[Literal["in-memory", "24h"]]` | Prompt cache retention policy |
| `reasoning_effort` | `Optional[ReasoningEffort]` | Reasoning effort, type: `Literal["low", "medium", "high"]` |
| `web_search_options` | `completion_create_params.WebSearchOptions` | Web search options |
| `service_tier` | `Optional[Literal["auto", "default", "flex", "scale", "priority"]]` | Service tier |
| `function_call` | `completion_create_params.FunctionCall` | ⚠️ **Deprecated**, use `tool_choice` instead |
| `functions` | `Iterable[completion_create_params.Function]` | ⚠️ **Deprecated**, use `tools` instead |
| `safety_identifier` | `str` | Safety identifier |
| `store` | `Optional[bool]` | Whether to store the response |
| `verbosity` | `Optional[Literal["low", "medium", "high"]]` | Verbosity level |

### 1.6 System Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `extra_headers` | `Headers | None` | `None` | Extra HTTP headers |
| `extra_query` | `Query | None` | `None` | Extra query parameters |
| `extra_body` | `Body | None` | `None` | Extra request body |
| `timeout` | `float | httpx.Timeout | None | NotGiven` | `not_given` | Timeout setting |

---

## 2. OpenAI Responses

**Entry function**: `openai_responses_client.responses.create()`  
**Total parameters**: 28

### 2.1 Core Input Content Parameters

| Parameter | Type | Required | Description |
|--------|------|------|------|
| `input` | `Union[str, ResponseInputParam]` | ✅ | Input content, supports 30+ types, extremely complex |
| `model` | `ResponsesModel` | ✅ | Model ID |
| `instructions` | `Optional[str]` | - | System instructions, similar to system message |
| `conversation` | `Optional[response_create_params.Conversation]` | - | The conversation this response belongs to, for multi-turn dialogue |

### 2.2 Tool-Related Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `tools` | `Iterable[ToolParam]` | `omit` | List of available tools |
| `tool_choice` | `response_create_params.ToolChoice` | `omit` | Tool selection strategy |
| `parallel_tool_calls` | `Optional[bool]` | `omit` | Whether to allow parallel tool calls |
| `max_tool_calls` | `Optional[int]` | `omit` | Maximum number of tool calls |

### 2.3 Generation Control Parameters

| Parameter | Type | Default | Range/Description |
|--------|------|--------|-----------|
| `temperature` | `Optional[float]` | `omit` | Range: `0.0-2.0` |
| `top_p` | `Optional[float]` | `omit` | Nucleus sampling, range: `0.0-1.0` |
| `max_output_tokens` | `Optional[int]` | `omit` | Maximum number of output tokens |
| `top_logprobs` | `Optional[int]` | `omit` | Return log probabilities for the top k tokens |
| `frequency_penalty` | `Optional[float]` | `omit` | Frequency penalty, range: `-2.0` to `2.0` |
| `presence_penalty` | `Optional[float]` | `omit` | Presence penalty, range: `-2.0` to `2.0` |
| `logit_bias` | `Optional[Dict[str, int]]` | `omit` | Logit bias |

### 2.4 Runtime Control Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `stream` | `Optional[Literal[False]]` | `omit` | Whether to stream output |
| `stream_options` | `Optional[response_create_params.StreamOptions]` | `omit` | Streaming output options |
| `response_format` | - | `omit` | Response format (not directly defined in the parameters) |
| `truncation` | `Optional[Literal["auto", "disabled"]]` | `omit` | Truncation strategy |
| `user` | `str` | `omit` | User identifier |
| `metadata` | `Optional[Metadata]` | `omit` | Metadata |

### 2.5 Miscellaneous Parameters

| Parameter | Type | Description |
|--------|------|------|
| `background` | `Optional[bool]` | Whether to run in the background |
| `include` | `Optional[List[ResponseIncludable]]` | Additional data to include |
| `previous_response_id` | `Optional[str]` | Previous response ID |
| `prompt` | `Optional[ResponsePromptParam]` | Prompt template reference |
| `prompt_cache_key` | `str` | Prompt cache key |
| `prompt_cache_retention` | `Optional[Literal["in-memory", "24h"]]` | Prompt cache retention policy |
| `reasoning` | `Optional[Reasoning]` | Reasoning configuration |
| `safety_identifier` | `str` | Safety identifier |
| `service_tier` | `Optional[Literal["auto", "default", "flex", "scale", "priority"]]` | Service tier |
| `store` | `Optional[bool]` | Whether to store the response |
| `text` | `ResponseTextConfigParam` | Text configuration |
| `audio` | - | Audio configuration (not directly defined in the parameters) |
| `modalities` | - | Supported modality types (not directly defined in the parameters) |
| `prediction` | - | Prediction configuration (not directly defined in the parameters) |
| `reasoning_effort` | - | Reasoning effort (not directly defined in the parameters) |

### 2.6 System Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `extra_headers` | `Headers | None` | `None` | Extra HTTP headers |
| `extra_query` | `Query | None` | `None` | Extra query parameters |
| `extra_body` | `Body | None` | `None` | Extra request body |
| `timeout` | `float | httpx.Timeout | None | NotGiven` | `not_given` | Timeout setting |

---

## 3. Anthropic Messages

**Entry function**: `anthropic_client.messages.create()`  
**Total parameters**: 14

### 3.1 Core Input Content Parameters

| Parameter | Type | Required | Description |
|--------|------|------|------|
| `messages` | `Iterable[MessageParam]` | ✅ | Conversation message list, type: `Union[TextBlockParam, ImageBlockParam]` |
| `model` | `ModelParam` | ✅ | Model ID, e.g. `claude-sonnet-4-20250514` |
| `system` | `Union[str, Iterable[TextBlockParam]]` | - | System prompt, can be a string or multiple text blocks |
| `max_tokens` | `int` | ✅ | Maximum number of tokens to generate (required) |

### 3.2 Tool-Related Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `tools` | `Iterable[ToolUnionParam]` | `omit` | List of available tools, type: `Union[ToolParam, ComputerToolParam, BashToolParam, ...]` |
| `tool_choice` | `ToolChoiceParam` | `omit` | Tool selection strategy, type: `Union[Literal["auto", "none", "any"], ToolChoiceToolParam]` |
| `thinking` | `ThinkingConfigParam` | `omit` | Thinking configuration, for reasoning models |

### 3.3 Generation Control Parameters

| Parameter | Type | Default | Range/Description |
|--------|------|--------|-----------|
| `temperature` | `float` | `omit` | Range: `0.0-1.0` |
| `top_p` | `float` | `omit` | Nucleus sampling, range: `0.0-1.0` |
| `top_k` | `int` | `omit` | Top-k sampling, integer value |

### 3.4 Runtime Control Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `stop_sequences` | `SequenceNotStr[str]` | `omit` | Stop sequences, a list of strings |
| `stream` | `Literal[False]` | `omit` | Whether to stream output |
| `metadata` | `MetadataParam` | `omit` | Metadata |

### 3.5 Miscellaneous Parameters

| Parameter | Type | Description |
|--------|------|------|
| `service_tier` | `Literal["auto", "standard_only"]` | Service tier |

### 3.6 System Parameters

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `extra_headers` | `Headers | None` | `None` | Extra HTTP headers |
| `extra_query` | `Query | None` | `None` | Extra query parameters |
| `extra_body` | `Body | None` | `None` | Extra request body |
| `timeout` | `float | httpx.Timeout | None | NotGiven` | `not_given` | Timeout setting |

---

## 4. Google GenerativeAI

**Entry function**: `google_client.models.generate_content()`  
**Total parameters**: 3 top-level parameters

### 4.1 Core Input Content Parameters

| Parameter | Type | Required | Description |
|--------|------|------|------|
| `contents` | `types.ContentListUnionDict` | ✅ | Input content list, type: `Union[List[Content], List[Part], ...]` |
| `model` | `str` | ✅ | Model ID, e.g. `gemini-2.0-flash` |

### 4.2 Tool-Related Parameters (passed via config)

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `tools` | `List[Tool]` | `None` | List of available tools, passed in `config` |

### 4.3 GenerationConfig (generation configuration object)

The `config` parameter is `Optional[types.GenerateContentConfigOrDict]`, containing the following fields:

| Parameter | Type | Default | Range/Description |
|--------|------|--------|-----------|
| `temperature` | `Optional[float]` | `None` | Controls randomness, lower values = more deterministic |
| `top_p` | `Optional[float]` | `None` | Nucleus sampling |
| `top_k` | `Optional[float]` | `None` | Top-k sampling |
| `max_output_tokens` | `Optional[int]` | `None` | Maximum number of output tokens |
| `candidate_count` | `Optional[int]` | `None` | Number of generated candidates |
| `stop_sequences` | `Optional[list[str]]` | `None` | List of stop sequences |
| `presence_penalty` | `Optional[float]` | `None` | Presence penalty |
| `frequency_penalty` | `Optional[float]` | `None` | Frequency penalty |
| `seed` | `Optional[int]` | `None` | Random seed |
| `response_logprobs` | `Optional[bool]` | `None` | Whether to return log probabilities |
| `logprobs` | `Optional[int]` | `None` | Number of tokens to return log probabilities for |
| `response_mime_type` | `Optional[str]` | `None` | Response MIME type, e.g. `text/plain`, `application/json` |
| `response_schema` | `Optional[Schema]` | `None` | Response schema, for structured output |
| `response_modalities` | `Optional[List[str]]` | `None` | Response modalities |

### 4.4 Runtime Control Parameters (passed via config)

| Parameter | Type | Default | Description |
|--------|------|--------|------|
| `system_instruction` | `Optional[ContentUnion]` | `None` | System instruction |
| `safety_settings` | `Optional[List[SafetySetting]]` | `None` | Safety settings |
| `cached_content` | `Optional[str]` | `None` | Cached content reference |
| `thinking_config` | `Optional[ThinkingConfig]` | `None` | Thinking configuration |

### 4.5 Miscellaneous Parameters (passed via config)

| Parameter | Type | Description |
|--------|------|------|
| `http_options` | `Optional[HttpOptions]` | HTTP request options |
| `should_return_http_response` | `Optional[bool]` | Whether to return the raw HTTP response |

---

## Cross-SDK Parameter Mapping Summary

### Core Input Content Parameter Mapping

| Function | OpenAI Chat | OpenAI Responses | Anthropic | Google |
|------|-------------|------------------|-----------|--------|
| **Message list** | `messages` | `input` | `messages` | `contents` |
| **Model** | `model` | `model` | `model` | `model` |
| **System instruction** | `messages[0].role="system"` | `instructions` | `system` | `config.system_instruction` |

### Tool-Related Parameter Mapping

| Function | OpenAI Chat | OpenAI Responses | Anthropic | Google |
|------|-------------|------------------|-----------|--------|
| **Tool list** | `tools` | `tools` | `tools` | `config.tools` |
| **Tool selection** | `tool_choice` | `tool_choice` | `tool_choice` | `config.tool_config` |
| **Parallel calls** | `parallel_tool_calls` | `parallel_tool_calls` | - | - |
| **Thinking config** | - | `reasoning` | `thinking` | `config.thinking_config` |

### Generation Control Parameter Mapping

| Function | OpenAI Chat | OpenAI Responses | Anthropic | Google |
|------|-------------|------------------|-----------|--------|
| **Temperature** | `temperature` | `temperature` | `temperature` | `config.temperature` |
| **Top-p** | `top_p` | `top_p` | `top_p` | `config.top_p` |
| **Top-k** | - | - | `top_k` | `config.top_k` |
| **Max tokens** | `max_completion_tokens` | `max_output_tokens` | `max_tokens` | `config.max_output_tokens` |
| **Frequency penalty** | `frequency_penalty` | `frequency_penalty` | - | `config.frequency_penalty` |
| **Presence penalty** | `presence_penalty` | `presence_penalty` | - | `config.presence_penalty` |
| **Random seed** | `seed` | - | - | `config.seed` |
| **Log probabilities** | `logprobs`, `top_logprobs` | `top_logprobs` | - | `config.response_logprobs`, `config.logprobs` |

### Runtime Control Parameter Mapping

| Function | OpenAI Chat | OpenAI Responses | Anthropic | Google |
|------|-------------|------------------|-----------|--------|
| **Stop sequence** | `stop` | - | `stop_sequences` | `config.stop_sequences` |
| **Streaming** | `stream` | `stream` | `stream` | Async iteration over response |
| **Response format** | `response_format` | - | - | `config.response_mime_type`, `config.response_schema` |
| **Metadata** | `metadata` | `metadata` | `metadata` | - |
| **User identifier** | `user` | `user` | - | - |

This analysis provides a clear reference for designing a unified request body structure. Although the parameter names differ across SDKs, the core functionality is similar — and that is precisely the value of body-level translation.
