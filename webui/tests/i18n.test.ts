import { afterEach, describe, expect, it } from 'vitest';
import { language, setLanguage, t } from '../src/shared/i18n.svelte';

afterEach(() => {
  setLanguage('en');
});

describe('shared frontend localization', () => {
  it('switches languages and persists the selection', () => {
    setLanguage('zh');

    expect(language.value).toBe('zh');
    expect(t('nav.providers')).toBe('服务方');
    expect(localStorage.getItem('codex-rosetta-lang')).toBe('zh');
    expect(document.documentElement.lang).toBe('zh-CN');
  });

  it('interpolates translated parameters without component-level fallbacks', () => {
    setLanguage('en');

    expect(t('toast.providerSaved', { name: 'Demo' })).toBe("Provider 'Demo' saved");
    expect(t('missing.translation.key')).toBe('missing.translation.key');
  });
});
