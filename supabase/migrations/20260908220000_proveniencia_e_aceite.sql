-- ============================================================
--  Proveniência e aceite — dados que não se recuperam depois
-- ============================================================
-- Três lacunas que só apareceriam quando já fosse tarde:
--
--   1. quem gerou cada questão. O prompt mudou cinco vezes e o modelo pode mudar;
--      sem registrar, não dá para responder depois "a regra nova reduziu o erro?"
--   2. quem aceitou os termos e quando. O checkbox só existia no navegador — não
--      havia como provar aceite, e o público é menor de idade.
--   3. em que versão do app a sessão rodou. `app_version` era o default fixo
--      "mvp-0.1" em toda sessão, então "antes x depois" de qualquer correção
--      ficaria indistinguível.
--
-- Aditiva e idempotente.

alter table if exists public.questoes_cache
  add column if not exists modelo         text,   -- GEMINI_MODEL que gerou
  add column if not exists versao_prompt  text;   -- versão das regras do prompt

alter table if exists public.perfis
  add column if not exists aceite_termos_em timestamptz,
  add column if not exists versao_termos    text;

create index if not exists idx_questoes_cache_modelo
  on public.questoes_cache (modelo, versao_prompt);
