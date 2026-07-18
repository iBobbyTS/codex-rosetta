# web.run Custom Exec Streaming Debug
Date: 2026-07-13
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Confirmed root causes

1. Responses→Chat streaming restored a custom `exec` call by forwarding the
   complete Chat JSON arguments object as JavaScript. A native custom-tool input
   must instead unwrap the single `input` string after the stream is complete.
2. Codex replays an `exec` result as `custom_tool_call_output`, often with
   multiple `input_text` blocks. Responses→Chat ignored this item type, so the
   paired Chat call received `[No output available yet]` instead of the real
   Tavily search result.

## Fix

- Buffer Chat-bridged custom-tool argument deltas until completion and unwrap
  only an exact single-key `{"input": string}` object. Preserve malformed or
  other argument objects without guessing execution intent.
- Treat `custom_tool_call_output` as a Responses tool-result input and normalize
  its text/image blocks through the existing IR tool-result path.
- Keep model-specific raw-JavaScript usage guidance in the Chat Default Profile
  rather than in protocol conversion code.

## Automated verification

- Focused Responses converter and pipeline suite: `163 passed`.
- Regression coverage verifies split streamed custom input, non-input argument
  preservation, `custom_tool_call_output` text-block conversion, and the paired
  Responses→Chat request shape.

## Real verification

- Run root: `tmp/agent_testing_workspace/202607131211`
- Codex alias/provider identity: `gpt-5.6-sol` / `OpenAI`
- Actual upstream model: `deepseek-v4-flash`
- Thread: `019f5cad-cf5c-7421-b1f0-a5bd850f2b7d`
- Gateway Logs: `/Volumes/RAMDisk/202607131211/rosetta-trace.jsonl`
- Result: `RESULT:NETWORK_SEARCH_OK`, process exit 0.
- Gateway Logs prove one `tools.web__run` call, `codex_search_request`, a
  Tavily-backed `codex_search_response` containing `https://docs.python.org`,
  and successful completion of the second upstream stream.
