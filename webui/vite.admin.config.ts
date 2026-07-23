import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';
import { resolve } from 'node:path';

export default defineConfig({
  base: '/admin/',
  plugins: [svelte()],
  build: {
    outDir: resolve(__dirname, '../src/codex_rosetta/gateway/admin/dist'),
    emptyOutDir: true,
    manifest: 'manifest.json',
    rollupOptions: {
      input: resolve(__dirname, 'admin.html'),
    },
  },
});
