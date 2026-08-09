import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// Dispensa o preloader de abertura (um clique/keydown o remove) e espera a UI real.
async function dispensarPreloader(page) {
  const pre = page.locator('#kaia-preloader');
  if (await pre.count()) {
    await pre.click({ timeout: 2000 }).catch(() => {});
    await pre.waitFor({ state: 'detached', timeout: 15_000 }).catch(() => {});
  }
}

// Páginas PÚBLICAS: renderizam sem sessão logada, então são alvos estáveis pro axe.
const PAGINAS = [
  '/pages/login.html',
  '/pages/cadastro.html',
  '/pages/termos.html',
  '/pages/privacidade.html',
];

for (const rota of PAGINAS) {
  test(`acessibilidade WCAG 2 A/AA (axe): ${rota}`, async ({ page }) => {
    await page.goto(rota);
    await dispensarPreloader(page);

    const r = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    // Anexa o detalhe ao relatório HTML pra facilitar a triagem.
    await test.info().attach('axe-violations.json', {
      body: JSON.stringify(r.violations, null, 2),
      contentType: 'application/json',
    });

    const resumo = r.violations
      .map((v) => `[${v.impact}] ${v.id}: ${v.nodes.length}x — ${v.help}`)
      .join('\n');
    // NOTA: é ESPERADO falhar na 1ª rodada — a lista acima é a triagem de
    // acessibilidade (contraste, ARIA...). Corrija ou ajuste o escopo conforme decidir.
    expect(r.violations, `Violações de acessibilidade em ${rota}:\n${resumo}`).toEqual([]);
  });
}
