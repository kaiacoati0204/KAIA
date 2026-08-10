-- ==== Reward implícito por mudança de estado (Thompson, Fase 1) ====
-- Guarda o estado no disparo e na resolução da intervenção, e a origem do reward.
-- Idempotente: pode rodar mais de uma vez sem erro.

alter table interventions
  add column if not exists estado_antes  text,          -- estado do aluno quando a intervenção disparou
  add column if not exists estado_depois text,          -- estado após a janela de medição
  add column if not exists reward_origem text;           -- 'explicito' (polegar) | 'auto_estado'
