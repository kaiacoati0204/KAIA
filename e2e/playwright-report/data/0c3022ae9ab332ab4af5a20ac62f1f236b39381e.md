# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: acessibilidade.spec.js >> acessibilidade WCAG 2 A/AA (axe): /pages/privacidade.html
- Location: tests\acessibilidade.spec.js:22:3

# Error details

```
Error: Violações de acessibilidade em /pages/privacidade.html:
[serious] color-contrast: 1x — Elements must meet minimum color contrast ratio thresholds

expect(received).toEqual(expected) // deep equality

- Expected  -  1
+ Received  + 64

- Array []
+ Array [
+   Object {
+     "description": "Ensure the contrast between foreground and background colors meets WCAG 2 AA minimum contrast ratio thresholds",
+     "help": "Elements must meet minimum color contrast ratio thresholds",
+     "helpUrl": "https://dequeuniversity.com/rules/axe/4.12/color-contrast?application=playwright",
+     "id": "color-contrast",
+     "impact": "serious",
+     "nodes": Array [
+       Object {
+         "all": Array [],
+         "any": Array [
+           Object {
+             "data": Object {
+               "bgColor": "#f7ecd2",
+               "contrastRatio": 4.17,
+               "expectedContrastRatio": "4.5:1",
+               "fgColor": "#8a6d1e",
+               "fontSize": "10.8pt (14.4px)",
+               "fontWeight": "normal",
+               "messageKey": null,
+             },
+             "id": "color-contrast",
+             "impact": "serious",
+             "message": "Element has insufficient color contrast of 4.17 (foreground color: #8a6d1e, background color: #f7ecd2, font size: 10.8pt (14.4px), font weight: normal). Expected contrast ratio of 4.5:1",
+             "relatedNodes": Array [
+               Object {
+                 "html": "<p class=\"aviso-placeholder\">
+             Texto provisório — pendente de revisão jurídica (LGPD). Será substituído pela
+             versão final antes do lançamento.
+         </p>",
+                 "target": Array [
+                   ".aviso-placeholder",
+                 ],
+               },
+             ],
+           },
+         ],
+         "failureSummary": "Fix any of the following:
+   Element has insufficient color contrast of 4.17 (foreground color: #8a6d1e, background color: #f7ecd2, font size: 10.8pt (14.4px), font weight: normal). Expected contrast ratio of 4.5:1",
+         "html": "<p class=\"aviso-placeholder\">
+             Texto provisório — pendente de revisão jurídica (LGPD). Será substituído pela
+             versão final antes do lançamento.
+         </p>",
+         "impact": "serious",
+         "none": Array [],
+         "target": Array [
+           ".aviso-placeholder",
+         ],
+       },
+     ],
+     "tags": Array [
+       "cat.color",
+       "wcag2aa",
+       "wcag143",
+       "TTv5",
+       "TT13.c",
+       "EN-301-549",
+       "EN-9.1.4.3",
+       "ACT",
+       "RGAAv4",
+       "RGAA-3.2.1",
+     ],
+   },
+ ]
```

# Page snapshot

```yaml
- article [ref=e2]:
  - link "← Voltar ao cadastro" [ref=e3] [cursor=pointer]:
    - /url: cadastro.html
  - heading "Política de Privacidade" [level=1] [ref=e4]
  - paragraph [ref=e5]: Texto provisório — pendente de revisão jurídica (LGPD). Será substituído pela versão final antes do lançamento.
  - heading "1. Dados que coletamos" [level=2] [ref=e6]
  - paragraph [ref=e7]: Coletamos nome, e-mail e preferências (hobbies) informados no cadastro, além de dados de uso da plataforma (sessões de estudo, foco e progresso) para personalizar a experiência.
  - heading "2. Para que usamos" [level=2] [ref=e8]
  - paragraph [ref=e9]: Os dados são usados para autenticar o acesso, gerar questões adequadas ao seu perfil e apoiar o acompanhamento de estudos. Não vendemos seus dados.
  - heading "3. Consentimento e menores (LGPD)" [level=2] [ref=e10]
  - paragraph [ref=e11]: O aceite desta política é registrado no cadastro (data e versão). Para menores, o uso pressupõe consentimento dos responsáveis, conforme a legislação aplicável.
  - heading "4. Seus direitos" [level=2] [ref=e12]
  - paragraph [ref=e13]: Você pode solicitar acesso, correção ou exclusão dos seus dados, bem como revogar o consentimento, pelos canais de contato da plataforma.
  - heading "5. Segurança" [level=2] [ref=e14]
  - paragraph [ref=e15]: Adotamos medidas para proteger seus dados. O controle de acesso é verificado no servidor, e credenciais são tratadas pelo provedor de autenticação.
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | import AxeBuilder from '@axe-core/playwright';
  3  | 
  4  | // Dispensa o preloader de abertura (um clique/keydown o remove) e espera a UI real.
  5  | async function dispensarPreloader(page) {
  6  |   const pre = page.locator('#kaia-preloader');
  7  |   if (await pre.count()) {
  8  |     await pre.click({ timeout: 2000 }).catch(() => {});
  9  |     await pre.waitFor({ state: 'detached', timeout: 15_000 }).catch(() => {});
  10 |   }
  11 | }
  12 | 
  13 | // Páginas PÚBLICAS: renderizam sem sessão logada, então são alvos estáveis pro axe.
  14 | const PAGINAS = [
  15 |   '/pages/login.html',
  16 |   '/pages/cadastro.html',
  17 |   '/pages/termos.html',
  18 |   '/pages/privacidade.html',
  19 | ];
  20 | 
  21 | for (const rota of PAGINAS) {
  22 |   test(`acessibilidade WCAG 2 A/AA (axe): ${rota}`, async ({ page }) => {
  23 |     await page.goto(rota);
  24 |     await dispensarPreloader(page);
  25 | 
  26 |     const r = await new AxeBuilder({ page })
  27 |       .withTags(['wcag2a', 'wcag2aa'])
  28 |       .analyze();
  29 | 
  30 |     // Anexa o detalhe ao relatório HTML pra facilitar a triagem.
  31 |     await test.info().attach('axe-violations.json', {
  32 |       body: JSON.stringify(r.violations, null, 2),
  33 |       contentType: 'application/json',
  34 |     });
  35 | 
  36 |     const resumo = r.violations
  37 |       .map((v) => `[${v.impact}] ${v.id}: ${v.nodes.length}x — ${v.help}`)
  38 |       .join('\n');
  39 |     // NOTA: é ESPERADO falhar na 1ª rodada — a lista acima é a triagem de
  40 |     // acessibilidade (contraste, ARIA...). Corrija ou ajuste o escopo conforme decidir.
> 41 |     expect(r.violations, `Violações de acessibilidade em ${rota}:\n${resumo}`).toEqual([]);
     |                                                                                ^ Error: Violações de acessibilidade em /pages/privacidade.html:
  42 |   });
  43 | }
  44 | 
```