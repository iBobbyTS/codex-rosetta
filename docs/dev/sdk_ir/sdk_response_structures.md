# Detailed Analysis of SDK Response Structures

Based on an in-depth analysis of the response types of the four major SDKs, this document details the complete response structure of each SDK and identifies their commonalities and differences. These structures represent the full API response format of each SDK.

## Analysis Method

This analysis is based on inspection of the source code of the actual installed SDKs, including:

- Direct examination of type definitions in `/data/pding/miniforge3/envs/codex-rosetta/lib/python3.10/site-packages/`
- Analysis of each SDK's response type structure
- In-depth study of the internal organization of content fields
- Identification of common patterns and unique features across SDKs

---

## 1. OpenAI Chat Completions Response Structure

**Return type**: [`ChatCompletion`](https://github.com/openai/openai-python/blob/main/src/openai/types/chat/chat_completion.py)
**Design philosophy**: Concise chat completion response, focused on conversation scenarios

### 1.1 Top-Level Response Fields (8 fields)

| Field Name           | Type                                                                | Required | Description                                                    |
| -------------------- | ------------------------------------------------------------------- | -------- | -------------------------------------------------------------- |
| `id`                 | `str`                                                               | ✅        | Unique identifier for the chat completion                      |
| `object`             | `Literal["chat.completion"]`                                        | ✅        | Object type, always "chat.completion"                          |
| `created`            | `int`                                                               | ✅        | Unix timestamp (seconds) when the chat completion was created  |
| `model`              | `str`                                                               | ✅        | Model used for the chat completion                             |
| `choices`            | `List[Choice]`                                                      | ✅        | **Core response content** - list of chat completion choices    |
| `usage`              | `Optional[CompletionUsage]`                                         | -        | Usage statistics for the completion request                    |
| `service_tier`       | `Optional[Literal["auto", "default", "flex", "scale", "priority"]]` | -        | Processing type used to serve the request                      |
| `system_fingerprint` | `Optional[str]`                                                     | -        | Fingerprint of the backend configuration running the model     |

### 1.2 Choice Structure (4 fields)

| Field Name      | Type                                                                         | Required | Description                                             |
| --------------- | ---------------------------------------------------------------------------- | -------- | ------------------------------------------------------- |
| `index`         | `int`                                                                        | ✅        | Index of the choice in the choices list                 |
| `message`       | `ChatCompletionMessage`                                                      | ✅        | **Core content** - model-generated chat completion message |
| `finish_reason` | `Literal["stop", "length", "tool_calls", "content_filter", "function_call"]` | ✅        | Reason the model stopped generating tokens              |
| `logprobs`      | `Optional[ChoiceLogprobs]`                                                   | -        | Log probability information for the choice              |

### 1.3 ChatCompletionMessage Content Structure (7 fields)

This is the core content carrier for OpenAI Chat Completions:

| Field Name      | Type                                                 | Required | Description                                              |
| --------------- | ---------------------------------------------------- | -------- | -------------------------------------------------------- |
| `role`          | `Literal["assistant"]`                               | ✅        | Role of the message author, always "assistant"           |
| `content`       | `Optional[str]`                                      | -        | **Primary text content**                                 |
| `refusal`       | `Optional[str]`                                      | -        | **Refusal response** - model-generated refusal message   |
| `tool_calls`    | `Optional[List[ChatCompletionMessageToolCallUnion]]` | -        | **Tool calls** - model-generated tool calls              |
| `function_call` | `Optional[FunctionCall]`                             | -        | ⚠️ **Deprecated** - replaced by tool_calls                |
| `annotations`   | `Optional[List[Annotation]]`                         | -        | **Reference annotations** - e.g., URL citations from web search |
| `audio`         | `Optional[ChatCompletionAudio]`                      | -        | **Audio response** - audio output modality data          |

#### Detailed Tool Call Structure

**ChatCompletionMessageToolCallUnion** contains:

- `ChatCompletionMessageFunctionToolCall` - Function tool call
- `ChatCompletionMessageCustomToolCall` - Custom tool call

**FunctionCall** (deprecated):

```python
{
    "name": str,        # Name of the function to call
    "arguments": str    # Function call arguments in JSON format
}
```

**Annotation** (URL citation):

```python
{
    "type": "url_citation",
    "url_citation": {
        "start_index": int,  # Citation start position
        "end_index": int,    # Citation end position
        "title": str,        # Web resource title
        "url": str          # Web resource URL
    }
}
```

---

## 2. OpenAI Responses API Response Structure

**Return type**: [`Response`](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response.py)
**Design philosophy**: Highly modular response system supporting complex interaction patterns

### 2.1 Top-Level Response Fields (20+ fields)

| Field Name           | Type                                        | Required | Description                                                         |
| -------------------- | ------------------------------------------- | -------- | ------------------------------------------------------------------- |
| `id`                 | `str`                                       | ✅        | Unique identifier for this response                                 |
| `object`             | `Literal["response"]`                       | ✅        | Object type of the resource, always set to "response"               |
| `created_at`         | `float`                                     | ✅        | Unix timestamp (seconds) when this response was created             |
| `model`              | `ResponsesModel`                            | ✅        | Model ID used to generate the response                              |
| `output`             | `List[ResponseOutputItem]`                  | ✅        | **Core list of output content items**                               |
| `status`             | `ResponseStatus`                            | ✅        | Status of the response                                              |
| `usage`              | `Optional[ResponseUsage]`                   | -        | Token usage details                                                 |
| `instructions`       | `Union[str, List[ResponseInputItem], None]` | -        | System message                                                      |
| `metadata`           | `Optional[Metadata]`                        | -        | Set of 16 key-value pairs                                           |
| `error`              | `Optional[ResponseError]`                   | -        | Error object                                                        |
| `incomplete_details` | `Optional[IncompleteDetails]`               | -        | Incomplete reason details                                           |
| `conversation`       | `Optional[Conversation]`                    | -        | The conversation this belongs to                                    |
| `prompt`             | `Optional[ResponsePrompt]`                  | -        | The prompt used                                                     |
| `reasoning`          | `Optional[Reasoning]`                       | -        | Reasoning configuration and output                                  |
| `text`               | `Optional[ResponseTextConfig]`              | -        | Text configuration                                                  |
| `tools`              | `Optional[List[Tool]]`                      | -        | List of available tools                                             |
| `tool_choice`        | `Optional[ToolChoice]`                      | -        | Tool choice configuration                                           |
| `top_logprobs`       | `Optional[int]`                             | -        | Number of most likely tokens to return                              |
| `truncation`         | `Optional[Literal["auto", "disabled"]]`     | -        | Truncation strategy                                                 |
| `user`               | `Optional[str]`                             | -        | User identifier                                                     |

### 2.2 ResponseOutputItem Output Content Structure (18 types)

This is the core innovation of OpenAI Responses - a highly modular output item system:

#### Core Output Types (3 types)

- `ResponseOutputMessage` - **Assistant message output**
- `ResponseReasoningItem` - **Reasoning process item**
- `ResponseCompactionItem` - **Compaction item**

#### Tool Call Types (9 types)

- `ResponseFileSearchToolCall` - File search tool call
- `ResponseFunctionToolCall` - Function tool call
- `ResponseFunctionWebSearch` - Web search function
- `ResponseComputerToolCall` - Computer tool call
- `ResponseCodeInterpreterToolCall` - Code interpreter tool call
- `ResponseFunctionShellToolCall` - Shell function tool call
- `ResponseApplyPatchToolCall` - Patch application tool call
- `ResponseCustomToolCall` - Custom tool call
- `LocalShellCall` - Local shell call

#### Tool Output Types (2 types)

- `ResponseFunctionShellToolCallOutput` - Shell function tool call output
- `ResponseApplyPatchToolCallOutput` - Patch application tool call output

#### Special Feature Types (4 types)

- `ImageGenerationCall` - Image generation call
- `McpCall` - MCP call
- `McpListTools` - MCP tool list
- `McpApprovalRequest` - MCP approval request

### 2.3 ResponseOutputMessage Message Structure (4 fields)

The core message type in OpenAI Responses:

| Field Name | Type                                                | Required | Description                        |
| ---------- | --------------------------------------------------- | -------- | ---------------------------------- |
| `id`       | `str`                                               | ✅        | Unique ID of the output message    |
| `role`     | `Literal["assistant"]`                              | ✅        | Message role, always "assistant"   |
| `content`  | `List[Content]`                                     | ✅        | **List of message content**        |
| `status`   | `Literal["in_progress", "completed", "incomplete"]` | ✅        | Message status                     |

#### Content Types (2 types)

- `ResponseOutputText` - **Text output**
- `ResponseOutputRefusal` - **Refusal output**

**ResponseOutputText** contains detailed information such as text content, annotations, and log probabilities, supporting multiple annotation types including file references and URL citations.

### 2.4 Key Tool Call Type Detailed Structures

#### ResponseFunctionToolCall (6 fields)

| Field Name  | Type                                                          | Required | Description                                                  |
| ----------- | ------------------------------------------------------------- | -------- | ------------------------------------------------------------ |
| `type`      | `Literal["function_call"]`                                    | ✅        | Type identifier, always "function_call"                      |
| `call_id`   | `str`                                                         | ✅        | **Unique tool call ID** - unique identifier generated by the model |
| `name`      | `str`                                                         | ✅        | **Function name** - name of the function to call             |
| `arguments` | `str`                                                         | ✅        | **Function arguments** - arguments in JSON string format     |
| `id`        | `Optional[str]`                                               | -        | Unique ID of the tool call (platform level)                  |
| `status`    | `Optional[Literal["in_progress", "completed", "incomplete"]]` | -        | **Execution status**                                         |

#### ResponseCustomToolCall (4 fields)

| Field Name | Type                          | Required | Description                                                |
| ---------- | ----------------------------- | -------- | ---------------------------------------------------------- |
| `type`     | `Literal["custom_tool_call"]` | ✅        | Type identifier, always "custom_tool_call"                 |
| `call_id`  | `str`                         | ✅        | **Custom tool call ID** - used to map to tool output       |
| `name`     | `str`                         | ✅        | **Custom tool name**                                       |
| `input`    | `str`                         | ✅        | **Tool input** - input data generated by the model         |
| `id`       | `Optional[str]`               | -        | Unique ID in the OpenAI platform                           |

#### McpCall (9 fields)

| Field Name            | Type                                                                               | Required | Description                                                  |
| --------------------- | ---------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------ |
| `type`                | `Literal["mcp_call"]`                                                              | ✅        | Type identifier, always "mcp_call"                           |
| `id`                  | `str`                                                                              | ✅        | **Unique tool call ID**                                      |
| `name`                | `str`                                                                              | ✅        | **Name of the tool being run**                               |
| `server_label`        | `str`                                                                              | ✅        | **MCP server label**                                         |
| `arguments`           | `str`                                                                              | ✅        | **Tool arguments** - JSON string format                      |
| `approval_request_id` | `Optional[str]`                                                                    | -        | **Approval request ID** - for subsequent approve/deny        |
| `output`              | `Optional[str]`                                                                    | -        | **Tool output**                                              |
| `error`               | `Optional[str]`                                                                    | -        | **Error information**                                        |
| `status`              | `Optional[Literal["in_progress", "completed", "incomplete", "calling", "failed"]]` | -        | **Execution status**                                         |

#### ResponseReasoningItem (6 fields)

| Field Name          | Type                                                          | Required | Description                             |
| ------------------- | ------------------------------------------------------------- | -------- | --------------------------------------- |
| `type`              | `Literal["reasoning"]`                                        | ✅        | Type identifier, always "reasoning"     |
| `id`                | `str`                                                         | ✅        | **Unique identifier for reasoning content** |
| `summary`           | `List[Summary]`                                               | ✅        | **Reasoning summary content**           |
| `content`           | `Optional[List[Content]]`                                     | -        | **Reasoning text content**              |
| `encrypted_content` | `Optional[str]`                                               | -        | **Encrypted reasoning content**         |
| `status`            | `Optional[Literal["in_progress", "completed", "incomplete"]]` | -        | **Reasoning status**                    |

**Summary substructure**:

```python
{
    "type": "summary_text",
    "text": str  # Reasoning output summary
}
```

**Content substructure**:

```python
{
    "type": "reasoning_text",
    "text": str  # Reasoning text
}
```

### 2.5 Server-Side Tool Types

#### ResponseFunctionWebSearch (4 fields)

| Field Name | Type                                                         | Required | Description                                                      |
| ---------- | ------------------------------------------------------------ | -------- | ---------------------------------------------------------------- |
| `type`     | `Literal["web_search_call"]`                                 | ✅        | Type identifier, always "web_search_call"                        |
| `id`       | `str`                                                        | ✅        | **Unique web search tool call ID**                               |
| `action`   | `Action`                                                     | ✅        | **Search action details** - contains the specific search behavior |
| `status`   | `Literal["in_progress", "searching", "completed", "failed"]` | ✅        | **Search status**                                                |

**Action union type** (3 types):

- `ActionSearch` - Execute a web search query
- `ActionOpenPage` - Open a specific URL from search results
- `ActionFind` - Search for a pattern in the loaded page

#### ResponseCodeInterpreterToolCall (6 fields)

| Field Name     | Type                                                                          | Required | Description                                                   |
| -------------- | ----------------------------------------------------------------------------- | -------- | ------------------------------------------------------------- |
| `type`         | `Literal["code_interpreter_call"]`                                            | ✅        | Type identifier, always "code_interpreter_call"               |
| `id`           | `str`                                                                         | ✅        | **Unique code interpreter tool call ID**                      |
| `container_id` | `str`                                                                         | ✅        | **Container ID where the code runs**                          |
| `code`         | `Optional[str]`                                                               | -        | **Code to run**                                               |
| `outputs`      | `Optional[List[Output]]`                                                      | -        | **Code execution output** - logs or images                    |
| `status`       | `Literal["in_progress", "completed", "incomplete", "interpreting", "failed"]` | ✅        | **Execution status**                                          |

**Output union type** (2 types):

- `OutputLogs` - Code execution logs
- `OutputImage` - Image generated by code

---

## 3. Anthropic Messages Response Structure

**Return type**: [`Message`](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/message.py)
**Design philosophy**: Clean and elegant content block architecture, balancing functionality and ease of use

### 3.1 Top-Level Response Fields (8 fields)

| Field Name      | Type                   | Required | Description                                                         |
| --------------- | ---------------------- | -------- | ------------------------------------------------------------------- |
| `id`            | `str`                  | ✅        | Unique object identifier                                            |
| `type`          | `Literal["message"]`   | ✅        | Object type, always "message"                                       |
| `role`          | `Literal["assistant"]` | ✅        | Conversational role of the generated message, always "assistant"    |
| `content`       | `List[ContentBlock]`   | ✅        | **Core content** - array of model-generated content blocks          |
| `model`         | `Model`                | ✅        | Model that completed the prompt                                     |
| `usage`         | `Usage`                | ✅        | Billing and rate-limiting usage                                     |
| `stop_reason`   | `Optional[StopReason]` | -        | Stop reason                                                         |
| `stop_sequence` | `Optional[str]`        | -        | Custom stop sequence generated                                      |

### 3.2 ContentBlock Content Structure (6 types)

Anthropic's core innovation - unified content block architecture:

#### Basic Content Blocks

- `TextBlock` - **Text content block**
- `ThinkingBlock` - **Thinking process block**
- `RedactedThinkingBlock` - **Redacted thinking block**

#### Tool-Related Blocks

- `ToolUseBlock` - **Tool use block**
- `ServerToolUseBlock` - **Server tool use block**
- `WebSearchToolResultBlock` - **Web search tool result block**

### 3.3 Detailed Content Block Structures

#### TextBlock (3 fields)

| Field Name  | Type                           | Required | Description                                                          |
| ----------- | ------------------------------ | -------- | -------------------------------------------------------------------- |
| `type`      | `Literal["text"]`              | ✅        | Content block type, always "text"                                    |
| `text`      | `str`                          | ✅        | **Text content**                                                     |
| `citations` | `Optional[List[TextCitation]]` | -        | **Citation support** - returns different citation formats by document type |

#### ToolUseBlock (4 fields)

| Field Name | Type                  | Required | Description                                |
| ---------- | --------------------- | -------- | ------------------------------------------ |
| `type`     | `Literal["tool_use"]` | ✅        | Content block type, always "tool_use"      |
| `id`       | `str`                 | ✅        | **Unique tool use identifier**             |
| `name`     | `str`                 | ✅        | **Tool name**                              |
| `input`    | `Dict[str, object]`   | ✅        | **Tool input parameters**                  |

#### ThinkingBlock

Used for the thinking process of reasoning models, containing the model's internal reasoning steps, typically not displayed to the end user.

#### WebSearchToolResultBlock (3 fields)

| Field Name    | Type                                | Required | Description                                             |
| ------------- | ----------------------------------- | -------- | ------------------------------------------------------- |
| `type`        | `Literal["web_search_tool_result"]` | ✅        | Content block type, always "web_search_tool_result"     |
| `tool_use_id` | `str`                               | ✅        | **Associated tool use ID**                              |
| `content`     | `WebSearchToolResultBlockContent`   | ✅        | **Search result content**                               |

Contains the execution results of the web search tool, an Anthropic-specific server-side tool feature.

#### ServerToolUseBlock

Anthropic's server-side tool use block, used for internal tool calls such as web_search.

---

## 4. Google GenerativeAI Response Structure

**Return type**: [`GenerateContentResponse`](https://github.com/google/generative-ai-python/blob/main/google/generativeai/types/generation_types.py)
**Design philosophy**: Multimodal-first Parts composition architecture, natively supporting multiple content types

### 4.1 Top-Level Response Fields (8 fields)

| Field Name                           | Type                                              | Required | Description                                       |
| ------------------------------------ | ------------------------------------------------- | -------- | ------------------------------------------------- |
| `candidates`                         | `Optional[List[Candidate]]`                       | -        | **Core content** - response variants returned by the model |
| `prompt_feedback`                    | `Optional[GenerateContentResponsePromptFeedback]` | -        | Content filtering results for the prompt          |
| `usage_metadata`                     | `Optional[GenerateContentResponseUsageMetadata]`  | -        | Usage metadata for the response                   |
| `create_time`                        | `Optional[datetime.datetime]`                     | -        | Request timestamp                                 |
| `model_version`                      | `Optional[str]`                                   | -        | Model version that generated the response         |
| `response_id`                        | `Optional[str]`                                   | -        | Response identifier                               |
| `sdk_http_response`                  | `Optional[HttpResponse]`                          | -        | Full HTTP response                                |
| `automatic_function_calling_history` | `Optional[List[Content]]`                         | -        | Automatic function calling history                |
| `parsed`                             | `Optional[Union[pydantic.BaseModel, dict, Enum]]` | -        | Parsed structured response                        |

### 4.2 Candidate Structure (7 fields)

Google's core response container:

| Field Name               | Type                                   | Required | Description                      |
| ------------------------ | -------------------------------------- | -------- | -------------------------------- |
| `content`                | `Optional[Content]`                    | -        | **Candidate content parts**      |
| `finish_reason`          | `Optional[FinishReason]`               | -        | Reason the model stopped generating |
| `safety_ratings`         | `Optional[List[SafetyRating]]`         | -        | List of safety ratings for the candidate |
| `citation_metadata`      | `Optional[CitationMetadata]`           | -        | **Citation metadata**            |
| `token_count`            | `Optional[int]`                        | -        | Number of tokens in the candidate |
| `grounding_attributions` | `Optional[List[GroundingAttribution]]` | -        | **Grounding attribution information** |
| `index`                  | `Optional[int]`                        | -        | Index of the candidate in the list |

### 4.3 Content Structure

Google's multimodal content organization approach:

#### Content Fields

- `parts` - **List of content parts**, can include text, images, function calls, etc.
- `role` - Role of the content ("user" or "model")

#### Detailed Parts Type Structure

Google's Parts system supports rich content types, based on the Part base class:

#### Part Base Structure

Part is a base class containing multiple optional fields; each Part instance should set only one field:

| Field Name              | Type                            | Description                                        |
| ----------------------- | ------------------------------- | -------------------------------------------------- |
| `text`                  | `Optional[str]`                 | **Text content**                                   |
| `inline_data`           | `Optional[Blob]`                | **Inline data** - e.g., base64-encoded images      |
| `file_data`             | `Optional[FileData]`            | **File data** - URI-referenced files               |
| `function_call`         | `Optional[FunctionCall]`        | **Function call**                                  |
| `function_response`     | `Optional[FunctionResponse]`    | **Function response**                              |
| `executable_code`       | `Optional[ExecutableCode]`      | **Executable code**                                |
| `code_execution_result` | `Optional[CodeExecutionResult]` | **Code execution result**                          |
| `media_resolution`      | `Optional[PartMediaResolution]` | **Media resolution settings**                      |

#### Key Parts Types

**TextPart** (via text field):

```python
{
    "text": str  # Plain text content
}
```

**FunctionCallPart** (via function_call field):

```python
{
    "function_call": {
        "name": str,           # Function name
        "args": Dict[str, Any] # Function arguments
    }
}
```

**FunctionResponsePart** (via function_response field):

```python
{
    "function_response": {
        "name": str,                    # Function name
        "response": Dict[str, Any]      # Function response data
    }
}
```

**ExecutableCodePart** (via executable_code field):

```python
{
    "executable_code": {
        "language": str,  # Programming language
        "code": str       # Code content
    }
}
```

**CodeExecutionResultPart** (via code_execution_result field):

```python
{
    "code_execution_result": {
        "outcome": str,     # Execution result status
        "output": str       # Execution output
    }
}
```

### 4.4 Detailed Usage Statistics Structure (11 fields)

Google provides the most detailed usage statistics:

| Field Name                       | Type                                 | Description                                            |
| -------------------------------- | ------------------------------------ | ------------------------------------------------------ |
| `prompt_token_count`             | `Optional[int]`                      | Total tokens in the prompt                             |
| `candidates_token_count`         | `Optional[int]`                      | Total tokens in the generated candidates               |
| `total_token_count`              | `Optional[int]`                      | Total tokens for the entire request                    |
| `cached_content_token_count`     | `Optional[int]`                      | Tokens in cached content                               |
| `thoughts_token_count`           | `Optional[int]`                      | Tokens in the model's "thinking" output                |
| `tool_use_prompt_token_count`    | `Optional[int]`                      | Tokens in tool execution results                       |
| `prompt_tokens_details`          | `Optional[List[ModalityTokenCount]]` | Token count per modality in the prompt                 |
| `candidates_tokens_details`      | `Optional[List[ModalityTokenCount]]` | Token count per modality in the candidates             |
| `cache_tokens_details`           | `Optional[List[ModalityTokenCount]]` | Token count per modality in cached content             |
| `tool_use_prompt_tokens_details` | `Optional[List[ModalityTokenCount]]` | Token count per modality in tool results               |
| `traffic_type`                   | `Optional[TrafficType]`              | Traffic type for this request                          |

---

## Cross-SDK Commonality Analysis

### Strong Consistency of Core Response Patterns

All four SDKs follow the same core response patterns:

#### 1. Text Content Output ✅

- **OpenAI Chat**: `ChatCompletionMessage.content` (string)
- **OpenAI Responses**: `ResponseOutputMessage` → `ResponseOutputText.text`
- **Anthropic**: `ContentBlock` → `TextBlock.text`
- **Google**: `Candidate.content.parts` → `TextPart.text`

#### 2. Tool Call Support ✅

- **OpenAI Chat**: `ChatCompletionMessage.tool_calls[]`
- **OpenAI Responses**: 9 specialized tool call types
- **Anthropic**: `ContentBlock` → `ToolUseBlock`
- **Google**: `Candidate.content.parts` → `FunctionCallPart`

#### 3. Refusal / Safety Filtering ✅

- **OpenAI Chat**: `ChatCompletionMessage.refusal`
- **OpenAI Responses**: `ResponseOutputRefusal`
- **Anthropic**: `stop_reason: "refusal"`
- **Google**: `safety_ratings` + `finish_reason`

#### 4. Citation / Annotation System ✅

- **OpenAI Chat**: `ChatCompletionMessage.annotations`
- **OpenAI Responses**: `ResponseOutputText` supports multiple annotations
- **Anthropic**: `TextBlock.citations`
- **Google**: `CitationMetadata` + `GroundingAttribution`

#### 5. Usage Statistics ✅

- **OpenAI Chat**: `usage` (CompletionUsage)
- **OpenAI Responses**: `usage` (ResponseUsage)
- **Anthropic**: `usage` (Usage)
- **Google**: `usage_metadata` (most detailed statistics)

#### 6. Stop Reason Description ✅

- **OpenAI Chat**: `choices[].finish_reason`
- **OpenAI Responses**: `status`
- **Anthropic**: `stop_reason`
- **Google**: `candidates[].finish_reason`

### Unified Structural Pattern

#### Container-Content Two-Level Structure

All SDKs adopt a container-content two-level structure:

- **OpenAI Chat**: `choices[]` → `message`
- **OpenAI Responses**: `output[]` → various OutputItems
- **Anthropic**: `content[]` → various ContentBlocks
- **Google**: `candidates[]` → `content.parts[]`

#### Typed Content Design

All SDKs use union types or polymorphic design:

- **OpenAI Chat**: Distinguished by field (content, tool_calls, refusal, etc.)
- **OpenAI Responses**: 18 different OutputItem types
- **Anthropic**: 6 ContentBlock types
- **Google**: 7+ Parts types

### Design Philosophy Comparison

| SDK                   | Design Complexity | Feature Richness | Multimodal Support | Tool Ecosystem | Design Philosophy        |
| --------------------- | ----------------- | ---------------- | ------------------ | -------------- | ------------------------ |
| **OpenAI Chat**       | ⭐⭐              | ⭐⭐⭐            | ⭐⭐               | ⭐⭐⭐          | Simple and practical     |
| **OpenAI Responses**  | ⭐⭐⭐⭐⭐         | ⭐⭐⭐⭐⭐         | ⭐⭐⭐              | ⭐⭐⭐⭐⭐       | Extremely modular        |
| **Anthropic**         | ⭐⭐⭐             | ⭐⭐⭐⭐          | ⭐⭐               | ⭐⭐⭐          | Elegant and concise      |
| **Google**            | ⭐⭐⭐⭐           | ⭐⭐⭐⭐          | ⭐⭐⭐⭐⭐           | ⭐⭐⭐          | Multimodal-first         |

## Key Findings and Body-Level Translation Feasibility

### 1. High Functional Consistency

The four SDKs exhibit remarkable consistency in core functionality:

- ✅ All SDKs support text, tool calls, refusals, citations, usage statistics, and stop reasons
- ✅ All SDKs adopt a container-content two-level structure
- ✅ All SDKs use typed content design

### 2. Body-Level Translation Is Fully Feasible

Due to the strong consistency, body-level translation of responses is fully feasible:

#### Core Mapping Strategy

1. **Text content** → Direct mapping to each SDK's text field
2. **Tool calls** → Standardized tool call format (id, name, input)
3. **Status information** → Unified stop reason and completion status
4. **Metadata** → Standardized usage statistics and timestamps
5. **Citation system** → Unified citation and annotation format

#### Translation Complexity Assessment

- **Anthropic ↔ Others**: ⭐ Simple (direct mapping)
- **OpenAI Chat ↔ Others**: ⭐⭐ Moderate (requires structural adjustment)
- **OpenAI Responses ↔ Others**: ⭐⭐⭐ Complex (requires type merging/splitting)
- **Google ↔ Others**: ⭐⭐ Moderate (requires Parts conversion)

### 3. Unified IRResponse Design Guiding Principles

Based on this analysis, the unified response IR should:

1. **Contain the common features of all four SDKs** - text, tools, refusals, citations, statistics
2. **Adopt a container-content two-level structure** - extensible and type-safe
3. **Support progressive feature mapping** - from basic to advanced features
4. **Maintain backward compatibility** - support each SDK's unique features

### 4. Implementation Priority Recommendations

**Phase 1: Core Features**

- Text content translation
- Basic tool call translation
- Usage statistics mapping
- Stop reason standardization

**Phase 2: Advanced Features**

- Citation and annotation system
- Multimodal content support
- Complex tool type translation
- Streaming response support

## Key Type Compatibility Analysis

### 1. Unified Mapping of Tool Call Types

Based on the detailed structural analysis, we found clear mapping relationships for tool calls across the four SDKs:

#### Core Tool Call Field Mapping

| Feature         | OpenAI Chat                       | OpenAI Responses          | Anthropic                   | Google                         |
| --------------- | --------------------------------- | ------------------------- | --------------------------- | ------------------------------ |
| **Tool ID**     | `tool_calls[].id`                 | `call_id`                 | `ToolUseBlock.id`           | Associated via name            |
| **Tool Name**   | `tool_calls[].function.name`      | `name`                    | `ToolUseBlock.name`         | `function_call.name`           |
| **Tool Args**   | `tool_calls[].function.arguments` | `arguments` (JSON string) | `ToolUseBlock.input` (Dict) | `function_call.args` (Dict)    |
| **Exec Status** | -                                 | `status`                  | -                           | -                              |

#### Advanced Tool Type Compatibility

- **MCP tools**: OpenAI Responses has native support; other SDKs can be compatible via custom tools
- **Server-side tools**: Anthropic's WebSearch, OpenAI's WebSearch/CodeInterpreter, Google's CodeExecution
- **Custom tools**: OpenAI Responses' CustomToolCall, mappable to other SDKs' generic tool calls

### 2. Reasoning Content Cross-SDK Support

#### Reasoning Content Mapping Strategy

| SDK                   | Reasoning Support | Implementation                     | Compatibility         |
| --------------------- | ----------------- | ---------------------------------- | --------------------- |
| **OpenAI Responses**  | ✅ Native         | `ResponseReasoningItem`            | Full support          |
| **Anthropic**         | ✅ Native         | `ThinkingBlock`                    | Full support          |
| **Google**            | ✅ Native         | `ExecutableCodePart` (thinking process) | Partial support   |
| **OpenAI Chat**       | ⚠️ Third-party    | `reasoning_content` field extension | Extensible support   |

### 3. Unified Abstraction for Server-Side Tools

#### CustomServerSideToolResponse Design Proposal

Based on the server-side tool analysis of each SDK, we can design a unified server-side tool response:

```python
class CustomServerSideToolResponse:
    type: Literal["server_side_tool"]
    tool_type: Literal["web_search", "code_execution", "file_search", "image_generation"]
    tool_id: str
    tool_name: str
    status: Literal["in_progress", "completed", "failed", "searching", "interpreting"]

    # Common output fields
    output: Optional[str]
    error: Optional[str]

    # Tool-type-specific details
    web_search_details: Optional[WebSearchDetails]
    code_execution_details: Optional[CodeExecutionDetails]
    file_search_details: Optional[FileSearchDetails]
    image_generation_details: Optional[ImageGenerationDetails]
```

#### Cross-SDK Server-Side Tool Mapping

| Tool Type          | OpenAI Responses                  | Anthropic                  | Google                | Unified Mapping             |
| ------------------ | --------------------------------- | -------------------------- | --------------------- | --------------------------- |
| **Web Search**     | `ResponseFunctionWebSearch`       | `WebSearchToolResultBlock` | -                     | `web_search_details`        |
| **Code Execution** | `ResponseCodeInterpreterToolCall` | -                          | `CodeExecutionResult` | `code_execution_details`    |
| **File Search**    | `ResponseFileSearchToolCall`      | -                          | `FileDataPart`        | `file_search_details`       |
| **Image Gen**      | `ImageGenerationCall`             | -                          | -                     | `image_generation_details`  |

### 4. Implementation Priority and Compatibility Strategy

#### Phase 1: Core Compatibility (Must implement)

1. **Basic tool call translation** - support function_call translation across the four SDKs
2. **Text content translation** - unified text response format
3. **Status information mapping** - standardization of finish_reason, stop_reason, etc.

#### Phase 2: Advanced Feature Compatibility (Should implement)

1. **Reasoning content support** - ResponseReasoningItem ↔ ThinkingBlock translation
2. **MCP tool compatibility** - OpenAI MCP ↔ other SDK custom tools
3. **Citation system unification** - annotations, citations, grounding_attributions

#### Phase 3: Server-Side Tool Compatibility (Can implement)

1. **CustomServerSideToolResponse** - unified server-side tool abstraction
2. **Cross-SDK server tool mapping** - web_search, code_execution, etc.
3. **Tool status synchronization** - unified tool execution state management

**Conclusion**: Through detailed structural analysis, we have confirmed the high degree of consistency in core functionality across the four SDKs and identified the key compatibility points. Critical types such as ResponseFunctionToolCall, ResponseCustomToolCall, McpCall, and ResponseReasoningItem provide clear translation paths. Based on this analysis, we can design a fully-featured IRResponse supporting comprehensive translation from basic tool calls to advanced reasoning content, providing a solid technical foundation for body-level response translation.
