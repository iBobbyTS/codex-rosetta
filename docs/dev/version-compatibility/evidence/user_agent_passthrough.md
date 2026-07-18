# User-Agent passthrough
Date: 2026-07-06
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Symptom

Requests through the gateway did not preserve the client's `User-Agent` header to
the upstream provider.

## Evidence

- `gateway/app.py` built `extra_headers` with only `x-request-id` and
  `OpenResponses-Version`.
- `transport/http/transport.py` already merged `extra_headers` into upstream
  request headers, so the missing behavior was at the gateway handler boundary.
- `gateway/embeddings.py` used `send_passthrough` without passing
  `extra_headers`, so passthrough endpoints had the same gap.

## Root cause

Gateway handlers did not explicitly whitelist `User-Agent` into the existing
upstream header forwarding channel.

## Fix

- Added `gateway.headers.build_upstream_extra_headers` for the explicit upstream
  header whitelist.
- Main proxy handler now forwards `User-Agent`, `x-request-id`, and
  `OpenResponses-Version` through that helper.
- Embeddings passthrough now uses the same helper and passes `extra_headers` to
  `send_passthrough`.

## Verification

- `/Users/ibobby/miniconda3/envs/llm-rosetta/bin/python -m pytest tests/gateway/test_app_headers.py tests/gateway/test_embeddings.py -q`
- `/Users/ibobby/miniconda3/envs/llm-rosetta/bin/ruff check src/llm_rosetta/gateway/app.py src/llm_rosetta/gateway/embeddings.py src/llm_rosetta/gateway/headers.py tests/gateway/test_app_headers.py tests/gateway/test_embeddings.py`
- `/Users/ibobby/miniconda3/envs/llm-rosetta/bin/ruff format --check src/llm_rosetta/gateway/app.py src/llm_rosetta/gateway/embeddings.py src/llm_rosetta/gateway/headers.py tests/gateway/test_app_headers.py tests/gateway/test_embeddings.py`
- `git diff --check`
