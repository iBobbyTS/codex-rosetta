#!/usr/bin/env python3
"""Inspect LLM-Rosetta gateway logs and Codex rollout sessions.

The script streams JSONL files and prints bounded, redacted summaries. It is
intended for investigation, not mutation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


SESSION_ROOTS = (
    Path.home() / ".codex" / "sessions",
    Path.home() / ".codex" / "archived_sessions",
)
SECRET_KEY_RE = re.compile(
    r"(authorization|api[-_]?key|token|secret|password|cookie)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+)[A-Za-z0-9._~+/=-]+|sk-[A-Za-z0-9._-]{8,}",
    re.IGNORECASE,
)
SCALAR_TYPES = (str, int, float, bool)


def redact_text(value: str) -> str:
    return SECRET_VALUE_RE.sub(lambda m: (m.group(1) + "<redacted>") if m.group(1) else "sk-<redacted>", value)


def redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_obj(item)
        return redacted
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(redact_obj(value), ensure_ascii=False, sort_keys=True)
    text = redact_text(text).replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def walk(value: Any):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def parse_roots(values: list[str] | None) -> list[Path]:
    if not values:
        return list(SESSION_ROOTS)
    return [Path(value).expanduser() for value in values]


def path_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return "unknown"


def path_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "unknown"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def find_session_paths(query: str, roots: list[Path], scan_content: bool = False) -> list[Path]:
    direct = Path(query).expanduser()
    if direct.exists():
        return [direct]

    matches: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            if query in path.name and path not in seen:
                matches.append(path)
                seen.add(path)

    if matches or not scan_content:
        return sorted(matches, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)

    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            if path in seen:
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for raw in handle:
                        if query in raw:
                            matches.append(path)
                            seen.add(path)
                            break
            except OSError:
                continue
    return sorted(matches, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)


def resolve_session_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.exists():
        return path
    matches = find_session_paths(value, list(SESSION_ROOTS), scan_content=False)
    if not matches:
        raise SystemExit(f"No session file found for {value!r}. Try find-session --content.")
    if len(matches) > 1:
        print(f"Multiple session files matched {value!r}; using newest:", file=sys.stderr)
        for item in matches[:5]:
            print(f"  {item}", file=sys.stderr)
    return matches[0]


def iter_jsonl(path: Path, tail: int | None = None):
    if tail is not None and tail > 0:
        buffered: deque[tuple[int, str]] = deque(maxlen=tail)
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, 1):
                buffered.append((line_no, raw.rstrip("\n")))
        iterable = buffered
    else:
        handle = path.open("r", encoding="utf-8", errors="replace")
        iterable = ((line_no, raw.rstrip("\n")) for line_no, raw in enumerate(handle, 1))

    try:
        for line_no, raw in iterable:
            if not raw:
                continue
            try:
                yield line_no, json.loads(raw), raw, None
            except json.JSONDecodeError as exc:
                yield line_no, None, raw, exc
    finally:
        if tail is None or tail <= 0:
            handle.close()


def counter_lines(counter: Counter[str], limit: int = 20) -> list[str]:
    if not counter:
        return ["  none"]
    return [f"  {key}: {count}" for key, count in counter.most_common(limit)]


def extract_tool_names(tools: Any) -> list[str]:
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = tool.get("name") or function.get("name") or tool.get("tool_name")
        if not name:
            tool_type = tool.get("type")
            name = f"<{tool_type}>" if tool_type else "<unnamed>"
        names.append(str(name))
    return names


def scalar_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, SCALAR_TYPES):
        return str(value)
    return None


def collect_text_parts(value: Any, limit: int) -> list[str]:
    parts: list[str] = []
    for node in walk(value):
        if not isinstance(node, dict):
            continue
        for key in ("text", "summary", "output", "input"):
            item = node.get(key)
            if isinstance(item, str) and item.strip():
                parts.append(clip(item, limit))
        content = node.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(clip(content, limit))
        elif isinstance(content, list):
            for child in content:
                if isinstance(child, dict) and isinstance(child.get("text"), str):
                    parts.append(clip(child["text"], limit))
    return parts


def iter_relevant_nodes(value: Any):
    """Yield protocol-like nodes while skipping nested JSON Schema definitions."""
    stack: list[tuple[Any, tuple[str, ...]]] = [(value, ())]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            if not is_schema_node(node, path):
                yield node
                for key, item in reversed(list(node.items())):
                    stack.append((item, (*path, str(key))))
        elif isinstance(node, list):
            for index, item in reversed(list(enumerate(node))):
                stack.append((item, (*path, str(index))))


def is_schema_node(node: dict[str, Any], path: tuple[str, ...]) -> bool:
    if any(part in {"schema", "parameters", "$defs", "properties"} for part in path):
        return True
    if "$ref" in node or "$defs" in node:
        return True
    if "type" in node and "description" in node and (
        "properties" in node or "items" in node or "enum" in node or path[-1:] == ("model",)
    ):
        return True
    return False


@dataclass
class Summary:
    lines: int = 0
    matched_lines: int = 0
    bytes_raw: int = 0
    parse_errors: list[str] = field(default_factory=list)
    top_types: Counter[str] = field(default_factory=Counter)
    all_types: Counter[str] = field(default_factory=Counter)
    stages: Counter[str] = field(default_factory=Counter)
    levels: Counter[str] = field(default_factory=Counter)
    models: Counter[str] = field(default_factory=Counter)
    previous_response_ids: Counter[str] = field(default_factory=Counter)
    phases: Counter[str] = field(default_factory=Counter)
    tool_defs: Counter[str] = field(default_factory=Counter)
    tool_def_sizes: Counter[str] = field(default_factory=Counter)
    tool_calls: Counter[str] = field(default_factory=Counter)
    tool_outputs: Counter[str] = field(default_factory=Counter)
    response_events: Counter[str] = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)


def record_summary(summary: Summary, line_no: int, obj: Any, raw: str, args: argparse.Namespace) -> None:
    summary.matched_lines += 1
    summary.bytes_raw += len(raw.encode("utf-8", errors="replace"))
    if isinstance(obj, dict):
        top_type = scalar_text(obj.get("type"))
        if top_type is not None:
            summary.top_types[top_type] += 1
        stage = obj.get("stage")
        if stage is not None:
            summary.stages[str(stage)] += 1
        level = obj.get("level") or obj.get("levelname")
        if level is not None:
            summary.levels[str(level)] += 1

    for node in iter_relevant_nodes(obj):
        if not isinstance(node, dict):
            continue

        node_type = scalar_text(node.get("type"))
        if node_type is not None:
            summary.all_types[node_type] += 1
            if node_type.startswith("response."):
                summary.response_events[node_type] += 1

        model = node.get("model")
        if model is not None:
            summary.models[str(model)] += 1

        previous_response_id = node.get("previous_response_id")
        if previous_response_id is not None:
            summary.previous_response_ids[str(previous_response_id)] += 1

        phase = node.get("phase")
        if phase is not None:
            summary.phases[str(phase)] += 1

        tools = node.get("tools")
        tool_names = extract_tool_names(tools)
        if tool_names:
            summary.tool_def_sizes[str(len(tool_names))] += 1
            for name in tool_names:
                summary.tool_defs[name] += 1
            if len(summary.samples) < args.max_samples:
                summary.samples.append(
                    f"line {line_no}: tools[{len(tool_names)}] {', '.join(tool_names[:24])}"
                )

        call_name = node.get("name") or node.get("tool_name")
        call_id = node.get("call_id") or node.get("tool_call_id")
        has_call_shape = call_id and (
            call_name
            or "arguments" in node
            or "input" in node
            or node_type in {"function_call", "custom_tool_call", "tool_call"}
        )
        if has_call_shape:
            name = str(call_name or "<unnamed>")
            summary.tool_calls[name] += 1
            if len(summary.samples) < args.max_samples:
                payload = node.get("arguments", node.get("input", ""))
                summary.samples.append(
                    f"line {line_no}: tool_call {name} id={clip(call_id, 80)} payload={clip(payload, args.max_text_chars)}"
                )

        if node_type in {"function_call_output", "custom_tool_call_output", "tool_result", "tool_output"}:
            summary.tool_outputs[str(call_id or "<unknown>")] += 1
            if len(summary.samples) < args.max_samples:
                output = node.get("output", node.get("content", ""))
                summary.samples.append(f"line {line_no}: tool_output id={clip(call_id, 80)} output={clip(output, args.max_text_chars)}")

        warning = node.get("warning") or node.get("warnings")
        if warning and len(summary.warnings) < args.max_samples:
            summary.warnings.append(f"line {line_no}: {clip(warning, args.max_text_chars)}")

        error = node.get("error")
        if error and len(summary.errors) < args.max_samples:
            summary.errors.append(f"line {line_no}: {clip(error, args.max_text_chars)}")

        message = node.get("message")
        level = str(node.get("level") or node.get("levelname") or "").upper()
        if isinstance(message, str):
            if "WARNING" in level and len(summary.warnings) < args.max_samples:
                summary.warnings.append(f"line {line_no}: {clip(message, args.max_text_chars)}")
            if "ERROR" in level and len(summary.errors) < args.max_samples:
                summary.errors.append(f"line {line_no}: {clip(message, args.max_text_chars)}")

    if getattr(args, "show_text", False) and len(summary.samples) < args.max_samples:
        for text in collect_text_parts(obj, args.max_text_chars):
            if len(summary.samples) >= args.max_samples:
                break
            summary.samples.append(f"line {line_no}: text {text}")


def print_summary(title: str, path: Path, summary: Summary, max_items: int) -> None:
    print(f"# {title}")
    print(f"path: {path}")
    print(f"mtime: {path_mtime(path)}")
    print(f"size: {path_size(path)}")
    print(f"lines_scanned: {summary.lines}")
    print(f"lines_matched: {summary.matched_lines}")
    print(f"matched_raw_bytes: {summary.bytes_raw}")
    if summary.bytes_raw:
        print(f"approx_matched_tokens: {round(summary.bytes_raw / 4)}")

    sections = [
        ("top-level types", summary.top_types),
        ("all type fields", summary.all_types),
        ("stages", summary.stages),
        ("levels", summary.levels),
        ("models", summary.models),
        ("previous_response_id values", summary.previous_response_ids),
        ("phase values", summary.phases),
        ("tool definition sizes", summary.tool_def_sizes),
        ("tool names in definitions", summary.tool_defs),
        ("tool calls", summary.tool_calls),
        ("tool outputs", summary.tool_outputs),
        ("response events", summary.response_events),
    ]
    for heading, counter in sections:
        print(f"\n## {heading}")
        print("\n".join(counter_lines(counter, max_items)))

    if summary.parse_errors:
        print("\n## parse errors")
        for item in summary.parse_errors[:max_items]:
            print(f"  {item}")

    if summary.warnings:
        print("\n## warnings")
        for item in summary.warnings[:max_items]:
            print(f"  {item}")

    if summary.errors:
        print("\n## errors")
        for item in summary.errors[:max_items]:
            print(f"  {item}")

    if summary.samples:
        print("\n## samples")
        for item in summary.samples[:max_items]:
            print(f"  {item}")


def command_find_session(args: argparse.Namespace) -> int:
    roots = parse_roots(args.root)
    matches = find_session_paths(args.query, roots, scan_content=args.content)
    if not matches:
        print(f"No session files matched {args.query!r}.", file=sys.stderr)
        return 1

    for path in matches[: args.limit]:
        print(f"{path}\tmtime={path_mtime(path)}\tsize={path_size(path)}")
    if len(matches) > args.limit:
        print(f"... {len(matches) - args.limit} more matches omitted", file=sys.stderr)
    return 0


def command_session_summary(args: argparse.Namespace) -> int:
    path = resolve_session_path(args.session)
    summary = Summary()
    for line_no, obj, raw, error in iter_jsonl(path, tail=args.tail):
        summary.lines += 1
        if error is not None:
            if len(summary.parse_errors) < args.max_samples:
                summary.parse_errors.append(f"line {line_no}: {error}")
            continue
        record_summary(summary, line_no, obj, raw, args)
    print_summary("Codex session summary", path, summary, args.max_items)
    return 0


def command_log_summary(args: argparse.Namespace) -> int:
    path = Path(args.log).expanduser()
    if not path.exists():
        print(f"Log file not found: {path}", file=sys.stderr)
        return 1

    stage_filter = set(args.stage or [])
    summary = Summary()
    for line_no, obj, raw, error in iter_jsonl(path, tail=args.tail):
        summary.lines += 1
        if args.session_id and args.session_id not in raw:
            continue
        if error is not None:
            if not args.session_id and len(summary.parse_errors) < args.max_samples:
                summary.parse_errors.append(f"line {line_no}: {error}")
            continue
        if stage_filter and isinstance(obj, dict) and str(obj.get("stage")) not in stage_filter:
            continue
        record_summary(summary, line_no, obj, raw, args)
    print_summary("LLM-Rosetta gateway log summary", path, summary, args.max_items)
    return 0


def add_common_summary_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tail", type=int, help="Only inspect the final N lines.")
    parser.add_argument("--max-items", type=int, default=20, help="Maximum counter rows per section.")
    parser.add_argument("--max-samples", type=int, default=30, help="Maximum detailed samples.")
    parser.add_argument("--max-text-chars", type=int, default=240, help="Maximum characters per sample snippet.")
    parser.add_argument("--show-text", action="store_true", help="Include bounded text/content snippets.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    find_parser = subparsers.add_parser("find-session", help="Find Codex rollout sessions by id or filename fragment.")
    find_parser.add_argument("query")
    find_parser.add_argument("--root", action="append", help="Session root to search. Defaults to ~/.codex sessions roots.")
    find_parser.add_argument("--content", action="store_true", help="Stream-scan file contents when filename lookup fails.")
    find_parser.add_argument("--limit", type=int, default=20)
    find_parser.set_defaults(func=command_find_session)

    session_parser = subparsers.add_parser("session-summary", help="Summarize a Codex rollout session JSONL.")
    session_parser.add_argument("session", help="Session id, filename fragment, or path.")
    add_common_summary_args(session_parser)
    session_parser.set_defaults(func=command_session_summary)

    log_parser = subparsers.add_parser("log-summary", help="Summarize an LLM-Rosetta gateway JSONL log.")
    log_parser.add_argument("log", help="Path to a gateway JSONL log.")
    log_parser.add_argument("--session-id", help="Filter lines containing this session id.")
    log_parser.add_argument("--stage", action="append", help="Only include a gateway log stage. May be repeated.")
    add_common_summary_args(log_parser)
    log_parser.set_defaults(func=command_log_summary)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
