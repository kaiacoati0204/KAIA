-- Contas da equipe (@teste.kaia) testando no ar sujavam o dado do beta: probes e
-- sessoes de teste entravam junto com os dos alunos reais.
--
-- A marca e COLUNA GERADA, nao logica no Python: a regra fica no banco, acompanha
-- qualquer troca de e-mail sozinha e nao vira comparacao de string espalhada pelo
-- codigo. O e-mail aqui CLASSIFICA a conta -- nao autoriza nada (acesso continua
-- sendo por `role`, verificado no backend).
--
-- lower(): "A@TESTE.KAIA" passava batido sem ele. O sufixo e ancorado no '@' de
-- proposito -- "aluno@teste.kaia.com" NAO e conta de teste.
alter table public.perfis drop column if exists conta_de_teste;
alter table public.perfis
  add column conta_de_teste boolean
  generated always as (lower(email) like '%@teste.kaia') stored;

create index if not exists perfis_conta_de_teste_idx
  on public.perfis (conta_de_teste) where conta_de_teste;
