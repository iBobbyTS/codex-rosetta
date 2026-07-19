# Zerodep Upstream Dirty-Patch Baseline Before Round-18 Repair

Captured before the round-18 request-parser/auth-boundary repair.

- Upstream working tree: `.agent-work/upstream/zerodep`
- Branch: `master`
- HEAD: `fb84dd10ca736129f937740e44a485034b51258b`
- Existing dirty diff: 8 files, 1,092 insertions, 77 deletions
- Existing complete patch SHA-256: `ab6a13fbf883cce898ad34ccf10dd75c801740a0fa922ccc83acf17110da8639`
- Existing purpose: prior `httpclient` response envelope, `sse` limits, and round-12 `httpserver` header/trailer envelope; no upstream commit or push is authorized.

| File | SHA-256 before round 18 |
| --- | --- |
| `httpclient/conftest.py` | `a0ae4b1e0b34ad9d15c5829bba8255e6e6e9ac7c148ca74ba76731d94bce17e2` |
| `httpclient/httpclient.py` | `6b860e82de594fa425a8fe55c1ac33b05dd2d631faa21a664089987b521ac838` |
| `httpclient/test_httpclient_correctness.py` | `638543df7ce8b3be4728b13888f8bcfefab52f79d52ea1a45316136bca1cec25` |
| `httpserver/httpserver.py` | `1f8b0d8384fca522eb94f9c75381e8184485c3b148149c314e139dffafea1125` |
| `httpserver/test_httpserver_correctness.py` | `3db211b187f348992a80af9eb1355177de5245c7a78f2ba3fd7e6d895ba46895` |
| `manifest.json` | `32242eccfdf9eec7a42ac648719265576728dd329e0ab4ff6409dc7fc74a5186` |
| `sse/sse.py` | `391df4d1fe5e2a037698c6416de5119f1de46e6c42f89be5f16dfcf496f8a5a7` |
| `sse/test_sse_correctness.py` | `882d2ccd23b3bc90d5bb7e33bf9e9db640ac2317fa46c779c74bf09060978034` |

The pre-round-18 patch is preserved as the baseline. Round-18 changes must be limited to upstream `httpserver` source/tests plus generated manifest/version metadata.

## Final round-18 upstream state

- Final complete dirty patch SHA-256: `0c31e3037b22b413b44ced49e17efb759cc498a2c4aa736d2363604d44b8c3fa`
- `httpserver` version: `0.2.3`
- Official re-vendor normalized upstream/vendor SHA-256: `1489f17beb816ff72a353a4c5a16ddb0998da37c2673ca1b30b09af2da174d73`
- No upstream commit or push was created.
