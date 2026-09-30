<div align="center">

<img src="Frontend/assets/Coati.jpg" alt="Coati, mascote da KaIA" width="130">

# KaIA

_Refúgio inteligente contra a dispersão digital — apoio ao foco + questões geradas por IA para o Ensino Médio._

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
- **Vínculo aluno ↔ responsável**: quando o responsável autoriza o consentimento, o backend
  grava a ligação em `pai_aluno` — é o que faz o painel dele listar os próprios filhos.
- **Temas de fundo**: 4 opções no perfil (Padrão, Neutro, Azul suave, Cinza-pedra), com
  contraste de texto conferido par a par.
- **Avaliação do beta**: `pages/avaliacao.html` com o formulário do Tally embutido, alcançada
  por um botão no fim do perfil.
- **Assinatura**: tabela, rotas e trial prontos, **esperando a chave do Mercado Pago**.
- **Apoio ao foco, em duas camadas** (o core, definido em 17/09/2026):
  - **Reativa** — sensores no front (troca de aba, ociosidade, trajetória do mouse, tempo de resposta) detectam desengajamento por **evidência medida**: saída da KaIA ≥ 30 s, regra DTS (bom na sessão + acerto caiu + tempo fora do próprio ritmo) ou pausa incomum na questão aberta. Um bandit Thompson escolhe qual das 7 intervenções mostrar. O gatilho **nunca** depende de modelo.
  - **Preventiva** — na pausa entre rodadas de 10, o sistema estima o **risco** de perda de foco nas próximas questões e oferece um plano "se-então" antes que ela aconteça. Um segundo bandit aprende qual apoio ajuda, com o braço `nada` como controle.
  - Um **probe de autorrelato** (o aluno declara o próprio estado, 1×/rodada) coleta rótulo real e é devolvido a ele. Sinais de foco/atenção — **não é diagnóstico**.

  > O core anterior (detectar mente vagando e intervir em tempo real) foi abandonado em 15/09/2026 — o alvo não tem gabarito. O Random Forest v2 segue no repositório como **pesquisa**: não decide nada. Por quê e o que não reabrir: [`ml/core_e_evidencias.md`](ml/core_e_evidencias.md) e [`ml/metodo_beta.md`](ml/metodo_beta.md).

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|--------|-----------|
| Frontend | HTML, CSS, JavaScript (sem framework) |
| Backend | Python + **FastAPI** (uvicorn) |
| Banco | **Supabase** (PostgreSQL), via `asyncpg` |
| IA | Google Gemini (`gemini-3.5-flash-lite`; configurável por `GEMINI_MODEL`) |
| ML | scikit-learn (regressão logística de risco; Random Forest v2 de pesquisa) + Thompson Sampling autoral + pandas/numpy |
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
Frontend/ (continuação)
  robots.txt, sitemap.xml, llms.txt → SEO. Ficam AQUI e não na raiz do repo porque
                  `staticPublishPath: ./Frontend` (render.yaml) faz de Frontend/ a raiz
                  servida — é daqui que respondem em /robots.txt, /sitemap.xml, /llms.txt
Backend/
  app.py                → backend FastAPI (IA, sessões, /events, /diagnose, painéis)
  pagamento.py          → regras de assinatura: valida a assinatura do webhook do Mercado
                          Pago, janela do trial, decisão de acesso (sem banco, sem rede)
  auth.py               → validação do JWT do Supabase Auth (JWKS)
  risco.py              → Modelo 1: features e regras de risco de perda de foco (camada preventiva)
  bandit_prevencao.py   → Modelo 2: Thompson Sampling autoral do apoio da pausa (hierárquico)
  thompson.py           → bandit das 7 intervenções reativas
  consentimento.py      → tokens, validação e hash do aceite do responsável (LGPD art. 14)
  mouse_features.py     → mouse_track bruto → features de mouse do modelo v2
  requirements.txt      → dependências Python
  seed_contas_teste.py  → cria as contas @teste.kaia (senha teste1234)
  seed_sintetico.py     → popula sessões sintéticas para os painéis
  limpar_*.{py,sql}     → desfazem os seeds
  .env                  → variáveis de ambiente (NÃO vai pro Git — veja "2. Configuração")
