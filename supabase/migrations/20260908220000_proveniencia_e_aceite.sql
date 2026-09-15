-- ============================================================
--  Proveniência e aceite — dados que não se recuperam depois
-- ============================================================
-- Registra o que não se reconstrói depois: modelo/versão do prompt de cada questão
-- (o prompt já mudou cinco vezes; sem isso não se mede se a regra nova reduziu o
-- erro); quem aceitou os termos e quando (o checkbox só existia no navegador, sem
-- prova de aceite, e o público é menor de idade). A terceira lacuna, `app_version`
-- fixo em "mvp-0.1", não passa por aqui: o front manda KAIA_VERSAO no POST /sessions.
-- Aditiva e idempotente.

alter table if exists public.questoes_cache
  add column if not exists modelo         text,   -- GEMINI_MODEL que gerou
  add column if not exists versao_prompt  text;   -- versão das regras do prompt

alter table if exists public.perfis
  add column if not exists aceite_termos_em timestamptz,
  add column if not exists versao_termos    text;

create index if not exists idx_questoes_cache_modelo
  on public.questoes_cache (modelo, versao_prompt);
