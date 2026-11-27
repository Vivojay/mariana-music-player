import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  use: { browserName: 'chromium', baseURL: 'http://127.0.0.1:8767', viewport: { width: 390, height: 844 } },
  webServer: {
    command: 'python -m http.server 8767 --bind 127.0.0.1 --directory ../build/web-player',
    url: 'http://127.0.0.1:8767',
    reuseExistingServer: !process.env.CI,
  },
});
