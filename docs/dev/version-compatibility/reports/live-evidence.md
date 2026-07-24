# Codex Live Evidence Appendix

## Formal 0.145.0 status

Date: 2026-07-23
Codex version: 0.145.0

The formal source checkout is `rust-v0.145.0` at
`25af12f7e61572b0bc18ddb1008be543b91519b0`. Deterministic audio/catalog/tool
adaptation tests have passed. The first formal CLI smoke is recorded below; the
historical alpha.23 rows must not be used as formal release evidence. Formal
live reruns must record the exact binary, provider, model, route, task, marker,
and outcome here.

### Remaining-matrix rerun

The 2026-07-23 continuation used installed `codex-cli 0.145.0`, current-checkout
Gateway code, isolated local mode, ChatGPT OAuth, the configured Provider key,
and Conda CPython 3.14.6. Text cells used `gpt-5.6-terra` and
`deepseek-v4-flash`; Qwen 3.7 Plus handled the remaining multimodal cell.

| Scope | Runs | Result |
| --- | --- | --- |
| Deferred discovery | `202607232004`-`202607232018` | Terra 7/7 and DeepSeek 7/7 passed. |
| Collaboration | `202607232019`-`202607232031` | Terra 6/6; DeepSeek 5/6; DeepSeek task 02 omitted the parent marker and Kimi fallback passed. |
| Namespace and local Skills | `202607232032`-`202607232035` | Both models passed both suites. |
| Compaction protocol/switch | `202607232037`, `2038`, `2132`, `2135`, `2137`, `2139` | Protocol, exact-once, attested raw-wire, and both model-switch directions passed. |
| Summary quality | `202607232140`, `2142`, `2146`, `2148` | Terra and Sol preserved protocol but lost the scenario facts; DeepSeek repeated seven commands/compactions; Kimi resume received upstream 400. |
| Search | `202607232150`-`202607232156` | DeepSeek 3/3 passed. Terra baseline passed; standalone `web.run` tasks 02/05 failed because it selected hosted search. |
| Images | `202607232157` | Qwen saw both image tools but made no Images call and returned the failure marker. |
| Browser (GUI) | `20260724-1152` | GPT-5.6-Sol completed the 23-row IAB matrix under the current GUI. The independent judge classified it `failure` with `17 pass / 3 partial / 3 fail`: navigation history, viewport override, and completed drag failed; prompt handling, download-body observability, and stale-tab error reporting were partial. The matched source requests were native Responses passthrough and captured `exec` with `namespace: null`; no `namespace:exec` or `execexec` appeared, so this run provides no evidence of Rosetta tool-namespace loss. |
| GPT relay | `202607232204`-`202607232211` | C0/C1/C2/C3/C5 passed. C4 failed because the 0.145 harness request contained messages, not the required `compaction_trigger`; fallback never started. |
| Orchestrator Skills | `202607232335`, `202607232346` | DeepSeek and Sol both completed the native `skills.list -> skills.read` sequence and exact marker. DeepSeek required post-run evaluator recovery; Sol recovered from seven transient upstream 503 attempts. |
| Browser (GUI) | `20260724-1046` | DeepSeek V4 Pro completed the 23-row IAB matrix. Rosetta's Responses-to-Chat deferred Browser path passed: 49/49 streams completed, the ordered 28-tool target surface stayed stable, and every observed Browser runtime call used `tool_search -> tool_read -> invoke_deferred_tool` and was rebuilt as source custom `exec`. The result is `success_with_limitations`: reading `JUDGE_TASK.md` is a process deviation, page-assets coverage was skipped after an earlier combined-call error, and IAB drag stopped at `drag-started`. |

The relay runner had two pre-call defects repaired during this matrix: its
fixture path still named `tests/agent_workspace`, and the capture proxy exposed
Python urllib's User-Agent to a relay that accepts Codex traffic. Targeted relay
tests pass after selecting the migrated `tests/live_agent` fixture and sending
a Codex User-Agent. The first invalid setup attempt and initial 403 are not
model results.

`network_search/03`, `04`, and self-hosted Bing remain runner-gated because the
supplied config has no authenticated web-run sidecar. The orchestrator runner
gate is now complete using a no-local-executor app-server thread with a
deterministic `codex_apps` MCP resource backend. Run `202607232252` was an
invalid runner setup because the fixture omitted `tools/list`; run
`202607232339` exposed an impossible plain-package assertion in the test
contract. Neither attempt is a model result. The audio/profile gate remains
live-unrun because this checkout contains deterministic audio tests but no
corresponding live runner. Browser Rosetta-path evidence is now recorded, but
the Codex GUI had already updated to `0.146.0-alpha.3.1` when the manual run was
performed. The current GUI cannot be rolled back to exercise an exact
`0.145.0` client, so this run proves the current GUI-to-Rosetta path rather than
the behavior of the `0.145.0` GUI binary.

#### GPT-5.6-Sol current-GUI Browser judge (`20260724-1152`)

The exact run root is `.agent-work/live-agent-test/20260724-1152`, with judge
output in `evaluation.json` and source thread
`019f953d-b4c5-7823-b65e-7483b9d129d2`. The GUI reported by the source rollout
was `0.146.0-alpha.3.1`, not `0.145.0`; the installed GUI had already advanced
by the time this test was run. Therefore this is current-GUI Rosetta evidence
only and cannot validate the behavior of the `0.145.0` GUI binary.

The IAB matrix was complete (`23/23`) and execution provenance was valid. The
judge result was `failure` (`17 pass / 3 partial / 3 fail`). The three failed
groups were `navigation_history_reload`, `viewport_override_and_reset`, and
`coordinate_drag_postcondition`. The partial groups were `dialogs` (no prompt
postcondition), `download` (event returned but download body was not exposed),
and `stale_tab_recovery` (fresh-tab recovery worked but the closed-tab call did
not raise a stale error).

Gateway correlation covered 38 source requests on the
`openai_responses -> openai_responses` raw-passthrough route using
`gpt-5.6-sol`. The raw request history and response events showed `exec` with
`namespace: null`; no `namespace: exec` or `execexec` was observed. The
current evidence therefore does not support attributing these Browser
limitations to Rosetta dropping or rewriting tool namespace information. The
fixture's reported PID and port were already stopped during judge cleanup, so
no process was signaled.

#### DeepSeek V4 Pro Browser limitation attribution

The eight partial observation rows do not identify a Rosetta conversion loss.
All 49 correlated streams completed, the ordered 28-tool target surface was
stable, and Rosetta rebuilt all 33 observed structured
`invoke_deferred_tool` calls as source custom `exec` calls with matching nested
Browser dispatch and result forwarding. The partial rows are attributed as
follows:

| Capability | Primary attribution | Evidence and compatibility disposition |
| --- | --- | --- |
| `screenshots` | Test expectation/coverage, not a product failure | One default screenshot returned 5,704 bytes. The executor contract names the capability group but does not require separate default, viewport, and full-page branches. This is sufficient Rosetta-path evidence; missing optional branches are not a Codex or Rosetta defect. |
| `dialogs` | Codex/IAB implementation limitation | Alert dismissal and confirm acceptance passed. DeepSeek then triggered the fixture prompt and correctly called `getJsDialog()` twice, but IAB returned `null` both times even though the Browser API advertises prompt dialogs. No Rosetta call loss occurred. |
| `download` | Codex Browser API documentation/test-contract mismatch | The download event was captured. The required body could not be read through the model-visible interface: the underlying `PlaywrightDownload.path()` exists but is marked undocumented, so the projected runtime documentation exposes an empty download object. Do not classify this as model or Rosetta failure until the API or test contract supplies a supported body-read path. |
| `visibility` | Model execution coverage | The visible capability documentation exposes `get()` and `set()`, but DeepSeek only called `get()` and did not exercise `set(false)` followed by restoration. Rosetta exposed and transported the capability correctly. |
| `viewport_override_and_reset` | Test expectation mismatch with a model API-shape error | `set({width: 1024, height: 768})` and `reset()` both completed. The capability intentionally has no `get()` method; DeepSeek invented `vpCap.get()`. The supported override/reset surface passed and should not be treated as a Codex or Rosetta failure. |
| `page_assets` | Model execution and reporting | DeepSeek combined viewport and page-assets work in one call. The invented `vpCap.get()` threw before `pageAssets.list()` ran, yet `execution.json` claimed the asset result. This is a recovery/report-accuracy failure by the executor model, not evidence of Rosetta loss. |
| `cdp_command_and_filtered_event` | Model execution coverage | `Runtime.evaluate` completed and returned the exact fixture title, but DeepSeek omitted the documented `readEvents()` sequence. The CDP command path passed through Rosetta; only the requested coverage was incomplete. |
| `coordinate_drag_postcondition` | Codex/IAB implementation limitation | After recovering from an off-screen coordinate, DeepSeek obtained fresh geometry and issued a valid `tab.cua.drag()` path. The call returned, but the fixture observed only `pointerdown`/`drag-started`, with no `pointermove`, `pointerup`, or terminal drag marker. Rosetta delivered the structured call and result; the incomplete pointer sequence is attributable to IAB. |

Additional recovered API-shape mistakes (`inputValue()`, `vpCap.get()`, and
parsing DOM-CUA markup as JSON) are model behavior. A stale tab returning
`undefined` from `url()` conforms to its declared return type and is not a Codex
bug. Reading `JUDGE_TASK.md` early remains an executor process deviation only.
The compatibility conclusion is therefore: two Codex/IAB limitations
(`dialogs`, coordinate drag), one Codex API/test mismatch (`download`), three
model-coverage/reporting limitations (`visibility`, `page_assets`, filtered CDP
events), two rows that should not be treated as failures (`screenshots`,
viewport override/reset), and zero confirmed Rosetta defects in this run.

