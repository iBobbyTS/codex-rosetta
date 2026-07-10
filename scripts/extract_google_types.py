#!/usr/bin/env python3
"""Extract Google GenAI type definitions.

This script uses inspect to analyze google.genai.types dynamically and extract
selected type definitions.
"""

import inspect
import json
import os
from typing import Any, get_type_hints

# Ensure that Python from the conda environment is used.
# If necessary, uncomment the line below and update the path.
# sys.path.insert(0, '/data/pding/miniforge3/envs/l_t_c/lib/python3.10/site-packages')
import google.genai.types as types


def get_class_info(cls) -> dict[str, Any]:
    """Extract class details, including fields, annotations, and docstrings."""
    result = {
        "name": cls.__name__,
        "module": cls.__module__,
        "doc": inspect.getdoc(cls),
        "fields": {},
        "bases": [base.__name__ for base in cls.__bases__ if base.__name__ != "object"],
        "annotations": {},
    }

    # Collect type annotations.
    try:
        type_hints = get_type_hints(cls)
        for name, hint in type_hints.items():
            result["annotations"][name] = str(hint)
    except (TypeError, ValueError) as e:
        result["annotations_error"] = str(e)

    # Collect fields and default values.
    if hasattr(cls, "__annotations__"):
        for name, annotation in cls.__annotations__.items():
            result["fields"][name] = {
                "annotation": str(annotation),
                "doc": None,  # Field documentation is extracted below.
            }

    # Try to extract field documentation from the class docstring.
    if result["doc"]:
        lines = result["doc"].split("\n")
        current_field = None
        field_doc = []

        for line in lines:
            if ":" in line and not line.startswith(" "):
                # This may be a field definition.
                parts = line.split(":", 1)
                field_name = parts[0].strip()
                if field_name in result["fields"]:
                    # Save the previous field's documentation, if any.
                    if current_field and field_doc:
                        result["fields"][current_field]["doc"] = "\n".join(field_doc)

                    # Start collecting documentation for a new field.
                    current_field = field_name
                    field_doc = [parts[1].strip()]
                else:
                    # This is not a field; append it to the current field's docs.
                    if current_field:
                        field_doc.append(line)
            elif current_field:
                # Continue collecting documentation for the current field.
                field_doc.append(line)

        # Save the final field's documentation.
        if current_field and field_doc:
            result["fields"][current_field]["doc"] = "\n".join(field_doc)

    return result


def get_union_type_info(type_obj) -> dict[str, Any]:
    """Extract information about a Union type."""
    result = {
        "name": str(type_obj),
        "origin": str(getattr(type_obj, "__origin__", None)),
        "args": [str(arg) for arg in getattr(type_obj, "__args__", [])],
    }
    return result


def extract_types_info() -> dict[str, Any]:
    """Extract information about all selected types."""
    result = {"classes": {}, "type_aliases": {}, "enums": {}}

    # Select the classes of interest.
    target_classes = ["Content", "ContentDict", "Part", "PartDict", "File", "FileDict"]

    # Select the type aliases of interest.
    target_type_aliases = ["ContentListUnionDict", "ContentUnionDict", "PartUnionDict"]

    # Extract classes.
    for name, obj in inspect.getmembers(types):
        if inspect.isclass(obj) and name in target_classes:
            result["classes"][name] = get_class_info(obj)

    # Extract type aliases.
    for name in target_type_aliases:
        if hasattr(types, name):
            type_obj = getattr(types, name)
            result["type_aliases"][name] = get_union_type_info(type_obj)

    return result


def main():
    """Extract Google GenAI types and write the generated reference files."""
    # Extract type information.
    types_info = extract_types_info()

    # Create the output directory.
    output_dir = "docs/dev/sdk_ir/provider_messages_typing_schemas"
    os.makedirs(output_dir, exist_ok=True)

    # Save the extracted information as JSON for inspection.
    with open(os.path.join(output_dir, "google_types_info.json"), "w") as f:
        json.dump(types_info, f, indent=2)

    # Print a summary.
    print("Extracted classes:")
    for name in types_info["classes"]:
        print(f"  - {name}")

    print("\nExtracted type aliases:")
    for name in types_info["type_aliases"]:
        print(f"  - {name}")

    # Generate the Markdown document.
    generate_markdown(types_info, output_dir)


