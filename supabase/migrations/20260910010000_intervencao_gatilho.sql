-- ============================================================
--  interventions.gatilho — o que disparou a intervenção
-- ============================================================
-- Passaram a existir três caminhos, e um deles NÃO usa o modelo de atenção:
--
--   'medicao'  — o aluno saiu da aba. O navegador avisou; não é inferência.
--   'regra'    — o comportamento acusou queda (acerto recente caiu, ou o tempo saiu
--                do próprio ritmo do aluno). Independe do Random Forest.
--   'modelo'   — reservado: o RF suspeita e nada objetivo confirma. Hoje não dispara.
--
-- Registrar isso é o que permite responder, depois, a pergunta que decide se o modelo
-- de atenção vale: "as intervenções disparadas pelo modelo tiveram desfecho melhor que
-- as disparadas pela regra?". Sem a coluna, os dois casos ficam indistinguíveis no dado
-- e a comparação não existe.
--
-- Aditiva e idempotente.

alter table if exists public.interventions
  add column if not exists gatilho text;

create index if not exists idx_interventions_gatilho
  on public.interventions (gatilho, intervention_type);
