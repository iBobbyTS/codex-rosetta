import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { parse } from 'svelte/compiler';
import { describe, expect, it } from 'vitest';
import translations from '../../src/codex_rosetta/gateway/admin/admin_i18n.json';

type AstNode = {
  type?: string;
  data?: string;
  name?: string;
  value?: unknown;
  attributes?: AstNode[];
  callee?: AstNode;
  arguments?: AstNode[];
  [key: string]: unknown;
};

function svelteFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? svelteFiles(path) : entry.name.endsWith('.svelte') ? [path] : [];
  });
}

function walk(node: unknown, visit: (node: AstNode, parent?: AstNode) => void, parent?: AstNode): void {
  if (!node || typeof node !== 'object') return;
  const current = node as AstNode;
  visit(current, parent);
  for (const [key, value] of Object.entries(current)) {
    if (key === 'metadata') continue;
    if (Array.isArray(value)) value.forEach((child) => walk(child, visit, current));
    else if (value && typeof value === 'object') walk(value, visit, current);
  }
}

const files = [
  ...svelteFiles(resolve('src/admin')),
  ...svelteFiles(resolve('src/bootstrap')),
];
const languageText = /[A-Za-z\u3400-\u9fff]/;
describe('frontend localization source', () => {
  it('keeps English and Chinese dictionaries in lockstep', () => {
    expect(Object.keys(translations.en).sort()).toEqual(Object.keys(translations.zh).sort());
  });

  it('resolves every literal translation key and keeps fallbacks out of components', () => {
    const missing: string[] = [];
    const inlineFallbacks: string[] = [];
    for (const file of files) {
      const source = readFileSync(file, 'utf8');
      const ast = parse(source, { modern: true });
      walk(ast, (node) => {
        if (node.type !== 'CallExpression' || node.callee?.type !== 'Identifier' || node.callee.name !== 't') return;
        const [key, params] = node.arguments ?? [];
        if (key?.type === 'Literal' && typeof key.value === 'string') {
          if (!(key.value in translations.en) || !(key.value in translations.zh)) missing.push(`${file}: ${key.value}`);
        }
        if (params?.type === 'Literal' && typeof params.value === 'string') inlineFallbacks.push(file);
      });
    }
    expect(missing).toEqual([]);
    expect(inlineFallbacks).toEqual([]);
  });

  it('keeps rendered text, placeholders, labels, and accessible names in the dictionaries', () => {
    const hardcoded: string[] = [];
    for (const file of files) {
      const source = readFileSync(file, 'utf8');
      const ast = parse(source, { modern: true });
      walk(ast.fragment, (node, parent) => {
        if (node.type === 'Text') {
          const text = node.data?.replace(/\s+/g, ' ').trim() ?? '';
          if (parent?.type !== 'Attribute' && text && languageText.test(text)) hardcoded.push(`${file}: ${text}`);
        }
        if (node.type === 'Attribute' && ['placeholder', 'title', 'aria-label', 'alt'].includes(node.name ?? '')) {
          const values = Array.isArray(node.value) ? node.value : [node.value];
          for (const value of values) {
            const text = (value as AstNode | undefined)?.type === 'Text' ? (value as AstNode).data ?? '' : '';
            if (languageText.test(text)) hardcoded.push(`${file}: ${node.name}=${text}`);
          }
        }
      });
    }
    expect(hardcoded).toEqual([]);
  });
});
