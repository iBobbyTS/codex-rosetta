I am looking at `comparison.md` and `ir_design.md` (the latter is a historical document that is not retained in this repository).

### Content Type Support

For audio input and output, we can temporarily leave that out. I do not currently need it, but we should be prepared to support it later if necessary with sufficient compatibility.

Even though the document and file names differ, are they actually the same thing?

For search results, we can also temporarily leave them out, or represent them as tool call results instead.

### Thought Process

Many OpenAI-compatible third parties add `reasoning_content` and `reasoning_details` fields outside `message.content`. We can use that as the representation of the thought process for the OpenAI type group.

Also, when we say OpenAI here, we are really referring to OpenAI Chat Completions. They also have the newer Responses API, which we can support later; for now, we can ignore it.

### Tool Calling

In my view, this part is basically the same across the three providers. The presentation differs, but the underlying structure is mostly the same. We can consider custom tools for compatibility later; at the moment, very few people use them. As for server tools, each provider has some, and we have also implemented some internal ones. In practice, we can treat all of them as function calls. One thing to note is the MCP tool category, which I did not see mentioned here. You may need to look for that separately.

### Special Features

We actually do not need to handle this part. It can be ignored directly.

### Citation System

Leave this aside for now.

### Type System Design Philosophy

For obsolete types, such as OpenAI's function-related types, we should ignore them directly and use `tool` instead. When we encounter them, we should convert them to `tool` immediately.

#### Tool Calling

Although Google does not provide ID information, their actual behavior is to match by order. That means the sequence in which the model returns tool calls determines the order of the user's feedback, and they will assume the tool call results correspond to the original request order.

The tool section involves `tool_choice` and similar fields, which we do not seem to have covered in the documentation. You should check that as well. MCP is a type of tool, so you need to examine the code for all three providers.

OpenAI: `ChatCompletionToolChoiceOptionParam`
Anthropic: `ToolChoiceParam`
Google GenAI: `ToolConfig`

In `google.md`, when did the role system gain a `function` role?

They only have `user` and `model` roles.

They have four tool-selection modes. When `ANY` is combined with `allowed_function_names` for restriction, it forces a selection in the fourth mode.

### System Prompt

Google: set `system_instruction` in `GenerateContentConfig`.
Example:

```python
from google import genai
from google.genai.types import GenerateContentConfig, HttpOptions

client = genai.Client(http_options=HttpOptions(api_version="v1"))
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Why is the sky blue?",
    config=GenerateContentConfig(
        system_instruction=[
            "You're a language translator.",
            "Your mission is to translate text in English to French.",
        ]
    ),
)
print(response.text)
# Example response:
# Pourquoi le ciel est-il bleu ?
```

Anthropic: set it when sending the request.
Example:

```python
import anthropic

client = anthropic.Anthropic()

message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": "You are a Python expert."
        },
        {
            "type": "text",
            "text": "Always include type hints and docstrings."
        }
    ],
    messages=[
        {"role": "user", "content": "Help me with Python code"}
    ]
)
```