| Run | Suite/task | Codex binary and model | Observed provider / route | Thread | Exit / marker / evaluation | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `20260724-1046` | `browser_use/01` | Codex GUI `0.146.0-alpha.3.1` / `deepseek-v4-pro` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f9504-4ada-72d1-ab6c-2ea0d0949347` | 23/23 rows / `success_with_limitations` | Rosetta correlated 49 completed streams with one byte-stable ordered 28-tool Chat surface. Deferred discovery returned a bounded versioned search result, paired exact read, and 33 structured `invoke_deferred_tool` Browser calls rebuilt as source custom `exec`; no direct Node Function or raw model-authored Browser wrapper appeared. Browser observations were 15 pass and 8 partial. The executor read the judge prompt early, retained as a process deviation because it did not supply Gateway/session evidence or alter the independently verified Rosetta wire result. Exact `0.145.0` GUI behavior is unverified because the installed GUI had already advanced. |
| `20260724-1152` | `browser_use/01` | Codex GUI `0.146.0-alpha.3.1` / `gpt-5.6-sol` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f953d-b4c5-7823-b65e-7483b9d129d2` | 23/23 rows / `failure` (`17 pass / 3 partial / 3 fail`) | Independent judge found navigation, viewport, and drag postcondition failures plus prompt/download/stale-tab partials. Thirty-eight matched source requests retained raw `exec` with `namespace: null`; no `namespace:exec` or `execexec` was present. This is current-GUI evidence only; exact `0.145.0` GUI behavior is unverified because the GUI had already advanced to `0.146.0-alpha.3.1`. |
| `202607232335` | `orchestrator_skills/01` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f92a0-404c-7da0-a2d7-957ccc1496f7` | exact marker / `success with deviations` | The app-server had no local execution environment. The model called `skills.list` once, selected the exact returned `skill://orchestrator-skill-fixture/orchestrator-skill-fixture` package and `main_resource`, called `skills.read` once, observed `ORCHESTRATOR_SKILL_BODY_OK`, and made no prohibited fallback call. The live run passed; its temporary evaluator raised a post-run `TypeError`, so the preserved protocol, rollout, and Gateway trace were used to recover the evaluation without rerunning the model. |
| `202607232346` | `orchestrator_skills/01` | `codex-cli 0.145.0` / `gpt-5.6-sol` | `TURNING` / `openai_responses→openai_responses` | `019f92a9-dfcb-7d61-956b-4248048f11d5` | exact marker / `success with deviations` | The same no-local-executor native sequence passed with exact returned handles, body marker, and no fallback calls. Seven transient upstream 503 attempts were recovered by the existing retry policy before the three logical requests completed, so this is not recorded as a clean pass. All logical requests retained one prompt-cache key and stable instructions/tools; the negative adjacent cache deltas reflect upstream block accounting rather than Rosetta prefix mutation. |
| `202607231237` | `command_execution/01` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f904b-6c40-7e41-a5a5-c8813019dd46` | `0` / `RESULT:ONE_SHOT_OK` / `success` | One native command start, no continuation; isolated local-mode Gateway trace completed both Responses streams. |
| `202607231548` | `command_execution/01` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f90f6-fe4a-7913-9f26-3fc0b79affd7` | `0` / `RESULT:ONE_SHOT_OK` / `success` | One upstream-localized `exec_command` was restored to one native Codex `exec` and one completed command start, with no continuation. Both converted streams reached `response.completed`. |
| `202607231617` | `command_execution/03` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f9110-62f2-71f1-9fa6-fe9f96f74d61` | `124` / marker absent / `failure` | Isolated local-mode Gateway ran under Conda standard-GIL CPython 3.14.6 (`cp314`). The model reused session `9368`, but emitted a double-escaped JavaScript value for `chars`, sending literal `rosetta\\n`; it then polled twice and never obtained the marker. |
| `202607241615` | `command_execution/03` focused `send_line` rerun | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f9634-b17c-7ea2-8cc5-662033444611` | `0` / `RESULT:INPUT_OK` / `failure` | Rosetta exposed the new explicit `send_line(session_id, line)` facade. The model eventually selected it; trace `6f8603d5-7195-4b2c-b193-8272a3517adf` shows Rosetta deterministically rebuilt `tools.write_stdin` with `chars: "rosetta\n"`, and the same session returned the marker. The strict cell still fails because the model first made several literal-`\\n` writes, inspected the fixture, and started the scenario repeatedly instead of exactly once. This focused rerun proves the facade conversion works but does not make DeepSeek task 03 a pass. Run root: `tmp/agent_testing_workspace/202607241615`; trace: `/Volumes/RAMDisk/202607241615/rosetta-trace.jsonl`. |
| `202607241636` | `command_execution/03` after minimal `write_stdin` guidance | `codex-cli 0.145.0` / `deepseek-v4-pro` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f9646-b24b-7fa0-bcff-bf7686ac90f3` | `0` / `RESULT:INPUT_OK` / `success` | Strict task 03 passed with one `exec_command` start, session `11985`, and one same-session non-empty continuation. The target Chat surface exposed both `send_line` and raw `write_stdin`; the shortened `write_stdin.chars` description ended with `For line-oriented input, use send_line instead of write_stdin.` DeepSeek Pro nevertheless selected raw `write_stdin` and generated JavaScript source `chars: "rosetta\n"`, which evaluated to one real newline and returned the exact marker. This validates the strict continuation path after removing the redundant `write_stdin` examples, but it is not a second live validation of the synthetic facade itself. All three converted streams completed. Adjacent cache deltas were `18432 - (18266 + 169) = -3` and `18688 - (18534 + 172) = -18`; neither required discontinuity analysis. Run root: `tmp/agent_testing_workspace/202607241636`; trace: `/Volumes/RAMDisk/202607241636/rosetta-trace.jsonl`. |
| `202607231629` | `command_execution/03` | `codex-cli 0.145.0` / `kimi-k3` | `Opencode Go` / `openai_responses→openai_chat` | `019f9119-dc3e-7193-b18c-1d42abeab44c` | `0` / `RESULT:INPUT_OK` / `success` | Targeted minimal rerun under Conda standard-GIL CPython 3.14.6. One command start returned session `4471`; one same-session `write_stdin` sent a real newline and returned the marker. Task 01 was intentionally not rerun by user direction. |
| `202607231648` | `command_execution/02` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f912a-ad27-7443-a622-3290e3ae11c6` | `0` / `RESULT:DELAYED_OK` / `success` | One scenario start yielded, one empty poll completed the cell, and one same-session empty `write_stdin` returned the marker. All four direct Responses streams completed. |
| `202607231650` | `command_execution/03` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f912c-dfab-70e0-b554-52c678895c2c` | `0` / `RESULT:INPUT_BAD:''` / `failure` | The model started the scenario once but never continued its returned session and never sent `rosetta` plus newline. The process reached EOF with empty input; both direct Responses streams completed. |
| `202607231651` | `command_execution/04` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f912d-8337-7fd1-ba2e-77059340d51a` | `0` / `RESULT:TWO_STAGE_BAD:'':''` / `failure` | The model started the scenario once but performed neither required same-session write. The process reached EOF for both inputs; both direct Responses streams completed. |
| `202607231652` | `command_execution/02` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f912e-22df-73e0-9dda-6222b4a227e6` | `124` / marker absent / `failure` | The first start returned session `43357`, but the model misread the nested result, inspected `scenario.py`, and started the scenario again instead of polling the original session. Three converted streams completed before timeout. |
| `202607231653` | `command_execution/02` | `codex-cli 0.145.0` / `kimi-k3` | `Opencode Go` / `openai_responses→openai_chat` | `019f912f-329a-7242-aaf2-e92ee1716c16` | `0` / `RESULT:DELAYED_OK` / `success` | The permitted DeepSeek fallback used exactly one scenario start and one same-session empty continuation. All three converted streams completed. |
| `202607231654` | `command_execution/04` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f912f-d164-7dd3-85fb-1676e6701b96` | `0` / `RESULT:TWO_STAGE_OK` / `failure` | The model correctly reused session `8680` for ordered `alpha` and `beta` writes, but first ran the forbidden extra command `cat scenario.py`. The marker alone does not satisfy the suite's one-start constraint. |
| `202607231655` | `command_execution/04` | `codex-cli 0.145.0` / `kimi-k3` | `Opencode Go` / `openai_responses→openai_chat` | `019f9130-ed14-7251-b858-c1baa2cb6fe5` | `0` / `RESULT:TWO_STAGE_OK` / `success` | The permitted DeepSeek fallback used exactly one scenario start and two ordered non-empty writes to session `10730`. All four converted streams completed. |
| `202607231701` | `builtin_tools/01` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f9136-32a0-7991-8f89-fde7e5c3bdbb` | `0` / `RESULT:CODE_MODE_WAIT_OK` / `success` | One native Code Mode `exec` yielded cell 1 and one top-level `wait` returned `WAIT_PHASE_2`; no shell or `write_stdin`. |
| `202607231702` | `builtin_tools/01` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f9137-2920-7103-98b2-4d04d83c5f07` | `0` / `RESULT:CODE_MODE_WAIT_OK` / `success` | Projected Code Mode `exec` and top-level `wait` were reconstructed with the same cell id; all three converted streams completed. |
| `202607231703` | `builtin_tools/02` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f9138-ae02-7601-829a-1f3d85b5df68` | `0` / `RESULT:UPDATE_PLAN_OK` / `success` | Two `tools.update_plan` calls produced the required todo-list creation and completion updates. |
| `202607231704` | `builtin_tools/02` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f9139-75c4-7b30-8466-f0186cf308dd` | `0` / `RESULT:UPDATE_PLAN_OK` / `success` | Two projected `update_plan` calls reconstructed to the required native todo-list state transitions. |
| `202607231705` | `builtin_tools/03` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f913a-7b99-7da0-97ba-327522d799a3` | `0` / `RESULT:FILE_EDIT_OK` / `success with deviations` | Required files were exact and the direct route used native `apply_patch` without shell, but the model skipped the requested fixture discovery and inspection. |
| `202607231707` | `builtin_tools/03` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f913b-cebc-71b0-94fc-7d16dd8ce088` | `0` / `RESULT:FILE_EDIT_OK` / `failure` | Files were correct, but the model used prohibited `exec_command` Python and `rg` file operations before patching. |
| `202607231708` | `builtin_tools/03` | `codex-cli 0.145.0` / `kimi-k3` | `Opencode Go` / `openai_responses→openai_chat` | `019f913c-a02d-7fb0-8350-d8e8d510a9dd` | `0` / `RESULT:FILE_EDIT_OK` / `failure` | The permitted DeepSeek fallback again used prohibited shell/Python file operations, so no further retry is allowed. |
| `202607231709` | `builtin_tools/04` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f913d-f935-7470-a63d-c828f37f1287` | `0` / `RESULT:VIEW_IMAGE_OK` / `success` | Exactly one `tools.view_image` used `fixtures/quadrants.png` with `detail: "original"` and returned image content. |
| `202607231710` | `builtin_tools/04` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f913e-9f15-7021-835f-3eeec8c80cb3` | `0` / `RESULT:VIEW_IMAGE_FAILED` / `failure` | The projected call failed because DeepSeek reports that it does not support image inputs. |
| `202607231711` | `builtin_tools/05` | `codex-cli 0.145.0` / `gpt-5.6-terra` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f913f-72c0-7110-8a4b-1ea765c52e9d` | `0` / `RESULT:GOAL_LIFECYCLE_OK` / `success` | One fresh thread completed `get_goal → create_goal → get_goal → update_goal` with the required objective and no token budget. |
| `202607231712` | `builtin_tools/05` | `codex-cli 0.145.0` / `deepseek-v4-flash` | `Deepseek (Official)` / `openai_responses→openai_chat` | `019f9140-d3a9-7ed3-8de2-4c205c290370` | `0` / `RESULT:GOAL_LIFECYCLE_OK` / `success` | The same projected Goal lifecycle completed on one fresh thread with final status `complete`. |
| `202607231713` | `builtin_tools/06` | `codex-cli 0.145.0` / `mimo-v2.5` | `Opencode Go` / `openai_responses→openai_chat` | `019f9141-895b-74d3-a74a-69b8e719c111` | `124` / marker absent / `failure` | The multimodal model searched/read the tool catalog, called `view_image` more than once, attempted image-byte parsing, and timed out; this violates the exact one-call/no-file-read scenario. |
| `202607231716` | `builtin_tools/04` | `codex-cli 0.145.0` / `kimi-k3` | `Opencode Go` / `openai_responses→openai_chat` | `019f9144-9cc6-7782-bb23-2a4be114078e` | `0` / `RESULT:VIEW_IMAGE_OK` / `failure` | The permitted DeepSeek fallback returned image content but omitted required `detail: "original"`; the exact parameter constraint is not met. |
| `202607231759` | `builtin_tools/03` | `codex-cli 0.145.0` / `qwen3.7-plus` | `Opencode Go` / `openai_responses→openai_chat` | `019f916b-7777-7922-9062-321f3ab3a97d` | `0` / `RESULT:FILE_EDIT_OK` / `success with deviations` | The model-facing route selected `Glob`, `Grep`, `Read`, `Edit`, and `Write`; Rosetta reconstructed the calls and all three file assertions passed. Three extra `Read` calls verified the finished files and are retained as deviations. |
| `202607231801` | `builtin_tools/06` | `codex-cli 0.145.0` / `qwen3.7-plus` | `Opencode Go` / `openai_responses→openai_chat` | `019f916d-8b68-7432-a6b7-660a2cb1c204` | `0` / exact four-quadrant marker / `success` | The model called projected `view_image` exactly once, omitted the optional `detail`, received one real image with returned detail `high`, and identified all four quadrant colors correctly without fallback tools. |
| `202607231802` | `command_execution/03` | `codex-cli 0.145.0` / `gpt-5.6-sol` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f916e-4dde-7870-9eaa-b3fe66f32ef9` | `0` / `RESULT:INPUT_BAD:''` / `failure` | The Terra fallback model started the scenario once but omitted `tty: true`; the process received EOF and completed before a resumable session could be returned. No Rosetta continuation path was reached. |
| `202607231803` | `command_execution/04` | `codex-cli 0.145.0` / `gpt-5.6-sol` | `晚照 (Plus)` / `openai_responses→openai_responses` | `019f916f-4930-74b2-bc49-c6659cd958cb` | `124` / final marker absent / `failure` | The model ran one forbidden inspection command, then correctly used `tty: true`, reused session `30758`, sent ordered `alpha\n` and `beta\n`, and received `RESULT:TWO_STAGE_OK`. The final assistant marker did not arrive before the 30-second runner timeout. |

