# Codex-Rosetta Code Audit Ledger — Round 16

Audit started: 2026-07-10 14:53 America/Edmonton  
Profile: `.agent-work/audit/PROFILE.md` (`Draft`)  
Assumption: the user requested immediate continuation, so the draft compatibility-focused profile is used without waiting for owner approval. Unknown governance fields remain report gaps.

| Area | Status | Severity | Files | Notes |
| --- | --- | --- | --- | --- |
| Repository reality and prior audit state | Reviewed | No Action | worktree, recent commits, `.agent-work/audit/*` | Round 16 starts from current dirty worktree; no staged diff; prior Round 15 closed its DOM-XSS finding. |
| Admin dynamic rendering and control-plane response sinks | Reviewed | No Action | `src/codex_rosetta/gateway/admin/admin.html`, admin JSON/profiling routes | Dynamic external/config values use contextual encoding or DOM text APIs; no second exploitable sink confirmed. |
| SDK compatibility alert workflow | Reviewed, repaired | No Action | `.github/workflows/sdk-compatibility.yml`, `tests/test_workflow_contracts.py` | Failure branch now has exact job-level issue permission and a structured safe-trigger contract test. |
| CI, release, and supply-chain sampling | Reviewed | Track as Debt | `.github/workflows/*`, `pyproject.toml`, Docker/Makefile | Main CI and local-wheel build paths are coherent; immutable action pinning and dependency policy remain owner-defined gaps. |
| Verification and report | Reviewed | No Action | lint/tests, compatibility/release gates, `REPORT.md` | Lint/type and 2,725-test non-integration suite pass; compatibility/release/diff/CodeGraph gates pass. |

## Repository reality and prior audit state

- **Status:** Reviewed
- **Severity:** No Action
- **Scope:** `git status --short --branch`, `git log -5`, latest audit reports, profile, repository inventory.
- **Focus:** stale-state detection, dirty-worktree ownership, active-audit collision, baseline scope.
- **Evidence:** branch `master` is one commit ahead of `origin/master` at `eb94742 feat(admin): add read-only tool catalog`; worktree contains a large pre-existing patch (97 tracked modified files and 31 untracked files at survey time), no staged files, and no `.agent-work/audit/CURRENT.md`. Round 15 reports one repaired Admin usage DOM-XSS and a full green local gate.
- **Verification:** direct shell inspection on 2026-07-10 14:53 MDT.
- **Gaps / Assumptions:** user-owned and other-agent changes must be preserved; prior reports inform sampling but are not treated as proof of current behavior.

## Admin dynamic rendering and control-plane response sinks

- **Status:** Reviewed
- **Severity:** No Action
- **Scope:** `admin.html` dynamic HTML/attribute/URL sinks; provider/model/key/log/metrics/test/diagnostic renderers; profiling result HTML and ZIP routes; `tests/gateway/test_admin_page_routes.py` and browser regression.
- **Focus:** stored/reflected DOM XSS, inline-handler breakout, same-origin generated HTML, malicious provider/config/log data, download filenames.
- **Evidence:** provider/model/key/log fields pass through `esc()`, `escAttr()`, or `handlerArg()`; model-test provider response fields use `textContent` and safe DOM construction after Round 15; diagnostics escape external text; profiling summaries escape model/source/target. `viewFlamegraph()` executes only the locally generated `pyinstrument.output_html()` document, while the user-controlled model metadata is not interpolated into that HTML. ZIP names replace `/` and `:`, and a usable profile model must already be configured by the Admin; no lower-privilege path to an extraction traversal was confirmed.
- **Verification:** direct source-to-sink inspection and existing source/browser test review.
- **Gaps / Assumptions:** no new real-browser run was required for unchanged sinks; third-party `pyinstrument` HTML generation is treated as trusted installed code, not untrusted provider output.

## Finding F-01 — SDK compatibility failure could not create its alert issue (resolved)

