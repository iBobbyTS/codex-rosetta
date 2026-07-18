# Remote compaction internal persistence
Date: 2026-07-15
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Confirmed observations

- Real task `01` (`deepseek-v4-flash`, run `202607151326`) triggers Remote
  Compaction V2 but fails before producing a mapping.
- Real task `04` (`deepseek-v4-flash -> gpt-5.6-terra`, run `202607151335`)
  fails in the same old-model summary route.
- Both gateway databases record conversion errors with the exact bounded text
  `Persistent tool-history storage is unavailable; refusing lossy replay`.
- `_run_rosetta_compaction()` calls the recursive `handle_non_streaming()` with
  `persistence=None`, even though the outer call has a valid
  `PersistenceManager` and body/error logging is already independently disabled.
- Real task `03` (`gpt-5.6-terra -> deepseek-v4-flash`, run `202607151330`)
  reaches Rosetta mode but the native summary response contains a tool call;
  this is a separate remaining symptom to reassess after the persistence fix.
- Post-fix run `202607151340` completes the full DeepSeek compaction and replay
  path. Its summary lacks all seven requested facts because task `01` did not
  inject them; the fixture was corrected before the final rerun.
- Corrected-fixture run `202607151343` completes canonical compaction and
  plaintext replay, but DeepSeek omits all seven facts in three summaries and
  reruns `scenario.py` three times under the 1000-token diagnostic threshold.
  This is recorded as ineffective summary quality and a task-level deviation,
  not a protocol failure.
- Post-fix Terra-to-DeepSeek run `202607151346` no longer has persistence
  failures, but all three `yieryier` internal summary responses contain no
  non-empty assistant text. Rosetta correctly returns 502 and creates no
  mapping, so the target DeepSeek turn is never reached.
- Post-fix DeepSeek-to-Terra run `202607151349` succeeds end to end: one
  `comp_hash_changed` Rosetta mapping is created, all seven fixture facts are
  present, and Terra returns the expected resume marker.

## Root-cause hypothesis

The Rosetta internal summary call must retain the outer persistence manager so
Responses-to-Chat conversion can replay existing tool history. Passing
`persistence=None` conflates request logging with converter state and causes a
hard refusal on real tool-bearing histories.

## Minimal fix

Pass the existing persistence object to the recursive summary call while
keeping `body_log_state=None`, `upstream_error_log_state=None`, and
`skip_codex_compaction=True`. Add a regression test proving those arguments are
independent, then rerun the real DeepSeek and switch fixtures.

## Resolution

The recursive summary call now receives the outer persistence manager while
`disable_error_dump=True` derives a separate no-op error-dump persistence.
Targeted tests, ruff, ty, the Codex compatibility contract, DeepSeek
context-limit replay, and DeepSeek-to-Terra switching verify the fix.
