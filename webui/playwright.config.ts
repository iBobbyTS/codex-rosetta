import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 15_000,
  reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:4177' },
  webServer: {
    command: 'npm run dev:admin -- --host 127.0.0.1 --port 4177',
    url: 'http://127.0.0.1:4177/admin/admin.html',
    reuseExistingServer: false,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'], browserName: 'chromium' } },
  ],
});
