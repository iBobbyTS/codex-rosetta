import { describe, expect, it } from 'vitest';

import { bundledProviderLogoNames, providerLogo } from '../src/admin/lib/provider-logos';

describe('provider logos', () => {
  it('maps every supported shim identity to a bundled asset', () => {
    const expected: Record<string, string> = {
      anthropic: 'anthropic.svg',
      deepseek: 'deepseek.svg',
      google: 'google.svg',
      'minimax--anthropic': 'minimax.svg',
      'minimax--openai_chat': 'minimax.svg',
      moonshot: 'moonshot.svg',
      openai: 'openai.svg',
      openai_responses: 'openai.svg',
      opencode_go: 'opencode.png',
      'openrouter--anthropic': 'openrouter.svg',
      'openrouter--openai_chat': 'openrouter.svg',
      qwen: 'qwen.svg',
      'volcengine--openai_chat': 'volcengine.svg',
      'volcengine--openai_responses': 'volcengine.svg',
      xai: 'xai.svg',
      zhipu: 'zhipu.svg',
    };

    expect(bundledProviderLogoNames).toEqual(Object.keys(expected));
    for (const name of Object.keys(expected)) {
      const logo = providerLogo(name);
      expect(logo).toBeTruthy();
      expect(logo).not.toContain('cdn.jsdelivr.net');
      if (/^https?:/.test(logo)) expect(new URL(logo).origin).toBe(window.location.origin);
    }
    expect(providerLogo('minimax--anthropic')).toBe(providerLogo('minimax--openai_chat'));
    expect(providerLogo('openai')).toBe(providerLogo('openai_responses'));
    expect(providerLogo('openrouter--anthropic')).toBe(providerLogo('openrouter--openai_chat'));
    expect(providerLogo('volcengine--openai_chat')).toBe(providerLogo('volcengine--openai_responses'));
    expect(providerLogo('custom')).toBe('');
  });
});