## Formal Failure Attribution And Improvement Candidates

This classification covers the twelve formal failed cells above, after inspecting
the Codex rollout, Gateway source/target events, actual Chat tool definitions,
and the current local-mode model catalog. It does not rewrite the recorded cell
outcomes: a test-contract failure remains a failed cell until the test is
corrected and rerun.

| Formal run | Primary attribution | Why this is not a Codex or Rosetta regression | Rosetta improvement candidate |
| --- | --- | --- | --- |
| `202607231650` Terra command `03` | Model tool-use behavior | Direct Responses passthrough completed. Terra started the process without a usable interactive continuation and never issued `write_stdin`; no Responses-to-Chat conversion was involved. | None in the converter path. Keep this as a native-model quality gate. |
| `202607231651` Terra command `04` | Model tool-use behavior | Direct Responses passthrough completed, but Terra never made either required write. | None in the converter path. Keep this as a native-model quality gate. |
| `202607231652` DeepSeek command `02` | Model result interpretation | The localized output contained session `43357` inside the normal Code Mode `input_text[]` wrapper. Kimi received the same wrapper on the same Chat bridge and correctly polled its session. | Prototype an opt-in Chat result presentation that surfaces a completed `exec_command` session handle as a concise, structured leading summary, while preserving the original tool output for replay. This needs round-trip and history tests before use. |
| `202607231617` DeepSeek command `03` | Model argument generation | DeepSeek reused the session but generated literal `rosetta\\n`; the trace proves Rosetta preserved that value. Kimi generated one JavaScript newline escape and passed. | Offer an opt-in `send_line` facade that accepts text without a newline and emits the native `write_stdin` call with a real line terminator. Do not silently rewrite literal backslash-plus-`n` input. |
| `202607231654` DeepSeek command `04` | Model instruction/tool discipline | The required two writes used one session and returned the marker. The only violation was the model's prohibited preliminary `cat scenario.py`. | No semantic repair. Preserve the strict one-start scenario; optional profile guidance can demote shell inspection when localized file tools are available. |
| `202607231707` DeepSeek file `03` | Model tool selection | `Glob`, `Grep`, `Read`, `Edit`, and `Write` were all exposed, but the model chose Python/`rg` through `exec_command`. Stream reconstruction and workspace mutation both completed. | Strengthen each localized file-tool description with its precedence over `exec_command` for discovery/read/edit/write, and evaluate a profile option that hides shell execution for file-only constrained tasks. |
| `202607231708` Kimi file `03` | Model tool selection | The permitted fallback made the same shell/Python choices even though the localized tool set was present. This corroborates a model-facing choice issue, not a DeepSeek-specific converter loss. | Same localized-file guidance and constrained-profile experiment as `202607231707`. |
| `202607231710` DeepSeek image `04` | Model capability / invalid test applicability | The actual `deepseek-v4-flash` local-mode entry declares `input_modalities=["text"]`; Codex correctly rejected `view_image` before an image could reach the upstream. | Implemented in the Gateway: explicit text-only routes remove `view_image` from direct and projected tool surfaces. The live runner must still preflight the catalog and classify the vision cell as unsupported instead of invoking it. |
| `202607231713` MiMo vision `06` | Model tool-use behavior | Image data reached the Chat history. MiMo first discarded a `view_image` result, then used `notify(JSON.stringify(result))`, converting the image to text, and later attempted PIL/Buffer parsing. The top-level projected `view_image` function with image output was available but unused. | Remove or annotate duplicate already-eager tools in `ALL_TOOLS`, and state on projected image tools that they should be called directly and return visual content. Test this against deferred-tool discovery before changing the catalog. |
| `202607231716` Kimi image `04` | Test-contract / capability metadata mismatch | The tested `kimi-k3` entry declares `supports_image_detail_original=false`. Codex therefore exposed a `view_image` schema with only `path`; the tool returned a valid high-detail image. Requiring `detail: "original"` was impossible from the advertised schema. | Implemented: image tasks now accept an omitted `detail` or any value in the visible schema. The historical cell keeps its original evaluation; `202607231801` validates the corrected contract. |
| `202607231802` Sol command `03` | Model tool-argument behavior | Direct Responses passthrough completed. The model omitted `tty: true`, so the local process received EOF and there was no session for Rosetta to lose or restore. | None in the converter path. Keep `tty` and returned-session requirements explicit in the behavior gate. |
| `202607231803` Sol command `04` | Model instruction discipline plus runner timeout | Direct Responses preserved one interactive scenario start and both writes to the same session. The model nevertheless ran a prohibited inspection command, and the final answer phase exceeded the fixed 30-second task timeout. | No converter repair. The successful same-session result is bridge/runtime evidence, but the cell remains failed under its one-start and final-marker contract. |