ml/
  gerar_base_v2.py      → gera a base sintética + treina o modelo v2 (seed fixa; .pkl NÃO versionado)
  gerar_risco.py        → gera a base sintética + treina o Modelo 1 (só salva se vencer as regras)
  treinar_com_probe.py  → valida/re-treina o modelo v2 com os rótulos reais do probe
  simular_bandit_prevencao.py → confere o mecanismo do Modelo 2 antes do beta (não mede efeito)
  relatorio_prevencao.py      → leitura do beta: IPW vs `nada`, aceitação, habituação
  medir_dano_probe.py         → o probe atrapalha a questão seguinte? (descritivo)
  core_e_evidencias.md  → o core com a fonte ao lado de cada afirmação
  metodo_beta.md        → método do beta, protocolo-piloto e critérios de abandono (datados)
supabase/
  migrations/           → schema versionado (snapshot de produção); ÚNICO SQL que o CI aplica
  README.md             → recriar o banco, regenerar o snapshot, criar migration nova
CLAUDE.md               → convenções do projeto (cores, acessibilidade, segurança, modelo, estilo)
```

---

# 🚀 Como rodar

> [!IMPORTANT]
> **Subindo numa máquina nova?** O banco fica no **Supabase (nuvem)** e todo mundo
> usa o **mesmo projeto**: schema, contas de teste e dados **já estão lá**. Na
> prática você só precisa de três coisas — **(1)** dependências, **(2)**
> `Backend/.env`, **(3)** `Frontend/config.js` (passos 1 a 3 abaixo). **Não** precisa
> recriar nem popular o banco; o passo 7 só serve para casos específicos.

> [!TIP]
> **Só vai testar (sem mexer em produção)?** Rode com `KAIA_DB_SCHEMA=teste` no `.env` — aponta o
> backend para o schema isolado `teste` (mesmo projeto Supabase), sem tocar em produção nem nos
> modelos. Peça ao Vitor o guia de teste passo a passo (contas de teste + barra de intervenções).

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

# Opcional — few-shot dinâmico (questões reais via pgvector) + Program-of-Thought
# nas questões de cálculo. Ligue para testar a geração baseada em reais.
KAIA_FEWSHOT_DINAMICO=1

# Camada preventiva (Fluxo B). ATIVA=0 desliga tudo. MODO: `fixo` oferece sempre (mede
# aceitação sem misturar com erro de modelo) e `bandit` sorteia entre `nada` e `pacote_foco`.
# GATILHO: `regra` decide (padrão) e `modelo` promove o Modelo 1 — só depois que ele vencer
# as regras no dado real. Escada: fixo → regra → modelo.
KAIA_PREVENCAO_ATIVA=1
KAIA_PREVENCAO_MODO=fixo
KAIA_PREVENCAO_GATILHO=regra
KAIA_PREVENCAO_LIMIAR=0.4

# OBRIGATÓRIA se houver aluno menor: segredo do HMAC do CPF do responsável. Só no BACKEND —
# nunca no config.js. Sem ela, /consentimento recusa o aceite com CPF.
KAIA_CPF_PEPPER=

# Opcional — exige consentimento também de quem não informou data de nascimento.
KAIA_CONSENTIMENTO_ESTRITO=0

# Opcional — SANDBOX: aponta o backend para o schema isolado `teste` (mesmo projeto
# Supabase), sem tocar em produção nem nos modelos. Deixe FORA em produção.
# Para testar de forma isolada, veja supabase/README.md.
KAIA_DB_SCHEMA=teste

# ---- Verificação das questões geradas ----
# Depois de gerar, um segundo modelo confere o gabarito antes de a questão sair da
# quarentena. PROVEDOR: `gemini` (padrão) ou `groq`.
KAIA_VERIF_PROVEDOR=gemini
KAIA_MODELO_VERIFICADOR=gemini-3.6-flash   # quando o provedor é gemini
KAIA_VERIF_MODELO_GROQ=openai/gpt-oss-20b  # quando é groq
GROQ_API_KEY=                              # OBRIGATÓRIA se KAIA_VERIF_PROVEDOR=groq
KAIA_VERIF_LOTE=10                         # questões por chamada de verificação
KAIA_VERIF_LOTE_RODADA=12                  # teto de questões verificadas por rodada
KAIA_VERIF_PAUSA_S=0                       # pausa entre chamadas (contorna rate limit)
KAIA_QUARENTENA_ALUNOS=3                   # alunos em paralelo no mutirão de quarentena

# Opcional — modelo de embedding do few-shot dinâmico (pgvector).
GEMINI_EMBED_MODEL=gemini-embedding-001

# ---- Pagamento (Mercado Pago) — SEMI-PRONTO, ver a seção "Pagamento" ----
# Sem MP_ACCESS_TOKEN o pagamento fica indisponível e NINGUÉM é barrado: as rotas
# respondem 503 e o acesso ao estudo segue liberado. O site não cai por falta de chave.
# Chave começada em TEST- = sandbox (o backend detecta sozinho e sinaliza no /assinatura).
MP_ACCESS_TOKEN=
MP_PUBLIC_KEY=
MP_WEBHOOK_SECRET=      # painel do MP → Webhooks → "Segredo". Sem ele o webhook RECUSA tudo.
APP_URL=                # URL pública do site; entra no back_url do checkout
```