def generate_markdown(types_info: dict[str, Any], output_dir: str):
    """Generate the Markdown reference document."""
    with open(os.path.join(output_dir, "google.md"), "w") as f:
        f.write("# Google GenAI ContentListUnionDict Type Definitions\n\n")

        f.write("## Overview\n\n")
        f.write(
            "The Google GenAI message type system is based on "
            "`ContentListUnionDict`, a highly flexible Union type that supports "
            "several content representations.\n\n"
        )

        f.write("## Type Hierarchy\n\n")
        f.write("```mermaid\n")
        f.write("graph TD\n")
        f.write("    A[ContentListUnionDict] --> B[ContentUnionDict]\n")
        f.write("    A --> C[list[ContentUnionDict]]\n")
        f.write("    B --> D[Content]\n")
        f.write("    B --> E[ContentDict]\n")
        f.write("    B --> F[PartUnionDict]\n")
        f.write("    B --> G[list[PartUnionDict]]\n")
        f.write("    F --> H[str]\n")
        f.write("    F --> I[PIL_Image]\n")
        f.write("    F --> J[File]\n")
        f.write("    F --> K[FileDict]\n")
        f.write("    F --> L[Part]\n")
        f.write("    F --> M[PartDict]\n")
        f.write("```\n\n")

        # Type aliases.
        f.write("## Primary Type Aliases\n\n")
        for name, info in types_info["type_aliases"].items():
            f.write(f"### {name}\n\n")
            f.write(f"**Definition**: `{name} = {info['name']}`\n\n")
            f.write("**Members**:\n")
            for arg in info["args"]:
                f.write(f"- `{arg}`\n")
            f.write("\n")

        # Class definitions.
        f.write("## Primary Class Definitions\n\n")
        for name, info in types_info["classes"].items():
            f.write(f"### {name}\n\n")
            if info["doc"]:
                f.write(f"{info['doc']}\n\n")

            if info["bases"]:
                f.write(f"**Inherits from**: {', '.join(info['bases'])}\n\n")

            f.write("**Fields**:\n\n")
            if info["fields"]:
                f.write("| Field | Type | Description |\n")
                f.write("|-------|------|-------------|\n")
                for field_name, field_info in info["fields"].items():
                    annotation = (
                        field_info["annotation"]
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    doc = field_info["doc"] or ""
                    doc = doc.replace("\n", " ")
                    f.write(f"| `{field_name}` | `{annotation}` | {doc} |\n")
            else:
                f.write(
                    "*No fields were found, or field information is unavailable.*\n"
                )
            f.write("\n")

        # Usage examples.
        f.write("## Usage Examples\n\n")

        f.write("### Simple Text Message\n")
        f.write("```python\n")
        f.write("# Using a string\n")
        f.write('content = "Hello, how are you?"\n\n')
        f.write("# Using a Content object\n")
        f.write(
            'content = types.Content(parts=[types.Part(text="Hello, how are you?")])\n\n'
        )
        f.write("# Using a dictionary\n")
        f.write('content = {"parts": [{"text": "Hello, how are you?"}]}\n')
        f.write("```\n\n")

        f.write("### Multimodal Message\n")
        f.write("```python\n")
        f.write("# Using a Content object\n")
        f.write("content = types.Content(\n")
        f.write("    parts=[\n")
        f.write('        types.Part(text="What\'s in this image?"),\n')
        f.write("        types.Part(inline_data=types.Blob(\n")
        f.write('            mime_type="image/jpeg",\n')
        f.write("            data=base64.b64encode(image_bytes).decode()\n")
        f.write("        ))\n")
        f.write("    ]\n")
        f.write(")\n\n")
        f.write("# Using a dictionary\n")
        f.write("content = {\n")
        f.write('    "parts": [\n')
        f.write('        {"text": "What\'s in this image?"},\n')
        f.write('        {"inline_data": {\n')
        f.write('            "mime_type": "image/jpeg",\n')
        f.write('            "data": base64.b64encode(image_bytes).decode()\n')
        f.write("        }}\n")
        f.write("    ]\n")
        f.write("}\n")
        f.write("```\n\n")

        f.write("### Conversation History\n")
        f.write("```python\n")
        f.write("# Using a list of Content objects\n")
        f.write("contents = [\n")
        f.write(
            '    types.Content(role="user", parts=[types.Part(text="Hello, how are you?")]),\n'
        )
        f.write(
            '    types.Content(role="model", parts=[types.Part(text="I\'m doing well, thank you!")]),\n'
        )
        f.write(
            '    types.Content(role="user", parts=[types.Part(text="Tell me about yourself.")])\n'
        )
        f.write("]\n\n")
        f.write("# Using a list of dictionaries\n")
        f.write("contents = [\n")
        f.write('    {"role": "user", "parts": [{"text": "Hello, how are you?"}]},\n')
        f.write(
            '    {"role": "model", "parts": [{"text": "I\'m doing well, thank you!"}]},\n'
        )
        f.write(
            '    {"role": "user", "parts": [{"text": "Tell me about yourself."}]}\n'
        )
        f.write("]\n")
        f.write("```\n\n")

        # Key feature summary.
        f.write("## Key Features\n\n")
        f.write("### 1. Flexible Type System\n")
        f.write(
            "- **Multiple representations**: The same content can be represented "
            "as a string, object, or dictionary\n"
        )
        f.write("- **Nested structures**: Supports complex nested content structures\n")
        f.write(
            "- **Type conversion**: Converts automatically between representations\n\n"
        )

        f.write("### 2. Role System\n")
        f.write("- **User and model**: Primarily uses the `user` and `model` roles\n")
        f.write("- **System messages**: Uses the `system` role to set context\n\n")

        f.write("### 3. Multimodal Support\n")
        f.write("- **Text**: Provided through the `text` field\n")
        f.write("- **Images**: Provided through the `inline_data` field\n")
        f.write("- **Mixed content**: One message can contain multiple media types\n\n")

        f.write("### 4. Key Differences from Other Providers\n")
        f.write("| Feature | Google GenAI | OpenAI | Anthropic |\n")
        f.write("|---------|--------------|--------|-----------|\n")
        f.write(
            "| Type flexibility | High (multiple representations) | Medium "
            "(fixed structure) | Medium (fixed structure) |\n"
        )
        f.write("| Role count | 3 (user, model, system) | 6 | 2 |\n")
        f.write(
            "| Multimodal support | Inline data | Content parts | Content blocks |\n"
        )
        f.write("| Tool calls | Function calls | Tool calls | Tool-use blocks |\n\n")

        # Considerations.
        f.write("## Considerations\n\n")
        f.write(
            "1. **Type flexibility**: Google GenAI's type system is highly flexible; "
            "the same content can have multiple representations\n"
        )
        f.write(
            "2. **Automatic conversion**: The API converts between representations "
            "automatically, but using the correct type explicitly can avoid potential "
            "problems\n"
        )
        f.write(
            "3. **Dictionary representation**: Dictionaries are the simplest option "
            "in most cases\n"
        )
        f.write(
            "4. **Object representation**: Objects provide better type checking and "
            "IDE support\n"
        )
        f.write(
            "5. **String limitations**: Plain strings support only text content, not "
            "roles or multimodal content\n\n"
        )

        # Version information.
        f.write("## Version Information\n\n")
        f.write("- **Source**: Google GenAI Python SDK\n")
        f.write("- **Package path**: `google.genai.types`\n")


if __name__ == "__main__":
    main()
