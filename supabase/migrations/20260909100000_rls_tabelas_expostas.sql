-- ============================================================
--  RLS nas três tabelas que ficaram abertas
-- ============================================================
-- O PostgREST expõe `public` e a chave anon é pública (config.js), então a proteção
-- é o RLS — e estas três nasceram sem. O motivo é questoes_cache: sem RLS, qualquer
-- aluno com devtools baixa resposta_correta/explicacao de TODAS as questões.
-- questoes_vistas (o que cada aluno viu) e pai_aluno (vínculo) vão junto.
-- Zero policies de propósito: nega tudo a anon/authenticated, igual às outras 16
-- tabelas. O backend conecta como `postgres` (rolbypassrls) e não é afetado. Idempotente.

alter table if exists public.questoes_cache  enable row level security;
alter table if exists public.questoes_vistas enable row level security;
alter table if exists public.pai_aluno       enable row level security;