> Duas variáveis que não entram no `.env` normal: `CHAVE_ACESSO` é apelido de `API_KEY`
> (o código aceita as duas), e `HOST` só vale ao rodar `python app.py` direto —
> o padrão `127.0.0.1` serve para desenvolvimento. `KAIA_GROQ_MODELO` é usada só pelo
> script offline `ml/temas_que_caem.py`, não pelo backend.

> [!WARNING]
> **`KAIA_DB_SCHEMA=teste` é só para máquina de teste local.** Em produção (Render) essa
> variável NÃO pode estar definida — senão a produção rodaria no schema de teste.

> O backend **não usa** chave de API do Supabase — só a `DATABASE_URL` (o único segredo) e a `SUPABASE_URL` (pública). **Nunca** coloque a chave secret (`sb_secret_`) aqui nem no frontend.

### 3. Criar o `config.js` do frontend

`config.js` está no `.gitignore` e **não vem no clone**. Copie `Frontend/config.example.js` para `Frontend/config.js` e preencha:

```js
SUPABASE_URL: 'https://<PROJECT_ID>.supabase.co',
SUPABASE_ANON_KEY: 'eyJ...',   // Supabase → Settings → API → Project API keys → anon public
```

> Use a chave **anon** (JWT, começa com `eyJ...`) — é pública por design (o RLS protege os dados).
> **NÃO** use a `sb_publishable_...`: o supabase-js @2 do CDN não a envia como `apikey` e o login quebra com `400 "No API key found"`. **Nunca** a `service_role` (secret).
> Onde achar o `<PROJECT_ID>`: Supabase → Settings → General (a URL é `https://<PROJECT_ID>.supabase.co`).

> [!NOTE]
> **Modelo de atenção (`/diagnose`):** o modelo v2 **não é versionado** — gere-o uma vez
> (seed fixa, sempre igual): `python ml/gerar_base_v2.py`. Cria `modelo_rf_v2.pkl` +
> `scaler_v2.pkl`. Sem eles o backend sobe normal, mas `/diagnose` responde 503. A tabela
> `probe_labels`, que guarda os rótulos do probe, já vem no schema versionado — nada a
> rodar à mão.

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

### 7. Banco de dados