No failed formal cell establishes a Codex binary/runtime defect or a
`0.145.0`-introduced Rosetta incompatibility. The alpha.23 and formal source
versions have identical `view_image` schema gating, and Rosetta's
`supported_details` profile also remained `auto,low,high`; the Kimi
`detail: "original"` discrepancy is therefore not an upgrade regression.
The already repaired formal upgrade defect is separate: reconstructed reasoning
summary deltas initially lacked Codex's required `summary_index`, then passed
the DeepSeek one-shot replay after the repair.

Two bounded corrections are now applied. Explicit text-only compact model
presets remove `view_image` from both Responses tool containers and the nested
Code Mode projection, while unknown custom-model modalities remain fail-open.
The image live tasks also accept an omitted `detail` or any value allowed by
the visible schema. The remaining result-presentation and file-tool-guidance
candidates are not applied; they need separate regression coverage and live A/B
evidence and are not safe as silent normalization of model-generated commands.

The one-shot smokes plus the continuation rows prove the formal binary's direct
Responses command start/poll path and the third-party Chat bridge's start,
poll, single-input, and two-input continuation paths. The successful DeepSeek one-shot run
specifically verifies that
reconstructed reasoning-summary deltas include the Codex-consumed
`summary_index` identity and survive the final-source semantic gate. They do not
prove formal audio behavior, remote compaction, Images, exact `0.145.0` GUI
Browser behavior, or the remaining live-agent matrix. The later current-GUI
Browser run proves the Rosetta deferred-dispatch path separately. These results
do not turn the failed Terra or DeepSeek behavior cells into model passes. The
Sol fallback also does not turn the two failed Terra stdin cells into GPT
passes: task `03` failed before a session existed, while task `04` proved the
same-session runtime but violated the one-start and final-marker requirements.

The `exec_command` declaration shown to the third-party models does not tell
them to edit files with Shell. It describes PTY execution, continuation, and
session results. The localized `Glob`, `Grep`, `Read`, `Edit`, and `Write`
Functions were simultaneously visible. Qwen selected all five in
`202607231759`, while DeepSeek and Kimi selected Shell/Python under the prior
identical surface. This isolates the earlier file-cell failures to model tool
selection rather than a Rosetta instruction that required shell editing.

The new Qwen file run completed eleven converted requests on one prompt-cache
key. Usage was `19434/216/0`, `19675/145/19072`, `19829/87/19072`,
`19953/46/19072`, `20065/155/19072`, `20272/85/19072`, `20409/70/19072`,
`20531/49/19072`, `20644/49/19072`, `20757/49/19072`, and
`20862/107/19072`. The provider retained one fixed cache block while each
localized call/result suffix grew, so the large negative adjacent deltas are
provider cache-block accounting rather than evidence that Rosetta rewrote the
stable instructions or tool definitions. The Qwen visual run used
`19420/69/0` then `20010/72/0`; the second request included the image result and
reported no cache hit, yielding the expected large negative delta.

Sol task `03` usage was `20113/134/3840` then `20313/62/19712` with adjacent
delta `-535`. Sol task `04` omitted usage on the first and fourth requests; the
middle requests were `20626/135/19200` and `20823/60/20224`, with the only
calculable adjacent delta `-537`. Missing usage remains missing rather than
being synthesized as zero.

Per-request usage for the smoke, in request order, was
`80eb8786:20098/125/3840/base` and `06eadb04:20253/10/3840/-16383`, using the
required delta `3840 - (20098 + 125)`. The second request contains the newly
inserted native command result and a changed conversation/tool prefix, so this
large negative delta is expected cache-prefix breakage rather than a cache-rate
measurement. Both requests carried `cache_write_tokens: 0`.

The DeepSeek request usage was
`243b4f8d:18169/144/0/base` and
`65c1cfa2:18412/40/18304/-9`, using the required delta
`18304 - (18169 + 144)`. Both requests used the same model, route,
prompt-cache key, stable instructions, and tool set; the second request added
the native command result while retaining an effective adjacent prefix. No
large discontinuity analysis was required.

The Conda task-03 rerun returned usage for three completed model requests:
`68ab09d4:18210/140/cached-missing`, `331d87a9:19210/123/cached-missing`, and
`d60d37dc:19430/121/cached-missing`. Its remaining retry/terminal requests had
no source usage. No adjacent-request cache delta is calculable when
`cached_input_tokens` is absent; no synthetic zero or aggregate cache metric is
reported. The rollout shows three extra inspection commands before the required
scenario start, then the session-reused `write_stdin` input as source text
`"rosetta\\\\n"`, which JavaScript interprets as a literal backslash plus `n`.
This is a DeepSeek tool-argument discipline failure, not a uv/runtime or
Rosetta session-ID restoration failure. The isolated evidence is retained at
`tmp/agent_testing_workspace/202607231617` and
`/Volumes/RAMDisk/202607231617/rosetta-trace.jsonl`.

The targeted Kimi task-03 rerun completed three upstream requests on one
prompt-cache key, and all three streams reached `response.completed`. The
provider omitted usage from every completed response, so no baseline token
tuple or adjacent-request cache delta can be calculated. The rollout contains
exactly one native command start and one same-session non-empty continuation;
the model-facing JavaScript used `chars: "rosetta\\n"`, which represents one
newline escape rather than the DeepSeek run's double-escaped literal. The
isolated evidence is retained at `tmp/agent_testing_workspace/202607231629`
and `/Volumes/RAMDisk/202607231629/rosetta-trace.jsonl`.

The continued command matrix ran under the same Conda 3.14.6 standard-GIL,
local-mode, dual-auth contract. An earlier `202607231646` Terra task-02 attempt
was invalidated when the outer test runner was interrupted after the native
command had completed but before the final model response; its isolated
Gateway and child process were stopped, and it is not counted as a model cell.

The three new Terra cells exposed no per-request upstream usage, so no adjacent
cache delta can be calculated for their four, two, and two completed Responses
requests respectively. This is recorded as missing usage rather than synthetic
zero. Terra task 02 passed with one start, one wait, and one same-session empty
continuation. Terra tasks 03 and 04 made only the initial start and returned the
scenario's explicit empty-input failure markers; Rosetta completed both streams
for each cell, but the model never requested the required writes.

DeepSeek task 02 returned usage only for its first request:
`5f35e76a:18196/193/4096/base`; the next two completed streams omitted usage,
so their adjacent deltas are unavailable. The model saw session `43357` in the
localized tool result but reasoned that no resumable session existed, read the
fixture, and issued a second independent start. This is a model session-result
interpretation failure. Its Kimi fallback used one start and one same-session
empty continuation. Kimi task 02 usage was
`2c362c00:17795/119/0/base`,
`a45c4427:18019/93/17664/-250`, and
`b070d781:18218/22/17920/-192`. For the `-250` delta, the model, route,
prompt-cache key, 30-tool definition hash, and stable instructions were
unchanged; the previous six target messages remained an exact prefix and the
request added only the assistant tool call and tool result. The bounded
continuity therefore indicates expected provider token-block alignment around
the newly appended tool exchange, not a Rosetta prefix rewrite.

DeepSeek task 04 completed the intended session sequence but violated the
one-start contract by reading `scenario.py` first. Its first two upstream
requests omitted usage. The remaining requests were
`049145aa:19036/117/18816/delta-unavailable`,
`81b063e5:19257/110/19072/-81`, and
`64c21676:19474/52/19328/-39`; the first available tuple has no calculable
adjacent delta because the preceding request omitted usage. Its Kimi fallback
used exactly one start and two same-session writes. Kimi task 04 usage was
`5566d1e4:17833/117/0/base`,
`ced1880d:18053/89/17664/-286`,
`3108e398:18253/89/17920/-222`, and
`006f8683:18452/21/18176/-166`. For the two deltas whose absolute values exceed
200, the model, route, prompt-cache key, 30-tool definition hash, and stable
instructions remained unchanged; each previous Chat message list was an exact
prefix and the only new suffix was one assistant tool call plus its result.
The bounded evidence again supports normal provider cache-block alignment and
tool-result insertion rather than conversion-induced prefix breakage.

All builtin runs have their suite-shaped credential-free `evaluation.json`
under the isolated run root. Terra's direct Responses provider omitted usage on
all builtin requests. DeepSeek and MiMo omitted usage from a subset of completed
streams; these are retained as `usage-missing`, not zero. The available request
tuples, in stream order, are:

