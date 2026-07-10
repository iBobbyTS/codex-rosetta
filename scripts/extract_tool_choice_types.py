"""Extract tool-choice type definitions from supported LLM providers.

This script extracts the tool-choice types used by OpenAI, Anthropic, and
Google GenAI, including ChatCompletionToolChoiceOptionParam, ToolChoiceParam,
and ToolConfig.
"""

import inspect
import json
import os
import sys
from typing import Any, get_type_hints

# Add the conda environment path.
sys.path.append(
    os.path.expanduser("~/miniforge3/envs/l_t_c/lib/python3.10/site-packages")
)

import anthropic
from google import genai


def get_class_info(cls: type) -> dict[str, Any]:
    """Return class details, including fields, annotations, and docstrings."""
    result = {
        "name": getattr(cls, "__name__", str(cls)),
        "module": getattr(cls, "__module__", "unknown"),
        "doc": inspect.getdoc(cls),
        "annotations": {},
    }

    # Try to inspect base classes.
    try:
        if hasattr(cls, "__bases__"):
            result["bases"] = [
                base.__name__ for base in cls.__bases__ if base.__name__ != "object"
            ]
        elif hasattr(cls, "__origin__") and hasattr(cls, "__args__"):
            result["origin"] = str(cls.__origin__)
            result["args"] = [str(arg) for arg in cls.__args__]
    except Exception as e:
        result["bases_error"] = str(e)

    # Collect type annotations.
    try:
        type_hints = get_type_hints(cls)
        for name, type_hint in type_hints.items():
            result["annotations"][name] = str(type_hint)
    except Exception as e:
        result["annotations_error"] = str(e)

    # Try to inspect the __dict__ attribute.
    try:
        if hasattr(cls, "__dict__"):
            attrs = {}
            for key, value in cls.__dict__.items():
                if not key.startswith("_"):
                    attrs[key] = str(type(value))
            if attrs:
                result["attributes"] = attrs
    except Exception as e:
        result["attributes_error"] = str(e)

    return result


def find_classes_by_name(module: Any, name_patterns: list[str]) -> list[type]:
    """Find classes whose names match any requested pattern in a module."""
    classes = []
    visited = set()

    # Recursively search for all classes in the module.
    def search_module(obj, path=""):
        # Avoid reference cycles.
        obj_id = id(obj)
        if obj_id in visited:
            return
        visited.add(obj_id)

        if inspect.ismodule(obj):
            # Copy the dictionary items to avoid mutation during iteration.
            try:
                for key, value in list(obj.__dict__.items()):
                    if not key.startswith("_"):  # Skip private attributes.
                        try:
                            search_module(value, f"{path}.{key}" if path else key)
                        except Exception:
                            # Ignore errors raised while accessing some attributes.
                            pass
            except Exception:
                pass
        elif inspect.isclass(obj):
            for pattern in name_patterns:
                if pattern in obj.__name__:
                    classes.append(obj)
                    break

    try:
        search_module(module)
    except Exception as e:
        print(f"Warning: error while searching module: {e}")

    return classes


def extract_openai_tool_choice_types() -> list[dict[str, Any]]:
    """Extract OpenAI tool-choice types."""
    # Extract only the selected types.
    target_classes = [
        "ChatCompletionToolChoiceOptionParam",
        "ChatCompletionToolChoiceParam",
        "ChatCompletionNamedToolChoiceParam",
        "ChatCompletionToolParam",
    ]
    classes = []

    # Look directly in the openai.types module.
    try:
        import openai.types.chat

        for name in target_classes:
            if hasattr(openai.types.chat, name):
                classes.append(getattr(openai.types.chat, name))
    except (ImportError, AttributeError) as e:
        print(f"Warning: could not import classes from openai.types.chat: {e}")

    # Search the full OpenAI package if no classes were found directly.
    if not classes:
        patterns = ["ToolChoice", "Tool"]
        classes = find_classes_by_name(openai, patterns)

    return [get_class_info(cls) for cls in classes]


def extract_anthropic_tool_choice_types() -> list[dict[str, Any]]:
    """Extract Anthropic tool-choice types."""
    # Extract only the selected types.
    target_classes = ["ToolChoiceParam", "ToolParam"]
    classes = []

    # Look directly in the anthropic.types module.
    try:
        for name in target_classes:
            if hasattr(anthropic, name):
                classes.append(getattr(anthropic, name))
    except AttributeError as e:
        print(f"Warning: could not import classes from anthropic: {e}")

    # Search the full Anthropic package if no classes were found directly.
    if not classes:
        patterns = ["ToolChoice", "Tool"]
        classes = find_classes_by_name(anthropic, patterns)

    return [get_class_info(cls) for cls in classes]


def extract_google_tool_config_types() -> list[dict[str, Any]]:
    """Extract Google GenAI tool-configuration types."""
    # Extract only the selected types.
    target_classes = ["ToolConfig", "Tool", "FunctionDeclaration"]
    classes = []

    # Look directly in the genai.types module.
    try:
        for name in target_classes:
            if hasattr(genai.types, name):
                classes.append(getattr(genai.types, name))
    except AttributeError as e:
        print(f"Warning: could not import classes from genai.types: {e}")

    # Search the full Google GenAI package if no classes were found directly.
    if not classes:
        patterns = ["ToolConfig", "Tool"]
        classes = find_classes_by_name(genai, patterns)

    return [get_class_info(cls) for cls in classes]


def main():
    """Extract and save tool-choice types for all supported providers."""
    # Extract each provider's tool-choice types.
    print("Extracting OpenAI tool-choice types...")
    openai_types = extract_openai_tool_choice_types()
    print(f"Found {len(openai_types)} OpenAI-related classes")

    print("Extracting Anthropic tool-choice types...")
    anthropic_types = extract_anthropic_tool_choice_types()
    print(f"Found {len(anthropic_types)} Anthropic-related classes")

    print("Extracting Google tool-choice types...")
    google_types = extract_google_tool_config_types()
    print(f"Found {len(google_types)} Google-related classes")

    # Combine the results.
    result = {
        "openai": openai_types,
        "anthropic": anthropic_types,
        "google": google_types,
    }

    # Save the result as JSON.
    output_dir = "docs/dev/sdk_ir/provider_messages_typing_schemas"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "tool_choice_types_info.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Saved tool-choice type definitions to {output_path}")


if __name__ == "__main__":
    main()
