"""Uniform E2E test: same model set across all available agents.

Tests every agent against the same set of models to ensure consistent
cross-format conversion behavior regardless of inbound API format.
"""

import os
import sys
from agentabi import run_sync

BASE_URL = os.environ.get("ROSETTA_DEV_TEST_BASE_URL", "")
API_KEY = os.environ.get("ROSETTA_DEV_TEST_KEY", "")

if not BASE_URL or not API_KEY:
    print("ERROR: Set ROSETTA_DEV_TEST_BASE_URL and ROSETTA_DEV_TEST_KEY")
    sys.exit(1)

OPENAI_ENV = {
    "OPENAI_BASE_URL": BASE_URL,
    "OPENAI_API_KEY": API_KEY,
    "CODEX_PROVIDER": "openai",
}
ANTHROPIC_ENV = {
    "ANTHROPIC_BASE_URL": BASE_URL.replace("/v1", ""),
    "ANTHROPIC_API_KEY": API_KEY,
}

# Models to test — covers all conversion paths
MODELS = [
    "gpt-5-nano",  # OpenAI pass-through
    "o4-mini",  # OpenAI reasoning
    "claude-haiku-4-5",  # Anthropic direct
    "argo:claude-opus-4.7",  # Anthropic via Argo (reasoning)
    "argo:gemini-2.5-flash",  # Google via Argo
    "gemini-3.5-flash",  # Google direct
    "deepseek-v4-flash",  # DeepSeek (non-vision)
    "MiniMax-M3",  # MiniMax
]

# Agents with their env configs
AGENTS = [
    ("codex", OPENAI_ENV),
    ("opencode", OPENAI_ENV),
    ("claude_code", ANTHROPIC_ENV),
]

counter = [0]


def make_prompt():
    counter[0] += 1
    a, b = counter[0] * 10, counter[0] * 10
    return f"What is {a}+{b}? Reply with just the number."


passed = failed = 0
results = []

for agent, env in AGENTS:
    for model in MODELS:
        prompt = make_prompt()
        label = f"{agent}/{model}"
        print(f"\n--- {label} ---")
        try:
            result = run_sync(
                prompt,
                agent=agent,
                model=model,
                env=env,
                max_turns=1,
                timeout=90,
            )
            status = result.get("status", "unknown")
            text = (result.get("result_text") or "")[:60]
            print(f"  status: {status}")
            print(f"  result: {text}")
            ok = status in ("success", "completed")
            passed += ok
            failed += not ok
            results.append((agent, model, "✅" if ok else "❌", text[:25]))
        except Exception as e:
            failed += 1
            print(f"  ERROR: {e}")
            results.append((agent, model, "❌", str(e)[:25]))

print(f"\n{'=' * 75}")
print(f"{'Agent':<14} {'Model':<28} {'St':<4} {'Output'}")
print(f"{'-' * 75}")
for a, m, s, t in results:
    print(f"{a:<14} {m:<28} {s:<4} {t}")
print(f"\n=== {passed}/{passed + failed} passed ===")
sys.exit(1 if failed else 0)