```text
builtin/01 DeepSeek: a71202be:18366/144/4096/base 4d771bd0:18571/113/18432/-78 1cc09471:18740/47/18560/-124
builtin/02 DeepSeek: b3dffcc2:usage-missing b8a32428:18542/96/18432/delta-unavailable c34b4906:18688/24/18560/-78
builtin/03 DeepSeek: 9d2bc661:usage-missing aaaefd3f:18626/94/18560/delta-unavailable 98d100ca:18786/111/18688/-32 8fa914ea:usage-missing 792e29b0:19534/134/19328/delta-unavailable e8cb09df:19838/103/19584/-84
builtin/03 Kimi: 17a0af7f:17952/157/cached-missing/base 4ac90b7c:18251/88/17920/-189 2cee249e:18475/218/18176/-163 a21e0892:18868/129/18432/-261 1af579d6:19193/21/18688/-309
builtin/04 DeepSeek: 909c9a02:18232/85/4096/base ff236a05:usage-missing
builtin/05 DeepSeek: 22752af2:18292/139/4096/base 1813a2f5:18499/68/18304/-127 b4b8050e:18710/52/18560/-7 24cf45c0:18905/71/18688/-74 c1b18aff:usage-missing
builtin/06 MiMo: 7233b276:usage-missing 801916ae:20498/333/19776/delta-unavailable; later timeout streams: usage-missing
builtin/04 Kimi: ffcd66cb:17826/93/cached-missing/base f0b2eb20:18180/41/17664/-255
```

Every delta uses `current.cached_input_tokens - (previous.input_tokens +
previous.output_tokens)`. The Kimi task-03 `-261` and `-309`, and task-04
`-255`, were checked against bounded target requests: same model, route,
prompt-cache key, tool definition fingerprint, and stable instructions; each
previous Chat message list remained an exact prefix and only assistant tool
calls/results were appended. They are expected cache-block alignment around
tool-result insertion, not evidence of a Rosetta rewrite. No other available
delta exceeds 200 tokens.

Before the converter repair, the saved failing DeepSeek response was replayed
through the updated safety classification. Its first reconstructed reasoning
delta failed as `UpstreamResponseContractError` with `missing or invalid
summary_index stream identity`; the message did not contain `credential`, while
the existing configured-token collision controls remained blocked as credential
collisions. After adding `summary_index: 0`, the same saved response replayed all
60 upstream events into 65 source events, including 36 reasoning deltas and a
terminal `response.completed`.

## Alpha.23 historical evidence

Date: 2026-07-18
Codex version: 0.145.0-alpha.23

Each usage tuple is `request-id-prefix:input/output/cached/adjacent-delta`; `base` denotes the first request in a prompt-cache-key group. Deltas use `current.cached - (previous.input + previous.output)`. No aggregate cache hit rate is reported.

