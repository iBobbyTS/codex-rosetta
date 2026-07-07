---
name: rosetta-codex-readme-test
description: Run controlled Codex-through-LLM-Rosetta README editing tests in /Users/ibobby/Projects/AGENTS.md-test. Use when Codex needs to enable Rosetta backend logging, route a Codex CLI run through the gateway for a specific model, test whole-file README rewrite versus localized edit behavior, identify the resulting Codex session JSONL and Rosetta log, verify the real working-tree outcome, and then revert the test repository changes.
---

# Rosetta Codex README Test

## Purpose

Use this skill to run repeatable agent-behavior tests against
`/Users/ibobby/Projects/AGENTS.md-test` through `llm-rosetta-gateway`.
The test repository is disposable for content changes, but preserve diagnostics
and revert the repository after inspection.

## Defaults

- Default model: `deepseek-v4-flash`, unless the user explicitly specifies a
  different model.
- Temporary Rosetta gateway configs live under
  `/Users/ibobby/Projects/codex-rosetta/rosetta-test-config`.
- The isolated Codex home lives at
  `/Users/ibobby/Projects/codex-rosetta/codex-test-home`.
- Gateway trace logs and captured Codex stdout/stderr should be kept under
  `/Volumes/RAM Disk`.

## Workflow

1. Confirm the test repository exists:

   ```bash
   test -d /Users/ibobby/Projects/AGENTS.md-test
   ```

2. Confirm `llm-rosetta-gateway` is running and locate the active port. The
   usual local endpoint is `http://127.0.0.1:8765/v1`. When testing current
   uncommitted gateway code, prefer launching a separate gateway instance on a
   free port with a config copied into
   `/Users/ibobby/Projects/codex-rosetta/rosetta-test-config`, rather than
   changing or killing the user's main gateway.

   ```bash
   curl -sS http://127.0.0.1:8765/v1/models | python3 -m json.tool | sed -n '1,120p'
   ```

3. Enable Rosetta backend logging before starting the Codex run. Use the admin
   UI/API or the project's current config mechanism. Set:

   - log path: an explicit path under `/Volumes/RAM Disk`, for example
     `/Volumes/RAM Disk/<model>-readme-test-<timestamp>.jsonl`
   - model filter: the model being tested. Use `deepseek-v4-flash` by default,
     unless the user explicitly specifies another model such as `glm-5.2` or
     `gpt-5.5`

   If the exact admin API is uncertain, inspect existing gateway config/routes
   before changing anything. Do not leave broad logging enabled after the test.

4. Run a single Codex CLI test with an isolated `CODEX_HOME` if the user has not
   specified another home. A known-good minimal config can live at
   `/Users/ibobby/Projects/codex-rosetta/codex-test-home/config.toml` and point
   to the Rosetta base URL:

   ```toml
   model_provider = "rosetta"
   model = "deepseek-v4-flash"
   sandbox_mode = "danger-full-access"
   approval_policy = "never"
   model_reasoning_effort = "medium"

   [model_providers.rosetta]
   name = "rosetta"
   wire_api = "responses"
   requires_openai_auth = true
   base_url = "http://127.0.0.1:8765/v1"
   experimental_bearer_token = "none"

   [projects."/Users/ibobby/Projects/AGENTS.md-test"]
   trust_level = "trusted"
   ```

5. Choose exactly one prompt according to the test goal:

   Whole-file rewrite:

   ```text
   帮我重新组织一下README.md里的语言（重写整个文件）
   ```

   Localized edit:

   ```text
   帮我重新组织一下README.md里的语言（使用局部编辑，不要整体重写）
   ```

   Run the prompt non-interactively, capture stdout/stderr, and keep the command
   bounded:

   ```bash
   MODEL=deepseek-v4-flash
   CODEX_HOME=/Users/ibobby/Projects/codex-rosetta/codex-test-home \
     codex exec --json --skip-git-repo-check \
     -C /Users/ibobby/Projects/AGENTS.md-test \
     -m "$MODEL" '<prompt>' \
     > "/Volumes/RAM Disk/codex-readme-test-${MODEL}.jsonl" \
     2> "/Volumes/RAM Disk/codex-readme-test-${MODEL}.stderr"
   ```

6. Immediately disable Rosetta backend logging after the Codex run finishes,
   even if the run failed. Keep the generated log file for inspection.

7. Confirm the result from three evidence sources:

   - Working tree: run `git -C /Users/ibobby/Projects/AGENTS.md-test status --short`
     and inspect the README diff with `git diff -- README.md`. Do not judge
     answer quality unless the user explicitly asks; focus on whether the file
     changed and how.
   - Codex session JSONL: extract `thread_id` from the `codex exec --json`
     stdout, then locate the rollout under
     `/Users/ibobby/Projects/codex-rosetta/codex-test-home/sessions`. Search
     filenames first and avoid reading the full file because early system
     prompts are large.
   - Rosetta log: inspect the configured log path with bounded JSONL tools,
     filtering by model, request id, session id, or timestamp. Do not dump full
     logs into the reply.

8. Revert the test repository changes after evidence capture:

   ```bash
   git -C /Users/ibobby/Projects/AGENTS.md-test restore README.md
   git -C /Users/ibobby/Projects/AGENTS.md-test status --short
   ```

   If files other than `README.md` changed, stop and report them before
   reverting unless the user explicitly asked for broader cleanup.

## Safety Rules

- Keep this workflow scoped to `/Users/ibobby/Projects/AGENTS.md-test`.
- Do not run it in the llm-rosetta repository or any production project.
- Do not leave backend logging enabled.
- Do not read whole Codex rollout JSONL files or whole Rosetta JSONL logs.
- Redact API keys, bearer tokens, cookies, and authorization headers from any
  report.
- Revert only the test repository changes produced by this run. Do not reset or
  clean unrelated user work.

## Final Report

Report:

- model, prompt variant, exit status, and final assistant message if relevant
- working-tree status before cleanup and after cleanup
- Codex thread/session id and exact rollout JSONL path
- Rosetta log path and whether the expected request or requests appeared
- any warning or error that affects interpreting the test
