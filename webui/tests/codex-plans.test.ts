import { describe, expect, it } from 'vitest';
import { getCodexPlanPresentation } from '../src/admin/lib/codex-plans';

describe('ChatGPT subscription presentation', () => {
  it.each([
    ['chatgpt_plus', 'Plus'],
    ['team', 'Team'],
    ['enterprise', 'Enterprise'],
    ['codex-pro-5x', 'Pro 5x'],
    ['codex-pro-20x', 'Pro 20x'],
    ['unknown-plan', 'unknown-plan'],
    ['', 'Free'],
  ])('maps %s to %s', (raw, label) => {
    expect(getCodexPlanPresentation(raw).label).toBe(label);
  });
});
