-- ============================================================
--  interventions.gatilho — o que disparou a intervenção
-- ============================================================
-- 'medicao' = saiu da aba (o navegador avisou, não é inferência); 'regra' = acerto
-- recente caiu ou o tempo saiu do ritmo do aluno, independe do Random Forest;
-- 'modelo' = reservado (RF suspeita sem confirmação objetiva), hoje não dispara.
-- Sem a coluna não dá para comparar desfecho modelo x regra — a pergunta que decide
-- se o modelo de atenção vale. Aditiva e idempotente.

alter table if exists public.interventions
  add column if not exists gatilho text;

create index if not exists idx_interventions_gatilho
  on public.interventions (gatilho, intervention_type);
