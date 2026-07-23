import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';
import { resolve } from 'node:path';

export default defineConfig({
  base: './',
  plugins: [svelte()],
  build: {
    outDir: resolve(__dirname, 'dist/bootstrap'),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, 'bootstrap.html'),
    },
  },
});
