-- ============================================================
--  ISENÇÃO DOS TESTERS (não-retroativo)
-- ============================================================
-- Quem já estava testando a KaIA de graça não pode ser empurrado para pagamento nem
-- para verificação de e-mail obrigatória por causa de uma regra criada depois. Conta
-- isenta segue usando exatamente como hoje; só conta NOVA entra no fluxo.
--
-- Duas populações, e elas se comportam de formas diferentes:
--
--   1. Contas da equipe (@teste.kaia) — a coluna gerada `conta_de_teste` (migration
--      20260924120000) já resolve, inclusive para contas criadas DEPOIS desta data.
--      Não duplico a regra aqui: ela continua morando em um lugar só.
--
--   2. Testers com e-mail pessoal — não têm marca no e-mail. O único traço é terem
--      sido criadas antes do corte, então é um UPDATE único.
--
-- Por que `isento` é coluna COMUM e não gerada: uma coluna gerada com data fixa exigiria
-- um literal timestamptz dentro da expressão, e o Postgres recusa isso em GENERATED
-- (o cast text->timestamptz é STABLE, não IMMUTABLE — depende do TimeZone da sessão).
-- Com UPDATE único o conjunto nasce congelado, que é justamente o "não-retroativo":
-- ninguém entra nele depois, e o default false já cobre as contas novas.
--
-- A checagem no backend é `isento OR conta_de_teste` (ver _conta_isenta no app.py):
-- a primeira cobre os testers de agora, a segunda as contas de teste futuras.
-- Idempotente.

alter table public.perfis
  add column if not exists isento boolean not null default false;

comment on column public.perfis.isento is
  'Tester anterior à cobrança: pula pagamento e verificação de e-mail. Congelado no corte de 2026-09-27; contas novas nascem false.';

-- O corte: tudo que já existia quando a regra foi criada. `where not isento` mantém
-- idempotente (rodar de novo não mexe em quem já está marcado).
update public.perfis
   set isento = true
 where not isento
   and created_at < timestamptz '2026-09-27 00:00:00-03';

create index if not exists perfis_isento_idx
  on public.perfis (isento) where isento;