> [!CAUTION]
> **3 MIGRATIONS AINDA NÃO APLICADAS NO SUPABASE DE PRODUÇÃO.** Elas estão
> versionadas e passam no CI, mas ninguém as rodou no projeto real ainda:
>
> | Migration | Cria |
> |---|---|
> | `20260927120000_isencao_testers.sql` | `perfis.isento` |
> | `20260927130000_email_do_responsavel.sql` | `consentimentos.responsavel_email` |
> | `20260927140000_assinaturas.sql` | tabelas `assinaturas` e `mp_webhooks` |
>
> **Sem aplicar, o backend quebra** com erro de coluna/tabela inexistente assim que
> alguém tocar em: consentimento (grava `responsavel_email`), qualquer rota de
> assinatura, ou a checagem de isenção (`_conta_isenta` lê `perfis.isento`).
> O `_conta_isenta` falha aberto e devolve `True` no erro — o site não cai, mas todo
> mundo passa como isento, o que não é o comportamento desejado.


O banco (schema **e** dados) vive no **Supabase, na nuvem**. Usando o **mesmo projeto**
(mesma `DATABASE_URL`) — o caso normal, inclusive numa máquina nova — **o banco já está
pronto: não precisa rodar nada aqui.** As contas de teste do passo 6 já existem, com as
senhas certas.

Você só mexe no banco nestes casos:

- **Recriar/resetar as contas de teste** (ex.: alguém trocou as senhas e o login parou):
  `python Backend/seed_contas_teste.py --commit` (sem `--commit` = dry-run, só mostra o
  plano; rode de dentro de `Backend/`). Recria as 6 contas com senha `teste1234`.
  ⚠️ **Depende do schema base já existir** (`escolas`, `turmas`, `professores`,
  `coordenadores`) — ele *reaproveita* essas linhas, **não as cria**.
- **Schema do banco** (inclusive o trigger de consentimento no signup): já vem inteiro no
  snapshot versionado — veja [`supabase/README.md`](supabase/README.md) para aplicar num
  projeto novo. Não há mais migration avulsa para rodar à mão.
- *(opcional)* **Dar volume ao dashboard**: `python Backend/seed_sintetico.py --commit`.

Limpeza (antes de produção / quando entrarem alunos reais): `Backend/limpar_sintetico.sql`
e `python Backend/limpar_contas_teste.py --commit`.

> [!NOTE]
> **O schema base está versionado** em `supabase/migrations/20260809203146_remote_schema.sql`
> — o snapshot traz o `CREATE TABLE` de `perfis`, `escolas`, `turmas`, `professores`,
> `coordenadores`, `sessions`, `session_events`, `pai_aluno` e companhia. O CI aplica todas
> as migrations num Postgres limpo a cada push, então um projeto Supabase novo pode ser
> recriado a partir daqui.

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
| `/events` | POST | Registra os eventos de foco dos sensores (e captura o rótulo do probe) |
| `/diagnose` | GET | Estima o estado de atenção da sessão (modelo v2) |
| `/intervencao/pendente`, `/intervencao/feedback` | GET/POST | Intervenções reativas (Fluxo A) |
| `/prevencao/pausa` | POST | Decide o apoio da pausa entre rodadas (Fluxo B) |
| `/consentimento/solicitar`, `/consentimento/status` | POST/GET | Gera e consulta o link de autorização do responsável |
| `/consentimento/{token}` | GET/POST | Página do responsável: lê o pedido e registra o aceite |
| `/dashboard/dados` | GET | Dados do dashboard interno (acesso restrito por `role`) |
| `/responsavel/aluno`, `/responsavel/painel` | GET | Painel de responsáveis |
| `/assinatura` | GET | Estado da assinatura da conta (acesso, status, planos, se é sandbox) |
| `/assinatura/criar` | POST | Abre a assinatura e devolveria o link do Mercado Pago — **503 sem chave** |
| `/webhook/mercadopago` | POST | Confirmação do MP. Exige `x-signature` válida; idempotente |

---

## 💳 Pagamento e isenção (SEMI-PRONTO)

Estrutura pronta, **esperando a chave do Mercado Pago**. O que já funciona hoje:

