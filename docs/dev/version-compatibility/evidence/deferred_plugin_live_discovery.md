# Deferred plugin/MCP/skill live discovery
Date: 2026-07-16
Codex version: 0.144.0

Historical compatibility evidence; use the maintained ledger and reports for
current conclusions.

## Resolution

- Codex CLI/source baseline: `0.144.4` / `8c68d4c87dc54d38861f5114e920c3de2efa5876`.
- The suite now separates explicit controls (`01`–`03`) from natural-language
  discovery (`04`–`07`) for standalone skills, standalone MCP, plugin skills,
  and plugin MCP.
- Every surface uses three local deterministic candidates: archive proof,
  integer addition, and color normalization. No Browser, app, login state,
  third-party plugin, or real user skill is copied into the isolated homes.

## Root causes found

1. Codex 0.144.4 code mode does not place deferred MCP candidate names in the
   Responses request. The request carries the `exec`/`ALL_TOOLS` contract;
   Codex injects candidate metadata into the V8 runtime.
2. On Responses-to-Chat profile routes, Rosetta projected static exec children
   and hid the `exec` container even when its description advertised runtime-
   only deferred tools. The target model therefore saw the discovery contract
   but had no declared `exec` function to call.
3. DeepSeek sometimes called `text()` with multiple arguments and then tried
   prohibited fixture inspection. The fixture now specifies the single-argument
   `text(JSON.stringify({ catalog, result }))` diagnostic contract and requires
   a failure marker instead of source/config/session fallback.

## Source repair

- `tool_adaptation.py` preserves the converted `exec(input: string)` function
  only when the Codex description contains the 0.144.4 deferred-nested-tools
  guidance. Ordinary profile routes without deferred runtime ownership retain
  the previous hidden-container behavior.
- The gateway round-trip regression proves that a Chat `exec` function call is
  reconstructed as a Codex `custom_tool_call` with the original JavaScript.

## Passing live evidence

Terra passed all tasks without deviations:

- `01` `202607161324`
- `02` `202607161326`
- `03` `202607161327`
- `04` `202607161328`
- `05` `202607161329`
- `06` `202607161330`
- `07` `202607161333`

After the source/fixture repairs, DeepSeek passed every core task:

- `01` `202607161342` (`success with deviations`)
- `02` `202607161347` (`success with deviations`)
- `03` `202607161348` (`success with deviations`)
- `04` `202607161349` (`success`)
- `05` `202607161350` (`success with deviations`)
- `06` `202607161351` (`success with deviations`)
- `07` `202607161352` (`success with deviations`)

The DeepSeek deviations are extra explanation, harmless empty resource/template
probes, or redundant selected-skill reads. No passing run used shell, Browser,
network, fixture source, config, session, or artifact data to recover a marker.
The failed pre-repair runs remain preserved at `202607161334` and
`202607161344` with their own evaluation evidence.

## Final classification

- Installation/exposure: passed for plugin, standalone MCP, and standalone
  skill surfaces.
- Rosetta contextual conversion: passed for ordered skill/plugin fragments and
  the `exec` discovery contract.
- Active discovery: passed for all four implicit tasks on Terra and DeepSeek.
- Deferred tool invocation/result use: passed, including plugin provenance and
  exact target arguments.