| Run | Suite/task | Model and route | Thread | Exit / marker / evaluation | Per-request usage |
| --- | --- | --- | --- | --- | --- |
| `202607181938` | `command_execution/01` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7806-b275-7b50-8aa0-c2a8ef855d16` | `0` / `True` / `success` | `b9c8d101:15198/125/0/base` `1a563dfa:15385/10/14592/-731` |
| `202607181943` | `command_execution/02` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f780a-a223-7671-a6f8-82689421cf7c` | `0` / `True` / `success` | `bc23bf8a:15224/146/0/base` `c59ce309:15432/78/15104/-266` `8c2563bd:15573/10/15104/-406` |
| `202607181944` | `command_execution/03` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f780b-8899-7aa3-bd7d-1c60a685c28b` | `0` / `True` / `success` | `4d08f397:15237/145/0/base` `ade30a6f:15442/72/0/-15382` `f56a59b9:15580/8/15104/-410` |
| `202607181947` | `command_execution/04` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f780e-5ddc-7891-a3d4-ffeea35f883e` | `124` / `False` / `failure` | `f214a624:15261/162/9984/base` `d1d60e57:15465/349/15104/-319` `2d95bcc7:usage-missing` |
| `202607181948` | `command_execution/01` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f780f-125f-7b61-9527-3fe8a9930ca4` | `0` / `True` / `success` | `9d8896f9:17309/143/0/base` `978add35:17550/38/17408/-44` |
| `202607181949` | `command_execution/02` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f780f-fcba-7c90-9319-80843a793810` | `0` / `True` / `success` | `01dd5ea0:17336/155/3328/base` `19f5093e:17588/364/17408/-83` `7e15566b:18052/102/17920/-32` `92a05c42:18219/68/18048/-106` |
| `202607181950` | `command_execution/03` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7810-e65e-7c32-b132-221d725df0e7` | `124` / `False` / `failure` | `2c504eb3:17350/266/3712/base` `0e6b97dd:17646/146/17536/-80` `a13dfae4:usage-missing` |
| `202607181951` | `command_execution/04` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7811-cfe9-7da0-9add-081e202c8d0e` | `0` / `True` / `success` | `e80ab23f:17376/85/3712/base` `40449e48:17678/133/17408/-53` `2c88628e:17912/129/17792/-19` `f47e60c8:18146/113/17920/-121` `a1952cad:18365/42/18176/-83` |
| `202607181952` | `deferred_tool_search/01` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7812-be65-7051-97e1-01310b5b1291` | `0` / `True` / `success` | `144ad361:16070/197/9984/base` `ad9c6ef5:16617/175/15616/-651` `a356e6e0:17183/10/9984/-6808` |
| `202607181953` | `deferred_tool_search/02` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7813-a6af-7a60-90e2-ec55b8a192ab` | `0` / `True` / `success` | `6d49ad3d:15815/196/0/base` `ede5a829:16326/126/15616/-395` `bf1d8fa4:16818/10/16128/-324` |
| `202607181954` | `deferred_tool_search/03` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7814-8f50-7f42-9efd-eeb7b345531f` | `0` / `True` / `success` | `8d6f734c:16041/18/9984/base` |
| `202607181955` | `deferred_tool_search/04` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7815-79c6-7fa3-82f8-a5811235552f` | `0` / `True` / `success` | `1ef83871:15860/358/9984/base` `66e8594e:16267/292/9984/-6234` `eff795a8:16583/427/16128/-431` `29d94425:17105/28/16128/-882` |
| `202607181956` | `deferred_tool_search/05` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7816-6634-7272-ae9a-d4eb9db0cf7b` | `0` / `True` / `success` | `644ccff4:15666/152/9984/base` `f72b9567:16184/16/15104/-714` |
| `202607181957` | `deferred_tool_search/06` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7817-5187-76b2-9868-62e298150a6c` | `0` / `True` / `success` | `b0590d99:16118/186/0/base` `94320bba:16408/18/15616/-688` |
| `202607181958` | `deferred_tool_search/07` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7818-3cbc-7da2-8ef7-9ca9d4e5a06b` | `0` / `True` / `success` | `1a173589:15874/132/9984/base` `b2185352:16397/16/15616/-390` |
| `202607181959` | `deferred_tool_search/01` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7819-24d4-7760-950a-29758daac313` | `0` / `True` / `success` | `4eb3ac39:18223/231/3328/base` `a62d6733:19139/89/18432/-22` `6c2d2ce4:19520/130/19200/-28` `656369d2:19710/51/19584/-66` |
| `202607182000` | `deferred_tool_search/02` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f781a-0f1c-7822-974f-90f4c91268d2` | `0` / `True` / `success` | `e0fbc3a9:17950/196/3712/base` `5bf3d418:18800/116/18048/-98` `21333e08:19201/123/18816/-100` `f3f71f4f:19384/47/19200/-124` |
| `202607182001` | `deferred_tool_search/03` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f781a-f7e9-7911-a18b-669c607c1f35` | `0` / `True` / `success` | `16ef22ca:18209/139/3712/base` |
| `202607182002` | `deferred_tool_search/04` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f781b-e46f-7530-a956-929656ce2634` | `0` / `True` / `success` | `2e973acb:18015/541/3712/base` `9ea9593b:18678/65/18432/-124` |
| `202607182003` | `deferred_tool_search/05` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f781c-cf35-7d43-a891-a3209597a529` | `0` / `True` / `success` | `c121cb59:17818/254/3712/base` `c8c68e25:18876/224/18048/-24` `d80e25b5:19540/131/18816/-284` `ed89115c:19763/41/19456/-215` |
| `202607182004` | `deferred_tool_search/06` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f781d-b78c-7641-9031-7053bbc0bb0a` | `0` / `True` / `success` | `271acfa5:18294/259/3456/base` `450e888e:18688/247/18432/-121` |
| `202607182005` | `deferred_tool_search/07` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f781e-a63d-78a1-9be4-8ad2cbed2d98` | `0` / `True` / `success` | `29e13eac:18012/315/3968/base` `a9003e40:19162/270/18304/-23` `0877af32:19880/129/19072/-360` `d735e353:20096/222/19840/-169` `616f6809:21153/54/20224/-94` |
| `202607182006` | `builtin_tools/01` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f781f-8c26-7293-9e2c-bc042dc7f753` | `0` / `True` / `success` | `01033683:15375/105/9984/base` `f53a6836:15512/25/15104/-376` `e2f77362:15564/10/15104/-433` |
| `202607182007` | `builtin_tools/02` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7820-77bb-7f02-ba85-63c5fee45377` | `0` / `True` / `success` | `f983b7f1:15324/160/0/base` `a8d63eb8:15516/9/15104/-380` |
| `202607182008` | `builtin_tools/03` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7821-624b-71a1-bc41-4624f6c99dc8` | `0` / `True` / `success` | `8d55dce8:15380/225/9984/base` `e6639131:25670/89/15104/-501` `80f6a229:25876/89/25344/-415` `1818ddd7:29124/123/25344/-621` `d7c583ce:29316/422/28928/-319` `6752ced8:29762/63/28928/-810` |
| `202607182009` | `builtin_tools/04` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7822-4a9f-7511-b0f4-0b69187b26c0` | `0` / `True` / `success` | `48cf2c18:15255/97/9984/base` `840309e5:15525/9/15104/-248` |
| `202607182010` | `builtin_tools/05` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7823-3521-74f3-9811-45bec58a4dd1` | `0` / `True` / `success` | `4fe404ae:15311/78/9984/base` `138b6618:15428/45/15104/-285` `7cecc8de:15574/23/15104/-369` `91532ce1:15698/28/15104/-493` `808eed84:15894/13/15104/-622` |
| `202607182011` | `builtin_tools/01` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7824-2140-7713-822e-4df2e032e23e` | `0` / `True` / `success` | `7bbce1fe:17506/165/3712/base` `90fa416f:17732/111/17664/-7` `36ba6d3f:17899/47/17792/-51` |
| `202607182012` | `builtin_tools/02` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7825-0a57-7303-97eb-0611a9f15f03` | `0` / `True` / `success` | `9a6482c3:17445/209/3712/base` `61ba7ba5:17698/95/17536/-118` `6057e97f:17843/28/17792/-1` |
| `202607182013` | `builtin_tools/03` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7825-f5a8-79c1-9297-7974f9925810` | `0` / `True` / `success` | `f65bdf8e:17536/287/3712/base` `e96f23fa:17947/170/17792/-31` `c258514c:18293/378/17920/-197` `db081f48:18965/139/18176/-495` `a39bc822:19295/167/18944/-160` |
| `202607182014` | `builtin_tools/05` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7826-e026-7753-a912-b3195732d485` | `0` / `True` / `success` | `140d511c:17432/69/3712/base` `c9ae47b2:17569/70/17408/-93` `142d6857:17776/53/17536/-103` `31ae58b0:17966/79/17792/-37` `78f00006:18252/127/17920/-125` |
| `202607182015` | `builtin_tools/04` | `mimo-v2.5`; Opencode Go openai_responses→openai_chat | `019f7827-ca71-7d50-aa80-5edf28c1c227` | `0` / `True` / `success` | `0b317ecf:18868/139/0/base` `eb14e8ff:19270/480/18816/-191` |
| `202607182016` | `builtin_tools/06` | `mimo-v2.5`; Opencode Go openai_responses→openai_chat | `019f7828-b3f2-7af1-9c4c-7d60dfb1478e` | `0` / `True` / `success` | `f757282b:18967/135/0/base` `ac68db9a:19621/171/18944/-158` |
| `202607182017` | `local_skills/01` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7829-9c80-7150-a59f-6bd138a6e6e8` | `0` / `True` / `success` | `fd1d2e14:15389/10/9984/base` |
| `202607182018` | `local_skills/01` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f782a-8778-7330-9a8e-5979dd2604f9` | `0` / `True` / `success` | `773638b0:17514/71/3712/base` |
| `202607182019` | `namespace_tools/01` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f782b-7191-71e2-966d-8209723bea23` | `0` / `True` / `success` | `b2107b17:17922/128/0/base` `b0170a84:18112/25/17664/-386` `1f3de52e:18220/10/17664/-473` |
| `202607182020` | `namespace_tools/01` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f782c-5b31-70b2-8292-5f617b6afe4a` | `0` / `True` / `success` | `e768e683:20175/122/3328/base` `13e7fc67:20486/90/3328/-16969` |
| `202607182021` | `subagent_tools/01` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f782d-4689-74b2-a360-e211ec02f183` | `0` / `True` / `success` | `8cf89232:15348/60/9984/base` `a3c29e9f:usage-missing` `62b9bb7b:15210/12/9984/-5424` `17258168:15486/49/15104/-118` `c6573723:15560/23/15104/-431` |
| `202607182022` | `subagent_tools/02` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f782e-30ee-77b0-99f6-4b82583d362b` | `0` / `True` / `success` | `f06017c0:15353/82/9984/base` `5c33983d:15457/21/15104/-331` `1832a42c:15208/10/9984/-5494` `ddfffe25:15545/9/15104/-114` |
| `202607182023` | `subagent_tools/03` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f782f-1d1f-7f83-8774-a4fb949094c3` | `0` / `True` / `success` | `b5c822b7:15367/81/0/base` `510564c0:15469/21/15104/-344` `266f307a:15206/10/9984/-5506` `405e5959:15555/21/15104/-112` `f0e584d4:15613/10/15104/-472` |
| `202607182024` | `subagent_tools/04` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7830-05ee-7e91-a225-9534a19f4f31` | `0` / `True` / `success` | `9d452fea:15374/78/9984/base` `a1971d7d:15473/29/15104/-348` `5c9c2fce:15514/21/15104/-398` `14d9ebf3:17632/23/9984/-5551` `00549d89:usage-missing` `8350a6b1:15617/9/15104/-2551` |
| `202607182025` | `subagent_tools/05` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7830-f061-78c0-adfd-2d5a907e699d` | `0` / `True` / `success` | `24abee4d:15400/61/0/base` `8332d9d0:15484/21/15104/-357` `c8f086ba:15211/11/9984/-5521` `4333a5f3:15575/53/15104/-118` `87d4f238:18453/11/14592/-1036` `52276f8f:15641/21/15104/-3360` `bd16648f:usage-missing` `3b71bd06:15744/10/15104/-558` |
| `202607182026` | `subagent_tools/06` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7831-dbac-7fc0-984c-f49f5355a438` | `0` / `True` / `success` | `33727a0c:15386/68/9984/base` `86fbcf69:15476/21/15104/-350` `7c1cc5a9:15218/38/9984/-5513` `eac97964:15528/24/15104/-152` `a8f2ba20:15571/21/15104/-448` `d4486912:15624/11/15104/-488` |
| `202607182027` | `subagent_tools/01` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7832-c50f-7861-b1aa-8adcb7f3fb8f` | `0` / `True` / `success` | `4f7b9d36:17486/230/3712/base` `94d08e73:17736/90/17408/-308` `40d872e1:17316/53/3712/-14114` `098298d7:17885/100/17792/423` |
| `202607182028` | `subagent_tools/02` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7833-b192-7fb1-ad3d-8bf715d07ecf` | `0` / `True` / `success` | `f1aeb88c:17492/199/3712/base` `f591f740:17711/100/17408/-283` `8b29948f:17315/30/3712/-14099` `2a9ccbae:17869/85/17792/447` |
| `202607182029` | `subagent_tools/03` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7834-9cfd-71c1-bec1-5be91580ab57` | `0` / `True` / `success` | `27c8bbd5:17502/172/3712/base` `1f4b4b1a:17693/74/17408/-266` `012d8e1d:17313/39/3712/-14055` `55ad2d58:17823/91/17664/312` `9f2b8ff2:17957/53/17792/-122` |
| `202607182030` | `subagent_tools/04` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7835-8691-7b63-8a24-d837d0846a7a` | `0` / `True` / `success` | `763810e1:17515/200/3712/base` `a65b91da:17735/88/17408/-307` `424acdd1:17337/116/3712/-14111` `9fa11320:17504/38/17408/-45` `df537a18:17834/75/17792/250` `7b9ee8d3:17899/57/17792/-117` |
| `202607182031` | `subagent_tools/05` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7836-6fd5-7512-9e1f-05c80eb815ff` | `0` / `True` / `success` | `86efbaac:17570/166/3712/base` `da590db5:17757/77/17536/-200` `48b5d219:17345/53/3712/-14122` `f59278bf:17896/162/17792/394` `b0127c1d:18114/69/17792/-266` `ddd60094:20806/20/4608/-13575` `dafcbffd:18194/134/17920/-2906` |
| `202607182032` | `subagent_tools/06` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7837-5821-7330-8a75-f0ce56d6ec55` | `0` / `True` / `success` | `a1a1a62e:17528/181/3712/base` `6cf67e1e:17729/84/17408/-301` `bbd148d3:17325/87/3712/-14101` `c78ba218:17848/74/17792/380` `39397005:17941/77/17920/-2` `95819a8c:18054/165/17920/-98` |
| `202607182033` | `network_search/01` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7838-441a-7993-a380-4f7e01b2b931` | `1` / `False` / `failure` | `9b53f11c:15258/84/9984/base` `50424c69:usage-missing` |
| `202607182034` | `network_search/05` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7839-2d0d-73e1-a84a-803810f121f8` | `0` / `True` / `success` | `02cf7a1c:15329/111/9984/base` `7045cecf:15513/10/0/-15440` |
| `202607182035` | `network_search/01` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f783a-183e-7bd1-aa3e-da277044e627` | `0` / `True` / `success` | `243b44a2:17378/162/3712/base` `fed386f0:18211/49/17280/-260` |
| `202607182040` | `network_search/05` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f783e-ec8c-7b70-9fd7-93e429c6366d` | `0` / `True` / `success` | `76e65e7c:17449/118/3712/base` `59004241:17664/115/17408/-159` |
| `202607182041` | `network_search/02` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f783f-9513-78d1-914f-4f0b26ae7af6` | `0` / `True` / `success` | `58daad6c:15396/75/9984/base` `9ee6177e:16188/44/0/-15471` `13bbce7e:17483/11/15104/-1128` |
| `202607182042` | `network_search/02` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7840-815a-7aa3-8f12-ce0a8bb37a31` | `0` / `True` / `success` | `39ab60f4:17524/176/3712/base` `76471e93:18460/157/17408/-292` `e5644fda:19509/104/18560/-57` |
| `202607182043` | `network_search/01` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7841-6caa-79e3-aaa5-c4abe6bc2718` | `0` / `True` / `success` | `901a56af:15258/86/9984/base` `72bbea27:15980/9/9984/-5360` |
| `202607182044` | `command_execution/04` | `gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f7842-57d4-7aa0-ba24-af02e60ac0ab` | `0` / `True` / `success` | `09c3f8f3:15261/115/9984/base` `49041c98:15438/54/15104/-272` `53ac760a:15558/54/15104/-388` `e9846cd3:15679/9/15104/-508` |
| `202607182045` | `command_execution/03` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7843-40b0-7c31-8041-f1d29f616621` | `124` / `False` / `failure` | `452bf17f:17350/193/3712/base` `c88cf210:17638/100/17536/-7` `49bc2355:17862/327/17664/-74` `507f7bd1:18288/144/18176/-13` `10ab89b9:18529/138/18432/0` `045cd7e1:usage-missing` |
| `202607182046` | `image_generation/01` | `mimo-v2.5`; Opencode Go openai_responses→openai_chat | `019f7844-2d65-7900-8b45-d41f572dd26d` | `0` / `False` / `failure` | `4f4a4619:19015/157/12288/base` `1776c311:24574/149/19008/-164` `739c1413:24927/182/24512/-211` |
| `202607182048` | `command_execution/03` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7846-678b-7da2-98be-afdfdf5fe696` | `124` / `False` / `failure` | `e7587b01:17350/198/3712/base` `154bc09b:17757/346/17536/-12` `76a48b52:18313/149/18048/-55` `77429503:18575/124/18432/-30` `a01cf57b:18822/519/18688/-11` `248618eb:19440/133/19328/-13` `13745885:19669/151/19456/-117` `06fb2df2:usage-missing` |
| `202607182049` | `context_compaction/01` | `deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f7846-ea7a-7162-a9c5-2a15d0fc06e8` | `0` / `True` / `infrastructure_failure` | `90bb8b27:17322/128/3712/base` `5bac6eed:17706/284/17280/-170` `31456223:17575/382/17280/-710` `cedde909:17533/74/17280/-677` |
| `202607182052` | `context_compaction/03` | `gpt-5.6-terra→deepseek-v4-flash`; Pixel (K12) openai_responses→openai_responses | `019f7849-aa1d-7e92-9e31-b355864a68a9` | `0/0` / `True` / `completed` | `96c677b8:15188/27/9984/base` `bdef5ba0:20733/134/3200/-12015` |
| `202607182053` | `context_compaction/04` | `deepseek-v4-flash→gpt-5.6-terra`; Deepseek (Official) openai_responses→openai_chat | `019f784a-91ec-7c10-bc20-4c9db56e103e` | `0/0` / `True` / `completed` | `95500515:17301/122/3712/base` `ad62f164:18648/49/6912/-10511` |
| `202607182054` | `context_compaction_summary_quality/01` | `gpt-5.6-terra→gpt-5.6-terra`; Pixel (K12) openai_responses→openai_responses | `019f784b-7e08-7f90-9637-191eb286bf2a` | `0/0` / `True` / `not_scored` | `48037b8d:15171/99/9984/base` `b5930a6b:19661/329/9984/-5286` `4f978083:15502/11/14592/-5398` `9ed5c91e:18450/311/15104/-409` |
| `202607182055` | `context_compaction_summary_quality/02` | `deepseek-v4-flash→deepseek-v4-flash`; Deepseek (Official) openai_responses→openai_chat | `019f784c-67cf-7d90-b9e5-79fa332eec6d` | `0/0` / `True` / `not_scored` | `98cc40da:17284/139/3712/base` `b03c354c:17710/59/17280/-143` `a83cfc99:20743/550/17664/-105` |
| `202607181640` | `context_compaction/02-None` | `gpt-5.6-terra`; `Pixel (K12)` | `unknown` | `1` / `False` / `remote_compaction_error_reproduced` | native app-server runner did not emit the shared usage artifact |
| `202607181644` | `context_compaction/02-manual` | `gpt-5.6-terra`; `Pixel (K12)` | `unknown` | `1` / `False` / `not_triggered` | native app-server runner did not emit the shared usage artifact |
| `202607181645` | `context_compaction/02-manual` | `gpt-5.6-terra`; `Pixel (K12)` | `unknown` | `1` / `False` / `remote_compaction_error_reproduced` | native app-server runner did not emit the shared usage artifact |
| `202607181646` | `context_compaction/02-manual` | `gpt-5.6-terra`; `Pixel (K12)` | `unknown` | `1` / `False` / `remote_compaction_error_reproduced` | native app-server runner did not emit the shared usage artifact |
| `202607181653` | `context_compaction/02-manual` | `gpt-5.6-terra`; `Pixel (K12)` | `unknown` | `0` / `True` / `completed` | native app-server runner did not emit the shared usage artifact |
| `202607182050` | `context_compaction/02-context-limit` | `gpt-5.6-terra`; `Pixel (K12)` | `019f7847-d1f8-7150-970b-0ce0194408c3` | `0` / `True` / `infrastructure_failure` | native app-server runner did not emit the shared usage artifact |
| `202607182051` | `context_compaction/02-manual` | `gpt-5.6-terra`; `Pixel (K12)` | `019f7848-bfb3-72b3-b2db-987c42de9c23` | `0` / `True` / `completed` | native app-server runner did not emit the shared usage artifact |
| `202607191010` | `command_execution/03` | `deepseek-v4-pro`; Deepseek (Official) openai_responses→openai_chat | `019f7b24-43b4-7911-89fe-6fe5cc5a9070` | `124` / `False` / `failure` | four upstream requests; first three completed, last cancelled; model emitted three new command starts and no `write_stdin` |
| `202607191330` | `command_execution/03` | `deepseek-v4-pro`; Deepseek (Official) openai_responses→openai_chat; Chat default example guidance | `019f7bdb-b7fd-7a13-994a-27aae9e07299` | `0` / `True` / `success` | three upstream requests; one `exec_command`, one same-session `write_stdin`, streaming arguments reconstructed to `chars: "rosetta\\n"`; marker observed |
| `202607191011` | `image_generation/01` | `mimo-v2.5`; Opencode Go openai_responses→openai_chat | `019f7b26-0637-7f52-82ba-3db10af0c2c2` | `0` / `False` / `failure` | eight upstream requests; corrected image call reached Images endpoint, which returned 404 `model_not_found` for `gpt-image-2`; no artifact/view call |
| `202607191246` | `command_execution/03` | `glm-5.2`; Opencode Go openai_responses→openai_chat | `019f7bb3-59e8-7382-a1ed-10258d1a0990` | `124` / `False` / `failure` | real Chat request exposed standalone `exec_command` and `write_stdin`; GLM started one PTY, then polled, sent `chars: "rosetta"` without LF, and polled again |
| `202607191300` | `command_execution/03` | `glm-5.2`; Opencode Go openai_responses→openai_chat; Chat default profile guidance revision | `019f7bc0-8dec-7d62-ba30-52ff96ca7264` | `124` / `False` / `failure` | profile guidance was present; GLM started one PTY, reused the same session, but emitted `chars: "rosetta\\n"` with an over-escaped literal backslash+n, then polled |
| `202607191309` | `command_execution/03` | `glm-5.2`; Opencode Go openai_responses→openai_chat; explicit call example added | `unknown` | `124` / `False` / `failure` | example improved the visible call sequence but GLM still reused the session with `chars: "rosetta\\n"` and then polled; no marker |

