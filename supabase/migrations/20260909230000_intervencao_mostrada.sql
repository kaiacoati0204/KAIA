-- ============================================================
--  interventions.mostrada_em — "esta já foi entregue ao aluno"
-- ============================================================
-- Só existia triggered_at (quando o motor decidiu), e /intervencao/pendente devolvia
-- qualquer linha sem reward dos últimos 5 min. Com o front consultando a cada 15s e
-- só o reward limpando a pendência, fechar o card sem polegar fazia o MESMO card
-- voltar até 20 vezes (1º teste real, pausa_ativa). O campo também separa, no dado,
-- "viu e ignorou" de "nunca chegou a ver". Aditiva e idempotente.

alter table if exists public.interventions
  add column if not exists mostrada_em timestamptz;

create index if not exists idx_interventions_pendente
  on public.interventions (session_id, triggered_at desc)
  where reward is null and mostrada_em is null;
