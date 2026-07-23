import translations from '../../../../src/codex_rosetta/gateway/admin/admin_i18n.json';

export type Language = 'en' | 'zh';

function initialLanguage(): Language {
  const saved = localStorage.getItem('codex-rosetta-lang');
  if (saved === 'en' || saved === 'zh') return saved;
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

export const language = $state<{ value: Language }>({ value: initialLanguage() });

export function setLanguage(value: Language): void {
  language.value = value;
  localStorage.setItem('codex-rosetta-lang', value);
  document.documentElement.lang = value === 'zh' ? 'zh-CN' : 'en';
}

export function t(key: string, fallback: string): string {
  const table = translations[language.value] as Record<string, string>;
  return table[key] ?? fallback;
}
