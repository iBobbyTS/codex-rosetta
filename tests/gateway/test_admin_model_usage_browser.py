"""Real-browser regression for Admin model-test usage rendering.

This test is opt-in because the Python package intentionally has no Node or
browser runtime dependency.  Run it with::

    RUN_ADMIN_BROWSER_TESTS=1 pytest \
        tests/gateway/test_admin_model_usage_browser.py -v

It serves the bundled Admin page from the current checkout and drives a real
Chromium DOM through the user-installed Playwright CLI wrapper.
"""

from __future__ import annotations

import functools
import http.server
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path

import pytest


_RUN_BROWSER = os.environ.get("RUN_ADMIN_BROWSER_TESTS") == "1"


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Keep the regression output focused on browser assertions."""


def _playwright_wrapper() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "skills" / "playwright" / "scripts" / "playwright_cli.sh"


@pytest.mark.skipif(
    not _RUN_BROWSER,
    reason=(
        "real Chromium DOM regression is opt-in; set RUN_ADMIN_BROWSER_TESTS=1 "
        "with npx and the bundled Playwright CLI wrapper available"
    ),
)
def test_admin_model_usage_is_text_only_and_never_reads_admin_token() -> None:
    """Malicious provider usage values stay inert across every model-test path."""
    wrapper = _playwright_wrapper()
    if not wrapper.is_file():
        pytest.fail(f"Playwright CLI wrapper is unavailable: {wrapper}")

    repo_root = Path(__file__).resolve().parents[2]
    handler = functools.partial(_SilentHandler, directory=str(repo_root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    session = f"rosetta-admin-dom-{uuid.uuid4().hex[:10]}"
    url = (
        f"http://127.0.0.1:{server.server_port}/"
        "src/codex_rosetta/gateway/admin/admin.html"
    )
    command = [str(wrapper), "--session", session]
    browser_assertions = r"""async (page) => {
const result = await page.evaluate(async () => {
  const meta = document.getElementById('testMeta');
  if (!meta) throw new Error('testMeta is missing from the real Admin page');

  await new Promise(resolve => setTimeout(resolve, 50));

  localStorage.setItem('admin_token', 'browser-regression-secret');
  let tokenReads = 0;
  let exfilAttempts = 0;
  let coercions = 0;
  const originalGetItem = Storage.prototype.getItem;
  const originalFetch = window.fetch;
  Storage.prototype.getItem = function(key) {
    if (key === 'admin_token') tokenReads += 1;
    return originalGetItem.call(this, key);
  };
  window.fetch = async (...args) => {
    exfilAttempts += 1;
    return new Response('{}', {status: 200, headers: {'Content-Type': 'application/json'}});
  };
  window.__adminUsageXss = 0;

  const markup = '<img src=x onerror="window.__adminUsageXss += 1; localStorage.getItem(\'admin_token\'); fetch(\'/exfil\')">';
  const svg = '<svg onload="window.__adminUsageXss += 1"></svg>';
  const closing = '</div><script>window.__adminUsageXss += 1</script>';
  const unicodeControl = 'safe\u2028\u0000</span><img src=x onerror="window.__adminUsageXss += 1">';
  const coercionProbe = {
    toString() { coercions += 1; return markup; },
    valueOf() { coercions += 1; return 7; },
    [Symbol.toPrimitive]() { coercions += 1; return markup; },
  };
  const invalidValues = [
    markup, svg, closing, unicodeControl, coercionProbe, [markup], {value: markup},
    NaN, Infinity, -1, Number.MAX_SAFE_INTEGER + 1,
  ];
  const paths = [
    ['responses', usage => ({input_tokens: usage, output_tokens: usage})],
    ['openai_chat', usage => ({prompt_tokens: usage, completion_tokens: usage})],
    ['anthropic', usage => ({input_tokens: usage, output_tokens: usage})],
    ['google', usage => ({input_tokens: usage, output_tokens: usage})],
  ];

  try {
    for (const [type, makeUsage] of paths) {
      for (const invalid of invalidValues) {
        _resetTestMeta(meta, `model-${type}`);
        _appendTestUsageMeta(meta, 'text', makeUsage(invalid));
        await new Promise(resolve => setTimeout(resolve, 0));
        if (meta.querySelector('img,svg,script')) {
          throw new Error(`${type}: provider markup created an element`);
        }
        const tokenLine = [...meta.querySelectorAll('.meta-item')].at(-1)?.textContent || '';
        const expected = 'Tokens: - in / - out';
        if (tokenLine !== expected) {
          throw new Error(`${type}: invalid usage rendered as ${JSON.stringify(tokenLine)}`);
        }
      }
    }

    const safeCases = [
      ['responses', 'text', {input_tokens: 12, output_tokens: 13}, 'Tokens: 12 in / 13 out'],
      ['openai_chat', 'text', {prompt_tokens: 14, completion_tokens: 15}, 'Tokens: 14 in / 15 out'],
      ['anthropic', 'text', {input_tokens: 16, output_tokens: 17}, 'Tokens: 16 in / 17 out'],
      ['google', 'text', {input_tokens: 18, output_tokens: 19}, 'Tokens: 18 in / 19 out'],
      ['max_safe_integer', 'text', {input_tokens: Number.MAX_SAFE_INTEGER, output_tokens: 42}, 'Tokens: 9007199254740991 in / 42 out'],
      ['invalid_primary_does_not_fallback', 'text', {input_tokens: markup, prompt_tokens: 20, output_tokens: 21}, 'Tokens: - in / 21 out'],
    ];
    for (const [label, type, usage, expected] of safeCases) {
      _resetTestMeta(meta, `safe-${label}`);
      _appendTestUsageMeta(meta, type, usage);
      const tokenLine = [...meta.querySelectorAll('.meta-item')].at(-1)?.textContent || '';
      if (tokenLine !== expected) {
        throw new Error(`${label}: safe/fallback rendering changed: ${JSON.stringify(tokenLine)}`);
      }
    }
    if (window.__adminUsageXss !== 0) throw new Error('provider event handler executed');
    if (tokenReads !== 0) throw new Error(`admin_token was read ${tokenReads} times`);
    if (exfilAttempts !== 0) throw new Error(`fetch was called ${exfilAttempts} times`);
    if (coercions !== 0) throw new Error(`custom coercion ran ${coercions} times`);
  } finally {
    Storage.prototype.getItem = originalGetItem;
    window.fetch = originalFetch;
    localStorage.removeItem('admin_token');
  }
  return 'DOM_ASSERTIONS_OK';
});
const chromiumVersion = page.context().browser()?.version();
if (!chromiumVersion) throw new Error('Chromium version is unavailable');
return `${result}|CHROMIUM_VERSION=${chromiumVersion}`;
}
"""

    try:
        opened = subprocess.run(
            [*command, "open", url],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        print(opened.stdout, end="")
        print(opened.stderr, end="")
        assert opened.returncode == 0, "Playwright could not open the Admin page"

        executed = subprocess.run(
            [*command, "run-code", browser_assertions],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        cli_output = executed.stdout + executed.stderr
        print(cli_output, end="")
        assert executed.returncode == 0, "Playwright DOM assertion command failed"
        assert "### Error" not in cli_output
        assert "SyntaxError" not in cli_output
        assert "DOM_ASSERTIONS_OK|CHROMIUM_VERSION=" in cli_output
        version_match = re.search(r"CHROMIUM_VERSION=([0-9.]+)", cli_output)
        assert version_match is not None
        print(f"Verified Chromium {version_match.group(1)}")
    finally:
        subprocess.run(
            [*command, "close"],
            check=False,
            timeout=30,
        )
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
