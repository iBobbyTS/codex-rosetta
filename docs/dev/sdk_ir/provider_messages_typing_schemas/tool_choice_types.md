# Tool Choice Type Definitions by Provider

This document summarizes the tool-choice-related type definitions for OpenAI, Anthropic, and Google GenAI, including tool-choice parameters and tool definitions.

## 1. OpenAI Tool Choice Types

OpenAI tool choice types primarily include the following key types:

### 1.1 ChatCompletionToolChoiceOptionParam

This is a Union type that can be one of the following types:

- `"none"` - Do not use any tool
- `"auto"` - Automatically choose whether to use a tool
- `"required"` - A tool must be used
- `ChatCompletionAllowedToolChoiceParam` - Allowed tool choice parameter
- `ChatCompletionNamedToolChoiceParam` - Named tool choice parameter
- `ChatCompletionNamedToolChoiceCustomParam` - Custom named tool choice parameter

### 1.2 ChatCompletionNamedToolChoiceParam

Named tool choice parameter, inherited from `dict`:

```python
{
    "function": Required[Function],
    "type": Required[Literal["function"]]
}
```

### 1.3 ChatCompletionFunctionToolParam

Function tool parameter, inherited from `dict`:

```python
{
    "function": Required[FunctionDefinition],
    "type": Required[Literal["function"]]
}
```

## 2. Anthropic Tool Choice Types

Anthropic tool choice types are quite rich and primarily include the following key types:

### 2.1 ToolChoiceParam

Tool choice parameter, which can be one of the following types:

- `ToolChoiceAnyParam` - Allow any tool to be used
- `ToolChoiceAutoParam` - Automatically choose whether to use a tool
- `ToolChoiceNoneParam` - Do not use any tool
- `ToolChoiceToolParam` - Use a specific tool

### 2.2 ToolChoiceAnyParam

Parameter that allows any tool:

```python
{
    "type": Required[Literal["any"]],
    "disable_parallel_tool_use": bool
}
```

### 2.3 ToolChoiceAutoParam

Parameter that automatically chooses whether to use a tool:

```python
{
    "type": Required[Literal["auto"]],
    "disable_parallel_tool_use": bool
}
```

### 2.4 ToolChoiceNoneParam

Parameter that does not use any tool:

```python
{
    "type": Required[Literal["none"]]
}
```

### 2.5 ToolChoiceToolParam

Parameter that specifies a particular tool:

```python
{
    "name": Required[str],
    "type": Required[Literal["tool"]],
    "disable_parallel_tool_use": bool
}
```

### 2.6 ToolParam

Tool parameter definition:

```python
{
    "input_schema": Required[Union[InputSchemaTyped, Dict[str, object]]],
    "name": Required[str],
    "cache_control": Optional[CacheControlEphemeralParam],
    "description": str,
    "type": Optional[Literal["custom"]]
}
```

## 3. Google GenAI Tool Choice Types

Google GenAI tool choice types are relatively simple and primarily include the following key types:

### 3.1 ToolConfig

Tool configuration, used for all tools:

```python
{
    "function_calling_config": Optional[FunctionCallingConfig],
    "retrieval_config": Optional[RetrievalConfig]
}
```

### 3.2 Tool

Tool details, the tools the model may use to generate responses:

```python
{
    "function_declarations": Optional[list[FunctionDeclaration]],
    "retrieval": Optional[Retrieval],
    "google_search_retrieval": Optional[GoogleSearchRetrieval],
    "computer_use": Optional[ComputerUse],
    "file_search": Optional[FileSearch],
    "code_execution": Optional[ToolCodeExecution],
    "enterprise_web_search": Optional[EnterpriseWebSearch],
    "google_maps": Optional[GoogleMaps],
    "google_search": Optional[GoogleSearch],
    "url_context": Optional[UrlContext]
}
```

### 3.3 FunctionDeclaration

Defines functions for which the model can generate JSON input:

```python
{
    "behavior": Optional[Behavior],
    "description": Optional[str],
    "name": Optional[str],
    "parameters": Optional[Schema],
    "parameters_json_schema": Optional[Any],
    "response": Optional[Schema],
    "response_json_schema": Optional[Any]
}
```

## 4. Tool Choice Type Comparison Across the Three Providers

### 4.1 Similarities

1. **Tool choice modes**: All three support automatic tool selection (`auto`) and no-tool mode (`none`).
2. **Function/tool definitions**: All three support defining functions/tools, including name, description, and parameters.
3. **Parameter definitions**: All three define parameters in a manner similar to OpenAPI.

### 4.2 Differences

1. **Type systems**:

   - OpenAI: Uses TypedDict and Union types
   - Anthropic: Uses Pydantic models and TypedDict
   - Google: Uses Pydantic models

2. **Breadth of tool types**:

   - OpenAI: Primarily supports function tools
   - Anthropic: Supports many tool types, including custom tools, web search, and code execution
   - Google: Supports many tool types, including function declarations, retrieval, Google Search, and code execution

3. **Parallel tool use**:

   - Anthropic explicitly supports controlling parallel tool use (`disable_parallel_tool_use` parameter)
   - OpenAI and Google do not expose explicit parallel tool-use controls

4. **Cache control**:
   - Anthropic supports cache control (`cache_control` parameter)
   - OpenAI and Google do not expose explicit cache control

## 5. Suggested Intermediate Representation (IR) Design

Based on the analysis above, we can design a unified tool choice intermediate representation (IR):

```python
from typing import Dict, List, Literal, Optional, Union, Any
from typing_extensions import TypedDict, Required, NotRequired

class ToolChoiceIR(TypedDict):
    """Tool choice intermediate representation"""
    mode: Required[Literal["none", "auto", "any", "tool"]]
    tool_name: NotRequired[str]  # Required when mode is "tool"
    disable_parallel: NotRequired[bool]  # Controls whether parallel tool use is disabled

class ToolDefinitionIR(TypedDict):
    """Tool definition intermediate representation"""
    name: Required[str]
    type: Required[Literal["function", "retrieval", "search", "code_execution", "custom"]]
    description: NotRequired[str]
    parameters: NotRequired[Dict[str, Any]]  # OpenAPI-formatted parameter definitions
    required_parameters: NotRequired[List[str]]  # Required parameter list
    cache_control: NotRequired[Dict[str, Any]]  # Cache control parameters
    metadata: NotRequired[Dict[str, Any]]  # Provider-specific metadata
```

### Conversion Strategy

#### OpenAI → IR

```python
def openai_tool_choice_to_ir(tool_choice):
    if tool_choice == "none":
        return {"mode": "none"}
    elif tool_choice == "auto":
        return {"mode": "auto"}
    elif tool_choice == "required":
        return {"mode": "any"}
    elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        return {
            "mode": "tool",
            "tool_name": tool_choice["function"]["name"]
        }
    # Other cases...
```

#### Anthropic → IR

```python
def anthropic_tool_choice_to_ir(tool_choice):
    if tool_choice["type"] == "none":
        return {"mode": "none"}
    elif tool_choice["type"] == "auto":
        return {
            "mode": "auto",
            "disable_parallel": tool_choice.get("disable_parallel_tool_use", False)
        }
    elif tool_choice["type"] == "any":
        return {
            "mode": "any",
            "disable_parallel": tool_choice.get("disable_parallel_tool_use", False)
        }
    elif tool_choice["type"] == "tool":
        return {
            "mode": "tool",
            "tool_name": tool_choice["name"],
            "disable_parallel": tool_choice.get("disable_parallel_tool_use", False)
        }
    # Other cases...
```

#### Google → IR

```python
def google_tool_config_to_ir(tool_config):
    # Google does not define an explicit tool choice parameter; default to auto
    return {"mode": "auto"}
```

#### IR → Providers

The reverse conversion process is similar: determine which provider-specific tool choice type to convert to based on the `mode` field in the IR.
