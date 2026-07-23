import translations from '../../../src/codex_rosetta/gateway/admin/admin_i18n.json';

export type Language = 'en' | 'zh';
export type TranslationParams = Record<string, string | number>;

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

export function t(key: string, params: TranslationParams = {}): string {
  const table = translations[language.value] as Record<string, string>;
  const fallback = translations.en as Record<string, string>;
  const template = table[key] ?? fallback[key] ?? key;
  return template.replace(/\{([A-Za-z0-9_]+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
  );
}
