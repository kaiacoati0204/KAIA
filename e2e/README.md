# Camada C — E2E (Playwright) + Acessibilidade (axe)

> ⚠️ **Não foi validado pelo Claude** — ele não roda navegador. Você é quem executa
> e depura. É **opt-in e isolado**: tem o PRÓPRIO `package.json`, então **não afeta**
> o `npm test` (Vitest) da raiz nem o CI atual.

## Por que existe
- **Acessibilidade automática (`axe`)** — o coração pro KaIA: mede contraste, ARIA,
  rótulos. É o único guarda contra "alguém mexeu numa cor e ficou ilegível pro
  aluno TEA/TDAH" — regra central do projeto que hoje nada verifica.
- **Bugs de navegador de verdade** — layout quebrado, e comportamento como o
  "clicar no feedback recarregava a página" (que jsdom/unit não pegam).

## Pré-requisitos
- **Node 18+** e **Python 3** (o static server das páginas usa `python -m http.server`).

## Instalar (uma vez)
```bash
cd e2e
npm install
npx playwright install chromium     # baixa o navegador (~150 MB)
```

## Rodar
```bash
cd e2e
npm run test:e2e                    # sobe o static server sozinho e roda os specs
npx playwright show-report          # abre o relatório (violações do axe, traces, anexos)
```

> Se seu sistema usa `python3` em vez de `python`, edite `playwright.config.js`
> (campo `webServer.command`).

## O que cada spec faz
- **`acessibilidade.spec.js`** — roda o **axe (WCAG 2 A/AA)** em login/cadastro/termos/
  privacidade (páginas públicas, renderizam sem login). **Espere achados na 1ª
  rodada** — é a sua lista de triagem (o detalhe fica anexado no relatório). Corrija
  os problemas ou ajuste o escopo da asserção conforme decidir.
- **`login.spec.js`** — funcional: o form renderiza, aceita digitação e, **sem
  config.js**, avisa em vez de quebrar (degradação graciosa). *Se você tem config.js
  local, a 2ª asserção muda.*
- **`fluxo-estudo.spec.js`** — **TEMPLATE** do fluxo interno (login stubbado + backend
  mockado). Carrega matérias e confirma o menu inicial. Os **TODOs** mostram como
  completar pra pegar o bug do "feedback recarrega a página".

## Quando estiver passando limpo: colocar no CI (opcional)
Deixei **fora do CI** de propósito — E2E baixa navegador e é mais frágil; eu não pude
validar, então não quis pintar o CI de vermelho. Depois que rodar verde na sua
máquina, um job assim resolve:
```yaml
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: cd e2e && npm ci && npx playwright install --with-deps chromium
      - run: cd e2e && npm run test:e2e
```

## Limites honestos
- O `axe` pega o **medível** (contraste, ARIA) — **não** "está calmo / não sobrecarrega",
  que é subjetivo e continua sendo olho humano.
- E2E é mais frágil que unit test (timing, seletores). Mantenha poucos e focados.
