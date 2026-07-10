# MCP Support Comparison Across Three Providers

This document compares the MCP support in OpenAI, Anthropic, and Google for the Model Context Protocol (MCP) in detail.

## Overview

**Key finding**: all three providers already support MCP, but they implement it in different ways, reflecting different design philosophies.

## MCP Implementation in the OpenAI Responses API

### The most complete native support

The OpenAI Responses API provides the **most complete MCP support**, including four MCP-related types:

#### 1. McpCall - MCP tool call

```python
class McpCall(TypedDict, total=False):
    type: Required[Literal["mcp_call"]]
    id: Required[str]
    name: Required[str]
    server_label: Required[str]  # MCP server label
    arguments: Required[str]
    approval_request_id: Optional[str]  # approval request ID
    output: Optional[str]  # tool output
    error: Optional[str]  # error details
    status: Literal["in_progress", "completed", "incomplete", "calling", "failed"]
```

#### 2. McpListTools - list available tools

```python
class McpListTools(TypedDict, total=False):
    type: Required[Literal["mcp_list_tools"]]
    id: Required[str]
    server_label: Required[str]
    output: Optional[str]  # tool list JSON
    error: Optional[str]
    status: Literal["in_progress", "completed", "incomplete", "calling", "failed"]
```

#### 3. McpApprovalRequest - approval request

```python
class McpApprovalRequest(TypedDict, total=False):
    type: Required[Literal["mcp_approval_request"]]
    id: Required[str]
    call: Required[McpCall]  # call requiring approval
    status: Literal["in_progress", "completed", "incomplete"]
```

#### 4. McpApprovalResponse - approval response

```python
class McpApprovalResponse(TypedDict, total=False):
    type: Required[Literal["mcp_approval_response"]]
    id: Required[str]
    approval_request_id: Required[str]
    approved: Required[bool]  # whether approved
    status: Literal["in_progress", "completed", "incomplete"]
```

### Complete workflow

```python
# 1. List available tools
{
    "type": "mcp_list_tools",
    "id": "list_123",
    "server_label": "calculator-server",
    "status": "calling"
}

# 2. Call tool
{
    "type": "mcp_call",
    "id": "call_456",
    "server_label": "calculator-server",
    "name": "calc_evaluate",
    "arguments": '{"expression": "26 * 9 / 5 + 32"}',
    "status": "calling"
}

# 3. Approval request (if needed)
{
    "type": "mcp_approval_request",
    "id": "approval_789",
    "call": {...},
    "status": "in_progress"
}

# 4. Approval response
{
    "type": "mcp_approval_response",
    "id": "response_012",
    "approval_request_id": "approval_789",
    "approved": true,
    "status": "completed"
}

# 5. Tool call result
{
    "type": "mcp_call",
    "id": "call_456",
    "output": "78.8",
    "status": "completed"
}
```

### Key features

- **MCP tools are first-class citizens**: there is a dedicated type system
- **Complete approval flow**: supports requests and responses
- **Tool discovery**: supports listing available tools
- **Independent state tracking**: each operation has detailed status
- **Error handling**: built-in error fields
- **Output management**: both tool calls and tool lists have output fields

## Anthropic's MCP Implementation

### Implemented through content blocks

Anthropic integrates MCP tools into its content block architecture, keeping the design consistent.

#### 1. MCPToolUseBlockParam - MCP tool call

```python
class MCPToolUseBlockParam(TypedDict, total=False):
    type: Required[Literal["mcp_tool_use"]]
    id: Required[str]
    server_name: Required[str]  # note: named server_name rather than server_label
    name: Required[str]
    input: Required[Dict[str, object]]
    cache_control: Optional[CacheControlEphemeralParam]
```

#### 2. MCPToolResultBlockParam - MCP tool result

```python
class MCPToolResultBlock(BaseModel):
    type: Literal["mcp_tool_result"]
    tool_use_id: str
    content: Union[str, List[TextBlock]]
    is_error: bool
```

### Usage example

```python
# Configure the MCP server in the API request
mcp_servers = [
    {
        "name": "calculator-server",
        "type": "url",
        "url": "https://calculator-mcp-server.example.com",
        "authorization_token": "auth_token_123",
        "tool_configuration": {
            "allowed_tools": ["calc_evaluate", "calc_help"],
            "enabled": True
        }
    }
]

# Assistant initiates an MCP tool call
{
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": "Let me calculate that for you."
        },
        {
            "type": "mcp_tool_use",
            "id": "mcptool_456",
            "server_name": "calculator-server",
            "name": "calc_evaluate",
            "input": {"expression": "26 * 9 / 5 + 32"}
        }
    ]
}

# MCP tool result (handled automatically by the system)
{
    "type": "mcp_tool_result",
    "tool_use_id": "mcptool_456",
    "content": "78.8",
    "is_error": False
}
```