## Cache-continuation review

Across the original recorded CLI cells there were 227 upstream requests, 154 non-first adjacent deltas, and eight requests without usage. The three 2026-07-19 follow-up cells add 18 source requests without a new combined cache aggregate. Of the original deltas, 61 were within ±200 tokens; 63 retained the same model, route, tool and instruction fingerprints and reflect an uncached conversation suffix or backend token-block alignment; 25 changed the instruction fingerprint in subagent lifecycle traffic; two changed model, provider, route, tools and instructions during deliberate compaction model switches; and three same-structure requests reported zero cached tokens, classified as backend cache misses rather than Rosetta request-shape drift.

The eight missing-usage requests are preserved explicitly in the table: one Terra 429 request, four requests from failed/timeout command cells, and three completed Terra subagent requests whose upstream completed event omitted usage. Their stream terminal stages were still inspected; missing usage was not converted into a synthetic zero or an aggregate rate.

## 2026-07-19 follow-up retests

The earlier new-key `deepseek-v4-pro` task-03 retest reproduced the command
failure: the model restarted the command instead of using the returned session
ID. A later retest after the Chat Default continuation example succeeded. The
model issued one `exec_command`, reused its returned session with one
`write_stdin`, and the streamed arguments reconstructed to `chars: "rosetta\\n"`;
the process returned `RESULT:INPUT_OK`. All requests reached the same DeepSeek
provider through Rosetta's Responses-to-Chat route, with no converter or
upstream transport error.

The new-key MiMo image retest also reached the isolated Images endpoint. MiMo
first emitted an invalid top-level `return` in the JavaScript wrapper, then
correctly invoked the image tool; the corrected request returned 404 because
the endpoint's configured model list omitted `gpt-image-2`. The key refresh did
not change the endpoint capability, and no generated artifact existed to pass
to `view_image`.

The GLM 5.2 task-03 control initially failed, but it confirms the projection
layer. After the Chat default profile gained explicit continuation and escape
guidance, GLM correctly started one PTY and reused its session ID. It still
emitted a raw argument containing two backslashes (`chars: "rosetta\\\\n"`),
which Rosetta reconstructed exactly as the literal two-character sequence
`\\n`; the process therefore remained blocked in `readline()` until the
30-second timeout. This narrows the remaining failure to GLM's JSON/tool-
argument escaping, not standalone `write_stdin` expansion or session routing.

