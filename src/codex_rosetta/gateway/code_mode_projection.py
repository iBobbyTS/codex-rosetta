"""Project selected Codex Code Mode tools into ordinary Chat functions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .tool_profiles import (
    apply_profile_tool_mutations,
    route_tool_state,
    tool_profile_contract,
)
from .web_run_capabilities import (
    WEB_RUN_PROFILE_ITEM_ID,
    WEB_RUN_SIDECAR_CAPABILITY,
    project_modified_web_run_function,
)


@dataclass(frozen=True)
class ExecToolProjection:
    """Declarative mapping between one Chat function and a nested exec tool."""

    item_id: str
    chat_name: str
    nested_name: str
    input_mode: str = "args"
    input_field: str = "input"
    output_mode: str = "text"
    model_visible: bool = True


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


_TOKEN_RE = re.compile(
    r"(?P<comment>//[^\n]*)"
    r"|(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
    r"|(?P<number>-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"|(?P<identifier>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"|(?P<symbol>[{}:;?,|&<>\[\]()])"
)
_WHITESPACE_RE = re.compile(r"\s+")


def _tokenize_typescript(source: str) -> list[_Token]:
    """Tokenize one rendered type without silently skipping unknown syntax."""
    tokens: list[_Token] = []
    index = 0
    while index < len(source):
        whitespace = _WHITESPACE_RE.match(source, index)
        if whitespace is not None:
            index = whitespace.end()
            continue
        match = _TOKEN_RE.match(source, index)
        if match is None:
            raise ValueError(f"unsupported TypeScript token at offset {index}")
        tokens.append(_Token(match.lastgroup or "", match.group()))
        index = match.end()
    return tokens


class _TypeScriptSchemaParser:
    """Parse the constrained TypeScript emitted by Codex Code Mode."""

    def __init__(self, source: str) -> None:
        self._tokens = _tokenize_typescript(source)
        self._index = 0

    def parse(self) -> dict[str, Any]:
        """Parse one complete TypeScript type into JSON Schema."""
        schema = self._parse_union()
        if self._peek() is not None:
            raise ValueError("unexpected trailing TypeScript tokens")
        return schema

    def _peek(self) -> _Token | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _take(self, value: str | None = None) -> _Token:
        token = self._peek()
        if token is None or (value is not None and token.value != value):
            raise ValueError(f"expected {value or 'token'}")
        self._index += 1
        return token

    def _accept(self, value: str) -> bool:
        token = self._peek()
        if token is None or token.value != value:
            return False
        self._index += 1
        return True

    def _parse_union(self) -> dict[str, Any]:
        choices = [self._parse_intersection()]
        while self._accept("|"):
            choices.append(self._parse_intersection())
        if len(choices) == 1:
            return choices[0]

        constants = [choice.get("const") for choice in choices]
        constant_types = [choice.get("type") for choice in choices]
        if (
            all(value is not None for value in constants)
            and len(set(constant_types)) == 1
        ):
            return {"type": constant_types[0], "enum": constants}
        return {"anyOf": choices}

    def _parse_intersection(self) -> dict[str, Any]:
        choices = [self._parse_postfix()]
        while self._accept("&"):
            choices.append(self._parse_postfix())
        if len(choices) == 1:
            return choices[0]
        return {"allOf": choices}

    def _parse_postfix(self) -> dict[str, Any]:
        schema = self._parse_primary()
        while self._accept("["):
            self._take("]")
            schema = {"type": "array", "items": schema}
        return schema

    def _parse_primary(self) -> dict[str, Any]:
        token = self._take()
        if token.value == "{":
            return self._parse_object()
        if token.value == "[":
            return self._parse_tuple()
        if token.value == "(":
            schema = self._parse_union()
            self._take(")")
            return schema
        if token.kind == "string":
            value = (
                json.loads(token.value)
                if token.value.startswith('"')
                else token.value[1:-1]
            )
            return {"type": "string", "const": value}
        if token.kind == "number":
            value = (
                float(token.value)
                if any(marker in token.value for marker in ".eE")
                else int(token.value)
            )
            return {"type": "number", "const": value}
        if token.kind == "identifier":
            return self._parse_identifier(token.value)
        raise ValueError(f"unsupported TypeScript type token {token.value!r}")

    def _parse_identifier(self, identifier: str) -> dict[str, Any]:
        if identifier in {"Array", "ReadonlyArray"} and self._accept("<"):
            items = self._parse_union()
            self._take(">")
            return {"type": "array", "items": items}
        if identifier == "Record" and self._accept("<"):
            self._parse_union()
            self._take(",")
            values = self._parse_union()
            self._take(">")
            return {"type": "object", "additionalProperties": values}
        if identifier == "string":
            return {"type": "string"}
        if identifier == "number":
            return {"type": "number"}
        if identifier == "boolean":
            return {"type": "boolean"}
        if identifier == "true":
            return {"type": "boolean", "const": True}
        if identifier == "false":
            return {"type": "boolean", "const": False}
        if identifier == "null":
            return {"type": "null"}
        if identifier == "never":
            return {"not": {}}
        if identifier in {"unknown", "any", "object"}:
            return {}
        raise ValueError(f"unsupported TypeScript type {identifier!r}")

    def _parse_object(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        comments: list[str] = []
        additional_properties: dict[str, Any] | None = None
        while not self._accept("}"):
            token = self._peek()
            if token is None:
                raise ValueError("unterminated object type")
            if token.kind == "comment":
                comments.append(self._take().value[2:].strip())
                continue
            if token.value == "[":
                if additional_properties is not None:
                    raise ValueError("duplicate object index signature")
                self._take("[")
                key_token = self._take()
                if key_token.kind != "identifier":
                    raise ValueError("invalid object index signature")
                self._take(":")
                self._take("string")
                self._take("]")
                self._take(":")
                additional_properties = self._parse_union()
                self._accept(";") or self._accept(",")
                comments.clear()
                continue
            name_token = self._take()
            if name_token.kind not in {"identifier", "string"}:
                raise ValueError("invalid object property")
            name = (
                json.loads(name_token.value)
                if name_token.kind == "string" and name_token.value.startswith('"')
                else name_token.value.strip("'\"")
            )
            optional = self._accept("?")
            self._take(":")
            property_schema = self._parse_union()
            if comments:
                property_schema = dict(property_schema)
                property_schema["description"] = "\n".join(comments)
                comments.clear()
            properties[name] = property_schema
            if not optional:
                required.append(name)
            self._accept(";") or self._accept(",")
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": (
                additional_properties if additional_properties is not None else False
            ),
        }
        if required:
            schema["required"] = required
        return schema

    def _parse_tuple(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        while not self._accept("]"):
            items.append(self._parse_union())
            if not self._accept(","):
                self._take("]")
                break
        return {
            "type": "array",
            "prefixItems": items,
            "minItems": len(items),
            "maxItems": len(items),
        }


def exec_tool_projections_for_route(route: Any) -> dict[str, ExecToolProjection]:
    """Return model-visible and internal Profile-owned exec projections."""
    projections: dict[str, ExecToolProjection] = {}
    for item_id, definition in tool_profile_contract()["exec_projections"].items():
        state = route_tool_state(route, item_id)
        model_visible = state in {"passthrough", "modified"}
        internal_when_disabled = definition.get("internal_when_disabled", False)
        if not model_visible and not (state == "disabled" and internal_when_disabled):
            continue
        projection_definition = {
            key: value
            for key, value in definition.items()
            if key != "internal_when_disabled"
        }
        projection = ExecToolProjection(
            item_id=item_id,
            model_visible=model_visible,
            **projection_definition,
        )
        projections[projection.chat_name] = projection
    return projections


def project_exec_tool_definitions(
    exec_description: str,
    projections: dict[str, ExecToolProjection],
    *,
    profile_route: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """Build Chat function definitions from selected exec description sections."""
    sections = _exec_description_sections(exec_description)
    definitions: dict[str, dict[str, Any]] = {}
    for chat_name, projection in projections.items():
        section = sections.get(projection.nested_name)
        if section is None:
            continue
        parsed = _project_one_definition(section, projection)
        if parsed is not None:
            if profile_route is not None:
                parsed = dict(parsed)
                if (
                    projection.item_id == WEB_RUN_PROFILE_ITEM_ID
                    and route_tool_state(profile_route, projection.item_id)
                    == "modified"
                ):
                    projected_function = project_modified_web_run_function(
                        parsed["function"],
                        browser_available=(
                            WEB_RUN_SIDECAR_CAPABILITY
                            in getattr(
                                profile_route, "tool_runtime_capabilities", frozenset()
                            )
                        ),
                    )
                    if projected_function is None:
                        continue
                    parsed["function"] = projected_function
                parsed["function"] = apply_profile_tool_mutations(
                    parsed["function"], projection.item_id, profile_route
                )
            definitions[chat_name] = parsed
    return definitions


def build_exec_script(
    projection: ExecToolProjection,
    arguments: dict[str, Any],
) -> str:
    """Build deterministic JavaScript for one projected nested-tool call."""
    if projection.input_mode == "freeform":
        value = arguments.get(projection.input_field)
        if not isinstance(value, str):
            raise ValueError(
                f"{projection.chat_name} requires string field "
                f"'{projection.input_field}'"
            )
        nested_input: Any = value
    else:
        nested_input = arguments
    literal = _javascript_json_literal(nested_input)
    output_helper = {
        "text": "text",
        "image": "image",
        "generated_image": "generatedImage",
    }[projection.output_mode]
    return (
        f"const result = await tools.{projection.nested_name}({literal});\n"
        f"{output_helper}(result);\n"
    )


def _exec_description_sections(description: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^### `([^`]+)`(?: \(`[^`]+`\))?\s*$", description))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(description)
        )
        sections[match.group(1)] = description[match.end() : end].strip()
    return sections


def _project_one_definition(
    section: str,
    projection: ExecToolProjection,
) -> dict[str, Any] | None:
    declaration = re.search(
        rf"\b{re.escape(projection.nested_name)}\((args|input):\s*(.*?)\)"
        r":\s*Promise<",
        section,
        flags=re.DOTALL,
    )
    if declaration is None:
        return None
    input_name, input_type = declaration.groups()
    try:
        parsed_schema = _TypeScriptSchemaParser(input_type.strip()).parse()
    except ValueError, json.JSONDecodeError:
        return None

    if projection.input_mode == "freeform":
        if input_name != "input" or parsed_schema.get("type") != "string":
            return None
        parameters = {
            "type": "object",
            "properties": {projection.input_field: parsed_schema},
            "required": [projection.input_field],
            "additionalProperties": False,
        }
    else:
        if input_name != "args" or parsed_schema.get("type") != "object":
            return None
        parameters = parsed_schema

    description = section.split("exec tool declaration:", 1)[0].strip()
    return {
        "type": "function",
        "function": {
            "name": projection.chat_name,
            "description": description,
            "parameters": parameters,
        },
        "strict": False,
    }


def _javascript_json_literal(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


__all__ = [
    "ExecToolProjection",
    "build_exec_script",
    "exec_tool_projections_for_route",
    "project_exec_tool_definitions",
]
