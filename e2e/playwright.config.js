import { defineConfig, devices } from '@playwright/test';

// Sobe um static server servindo a pasta Frontend/ (rodado a partir da RAIZ do
// repo — cwd '..'). Requer Python 3. Se seu sistema usa `python3`, troque no
// campo webServer.command abaixo.
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  fullyParallel: true,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5510',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'python -m http.server 5510 --directory Frontend',
    cwd: '..',
    url: 'http://127.0.0.1:5510/pages/login.html',
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
