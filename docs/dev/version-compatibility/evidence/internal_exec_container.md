# Internal exec container in Chat Default
Date: 2026-07-14
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Root cause

`custom.exec` inherited a Modified guidance policy solely so the pre-conversion Profile filter would not delete the container that owns Codex's live nested tool declarations. The Chat localization layer also treated raw parent exposure as a fallback whenever no visible child parsed.

## Fix

- Chat Default declares `custom.exec` Disabled and marks it as an internal container when Disabled.
- Responses-to-Chat source filtering retains that container for conversion; other routes apply Disabled normally.
- Chat localization parses selected child declarations, retains reverse-translation metadata, and always removes the Disabled parent before the upstream request.
- An unparseable container now fails closed and resets an `exec` tool choice to `auto` instead of exposing raw `exec`.
- A copied Profile can still explicitly choose Pass through or Modified when raw parent exposure is intentional.

## Verification

- Focused catalog, Profile, projection, proxy, passthrough, and transform suite: `116 passed`.
- Full lint: Ruff, format, Ty, and complexity ratchet passed.
- Full unit suite: `3148 passed, 5 skipped`.
- CodeGraph synchronized after the source edits.
