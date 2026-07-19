# Zerodep Upstream Dirty-Patch Baseline

Captured before round-12 header-envelope edits.

- Upstream working tree: `.agent-work/upstream/zerodep`
- Branch: `master`
- HEAD: `fb84dd10ca736129f937740e44a485034b51258b`
- Existing diff: 6 files, 465 insertions, 43 deletions
- Existing purpose: `httpclient` 0.4.5 incremental body/line safety and `sse` 0.3.3 line/event limits, already vendored into Codex-Rosetta before this round

| File | SHA-256 before round 12 |
| --- | --- |
| `httpclient/conftest.py` | `f84d7e203277d1423ba74943b55d77c5369f13e7604069145c783344b8f4b1f4` |
| `httpclient/httpclient.py` | `d79b14f88ebac8616a952feb96f2a8aacadc15ea00004e98fc2dafdd9ac655db` |
| `httpclient/test_httpclient_correctness.py` | `8cfb606f61dfb14ee12d4e5ba26882ef4abdea8bcbff4cadb5c2977d2e747f39` |
| `manifest.json` | `dadcef8ed77510aecabbc572930a82833a62c50413bd58c28ea5f90c7a8249dd` |
| `sse/sse.py` | `391df4d1fe5e2a037698c6416de5119f1de46e6c42f89be5f16dfcf496f8a5a7` |
| `sse/test_sse_correctness.py` | `882d2ccd23b3bc90d5bb7e33bf9e9db640ac2317fa46c779c74bf09060978034` |

`git diff --check` passed at capture time. No upstream commit or push is authorized.
