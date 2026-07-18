# Pipeline profile rounding flake
Date: 2026-07-09
Codex version: 0.144.0

This historical verification note explains one false-negative test result in an
earlier Codex compatibility run. It is not a current compatibility claim.

## Confirmed observations

- Main-thread verification `conda run -n llm-rosetta make test` failed at
  `tests/test_pipeline_profile.py::TestPipelineProfile::test_profile_populated_after_convert_request`;
  the run ended with `1 failed, 2377 passed, 4 skipped`.
- The isolated failing test passed, and a subsequent complete `pytest -q -x` run passed.
- A 20,000-iteration in-process repro failed at iteration 13,010 with rounded
  profile values `source_to_ir_ms=0.02`, `ir_transforms_ms=0.0`,
  `ir_to_target_ms=0.03`, `body_transforms_ms=0.0`, and
  `request_conversion_ms=0.04`. The rounded parts sum was `0.05`.
- Runtime phases and the total were each measured correctly, but every exported
  duration was independently rounded to 0.01 ms before the test added them.

## Root cause

The test's relative-only assertion was invalid for very fast conversions.
Independent rounding could overstate the four-part sum relative to the separately
rounded total by up to roughly 0.025 ms, larger than the 10% relative allowance
when the total was only a few hundredths of a millisecond.

## Fix and verification

- `tests/test_pipeline_profile.py` now uses 0.03 ms absolute tolerance for the
  four request phases and 0.02 ms for the two response phases, matching the
  worst-case 0.01 ms reporting quantization.
- The focused file passed all 5 tests.
- A 50,000-iteration stress run passed; its smallest observed assertion margin
  was approximately 0.02 ms.
- Final `make lint` passed, final `make test` passed with 2,378 passed and 4
  skipped, and `make check-codex-compat` passed with `Changed: None`.
