-- Few-shot DINÂMICO (Passo 2): banco de questões reais + busca por similaridade (pgvector).
-- As questões reais NÃO são servidas ao aluno — entram só como exemplo recuperado no prompt.
create extension if not exists vector;

create table if not exists questoes_reais (
    id           bigserial primary key,
    materia      text,
    enunciado    text  not null,
    alternativas jsonb not null,
    gabarito     int,
    embedding    vector(768)   -- TEM de bater com EMBED_DIM no Backend/app.py
);

-- Índice p/ busca por similaridade de cosseno (o operador <=> usa cosine distance).
create index if not exists questoes_reais_embedding_idx
    on questoes_reais using ivfflat (embedding vector_cosine_ops) with (lists = 100);

create index if not exists questoes_reais_materia_idx on questoes_reais (materia);
