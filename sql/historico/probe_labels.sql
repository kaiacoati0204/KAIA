-- ==== ROTULOS REAIS DO PROBE (dataset supervisionado) ====
-- Cada resposta do probe de autorrelato vira 1 exemplo (features no momento +
-- rótulo declarado pelo aluno). É o que tira o modelo do "100% sintético":
-- o ml/treinar_com_probe.py lê daqui pra validar e re-treinar (híbrido).
create table if not exists probe_labels (
    id          bigserial primary key,
    session_id  uuid not null,
    user_id     uuid,
    estado      text not null check (estado in ('engajado', 'distraido', 'muito_distraido')),
    features    jsonb not null,            -- vetor das 20 features NA MESMA representação do serving
    created_at  timestamptz not null default now()
);

create index if not exists idx_probe_labels_user on probe_labels (user_id);
create index if not exists idx_probe_labels_criado on probe_labels (created_at);
