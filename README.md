<div align="center">

<img src="Frontend/assets/Coati.jpg" alt="Coati, mascote da KaIA" width="130">

# KaIA

_Refúgio inteligente contra a dispersão digital — monitoramento de atenção + questões geradas por IA para o Ensino Médio._

<img alt="Python" src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
<img alt="Supabase" src="https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase&logoColor=white">
<img alt="status: MVP" src="https://img.shields.io/badge/status-MVP-F3D009">

</div>

Plataforma educacional voltada para estudantes do ensino médio — o público inclui muitos alunos com **TEA/TDAH**, o que orienta as decisões de design (ver `CLAUDE.md`).

---

## 🎯 O que o projeto faz por enquanto

- **Login → Hobbies → App**: o aluno entra, escolhe hobbies (usados para personalizar as questões) e acessa o painel principal.
- **Missões por matéria**: ao escolher uma matéria, a IA gera uma lista de subtemas (temas de maior incidência no ENEM); ao escolher o subtema, a IA cria uma questão de múltipla escolha com explicação.
- **Caderno de anotações**: canvas livre por tema (texto no Supabase, imagens só no dispositivo).
- **Perfil com estatísticas**: desempenho semanal + sinais da última sessão + análise por regras.
- **Painéis internos**: dashboard da equipe (acesso restrito por `role`) e painel de responsáveis.
- **Monitoramento de foco**: sensores no front (troca de aba, scroll, teclado, ociosidade, etc.) registram eventos de atenção durante a missão.

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|--------|-----------|
| Frontend | HTML, CSS, JavaScript (sem framework) |
| Backend | Python + **FastAPI** (uvicorn) |
| Banco | **Supabase** (PostgreSQL), via `asyncpg` |
| IA | Google Gemini (`gemini-2.5-flash`) |
| ML | scikit-learn (Random Forest) + pandas/numpy |
| Agendamento | APScheduler (agregação + encerramento de sessões ociosas) |

---

## 📁 Estrutura dos arquivos

```
Frontend/
  pages/        → os .html (login, index, hobbies, materias, perfil, meu-coati, dashboard, responsaveis)
  css/          → style.css
  js/           → módulos do front: comum.js (base/rail/apiFetch), login.js (auth/cadastro),
                  materias.js (missões/sensores/pomodoro), hobbies.js, perfil.js, dashboard.js
  assets/       → Coati.jpg, Coati_3d.glb
  config.js     → API_URL + Supabase (NÃO vai pro Git — copie de config.example.js)
Backend/
  app.py                → backend FastAPI (rotas da IA, sessões, painéis)
  auth.py               → validação do JWT do Supabase Auth (JWKS)
  requirements.txt      → dependências Python
  migrations/           → schema/trigger do banco (rode em ordem numérica; nunca apague)
  seed_contas_teste.py  → cria as contas @teste.kaia (senha teste1234)
  seed_sintetico.py     → popula sessões sintéticas para os painéis
  limpar_*.{py,sql}     → desfazem os seeds
  .env                  → variáveis de ambiente (NÃO vai pro Git — copie de .env.example)
ml/                     → treino e pré-processamento do Random Forest
CLAUDE.md               → convenções do projeto (cores, acessibilidade, segurança, estilo)
```

---

# 🚀 Como rodar

### 1. Pré-requisitos e dependências

- **Python 3.11+** (backend FastAPI).
- **VS Code + extensão Live Server** (ou qualquer servidor estático) para o frontend.
- **Não precisa de Node nem build:** o frontend é HTML/CSS/JS puro; libs (Supabase, Chart.js) entram via CDN.

```bash
pip install -r Backend/requirements.txt
```

### 2. Configuração — criar o `.env`

`Backend/.env` está no `.gitignore` (não vem no clone). Crie o arquivo e cole o bloco abaixo, preenchendo os valores (sem aspas, sem espaço em volta do `=`):

```bash
# Chave do Google Gemini (Google AI Studio) — gera as questões.
API_KEY=

# Postgres do Supabase: Settings → Database → Connection string (URI).
# Troque [YOUR-PASSWORD] pela senha do banco. É o ÚNICO segredo do backend.
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.<PROJECT_ID>.supabase.co:5432/postgres

# URL pública do projeto (Settings → General → Project ID).
# OBRIGATÓRIA: sem ela o auth.py não valida o JWT e o login falha ("perfil não encontrado").
SUPABASE_URL=https://<PROJECT_ID>.supabase.co

# Opcional — minutos até encerrar sessão ociosa (padrão: 15).
STALE_SESSAO_MIN=15
```