### Configuration

Configure it through the API request's `mcp_servers` parameter:

```python
class RequestMCPServerURLDefinitionParam(TypedDict, total=False):
    name: Required[str]
    type: Required[Literal["url"]]
    url: Required[str]
    authorization_token: Optional[str]
    tool_configuration: Optional[RequestMCPServerToolConfigurationParam]
```

### Key features

- **Content block architecture**: MCP tools follow the content block design
- **Automatic system handling**: tool results are handled by the system automatically and do not need to be provided by the user
- **Tool configuration**: supports tool allowlists and enable/disable controls
- **Caching support**: MCP tool calls support cache control
- **Uses `server_name`**: instead of OpenAI's `server_label`

### Key differences

- No explicit approval flow
- No tool listing feature
- Tool results are handled automatically

## Google's MCP Implementation

### Implemented through an adapter pattern

Google takes a completely different approach, using an adapter to convert MCP tools into Gemini-native tools.

#### Adapter architecture

```python
class McpToGenAiToolAdapter:
    """Converts MCP tools into Gemini-usable tools."""

    def __init__(
        self,
        session: "mcp.ClientSession",
        list_tools_result: "mcp_types.ListToolsResult",
    ) -> None:
        self._mcp_session = session
        self._list_tools_result = list_tools_result

    async def call_tool(
        self, function_call: FunctionCall
    ) -> "mcp_types.CallToolResult":
        """Call a function on the MCP server."""
        name = function_call.name if function_call.name else ""
        arguments = dict(function_call.args) if function_call.args else {}

        return await self._mcp_session.call_tool(
            name=name,
            arguments=arguments,
        )

    @property
    def tools(self) -> list[Tool]:
        """Return the Google GenAI tool list."""
        return mcp_to_gemini_tools(self._list_tools_result.tools)
```

#### Tool conversion

```python
def mcp_to_gemini_tool(tool: McpTool) -> types.Tool:
    """Convert an MCP tool into a Google GenAI tool."""
    return types.Tool(
        function_declarations=[{
            "name": tool.name,
            "description": tool.description,
            "parameters": types.Schema.from_json_schema(
                json_schema=types.JSONSchema(
                    **_filter_to_supported_schema(tool.inputSchema)
                )
            ),
        }]
    )

def mcp_to_gemini_tools(tools: list[McpTool]) -> list[types.Tool]:
    """Convert an MCP tool list into a Google GenAI tool list."""
    return [mcp_to_gemini_tool(tool) for tool in tools]
```

### Usage example

```python
import asyncio
from datetime import datetime
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google import genai

client = genai.Client()

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@philschmid/weather-mcp"],
    env=None,
)

async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection between the client and server
            await session.initialize()

            # Send a request with MCP function declarations to the model
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents="What is the weather in London?",
                config=genai.types.GenerateContentConfig(
                    temperature=0,
                    tools=[session],  # pass the session through directly
                ),
            )
            print(response.text)

asyncio.run(run())
```

### Internal behavior

1. **Tool conversion**: MCP tools are converted to Gemini's `FunctionDeclaration`
2. **Automatic function calling**: by default, the SDK handles function calling automatically
3. **Session management**: the SDK manages the MCP session lifecycle
4. **Error handling**: the SDK provides error handling mechanisms

### Key features

- **Transparent conversion**: MCP tools are converted into ordinary `function_call`s
- **Automatic calling**: tool calls are handled automatically by default
- **Session management**: the SDK manages the MCP session lifecycle
- **Asynchronous operations**: a fully async API
- **No special types**: there are no MCP-specific types at the message layer

## MCP Implementation Comparison Summary