- **Status:** Reviewed, repaired
- **Severity:** No Action
- **Scope:** `.github/workflows/sdk-compatibility.yml:1-86`; live GitHub repository Actions permissions and labels.
- **Focus:** operational alert delivery, CI permissions, regression-monitor ownership.
- **Finding:** the scheduled workflow intentionally calls `github.rest.issues.create()` after an SDK compatibility failure, but neither the workflow nor the job grants `issues: write`. The live repository reports `default_workflow_permissions: read`, so `GITHUB_TOKEN` cannot create the issue on the only branch where the alert is needed.
- **Trigger:** a scheduled/manual SDK compatibility run reaches a failing type-test outcome; `continue-on-error: true` advances to the `actions/github-script@v9` step, whose Issues API call is rejected for insufficient token permissions.
- **Impact:** the compatibility monitor fails to deliver its durable issue alert. Maintainers must notice the failed Actions run directly; the repository's stated weekly SDK-drift notification path is not operational. This does not change gateway runtime behavior, so it is `Should Plan`, not `Must Fix`.
- **Evidence:** `gh api repos/iBobbyTS/codex-rosetta/actions/permissions/workflow` returned `{"default_workflow_permissions":"read","can_approve_pull_request_reviews":false}`; workflow-list API reports the workflow active; `gh run list --workflow sdk-compatibility.yml` returned no runs; the live label list also lacks `sdk-compatibility` and `automated`.
- **Verification:** live read-only GitHub API inspection plus current source inspection. The failure branch was not externally triggered because that would mutate remote Actions state.
- **Suggested fix direction:** add least-privilege workflow/job permissions (`contents: read`, `issues: write`), provision or deliberately omit the two labels, then run `workflow_dispatch` with a controlled failing test or extract/test the alert action separately. Keep the normal test job read-only.
- **Gaps / Assumptions:** GitHub could change token defaults later, but the current repository setting is direct evidence. Missing labels are secondary; the permission failure occurs first and is sufficient to establish the finding.
- **Resolution:** `.github/workflows/sdk-compatibility.yml` now grants exactly `contents: read` and `issues: write` on the sole `sdk-compatibility` job. The workflow remains schedule/manual-only and has no PR, fork, push, or workflow-chaining trigger. The nonexistent-label filter and create parameters were removed, so delivery no longer depends on mutable repository label setup while title-based duplicate suppression remains.
- **Regression protection:** `tests/test_workflow_contracts.py` parses the YAML structure and asserts the exact trigger set, absence of workflow-wide permissions, exact job-level permission map, test step command and `PIPESTATUS` propagation, failure-only issue condition, pinned `github-script` action, Issues API calls, repository context, and no label dependency.
- **Repair verification:** targeted contract tests passed; full lint/type and non-integration suite passed; Codex compatibility and release-version gates passed. No remote workflow or issue was triggered.

## CI, release, and supply-chain sampling

- **Status:** Reviewed
- **Severity:** Track as Debt
- **Scope:** `.github/workflows/ci.yml`, `docker-safety.yml`, `sdk-compatibility.yml`, Dependabot, `pyproject.toml`, `Makefile`, Docker build/entrypoint/Compose.
- **Focus:** required gates, supported Python versions, local-source artifact integrity, privilege, dependency/action pinning, publication paths.
- **Evidence:** CI runs lint/type/full non-integration tests and clean-wheel smoke on Python 3.10/3.13; Docker builds only the current local wheel and runs as `appuser`; automated package/registry publication is disabled. GitHub Actions use moving major tags and most optional dependencies are unbounded, while the Draft profile leaves signing/SBOM/dependency policy undefined.
- **Verification:** static inspection. Remote Actions have not run in this repository yet.
- **Gaps / Assumptions:** immutable SHA pinning, vulnerability/license response, artifact signing/SBOM, and branch-protection policy remain owner decisions and are not promoted to a new implementation defect in this round.

## Independent verification

- **Status:** Reviewed
- **Severity:** No Action
- **Scope:** current worktree, staged/unstaged diff, lint/type checks, full non-integration tests, remote workflow metadata.
- **Focus:** repository reality, regression gate, stale conclusions, evidence freshness.
- **Evidence / commands:**
  - `conda run -n llm-rosetta python -m pytest tests/test_workflow_contracts.py -vv` — **2 passed**.
  - `conda run -n llm-rosetta make lint` — passed after formatting the new test: Ruff, format check for 292 files, and `ty`.
  - `conda run -n llm-rosetta make test` — collected 2,725 tests; **2,720 passed, 5 skipped, 9 warnings** in 14.85 seconds.
  - `conda run -n llm-rosetta make check-codex-compat` — passed at Codex source commit `2e8c3756f95789c215d9ea9a5ade6ec377934b3f`; Changed: None, with 12 documented Possibly unchanged groups.
  - `conda run -n llm-rosetta make check-release-version RELEASE_TAG=v0.144.0.r0` — passed.
  - `git diff --check` and `git diff --cached --check` — passed.
  - `codegraph sync` — passed (`Already up to date`).
  - Final pre-report `git status --short --branch` — branch still one commit ahead; 98 tracked modified files and 32 untracked files; no staged diff. Audit artifacts are ignored and do not appear in status.
  - GitHub read-only API — workflow active; default workflow permission remains read; no historical run is available.
- **Gaps / Assumptions:** `actionlint` was not installed, so the structured repository contract tests and project gates were used instead. No credentialed integration/agentabi/live provider matrix, external workflow dispatch, vulnerability/license scan, load/capacity run, backup/restore drill, or real release/deploy/rollback was run. The skipped browser test is opt-in and was not rerun in this independent pass.

## Simplification pass

- The finding was resolved with a small permission declaration, removal of a nonexistent-label dependency, and alert-path validation; it did not require a new CI abstraction, bot, service, or dependency.
- The existing SDK monitor can remain one workflow. Avoid granting broad `write-all`; grant only `contents: read` and `issues: write` at the narrowest practical scope.
- No runtime code deletion or consolidation is recommended from this round's source-to-sink sampling.
