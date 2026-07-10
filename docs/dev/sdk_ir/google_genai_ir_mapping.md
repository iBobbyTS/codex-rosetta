# IR Types to Google GenAI SDK Mapping

This document describes the mapping between Codex-Rosetta IR (Intermediate Representation) types and the native types of the `google-genai` SDK.

## 1. Request Mapping

IR requests primarily map to `google.genai.types.GenerateContentConfig` and `google.genai.types.Content`.

### 1.1 IRRequest Top-Level Mapping

| IRRequest Field | Google GenAI SDK Type/Field | Notes |
| :--- | :--- | :--- |
| `model` | `model` (str) | Model ID |
| `messages` | `contents` (List[Content]) | Conversation content list |
| `system_instruction` | `config.system_instruction` (ContentUnion) | System instruction |
| `tools` | `config.tools` (List[Tool]) | Tool definition list |
| `tool_choice` | `config.tool_config.function_calling_config.mode` | Tool choice mode mapping |
| `generation` | `config` (GenerateContentConfig) | Generation config parameters |
| `response_format` | `config.response_mime_type` / `response_schema` | Response format configuration |

### 1.2 GenerationConfig Mapping

| IR GenerationConfig Field | Google GenerateContentConfig Field | Notes |
| :--- | :--- | :--- |
| `temperature` | `temperature` | Temperature control |
| `top_p` | `top_p` | Nucleus sampling |
| `top_k` | `top_k` | Top-k sampling |
| `max_tokens` | `max_output_tokens` | Maximum generation token count |
| `stop_sequences` | `stop_sequences` | Stop sequences |
| `frequency_penalty` | `frequency_penalty` | Frequency penalty |
| `presence_penalty` | `presence_penalty` | Presence penalty |
| `seed` | `seed` | Random seed |
| `candidate_count` | `candidate_count` | Candidate count |

### 1.3 Message & ContentPart Mapping

IR `Message` maps to Google's `Content` type.

| IR Message/Part | Google SDK Type | Mapping Details |
| :--- | :--- | :--- |
| `Message.role` | `Content.role` | `user` -> `user`, `assistant` -> `model` |
| `TextPart` | `Part.text` | Plain text content |
| `ImagePart` | `Part.inline_data` (Blob) | Image data (base64) |
| `FilePart` | `Part.file_data` (FileData) | File data (URI) |
| `ToolCallPart` | `Part.function_call` (FunctionCall) | Tool call request |
| `ToolResultPart` | `Part.function_response` (FunctionResponse) | Tool execution result |

---

## 2. Response Mapping

IR responses are primarily mapped from `google.genai.types.GenerateContentResponse`.

### 2.1 IRResponse Top-Level Mapping

| IRResponse Field | Google GenerateContentResponse Field | Notes |
| :--- | :--- | :--- |
| `id` | `response_id` | Response unique ID |
| `model` | `model_version` | Actual model version used |
| `choices` | `candidates` (List[Candidate]) | Generated candidate result list |
| `usage` | `usage_metadata` | Token usage statistics |

### 2.2 ChoiceInfo & FinishReason Mapping

| IR ChoiceInfo Field | Google Candidate Field | Notes |
| :--- | :--- | :--- |
| `index` | `index` | Candidate index |
| `message` | `content` (Content) | Generated message content |
| `finish_reason` | `finish_reason` | Finish reason mapping |

**FinishReason Mapping Details:**
- `STOP` -> `stop`
- `MAX_TOKENS` -> `length`
- `SAFETY` -> `content_filter`
- `MALFORMED_FUNCTION_CALL` -> `error`

### 2.3 UsageInfo Mapping

| IR UsageInfo Field | Google UsageMetadata Field | Notes |
| :--- | :--- | :--- |
| `prompt_tokens` | `prompt_token_count` | Input token count |
| `completion_tokens` | `candidates_token_count` | Output token count |
| `total_tokens` | `total_token_count` | Total token count |
| `reasoning_tokens` | `thoughts_token_count` | Tokens consumed by reasoning/thinking |

---

## 3. Special Types Mapping

### 3.1 Reasoning (Thinking Process)
- **IR**: `ReasoningPart` (type="reasoning")
- **Google SDK**: `Part.thought` (bool) and `Part.text`. When `thought=True`, the `text` content of that Part is the thinking process.

### 3.2 Tool Call Metadata
- **IR**: `ToolCallPart.provider_metadata`
- **Google SDK**: `Part.thought_signature`. In Gemini 3, tool calls are typically accompanied by a `thought_signature`; IR stores this in `provider_metadata` so it can be carried back in subsequent turns.

### 3.3 Response Format
- **IR**: `ResponseFormatConfig`
- **Google SDK**: Mapped to `GenerateContentConfig`'s `response_mime_type` (e.g. `application/json`) and `response_schema` (Schema object).
