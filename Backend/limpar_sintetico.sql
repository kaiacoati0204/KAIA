-- ============================================================
--  KaIA — apaga TODOS os dados sintéticos do dashboard
-- ============================================================
-- Tudo que o seed cria fica carimbado com sessions.app_version = 'seed-sintetico'.
-- As 34 sessões reais (app_version='mvp-0.1') NÃO são tocadas.
--
-- As FKs de session_features/session_events -> sessions NÃO têm ON DELETE CASCADE,
-- então apagamos os FILHOS antes do PAI. Idempotente: rode quantas vezes quiser.
--
-- Rode no Supabase → SQL Editor quando entrarem alunos reais (ou para regerar).

begin;

delete from session_events
 where session_id in (select session_id from sessions where app_version = 'seed-sintetico');

delete from session_features
 where session_id in (select session_id from sessions where app_version = 'seed-sintetico');

delete from sessions
 where app_version = 'seed-sintetico';

commit;

-- Conferência (deve voltar 0):
select count(*) as sessoes_sinteticas_restantes
from sessions where app_version = 'seed-sintetico';
