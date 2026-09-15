-- ============================================================
--  eventos_perda_foco — rótulos objetivos para os modelos de prevenção
-- ============================================================
-- Junta num lugar só o que conta como "o foco caiu": saída da KaIA >= 30 s (sem as abas da
-- própria KaIA), questão marcada pela regra DTS, abandono de questão e probe respondido como
-- vagando/fora. É daqui que o modelo de risco tira o rótulo; as decisões ficam nos eventos
-- 'decisao_intervencao' (grupo controle e probabilidade), para treinar só no controle.
-- security_invoker: a view respeita o RLS de session_events e não fica exposta à chave anon.
-- Idempotente.

create or replace view public.eventos_perda_foco
  with (security_invoker = true) as
select session_id, ts, 'saida_aba'::text as tipo,
       (payload->>'tempo_fora_foco_s')::double precision as duracao_s
  from public.session_events
 where event_type = 'tab_change'
   and coalesce((payload->>'interno')::boolean, false) = false
   and coalesce((payload->>'tempo_fora_foco_s')::double precision, 0) >= 30
union all
select session_id, ts, 'regra_dts', null
  from public.session_events
 where event_type = 'desengajamento_regra'
union all
select session_id, ts, 'abandono_questao',
       (payload->>'tempo_ate_abandono_ms')::double precision / 1000
  from public.session_events
 where event_type = 'question_abandon'
union all
select session_id, ts, 'probe_' || coalesce(payload->>'resposta', payload->>'estado'), null
  from public.session_events
 where event_type = 'probe_atencao'
   and payload->>'estado' in ('distraido', 'muito_distraido');

revoke all on public.eventos_perda_foco from anon, authenticated;
