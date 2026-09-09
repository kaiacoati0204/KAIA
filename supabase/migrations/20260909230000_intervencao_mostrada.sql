-- ============================================================
--  interventions.mostrada_em — "esta já foi entregue ao aluno"
-- ============================================================
-- A tabela só sabia QUANDO o motor decidiu intervir (triggered_at). Não havia
-- registro de a intervenção ter chegado à tela, e a rota /intervencao/pendente
-- devolvia qualquer linha sem reward dos últimos 5 min. Como o front consulta a
-- cada 15s e só o reward limpava a pendência, fechar o card sem dar o polegar
-- fazia o MESMO card voltar a cada ciclo — até 20 vezes. Foi visto no primeiro
-- teste real (pausa_ativa repetindo).
--
-- Além de corrigir a repetição, o campo separa dois casos que antes eram
-- indistinguíveis no dado: "o motor disparou e o aluno viu e ignorou" e "o motor
-- disparou e o aluno nunca chegou a ver".
--
-- Aditiva e idempotente.

alter table if exists public.interventions
  add column if not exists mostrada_em timestamptz;

create index if not exists idx_interventions_pendente
  on public.interventions (session_id, triggered_at desc)
  where reward is null and mostrada_em is null;