## Compaction failure classification

The original DeepSeek context-limit task 01 was not a Rosetta replay
duplication. Its rollout contained three separate `exec` calls for
`python3 scenario.py`, each followed by a completed large result and a new
compaction. Rosetta recognized the Remote V2 trigger and installed follow-up
items; the model resumed from the compacted context and chose to rerun a task
marked “exactly once”. That result was useful, but the fixture coupled
protocol correctness with model behavior and could not attribute the failure
cleanly.

The suite is now split. Tasks 01–04 score only the Remote Compaction V2
protocol; task 05 separately scores post-compaction exactly-once behavior. A
protocol task accepts one complete trigger → compact result → installed
follow-up → replay chain and records later model-issued repeats as deviations.
The exactly-once task retains the exact-one command/compaction/mapping
assertions.

Terra context-limit task 02 is a runner/test-design mismatch, not evidence of
the Terra model or Rosetta losing the request. The CLI path uses `codex exec`,
which does not supply the attested `x-oai-attestation` wire envelope required
by `InboundWireRequest` for `wire_passthrough=true`. The same alpha.23 Terra
route passed the manual app-server compaction cell, where DeviceCheck
attestation was present and the compaction trigger/profile reported
`wire_passthrough=true`. The context-limit CLI run therefore validly exercised
native compaction/replay but cannot satisfy the stricter raw-wire assertion;
the runner should either use app-server for that gate or make the raw-wire
assertion conditional on attestation.

The historical `Pixel (K12)` label in this result came from the former native
smoke-runner contract, not from a protocol requirement. The runner contract is
now provider-neutral for GPT: it accepts any configured provider that serves
the selected GPT model, records the observed provider, and stops with a
user-decision-required result when the model route is missing or unavailable.

The first provider-neutral Terra smoke (`202607191438`) resolved the model to
the configured `Pixel (Plus)` provider, so the old Pixel (K12) precondition no
longer blocked it. Codex then stopped at `thread/start` because the copied
local `model_catalog.json` lacks the current
`supports_reasoning_summaries` field. This is recorded as a user-decision
configuration block; no provider or model substitution was attempted.

## Terra catalog compatibility repair and rerun — 2026-07-19

The `202607191438` block occurred before any model request. The installed
`codex-cli 0.144.6` requires the legacy `supports_reasoning_summaries` field
when parsing `model_catalog_json`, while the alpha.23 Rosetta catalog had
removed it after adopting `supports_reasoning_summary_parameter`. Rosetta now
projects the legacy boolean for every local-mode model, deriving it from the
current capability when present and defaulting to `true` for Codex's default
summary behavior. The alpha.23 client accepts this extra field, while 0.144.6
can start normally.

| Run | Codex binary | Model / provider | Thread | Exit / marker / evaluation | Compaction evidence |
| --- | --- | --- | --- | --- | --- |
| `202607191446` | `codex-cli 0.144.6` | `gpt-5.6-terra` / `Pixel (Plus)` | `019f7c21-b519-7da2-8810-393472132d28` | `0` / `RESULT:COMPACTION_PROTOCOL_OK` / `completed` | 3 Responses 200s; one `user_requested` native profile; `wire_passthrough=true`; installed `compaction` follow-up observed |
| `202607191451` | `codex-cli 0.145.0-alpha.23` | `gpt-5.6-terra` / `Pixel (Plus)` | `019f7c25-9625-7823-9520-6b1fa2bb47e6` | `0` / `RESULT:COMPACTION_PROTOCOL_OK` / `completed` | 3 Responses 200s; one `user_requested` native profile; `wire_passthrough=true`; installed `compaction` follow-up observed |

Both cells used the required OAuth plus isolated Gateway bearer local mode and
the same configured GPT route. The first run's failure was a catalog-version
compatibility defect in Rosetta local mode, not a Terra upstream or compaction
replay failure; both repaired runs reached the real model and completed the
native compaction chain. This manual app-server runner does not emit the shared
per-upstream-request usage artifact, so adjacent cache deltas remain explicitly
unavailable rather than being synthesized from thread-level token updates.

## Split DeepSeek Flash compaction rerun — 2026-07-19

The rerun used the local Codex source binary `0.145.0-alpha.23`, the isolated
local-mode Gateway, the copied Gateway configuration/key, and
`/Users/ibobby/.codex-multi-2/auth.json`. The task prompts and expectations now
explicitly require both the outer Code Mode cell and nested command to retain
20,000 output tokens; the protocol task also requires emitting the nested
result with `text(JSON.stringify(result))`, so a discarded outer result is
treated as an invalid precondition rather than as a compaction failure.

| Run | Scope | Exit / marker | Protocol evidence | Model-behavior result |
| --- | --- | --- | --- | --- |
| `202607191359` | `context_compaction/01`, `remote_compaction_protocol` | `0` / observed | DeepSeek Flash via `openai_responses→openai_chat`; 3 context-limit profiles, 3 completed Rosetta mappings, 3 installed follow-ups, baseline 17,796 and post-compaction 17,884 tokens, 128,042 retained output chars | `completed_with_deviations`: the model started the command 3 times and caused 3 compactions; repeats are outside this task's protocol scope |
| `202607191356` | `context_compaction/05`, `post_compaction_exactly_once` | `0` / observed | DeepSeek Flash via `openai_responses→openai_chat`; 1 complete Remote V2 chain, one mapping, baseline 17,867 and post-compaction 18,154 tokens, 79,908 retained output chars | `completed`: exactly one command start, one compaction, one mapping |

The protocol-only result demonstrates that Rosetta can recognize and replay
multiple Remote Compaction V2 chains on the Responses-to-Chat path. The
exactly-once result demonstrates that the same path can also preserve the
single-command behavior when the model follows that contract. Therefore the
earlier three-repeat observation should be classified as a DeepSeek model
behavior deviation exposed by the coupled fixture, not as evidence that
Rosetta duplicated a tool call. The test artifacts are bounded in
`tmp/agent_testing_workspace/202607191359/artifacts/evaluation.json` and
`tmp/agent_testing_workspace/202607191356/artifacts/evaluation.json`; no
credentials or compaction payloads are included.

## New-key command task 03 retest — 2026-07-19

These two cells were rerun after the configured Gateway API key was replaced.
The key value is not recorded; both cells retain the required dual-auth
artifact proving the copied Gateway config, ChatGPT OAuth source, local-mode
provider, and isolated localhost Gateway.

| Run | Model / route | Result | Native interaction | Upstream argument evidence |
| --- | --- | --- | --- | --- |
| `202607190955` | `deepseek-v4-flash`; `openai_responses→openai_chat`, provider `Deepseek (Official)` | `failure`, exit 124 after 30 seconds, no `RESULT:INPUT_OK` | Started `scenario.py` once without `tty` (it exited with `RESULT:INPUT_BAD:''`), started it again with `tty`, sent one write to the second session, then polled; this violates the one-start/same-session contract even before the write content is considered. | The raw upstream Chat function arguments parse to `chars = "rosetta\\n"` (one literal backslash plus `n`, not a newline). Rosetta's emitted `custom_tool_call` contains the corresponding JSON-escaped JS source `chars:"rosetta\\\\n"`; this is faithful serialization, not an added semantic newline loss. |
| `202607190957` | `gpt-5.6-terra`; `openai_responses→openai_responses`, provider `Pixel (Plus)` | `success`, exit 0, `RESULT:INPUT_OK` | One `tty` command start, one outer wait for the returned tool cell, and one non-empty `write_stdin` to the same native process session. | The model-facing code contains `chars:"rosetta\\n"` in JavaScript source, which evaluates to a real newline; the scenario returns `RESULT:INPUT_OK`. |

The difference is visible before execution in the upstream evidence. For the
DeepSeek cell, the parsed Chat function argument has the code-point sequence
`rosetta`, backslash, `n`; for Terra, the model-facing JavaScript source has one
backslash followed by `n`, so JavaScript evaluates it as LF. The Rosetta Chat
stream handler forwards argument deltas and the Responses bridge restores the
same custom input string; no converter branch rewrites `\\n` into or out of a
newline. Existing source locations are `openai_chat/converter.py:697-710` and
`openai_responses/converter.py:1923-1933`.

### Interpretation

- This is a valid compatibility boundary test: it checks process-session
  ownership, interactive stdin, nested tool execution, and the
  Responses-to-Chat-to-Code-Mode route.
- The DeepSeek failure is primarily a **third-party model/tool-call generation
  failure**: it over-escaped the newline and also restarted the process. The
  same model succeeded on the two-stage command task when it generated
  `alpha\\n`/`beta\\n` correctly, so this is not a blanket lack of stdin ability.
- It is not evidence of a Rosetta serialization regression. Terra passed over
  the same isolated Rosetta checkout, and the trace shows Rosetta preserving the
  DeepSeek argument value exactly.
- Terra is a direct `Responses→Responses` control while DeepSeek is a
  `Responses→Chat` conversion cell, so the matrix does not isolate model and
  route as two independently randomized variables. The raw upstream argument
  still localizes this failure to the DeepSeek model-facing tool-call output;
  a deterministic preconstructed-argument fixture remains the final control if
  a causal proof across both routes is required.
- The test is not a pure converter unit test: its prompt intentionally makes
  the model construct nested JavaScript/JSON. Therefore it is appropriate as a
  live interoperability gate, but the result should be classified as
  model-facing reliability, not as a Rosetta code defect unless a deterministic
  fixture with preconstructed arguments also fails.
