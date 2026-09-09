-- ============================================================
--  RLS nas três tabelas que ficaram abertas
-- ============================================================
-- O Supabase publica o schema `public` via PostgREST, e a chave anon fica no
-- config.js do frontend — pública por design. A proteção é o RLS, e estas três
-- tabelas nasceram sem ele:
--
--   questoes_cache   — traz resposta_correta e explicacao. Sem RLS, qualquer
--                      aluno com o devtools aberto baixa o gabarito de TODAS as
--                      questões do cache. É o motivo desta migration.
--   questoes_vistas  — o que cada aluno já viu.
--   pai_aluno        — vínculo responsável/aluno.
--
-- Sem policy nenhuma de propósito: RLS ligada e zero policies = nega tudo para
-- anon e authenticated. É o mesmo estado das outras 16 tabelas. O backend não
-- passa por aqui — conecta como `postgres`, que tem rolbypassrls.
--
-- Idempotente.

alter table if exists public.questoes_cache  enable row level security;
alter table if exists public.questoes_vistas enable row level security;
alter table if exists public.pai_aluno       enable row level security;
