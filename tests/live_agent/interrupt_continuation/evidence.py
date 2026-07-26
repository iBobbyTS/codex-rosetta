"""Credential-free trace evidence extraction for interrupt cells."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def trace_usage(path: Path) -> list[dict[str, Any]]:
    """Extract request-level usage without copying prompt or output content."""

    requests: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return []
    for line in path.open(encoding="utf-8"):
        event = json.loads(line)
        request_id = event.get("request_id")
        if not isinstance(request_id, str):
            continue
        entry = requests.setdefault(request_id, {"request_id": request_id})
        data = event.get("data")
        if event.get("stage") == "target_request" and isinstance(data, dict):
            messages = data.get("messages")
            if isinstance(messages, list):
                entry["target_message_count"] = len(messages)
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict) and isinstance(data, dict):
            response = data.get("response")
            usage = response.get("usage") if isinstance(response, dict) else None
        if isinstance(usage, dict):
            values = {
                key: usage.get(key)
                for key in ("input_tokens", "output_tokens", "total_tokens")
                if isinstance(usage.get(key), int)
            }
            details = usage.get("input_tokens_details")
            if isinstance(details, dict):
                for key in ("cached_tokens", "cache_write_tokens"):
                    if isinstance(details.get(key), int):
                        values[key] = details[key]
            if values:
                entry["usage"] = values
    ordered = list(requests.values())
    previous_cached: int | None = None
    for entry in ordered:
        usage = entry.get("usage")
        cached = usage.get("cached_tokens") if isinstance(usage, dict) else None
        entry["cached_tokens_delta"] = (
            cached - previous_cached
            if isinstance(cached, int) and isinstance(previous_cached, int)
            else None
        )
        if isinstance(cached, int):
            previous_cached = cached
    return ordered
