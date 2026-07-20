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
  js/           → script.js (lógica do front: hobbies, missões, IA, sensores, caderno, rail)
  assets/       → Coati.jpg, Coati_3d.glb
  config.js     → API_URL + credenciais do Supabase (NÃO vai pro Git — copie de config.example.js)
Backend/
  app.py                → backend FastAPI (rotas da IA, sessões, painéis)
  requirements.txt      → dependências Python
  seed_logins.sql       → gera e-mails de professor/coordenador em `perfis`
  seed_sintetico.py     → popula sessões sintéticas para os painéis
  limpar_sintetico.sql  → apaga os dados sintéticos
  .env                  → variáveis de ambiente (NÃO vai pro Git)
ml/                     → treino e pré-processamento do Random Forest
CLAUDE.md               → convenções do projeto (cores, acessibilidade, segurança, estilo)
```

---

## 🚀 Como rodar

### 1. Instalar as dependências do backend

```bash
pip install -r Backend/requirements.txt
```

### 2. Criar o arquivo `.env`

Na pasta `Backend/`, crie um arquivo `.env` com as variáveis abaixo (sem aspas, sem espaços em volta do `=`):

```
API_KEY=          # chave do Google Gemini (gerada no Google AI Studio)
DATABASE_URL=     # string de conexão do Supabase (Settings → Database)
STALE_SESSAO_MIN= # opcional; minutos até encerrar sessão ociosa (padrão: 15)
```

> Nunca coloque a chave `service_role` do Supabase aqui nem no frontend — ela ignora RLS.

### 3. Criar o `config.js` do frontend

Copie `Frontend/config.example.js` para `Frontend/config.js` e preencha os valores (use sempre a chave **publishable/anon**, nunca a `service_role`).

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

> [!WARNING]
> **MVP sem autenticação real.** O login é só por e-mail (sem senha). O controle de acesso vive no `role` do banco, verificado no backend — mas sem auth de verdade isso é conveniência, não proteção. **Bloqueador de produção.**

- [ ] Implementar autenticação real (senha / provedor de identidade).
- [ ] Regenerar `ml/artifacts/scaler.pkl` (via `preprocessing.ipynb`) para as predições do Random Forest.
- [ ] Dividir o `script.js` em um arquivo por página + um comum.