> O backend **não usa** chave de API do Supabase — só a `DATABASE_URL` (o único segredo) e a `SUPABASE_URL` (pública). **Nunca** coloque a chave secret (`sb_secret_`) aqui nem no frontend.

### 3. Criar o `config.js` do frontend

`config.js` está no `.gitignore` e **não vem no clone**. Copie `Frontend/config.example.js` para `Frontend/config.js` e preencha:

```js
SUPABASE_URL: 'https://<PROJECT_ID>.supabase.co',
SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_...',   // Supabase → Settings → API Keys → publishable
```

> No frontend vai **só a publishable** (é pública; o RLS protege os dados). **Nunca** a secret.
> Onde achar o `<PROJECT_ID>`: Supabase → Settings → General (a URL é `https://<PROJECT_ID>.supabase.co`).

### 4. Subir o backend

```bash
python Backend/app.py
```

Para testar se está no ar, abra: `http://127.0.0.1:5000/`
Deve aparecer: `{"status": "KaIA backend no ar"}`

> Use `127.0.0.1`, não `localhost`: no Windows `localhost` pode resolver para IPv6 e o servidor dev só escuta em IPv4.

### 5. Abrir o frontend

Rode com um servidor local (ex.: extensão **Live Server** do VS Code). O ponto de entrada é `pages/login.html`:

- Se abriu a pasta do repositório: `http://127.0.0.1:5500/Frontend/pages/login.html`
- Se abriu a pasta `Frontend/`: `http://127.0.0.1:5500/pages/login.html`

### 6. Entrar com uma conta de teste

Senha de todas: **`teste1234`**.

| E-mail | Papel |
|--------|-------|
| `aluno1@teste.kaia` | aluno |
| `aluno2@teste.kaia` | aluno |
| `aluno.individual@teste.kaia` | aluno (sem escola) |
| `professor@teste.kaia` | professor |
| `coordenador@teste.kaia` | coordenador |

Login OK = cai na tela do aluno. Conferência técnica: DevTools → Network → `GET /perfil` retorna **200**.

### 7. Banco de dados (montar do zero)

Scripts em `Backend/` e `Backend/migrations/`. Ordem:

1. **`Backend/migrations/0001_perfil_signup_termos.sql`** — schema + trigger de consentimento no signup. Rode uma vez no Supabase → SQL Editor.
2. **`python Backend/seed_contas_teste.py --commit`** — cria as contas de teste acima (sem `--commit` = dry-run). Rode de dentro de `Backend/`.
3. *(opcional)* **`python Backend/seed_sintetico.py --commit`** — popula sessões sintéticas para dar volume ao dashboard.

Limpeza (antes de produção / quando entrarem alunos reais): `Backend/limpar_sintetico.sql` e `python Backend/limpar_contas_teste.py --commit`.

---

## 🔌 Rotas do backend (principais)

| Rota | Método | O que faz |
|------|--------|-----------|
| `/` | GET | Verifica se o servidor está no ar |
| `/temas` | POST | Gera subtemas de uma matéria (com cache) |
| `/gerar-questao` | POST | Cria questão de múltipla escolha com explicação |
| `/perguntar` | POST | Resposta livre da IA (personalizada por hobbies) |
| `/anotacoes` | GET/PUT | Lê e grava o caderno de anotações (texto) |
| `/perfil` | GET/POST | Dados do aluno (login por e-mail; grava hobbies) |
| `/perfil/estatisticas` | GET | Desempenho semanal + última sessão + análise |
| `/sessions`, `/sessions/{id}/end` | POST | Abre e encerra sessões de estudo |
| `/events` | POST | Registra os eventos de foco dos sensores |
| `/intervencao/pendente`, `/intervencao/feedback` | GET/POST | Intervenções de atenção |
| `/dashboard/dados` | GET | Dados do dashboard interno (acesso restrito por `role`) |
| `/responsavel/aluno`, `/responsavel/painel` | GET | Painel de responsáveis |

---

## 📖 Convenções

> [!NOTE]
> Antes de contribuir, veja o **`CLAUDE.md`** na raiz do projeto. Ele define as convenções: paleta de cores, acessibilidade (público TEA/TDAH), regra de segurança (e-mail é identificador, não credencial) e estilo de comentários.

---

## 🧭 Problemas conhecidos / próximos passos

> [!NOTE]
> **Autenticação: Supabase Auth (e-mail + senha).** O backend valida o **JWT** nas rotas de dados (`Backend/auth.py`); o front envia o token via `apiFetch`. O controle de acesso continua no `role` do banco, verificado no backend.

- [ ] Estender a proteção por JWT às rotas ainda abertas (baixa sensibilidade) e revisar o gate `X-Kaia-User` do dashboard.
- [ ] Dividir o `script.js` em um arquivo por página + um comum.
