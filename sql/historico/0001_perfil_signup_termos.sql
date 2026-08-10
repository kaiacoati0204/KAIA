-- ============================================================
--  KaIA — perfil no signup + consentimento (LGPD)
-- ============================================================
-- Versiona a infra que garante auth + perfil ATÔMICOS: o trigger
-- `on_auth_user_created` em auth.users chama `criar_perfil_no_signup()`, que
-- cria a linha em `perfis` na MESMA transação do Supabase Auth. Assim, mesmo que
-- o aluno feche a aba logo após o signup, não existe conta órfã.
--
-- Esta migration:
--   1) adiciona o registro de consentimento em `perfis` (LGPD, público menor);
--   2) estende a função para gravar o consentimento vindo do metadata do signup;
--   3) (re)garante o trigger — idempotente, reconstrói tudo num banco limpo.
--
-- Idempotente: pode rodar quantas vezes precisar.

-- 1) Consentimento -----------------------------------------------------------
alter table public.perfis add column if not exists termos_aceite_ts timestamptz;
alter table public.perfis add column if not exists termos_versao   text;

-- 2) Função do trigger (mantém o nome já em uso; só acrescenta o consentimento)-
-- O nome/termos vêm de raw_user_meta_data (options.data do supabase.auth.signUp).
-- `on conflict do nothing`: convive com inserts diretos do seed de contas de teste.
create or replace function public.criar_perfil_no_signup()
 returns trigger
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
begin
  insert into public.perfis (
    user_id, email, nome, role,
    termos_versao, termos_aceite_ts, updated_at
  )
  values (
    new.id,
    new.email,
    nullif(new.raw_user_meta_data->>'nome', ''),
    'aluno',
    nullif(new.raw_user_meta_data->>'termos_versao', ''),
    case when nullif(new.raw_user_meta_data->>'termos_versao', '') is not null
         then now() else null end,
    now()
  )
  on conflict (user_id) do nothing;
  return new;
end; $function$;

-- 3) Trigger (idempotente) ---------------------------------------------------
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.criar_perfil_no_signup();
