-- ============================================================
--  SMILES da molécula da questão (Química Orgânica)
-- ============================================================
-- A questão de classificação de cadeia mostra a molécula numa figura desenhada a partir
-- do SMILES. Nula: questão antiga e de qualquer outro tema não tem molécula, e continua
-- valendo como sempre. O backend só lê/escreve esta coluna com KAIA_ORGANICA_MOLECULA=1.
-- O nome da molécula NÃO é guardado em lugar nenhum (só serve ao portão de nome).
-- O portão de repetição busca por (materia, tema): o índice ix_cache_busca já cobre.
-- Aditiva e idempotente.

alter table if exists public.questoes_cache
  add column if not exists smiles text;   -- SMILES da molécula da figura; NULL = sem figura
