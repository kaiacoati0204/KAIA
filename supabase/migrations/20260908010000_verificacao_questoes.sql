-- ============================================================
--  Verificação de questões geradas — funil antes de chegar ao aluno
-- ============================================================
-- Professores acharam questões com gabarito errado ou sem alternativa certa. O
-- filtro estrutural (Backend/app.py) pega o malformado; estas colunas sustentam a
-- verificação: veredito NULL = não verificada (QUARENTENA, servida só enquanto
-- poucos alunos a viram); 'ok' = verificador independente concordou com o
-- gabarito; 'suspeita' = divergiu ou disse que NENHUMA é correta, deixa de ser servida.
-- Aditiva e idempotente.

alter table if exists public.questoes_cache
  add column if not exists veredito           text,
  add column if not exists verificada_em      timestamptz,
  add column if not exists verificador_disse  integer,   -- índice da alternativa; -1 = "nenhuma"
  add column if not exists verificador_nota   text;      -- o problema apontado, quando houver

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'questoes_cache_veredito_check') then
    alter table public.questoes_cache
      add constraint questoes_cache_veredito_check
      check (veredito is null or veredito in ('ok', 'suspeita'));
  end if;
end $$;

-- Servir prioriza verificada; o índice evita varredura a cada busca no cache.
create index if not exists idx_questoes_cache_veredito
  on public.questoes_cache (materia, tema, nivel, veredito);
