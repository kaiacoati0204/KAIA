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

> Dica: se tiver **Docker**, `supabase db pull` faz os dois passos de uma vez e já
> organiza como migration. Sem Docker, use o `pg_dump`/`psql` acima.

## Mudanças novas de schema (daqui pra frente)

Toda alteração de estrutura deve virar uma migration nova (não editar o snapshot):

```bash
supabase migration new nome_curto     # cria migrations/<ts>_nome_curto.sql
# escreva o ALTER/CREATE dentro do arquivo
```

Manter isto em dia é o que evita a migration virar mentira — o ponto fraco de todo
schema versionado.
