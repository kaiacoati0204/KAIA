-- ============================================================
--  ASSINATURAS (Mercado Pago)
-- ============================================================
-- Uma linha por conta que PAGA. Menor de idade não assina: quem paga é o responsável
-- vinculado (pai_aluno), então `user_id` aqui pode ser o perfil do responsável e o
-- acesso do filho é liberado pelo vínculo — ver _acesso_liberado no app.py.
--
-- `mp_id` é UNIQUE de propósito: o Mercado Pago REENVIA o mesmo webhook (retry por
-- timeout, reentrega manual pelo painel). Sem essa restrição, um retry viraria segunda
-- ativação e o trial poderia ser estendido de graça. A unicidade é a rede de baixo —
-- o código também checa antes, mas quem garante é o banco.
--
-- NADA de dado de cartão aqui. O cartão vive no Mercado Pago; guardamos só o id da
-- transação/assinatura deles. Guardar cartão exigiria PCI-DSS e não é o nosso caso.
--
-- Suspender NÃO apaga: o aluno perde o acesso ao estudo, nunca o caderno, o histórico
-- ou o progresso. A linha muda de status e pronto.
-- Idempotente.

create table if not exists public.assinaturas (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null,
  plano       text not null,
  status      text not null default 'trial'
                check (status in ('trial', 'ativa', 'suspensa', 'cancelada')),
  inicio      timestamptz not null default now(),
  fim         timestamptz,                    -- fim do trial, ou do período pago
  mp_id       text unique,                    -- id no Mercado Pago (preapproval/payment)
  criado_em   timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

comment on table public.assinaturas is
  'Assinatura por conta pagante. Menor de 18: a linha é do responsável, e o acesso do aluno vem do vínculo em pai_aluno.';
comment on column public.assinaturas.mp_id is
  'Id da transação no Mercado Pago. UNIQUE porque o MP reenvia o mesmo webhook — é o que impede dupla ativação.';

-- A consulta quente é "esta conta tem assinatura válida agora?" a cada entrada no estudo.
create index if not exists assinaturas_user_idx on public.assinaturas (user_id, status);

-- Eventos de webhook JÁ processados. O UNIQUE em mp_id acima cobre o caso de ativação,
-- mas o MP manda outros tipos (cancelamento, falha de cobrança) que não criam linha em
-- `assinaturas` — e esses também não podem ser processados duas vezes.
create table if not exists public.mp_webhooks (
  mp_id        text primary key,
  tipo         text,
  recebido_em  timestamptz not null default now()
);

comment on table public.mp_webhooks is
  'Log de idempotência: mp_id já visto é ignorado. O MP reenvia por timeout e por reentrega manual.';

-- Dinheiro e vínculo: só o backend (service role). RLS ligada e SEM política = a chave
-- anon/authenticated não lê assinatura de ninguém.
alter table public.assinaturas enable row level security;
alter table public.mp_webhooks enable row level security;
revoke all on public.assinaturas from anon, authenticated;
revoke all on public.mp_webhooks from anon, authenticated;
