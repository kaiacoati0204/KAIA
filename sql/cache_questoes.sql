-- ============================================================
--  KaIA — cache de questões (reuso entre alunos, menos Gemini)
-- ============================================================
-- questoes_cache: banco de questões geradas, reusáveis entre alunos.
-- questoes_vistas: o que cada aluno já viu (para não repetir).
-- Rode no Supabase -> SQL Editor.

CREATE TABLE IF NOT EXISTS questoes_cache (
    questao_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    materia          VARCHAR NOT NULL,
    tema             VARCHAR NOT NULL,
    nivel            INTEGER NOT NULL CHECK (nivel BETWEEN 1 AND 5),
    hobbie           VARCHAR,        -- NULL = questão genérica sem hobbie
    enunciado        TEXT NOT NULL,
    alternativas     JSONB NOT NULL, -- array de 5 strings
    resposta_correta INTEGER NOT NULL CHECK (resposta_correta BETWEEN 0 AND 4),
    explicacao       TEXT NOT NULL,
    porque_erradas   JSONB NOT NULL,
    criada_em        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS questoes_vistas (
    aluno_id    UUID NOT NULL REFERENCES perfis(user_id) ON DELETE CASCADE,
    questao_id  UUID NOT NULL REFERENCES questoes_cache(questao_id) ON DELETE CASCADE,
    visto_em    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (aluno_id, questao_id)
);

CREATE INDEX IF NOT EXISTS ix_cache_busca
    ON questoes_cache (materia, tema, nivel, hobbie);
CREATE INDEX IF NOT EXISTS ix_vistas_aluno
    ON questoes_vistas (aluno_id);
