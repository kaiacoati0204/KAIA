-- ============================================================
--  consentimento do responsável legal (LGPD art. 14)
-- ============================================================
-- Público do beta é menor de idade e a coleta é de comportamento (tempo, saída de aba,
-- ociosidade, mouse, autorrelato). Checkbox no navegador não reconstrói quem autorizou:
-- o aceite precisa ficar registrado com quem, quando, de onde e qual versão do documento.
-- O CPF NUNCA é guardado em claro — só o HMAC (ver Backend/consentimento.py).
-- Idempotente.

alter table public.perfis
  add column if not exists data_nascimento     date,
  add column if not exists consentimento_status text;   -- null = ainda não solicitado

create table if not exists public.consentimentos (
  id                      uuid primary key default gen_random_uuid(),
  aluno_id                uuid not null,
  token                   text not null unique,          -- o link enviado ao responsável
  status                  text not null default 'pendente'
                            check (status in ('pendente', 'aprovado', 'recusado', 'expirado')),
  responsavel_nome        text,
  responsavel_cpf_hash    text,                          -- HMAC-SHA256, nunca o CPF
  responsavel_parentesco  text,
  documento_versao        text not null,
  aceite_ts               timestamptz,
  aceite_ip               text,
  criado_em               timestamptz not null default now(),
  expira_em               timestamptz not null
);

create index if not exists consentimentos_aluno_idx on public.consentimentos (aluno_id);

-- Só o backend (service role) enxerga: RLS ligada e SEM política = ninguém com a chave
-- anon/authenticated lê nome de responsável nem hash de CPF.
alter table public.consentimentos enable row level security;
revoke all on public.consentimentos from anon, authenticated;