- `Backend/pagamento.py` — planos, trial de 7 dias, validação da assinatura do webhook
  (HMAC-SHA256 do header `x-signature`, com `compare_digest` e janela de 5 min contra
  replay) e a decisão de acesso. Tudo sem banco e sem rede, então dá para testar sem chave.
- Tabela `assinaturas` (`trial | ativa | suspensa | cancelada`) com `mp_id` **UNIQUE** e
  tabela `mp_webhooks` — as duas camadas de idempotência, porque o MP reenvia a mesma
  notificação por timeout e por reentrega manual.
- Suspender **não apaga nada**: bloqueia o acesso ao estudo; caderno, histórico e progresso ficam.

**Isenção (não-retroativa).** Quem já testava a KaIA de graça não é empurrado para pagar:

| Fonte | O que cobre |
|---|---|
| `perfis.isento` | Coluna comum, preenchida por `UPDATE` único no corte de 2026-09-27 — os testers com e-mail pessoal. O conjunto nasce congelado; conta nova nasce `false`. |
| `perfis.conta_de_teste` | Coluna **gerada** (`lower(email) like '%@teste.kaia'`) — vale também para contas da equipe criadas depois. |

O backend checa `isento OR conta_de_teste` (`_conta_isenta` no `app.py`). Ela falha
**aberto**: se o Postgres cair, libera — barrar quem já pagou por causa de infraestrutura
seria pior. E **sem `MP_ACCESS_TOKEN` ninguém é barrado**: esquecer de configurar não pode
virar "o site caiu".

### O que falta (marcado como `PENDENTE (Bia)` no código)

1. `pip install mercadopago` + somar ao `Backend/requirements.txt`
2. Preencher `MP_ACCESS_TOKEN`, `MP_PUBLIC_KEY`, `MP_WEBHOOK_SECRET` e `APP_URL` no `.env`
3. Trocar os dois blocos comentados em `app.py` pela chamada real: `preapproval().create()`
   em `/assinatura/criar` e `preapproval().get()` em `/webhook/mercadopago`. O código de
   exemplo já está escrito nos comentários, com o `free_trial` de 7 dias e o
   `external_reference` (o elo entre o pagamento e a linha em `assinaturas`).
4. Conferir os preços em `pagamento.py` antes de cobrar de verdade.

Hoje o webhook **valida e registra, mas não ativa nada** — de propósito. Sem confirmar o
estado real na API do MP, confiar no corpo da notificação seria confiar em quem chamou.

> **Menor de 18:** quem paga é o responsável vinculado. `_assinatura_da_conta` procura a
> assinatura do próprio aluno e, não achando, a do responsável via `pai_aluno`.

---

## 🎨 Detalhes da interface

**Caderno** (`materias.js`, só aparece com o caderno aberto)
- **Alça de redimensionar** entre a questão e o caderno: arrasta para decidir quanto cada
  lado ocupa, com mínimo de 28% para nenhum dos dois sumir. Some abaixo de 820px, onde o
  split vira coluna. A preferência fica no `localStorage`.
  Durante o arrasto a flag `redimensionandoSplit` faz o sensor de `mousemove` pular a
  amostragem — sem isso o traço horizontal do arrasto entraria no `mouse_track` como
  trajeto de estudo, que não é.
- **Paleta de símbolos** (27 caracteres Unicode: π √ ∑ ∫ ≤ ± ² ½ Δ θ → …) num `<details>`
  recolhido, **só em MAT e FIS**. Clica e o símbolo entra no ponto do cursor. É texto puro:
  salva no caderno como qualquer letra, sem mudar o armazenamento. Sem biblioteca de
  fórmula — fração montável exigiria trocar o caderno de texto para conteúdo rico.

**Temas de fundo** (perfil → Configurações; tokens em `style.css`, blocos `html[data-luz]`)

