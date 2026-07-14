-- ============================================================
--  KaIA — logins de professor e coordenador
-- ============================================================
-- POR QUE ESTE ARQUIVO EXISTE:
-- `professores.email` e `coordenadores.email` são NULL em TODAS as linhas, e a
-- tabela `perfis` (que é onde o login procura o usuário) só tem role='aluno'.
-- Sem isso, nenhum professor ou coordenador consegue entrar na plataforma.
--
-- Rode este script no Supabase → SQL Editor. Ele é idempotente.
-- Depois, os e-mails gerados aparecem na consulta do final — use-os no login.

-- ------------------------------------------------------------
-- 1) Gera um e-mail para cada professor / coordenador
-- ------------------------------------------------------------
-- Formato: primeiro-nome.ultimo-nome@escola.kaia (sem acento, sem espaço).
-- O sufixo com os 4 primeiros caracteres do id evita colisão de homônimos.
update professores
set email = lower(
        regexp_replace(unaccent(nome), '\s+', '.', 'g')
        || '.' || substr(professor_id::text, 1, 4) || '@escola.kaia'
    )
where email is null;

update coordenadores
set email = lower(
        regexp_replace(unaccent(nome), '\s+', '.', 'g')
        || '.' || substr(coordenador_id::text, 1, 4) || '@escola.kaia'
    )
where email is null;

-- Se o `unaccent` não estiver habilitado, rode antes:
--   create extension if not exists unaccent;

-- ------------------------------------------------------------
-- 2) Cria a linha em `perfis` — é AQUI que o login procura
-- ------------------------------------------------------------
-- O user_id do perfil é o MESMO id do professor/coordenador, então o vínculo
-- entre as tabelas fica direto.
insert into perfis (user_id, email, nome, role, escola_id, hobbies,
                    sequencia_dias_estudo, sessoes_no_dia)
select professor_id, email, nome, 'professor', escola_id, '[]'::jsonb, 0, 0
from professores
where email is not null
on conflict (user_id) do update
    set email = excluded.email,
        nome  = excluded.nome,
        role  = 'professor',
        escola_id = excluded.escola_id;

insert into perfis (user_id, email, nome, role, escola_id, hobbies,
                    sequencia_dias_estudo, sessoes_no_dia)
select coordenador_id, email, nome, 'coordenador', escola_id, '[]'::jsonb, 0, 0
from coordenadores
where email is not null
on conflict (user_id) do update
    set email = excluded.email,
        nome  = excluded.nome,
        role  = 'coordenador',
        escola_id = excluded.escola_id;

-- ------------------------------------------------------------
-- 3) Os logins criados — use qualquer um destes e-mails na tela de login
-- ------------------------------------------------------------
select role, nome, email from perfis
where role in ('professor', 'coordenador', 'pai')
order by role, nome;
