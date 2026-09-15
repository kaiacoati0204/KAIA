-- ============================================================
--  KaIA — apaga TODOS os dados sintéticos do dashboard
-- ============================================================
-- Apaga só sessions.app_version = 'seed-sintetico'; as reais ('mvp-0.1') ficam.
-- FKs de session_features/session_events não têm ON DELETE CASCADE, então filhos
-- saem antes do pai. Idempotente. Rode no SQL Editor do Supabase.

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
