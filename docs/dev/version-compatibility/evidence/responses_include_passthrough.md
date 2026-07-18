# Responses Include Passthrough
Date: 2026-07-06
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Symptom

After preserving `reasoning` response output items, llm-rosetta sessions showed `reasoning` items but their `encrypted_content` field was `null`. Direct sessions had long encrypted reasoning content.

## Evidence

- Same-format `ConversionPipeline("openai_responses", "openai_responses")` dropped `include: ["reasoning.encrypted_content"]` from the request.
- Without the `include` field, upstream Responses providers can emit reasoning containers without encrypted reasoning content.

## Root Cause

`request_from_provider()` preserved only selected provider-native request extensions such as `allowed_tools`. It did not preserve OpenAI Responses `include`, so `request_to_provider()` had no provider extension to merge back into the upstream request.

## Fix

Preserve `include` in `provider_extensions` during OpenAI Responses request parsing. Existing request emission already merges provider extensions back into provider requests.

## Verification

- `python -m pytest tests/converters/openai_responses -q`
- `python -m pytest tests/test_pipeline.py -q`
- `ruff check src/llm_rosetta/converters/openai_responses/converter.py tests/converters/openai_responses/test_converter.py tests/converters/openai_responses/test_stream.py tests/test_pipeline.py`
- `ruff format --check src/llm_rosetta/converters/openai_responses/converter.py tests/converters/openai_responses/test_converter.py tests/converters/openai_responses/test_stream.py tests/test_pipeline.py`
- Synthetic same-format pipeline probe preserved `include: ["reasoning.encrypted_content"]`.
