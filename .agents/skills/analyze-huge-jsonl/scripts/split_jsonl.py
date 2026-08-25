#!/usr/bin/env python3
"""Bounded, resumable hourly splitter for JSONL files."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

MAX_READ = 2 * 1024**3
CHUNK = 1024 * 1024
MAX_RECORD = 128 * 1024 * 1024
STAMP = re.compile(rb'[" ]timestamp[" ]\s*:\s*"([^"\\]+)"')


def load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def identity(path: Path) -> str:
    info = path.stat()
    return f"{info.st_dev}:{info.st_ino}"


def timestamp_from_prefix(prefix: bytes) -> datetime | None:
    match = STAMP.search(prefix)
    if not match:
        return None
    value = match.group(1).decode("utf-8", errors="replace")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def records(path: Path, start: int, budget: int) -> Iterator[tuple[int, bytes]]:
    """Yield complete lines while keeping reads and line memory bounded."""
    consumed = 0
    with path.open("rb") as source:
        source.seek(start)
        while consumed < budget:
            line = source.readline()
            if not line:
                return
            if len(line) > MAX_RECORD:
                raise RuntimeError("a single JSONL record exceeds 128 MiB")
            consumed += len(line)
            yield start + consumed, line


def split(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    output = Path(args.split_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / ".split-state.json"
    state = load_state(state_path)
    source_id = identity(source)
    sources = state.setdefault("sources", {})
    source_state = sources.setdefault(source_id, {"source": str(source), "offset": 0})
    offset = int(source_state.get("offset", 0))
    size = source.stat().st_size
    if size < offset:
        raise SystemExit("source shrank below checkpoint; refusing to reread")
    stats = state.setdefault("stats", {})
    records_seen = 0
    for new_offset, raw in records(source, offset, args.max_read_bytes):
        stamp = timestamp_from_prefix(raw[:4096])
        if stamp is None:
            target = output / ("invalid.jsonl" if b"timestamp" in raw[:4096] else "undated.jsonl")
        else:
            target = output / f"{stamp:%Y-%m-%dT%H}.jsonl"
        with target.open("ab") as handle:
            handle.write(raw)
        entry = stats.setdefault(target.name, {"bytes": 0, "records": 0})
        entry["bytes"] += len(raw)
        entry["records"] += 1
        offset = new_offset
        records_seen += 1
        if records_seen % 1000 == 0:
            source_state["offset"] = offset
            save_state(state_path, {"sources": sources, "stats": stats})
    complete = offset >= source.stat().st_size
    source_state["offset"] = offset
    state.update({"sources": sources, "stats": stats, "complete": complete})
    save_state(state_path, state)
    print(json.dumps({"complete": complete, "offset": offset, "source_size": source.stat().st_size, "stats": stats}, ensure_ascii=False, sort_keys=True))
    return 0


def validate(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    output = Path(args.split_dir).resolve()
    state = load_state(output / ".split-state.json")
    issues: list[str] = []
    source_id = identity(source)
    source_size = source.stat().st_size
    source_entries = state.get("sources", {})
    source_state = source_entries.get(source_id)
    if not state.get("complete"):
        issues.append("checkpoint is not complete")
    if not source_state or int(source_state.get("offset", -1)) != source_size:
        issues.append("source inode/offset does not reach current source size")
    stats = state.get("stats", {})
    stat_bytes = sum(int(item.get("bytes", 0)) for item in stats.values())
    if stat_bytes != source_size:
        issues.append(f"checkpoint bytes {stat_bytes} != source size {source_size}")
    sampled: list[dict[str, Any]] = []
    for name, item in sorted(stats.items()):
        path = output / name
        if not path.is_file():
            issues.append(f"missing output {name}")
            continue
        actual_size = path.stat().st_size
        expected_size = int(item.get("bytes", -1))
        if actual_size != expected_size:
            issues.append(f"{name}: file bytes {actual_size} != checkpoint {expected_size}")
        if name.endswith(".jsonl") and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}\.jsonl", name):
            with path.open("rb") as handle:
                first = handle.readline()
                handle.seek(max(0, actual_size - MAX_RECORD))
                tail = handle.read(MAX_RECORD)
            last = tail.splitlines()[-1] if tail.splitlines() else b""
            hour = name[:13]
            for label, raw in (("first", first), ("last", last)):
                stamp = timestamp_from_prefix(raw[:4096])
                if stamp is None or stamp.strftime("%Y-%m-%dT%H") != hour:
                    issues.append(f"{name}: {label} sampled timestamp does not match hour")
            sampled.append({"file": name, "bytes": actual_size, "records": item.get("records", 0)})
    result = {"ok": not issues, "source_size": source_size, "split_bytes": stat_bytes, "files": len(stats), "sampled": sampled, "issues": issues}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not issues else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("split")
    command.add_argument("--source", required=True)
    command.add_argument("--split-dir", required=True)
    command.add_argument("--max-read-bytes", type=int, default=MAX_READ)
    check = sub.add_parser("validate")
    check.add_argument("--source", required=True)
    check.add_argument("--split-dir", required=True)
    args = parser.parse_args()
    if args.command == "split" and not 0 < args.max_read_bytes <= MAX_READ:
        parser.error("--max-read-bytes must be between 1 and 2147483648")
    return split(args) if args.command == "split" else validate(args)


if __name__ == "__main__":
    sys.exit(main())