| # | Tema | Fundo | Observação |
|---|---|---|---|
| 1 | Padrão | `#f4ecdd` | o marfim da marca; não redeclara nada |
| 2 | Neutro | `#f1eee9` | mesmo papel, menos amarelo |
| 3 | Azul suave | `#8897ba` | *skin* — não segue o 60-30-10 |
| 4 | Cinza-pedra | `#a9a29a` | *skin* |

Nos dois *skins* o fundo da página é médio, então os tokens de TEXTO também mudam (o
`#7d5f45` original dava 1,8:1 sobre o azul). Todos os pares texto × superfície foram
medidos: o pior fica em **4,60:1**, acima do 4,5:1 da WCAG AA. Aplica em toda página
(`aplicarLuzFundo` no `comum.js`).

**Barra de teste das intervenções** — **escondida por padrão**, inclusive nas contas
`@teste.kaia`. Era automática nesses e-mails, mas os testers do beta usam justamente essas
contas: uma intervenção disparada à mão entrava na sessão como se fosse do modelo. Para
ligar: `kaiaGatilhoTeste(true)` no console (persiste; `false` desliga).

**Avaliação** — `pages/avaliacao.html` com o formulário do Tally, alcançada pelo botão no
fim do perfil. O iframe usa `data-tally-src` **sem** `src`: o `loadEmbeds()` do Tally
procura por `iframe[data-tally-src]:not([src])` e cresce o iframe até a altura total, então
quem rola é a página. Se o `embed.js` for bloqueado, o `onerror` preenche o `src` na mão e
o formulário aparece mesmo assim.

---

## 🔍 SEO

`robots.txt`, `sitemap.xml` e `llms.txt` ficam em **`Frontend/`**, não na raiz do repo.
O `render.yaml` define `staticPublishPath: ./Frontend`, então `Frontend/` **é** a raiz
servida — é dali que eles respondem em `/robots.txt`, `/sitemap.xml` e `/llms.txt`, os
únicos lugares onde o Google procura. Na raiz do repo nunca seriam publicados.

- **robots.txt** bloqueia as 10 páginas atrás de login. `consentimento.html` fica de fora
  com destaque: o link carrega um **token de autorização** na query.
- **sitemap.xml** lista só as 5 públicas (index, login, cadastro, termos, privacidade).
  A raiz `/` fica de fora: é só um redirect para `/pages/index.html`, e sitemap lista URL
  canônica.
- As 5 públicas têm `title`, `description`, `canonical` e `og:*` (sem os `og:` o link
  colado no WhatsApp saía sem texto).

---

## 🚀 Deploy (Render)

São **dois** serviços — o `render.yaml` na raiz descreve os dois. O site é estático e
não hiberna; a API no plano grátis dorme após 15 min parada e a primeira chamada
depois disso leva ~50s.

| Serviço | Tipo | Pasta | Build | Start |
|---|---|---|---|---|
| `kaia-api` | Web Service | `Backend/` | `pip install -r Backend/requirements.txt && python ml/gerar_base_v2.py` | `uvicorn app:app --app-dir Backend --host 0.0.0.0 --port $PORT` |
| `kaia` | Static Site | `Frontend/` | `node Frontend/gerar-config.js` | — |

Dois detalhes que quebram o deploy se passarem despercebidos:

- **O modelo não vai para o git.** O `.pkl` está no `.gitignore`, então o build
  precisa rodar `ml/gerar_base_v2.py` (~3s, seed fixa). Sem isso o `/diagnose`
  responde 503.
- **O `config.js` também não.** O `Frontend/gerar-config.js` o escreve a partir das
  variáveis do Render. Sem esse passo o front sobe sem configuração: a API cai no
  fallback `127.0.0.1:5000` e o `supabaseClient` fica `null` — login morto.

### Variáveis no painel

**API** — `DATABASE_URL`, `API_KEY`, `SUPABASE_URL`, `KAIA_CORS_ORIGINS` (a URL do
site), `KAIA_DB_SCHEMA=public`, `KAIA_CPF_PEPPER` (se houver aluno menor) e, para ligar a
camada preventiva no beta, `KAIA_PREVENCAO_ATIVA=1` + `KAIA_PREVENCAO_MODO=fixo` +
`KAIA_AB_TESTE=0`. **Deixe `KAIA_SEED_ATIVO` de fora.**

