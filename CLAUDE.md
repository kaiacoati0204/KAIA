# KaIA

Plataforma de estudos (ENEM/vestibular) para Ensino Médio. Público inclui muitos alunos com **TEA/TDAH**.

## Acessibilidade (regra de projeto — sempre)

- Público neurodivergente: **evitar estímulo visual desnecessário** (nada de animação/notificação chamativa, brilho, saturação forte).
- Contraste **alto porém macio**: legível, sem agredir. Off-white e quase-preto, nunca extremos.

## Cores (regra fixa — nunca violar)

**NUNCA branco puro (#fff) nem preto puro (#000)** em texto, fundo ou superfície — sempre marfim e quase-preto.

Tokens:
- `--marfim #f4ecdd` — fundo da página
- `--card #fbf6ec` — superfícies/cards
- `--tinta #2b2a26` — texto de corpo
- `--profundo #1a2b4c` — títulos / texto principal
- `--gravata-kinrou #f3d009` — amarelo: **só acento/realce/hover**, nunca fundo grande ou texto
- `--vd-uniao #57d979` — verde: **só estrutural**, não decorativo
- Status: `--acerto-bg #e4efe3`/`--acerto-tx #2f5d3a` · `--erro-bg #f3e2e2`/`--erro-tx #8a3b3b` · `--alerta-bg #f7ecd2`/`--alerta-tx #8a6d1e`

## Segurança / acesso

- **E-mail é identificador, não credencial.** Nunca controlar acesso comparando strings de e-mail no código.
- Controle de acesso via **`role` no banco (tabela `perfis`), verificado no backend** — nunca só em JavaScript.
- **MVP sem autenticação real** (login sem senha). Dívida conhecida e **bloqueador de produção**. Cabeçalhos tipo `X-Kaia-User` são conveniência, não proteção.

## Estilo de comentários

Comentários **estruturais**, não blocos explicativos longos. Vale para código novo.

- Divisores de seção: JS `// ==== SEÇÃO ====`, Python `# ==== SEÇÃO ====`.
- Comentar o **porquê** quando não for óbvio (uma linha), não o **o quê**.
- Sem parágrafos explicativos dentro do código.
