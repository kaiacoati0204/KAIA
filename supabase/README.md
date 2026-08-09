# Migrations do banco (Supabase / Postgres)

Schema versionado do KaIA. Antes disso, a estrutura vivia **só** dentro do projeto
Supabase e não dava para recriar o banco a partir do repositório.

## O que tem aqui

- `migrations/<timestamp>_remote_schema.sql` — **snapshot completo do schema `public`**
  (tabelas, colunas, tipos, FKs, CHECKs, RLS habilitado) gerado por `pg_dump --schema-only`,
  **mais** o trigger `on_auth_user_created` em `auth.users` (capturado à parte, pois o
  `auth` é schema gerenciado pelo Supabase). Esse trigger chama `public.criar_perfil_no_signup()`
  e cria a linha em `perfis` a cada cadastro — é a base do `perfis.user_id == sub` do JWT.
- **Só schema, sem dados.** Dados de teste ficam no `/seed/aluno-teste` (backend), não aqui.
- RLS: 15 tabelas têm RLS **habilitado sem policies** — o acesso é feito pelo backend
  (conexão de serviço), não pela anon key. Não é bug; é o modelo atual.

## Recriar o banco do zero (projeto Supabase novo)

O trigger referencia `auth.users`, então o alvo precisa ser um **projeto Supabase**
(o schema `auth` já existe lá). Use o **Session Pooler (porta 5432)** — o Transaction
Pooler (6543) do `.env` **não** serve para aplicar schema.

Com `psql`:

```bash
psql "postgresql://postgres.<project-ref>:<senha>@aws-1-<região>.pooler.supabase.com:5432/postgres" \
  -f supabase/migrations/<timestamp>_remote_schema.sql
```

Ou, com a Supabase CLI ligada ao projeto (precisa de Docker):

```bash
supabase link --project-ref <project-ref>
supabase db push
```

## Regenerar o snapshot (depois de mudar o schema no Supabase)

Precisa do `pg_dump` **17.x** (versão do servidor) e da URL do Session Pooler:

```bash
pg_dump --schema-only --schema=public --no-owner "<session-pooler-url>" \
  -f supabase/migrations/<novo-timestamp>_remote_schema.sql
# depois, re-anexar o trigger de auth.users (não sai no dump do schema public):
psql "<session-pooler-url>" -At \
  -c "select pg_get_triggerdef(t.oid)||';' from pg_trigger t
       where t.tgrelid='auth.users'::regclass and not t.tgisinternal;"
```

**Dois retoques manuais obrigatórios no arquivo regenerado** (senão o apply aborta):
1. Trocar `CREATE SCHEMA public;` por `CREATE SCHEMA IF NOT EXISTS public;` — todo
   alvo (Supabase novo, CI) já tem o `public`.
2. Anexar o `CREATE TRIGGER ... ON auth.users` (o passo do `pg_get_triggerdef` acima).

> Dica: se tiver **Docker**, `supabase db pull` faz o dump de uma vez. Sem Docker,
> use o `pg_dump`/`psql` acima. O trigger de `auth.users` e o retoque do schema
> continuam sendo manuais nos dois caminhos.

## Aplicar num alvo que NÃO é Supabase (ex.: Postgres puro / CI)

O dump referencia roles internos do Supabase (`anon`, `authenticated`, `service_role`,
`supabase_admin`) e o `auth.users`. Num Postgres puro eles não existem — crie stubs
antes de aplicar:

```sql
create role anon; create role authenticated; create role service_role; create role supabase_admin;
create schema auth; create table auth.users (id uuid primary key, email text);
```

## CI valida isto automaticamente

O job `migrations` em `.github/workflows/ci.yml` sobe um Postgres limpo, cria esses
stubs, aplica todas as migrations com `ON_ERROR_STOP=1` e **falha se qualquer uma
der erro** — é o guarda contra a migration envelhecer ou quebrar. Em seguida, no
mesmo Postgres já migrado, roda os **testes de integração** (`tests/test_integracao.py`):
o app real contra dados reais (autorização entre usuários, ownership de sessão,
isolamento por token).

### Rodar os testes de integração localmente

São opt-in: só rodam se `KAIA_TEST_DATABASE_URL` apontar para um Postgres com a
migration aplicada (senão são pulados). Com um Postgres de teste no ar:

```bash
# 1) crie os stubs e aplique a migration (ver seção "alvo que NÃO é Supabase")
# 2) aponte a env e rode só os de integração:
KAIA_TEST_DATABASE_URL="postgresql://user:senha@host:5432/db" pytest tests/test_integracao.py -q
```

## Mudanças novas de schema (daqui pra frente)

Toda alteração de estrutura deve virar uma migration nova (não editar o snapshot):

```bash
supabase migration new nome_curto     # cria migrations/<ts>_nome_curto.sql
# escreva o ALTER/CREATE dentro do arquivo
```

Manter isto em dia é o que evita a migration virar mentira — o ponto fraco de todo
schema versionado.