**Site** — `KAIA_API_URL` (a URL da API), `KAIA_SUPABASE_URL`,
`KAIA_SUPABASE_ANON_KEY` (a anon `eyJ...`, nunca a `service_role`).

As duas URLs cruzadas só existem depois do primeiro deploy: suba, copie e volte
para preencher.

### Antes de mandar o link

- [ ] Rodar a migration `20260909100000_rls_tabelas_expostas.sql` — sem ela a chave
      anon lê `questoes_cache` inteira, **gabarito junto**.
- [ ] Desligar a confirmação de e-mail no Supabase (Auth → Providers → Email). Ligada,
      o limite grátis é de **3 e-mails por hora** e o quarto cadastro trava.
- [ ] Conferir que `KAIA_CORS_ORIGINS` tem a URL do site, sem barra no fim.

---

## 📖 Convenções

> [!NOTE]
> Antes de contribuir, veja o **`CLAUDE.md`** na raiz do projeto. Ele define as convenções: paleta de cores, acessibilidade (público TEA/TDAH), regra de segurança (e-mail é identificador, não credencial) e estilo de comentários.

---

## ⏳ Semi-pronto, esperando algo

| O quê | Esperando | Onde |
|---|---|---|
| **Pagamento (Mercado Pago)** | chave no `.env` + `pip install mercadopago` + trocar os 2 blocos comentados | `PENDENTE (Bia)` no `app.py`; ver a seção "Pagamento e isenção" |
| **3 migrations** | serem aplicadas no Supabase de produção | aviso em "7. Banco de dados" |
| **Confirmação de e-mail** | ligar no painel do Supabase (Auth → Providers → Email) **e** corrigir o front antes | ver abaixo |
| **`og:image`** | uma arte 1200×630 para o preview de compartilhamento | as 5 páginas públicas têm os outros `og:*` |

> [!WARNING]
> **Não ligue a confirmação de e-mail do Supabase sem mexer no front primeiro.** O
> `login.js` já trata os dois casos, mas o ramo "confirmação ligada" é **uma linha só**:
> ele mostra a mensagem e **não** chama `POST /perfil` (que grava `versao_termos`,
> `data_nascimento` e o aceite dos termos) nem `mostrarLinkResponsavel()`. Ligar hoje
> faria: aceite de termos **não registrado** e menor de idade **sem link do responsável**.
> Quebra silenciosamente o registro de LGPD.

---

## 🧭 Problemas conhecidos / próximos passos

> [!NOTE]
> **Autenticação: Supabase Auth (e-mail + senha).** O backend valida o **JWT** nas rotas de dados (`Backend/auth.py`); o front envia o token via `apiFetch`. O controle de acesso continua no `role` do banco, verificado no backend.

- [ ] Estender a proteção por JWT às rotas ainda abertas (baixa sensibilidade) e revisar o gate `X-Kaia-User` do dashboard.
- [ ] **Validar o modelo v2 com dado real**: hoje é 100% sintético (hipótese). Coletar probes → rodar `python ml/treinar_com_probe.py` (dá a acurácia real e re-treina híbrido). Vale como pesquisa: o v2 não decide nada.
- [ ] **Rodar o beta do Fluxo B** com `KAIA_PREVENCAO_MODO=fixo` e medir a aceitação do plano. Só então ligar o `bandit`, e só depois promover o Modelo 1 de sombra para gatilho.
- [ ] **Teto de intervenções reativas é por sessão inteira** (5, sem reset por rodada): em sessão longa as últimas questões ficam sem a camada reativa. Medir quantos batem no teto antes de trocar por uma janela de tempo.
- [ ] **Aplicar as 3 migrations pendentes no Supabase de produção** (ver o aviso em "7. Banco de dados").
