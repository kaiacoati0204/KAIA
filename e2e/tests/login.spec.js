import { test, expect } from '@playwright/test';

async function dispensarPreloader(page) {
  const pre = page.locator('#kaia-preloader');
  if (await pre.count()) {
    await pre.click({ timeout: 2000 }).catch(() => {});
    await pre.waitFor({ state: 'detached', timeout: 15_000 }).catch(() => {});
  }
}

test('login: formulário renderiza e aceita digitação', async ({ page }) => {
  await page.goto('/pages/login.html');
  await dispensarPreloader(page);

  await expect(page.locator('#login-email')).toBeVisible();
  await expect(page.locator('#login-senha')).toBeVisible();
  await page.fill('#login-email', 'aluno@teste.com');
  await page.fill('#login-senha', 'senha123');
  await expect(page.locator('#login-email')).toHaveValue('aluno@teste.com');
  await expect(page.getByRole('button', { name: /entrar/i })).toBeVisible();
});

// Degradação graciosa: num clone SEM config.js, o supabaseClient não existe e o
// login AVISA em vez de quebrar. Se você tem config.js local, esta asserção muda
// (viraria "Email ou senha incorretos" ou erro de rede) — ajuste conforme o caso.
test('login sem config.js avisa em vez de quebrar', async ({ page }) => {
  await page.goto('/pages/login.html');
  await dispensarPreloader(page);

  await page.fill('#login-email', 'a@b.com');
  await page.fill('#login-senha', 'x');
  await page.getByRole('button', { name: /entrar/i }).click();

  await expect(page.locator('#login-erro')).not.toHaveText('');
});