| Feature        | OpenAI Responses | Anthropic | Google |
| -------------- | ----------------- | --------- | ------ |
| **Approach**   | Dedicated types   | Content blocks | Adapter conversion |
| **Server ID**  | `server_label`    | `server_name` | Session object |
| **Tool list**  | ✓ `McpListTools`  | ✗         | ✓ via session |
| **Approval**   | ✓ explicit support | ✗        | ✗      |
| **Tool result** | In `McpCall`     | Separate content block | Converted to `function_response` |
| **Configuration** | Input items     | API parameters | Session object |
| **State tracking** | ✓ detailed state | ✗        | ✗      |
| **Error handling** | ✓ built-in fields | ✓ `is_error` | ✓ SDK handling |
| **Auto-calling** | Optional         | Automatic | Automatic by default |
| **Type visibility** | High (dedicated types) | Medium (content blocks) | Low (transparent conversion) |
| **Caching support** | ✗              | ✓         | ✗      |
| **Async requirement** | ✗            | ✗         | ✓ required |

## Key Insights

### 1. OpenAI is the most explicit

- MCP is a first-class citizen with a complete type system
- Supports the full workflow (discovery, calling, approval)
- Suitable for scenarios that need fine-grained control
- Has the most detailed state tracking

### 2. Anthropic is the most consistent

- MCP tools follow the content block architecture
- Keeps consistency with ordinary tool calls
- Results are handled automatically by the system
- Supports caching control

### 3. Google is the most transparent

- MCP tools are converted into ordinary tools
- Users do not need to care about MCP details
- Suitable for simple integration scenarios
- Fully asynchronous API

## Implications for IR Design

### Option A: Follow OpenAI - explicit types

```python
IRInputItem = Union[
    IRMessage,
    IRToolCall,
    IRToolResult,
    IRMcpCall,              # dedicated MCP call type
    IRMcpListTools,         # MCP tool list
    IRMcpApprovalRequest,   # approval request
    IRMcpApprovalResponse,  # approval response
]
```

**Pros**:

- Full MCP workflow support
- Fine-grained control
- Consistent with the OpenAI Responses API

**Cons**:

- More types, higher complexity
- Inconsistent with Anthropic/Google

### Option B: Follow Anthropic - unified content blocks

```python
ContentPart = Union[
    TextPart,
    ToolUsePart,
    ToolResultPart,
    McpToolUsePart,      # MCP tool call (content block)
    McpToolResultPart,   # MCP tool result (content block)
]
```

**Pros**:

- Consistent with ordinary tools
- Simple structure
- Consistent with Anthropic

**Cons**:

- Lacks approval flow
- Lacks tool listing functionality

### Option C: Follow Google - transparent conversion

```python
# MCP tools are converted into ordinary tool calls
ToolCall = {
    "type": "tool_call",
    "tool_name": "calc_evaluate",
    "tool_input": {...},
    "mcp_server": "calculator-server"  # optional field identifying MCP
}
```

**Pros**:

- Simplest
- Users do not need to care about MCP details
- Easy to implement

**Cons**:

- Loses MCP-specific features (approval, tool listing)
- Not explicit enough

### Recommended option: hybrid approach

**Base layer**: adopt Option B (content blocks)

```python
ContentPart = Union[
    TextPart,
    ToolUsePart,
    ToolResultPart,
    McpToolUsePart,      # includes server_name field
    McpToolResultPart,
]
```

**Support advanced features through metadata**:

```python
class McpToolUsePart(TypedDict):
    type: Required[Literal["mcp_tool_use"]]
    tool_call_id: Required[str]
    server_name: Required[str]  # MCP server name
    tool_name: Required[str]
    tool_input: Required[Dict[str, Any]]
    metadata: NotRequired[McpMetadata]  # supports advanced features such as approval

class McpMetadata(TypedDict, total=False):
    approval_required: bool
    approval_request_id: Optional[str]
    list_tools: bool  # whether this is a tool list request
```

**Provide a simplified API**:

```python
# For simple scenarios, conversion can be automatic
def create_tool_call(name: str, input: dict, mcp_server: Optional[str] = None):
    if mcp_server:
        return McpToolUsePart(
            type="mcp_tool_use",
            server_name=mcp_server,
            tool_name=name,
            tool_input=input
        )
    else:
        return ToolUsePart(
            type="tool_use",
            tool_name=name,
            tool_input=input
        )
```

## Conclusion

The three providers' MCP implementations each have their own characteristics, reflecting different design philosophies:

1. **OpenAI**: explicit, complete, controllable
2. **Anthropic**: consistent, concise, automatic
3. **Google**: transparent, simple, asynchronous

Our IR design should:

- Use Anthropic's content block architecture as the foundation
- Support OpenAI's advanced features through metadata
- Provide a Google-style simplified API
- Ensure conversion among all three providers is feasible
