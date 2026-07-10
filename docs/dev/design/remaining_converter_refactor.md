# Remaining Converter Refactoring Plan

## Background

The Codex-Rosetta project is refactoring all converters from the old single-file architecture to the Bottom-Up Ops Pattern.

### Completion status

All 4 converters have been refactored with Bottom-Up Ops Pattern.

| Converter | PR | Status |
|-----------|-----|------|
| OpenAI Chat | PR #16 | ✅ Completed |
| Anthropic | PR #22 | ✅ Completed |
| Google GenAI | PR #23 | ✅ Completed |
| OpenAI Responses | PR #24 | ✅ Completed |

## Refactoring Pattern (Based on the Completed Implementation)

Each converter is split into 5 files:

```
src/codex-rosetta/converters/{provider}/
├── __init__.py # Export all classes
├── content_ops.py # Inherit BaseContentOps
├── tool_ops.py # Inherit BaseToolOps
├── message_ops.py # Inherit BaseMessageOps (combine content_ops + tool_ops)
├── config_ops.py # Inherit BaseConfigOps
└── converter.py # Inherit BaseConverter (combine 4 Ops + streaming method)
```

Test structure:

```
tests/converters/{provider}/
├── __init__.py
├── test_content_ops.py
├── test_tool_ops.py
├── test_message_ops.py
├── test_config_ops.py
└── test_converter.py

tests/integration/
├── test_{provider}_sdk_e2e.py
└── test_{provider}_rest_e2e.py
```

## Completed Subtasks

### Subtask 1: Google GenAI Converter Refactoring ✅

- PR #23 merged
- Directory rename `google/` → `google_genai/` completed
- 4 Ops files + converter.py rewritten
- Layered testing completed

### Subtask 2: OpenAI Responses Converter Refactoring ✅

- PR #24 merged
- 4 Ops files + converter.py rewritten
- Layered testing completed

### Subtask 3: Cleanup ✅

- Delete the `src/codex-rosetta/utils/` directory and the `tests/utils/` directory
- Delete `src/codex-rosetta/types/providers/` empty directory
- Update `plans/architecture.md` (remove DEPRECATED mark, update refactoring status table)
- Update `src/codex-rosetta/converters/__init__.py` (restore export of all converters)
- Update `src/codex-rosetta/__init__.py` (restore export of all converters)

## Key Reference Documents

- **Architecture Design**: `plans/architecture.md`
- **Base ABC**: `src/codex-rosetta/converters/base/`
- **OpenAI Chat reference implementation**: `src/codex-rosetta/converters/openai_chat/`
- **Anthropic reference implementation**: `src/codex-rosetta/converters/anthropic/`
- **IR type**: `src/codex-rosetta/types/ir/`
- **Streaming event types**: `src/codex-rosetta/types/ir/stream.py`
