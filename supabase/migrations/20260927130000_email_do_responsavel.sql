-- ============================================================
--  E-MAIL DO RESPONSÁVEL NO ACEITE (fecha o vínculo aluno ↔ responsável)
-- ============================================================
-- O consentimento gravava só um STATUS ('aprovado') no perfil do aluno: ficava registrado
-- QUE alguém autorizou, nunca QUEM. O painel do responsável tinha um ramo "pai" lendo de
-- `pai_aluno`, mas nada no sistema preenchia essa tabela — por isso ele rodava com dados
-- de demonstração.
--
-- A tabela do vínculo NÃO é criada aqui: `pai_aluno` (pai_id, aluno_id) já existe desde o
-- schema inicial, com PK composta e FK para `perfis`. Faltava só quem escrevesse nela.
--
-- O que faltava de verdade era IDENTIDADE. Quem aprova não está logado (o link é público
-- por token, de propósito) e o formulário coletava nome, CPF e parentesco — nenhum deles
-- liga a uma conta. O e-mail é o mínimo que resolve: o backend acha o perfil por ele, ou
-- cria um com role='pai'.
--
-- Fica em `consentimentos` e não em `perfis`: é um dado do ACEITE, e o aceite é prova
-- legal — precisa registrar o e-mail informado naquele momento, mesmo que a pessoa troque
-- de e-mail depois.
--
-- Campo OPCIONAL no formulário, seguindo a mesma lógica do CPF: sem e-mail o aceite ainda
-- vale (nome + parentesco + declaração + data/hora/IP já formam registro), só não gera
-- vínculo. Obrigar mais dado de terceiro vai contra minimização.
-- Idempotente.

alter table public.consentimentos
  add column if not exists responsavel_email text;

comment on column public.consentimentos.responsavel_email is
  'E-mail informado no aceite. É por ele que o vínculo acha (ou cria) o perfil do responsável em pai_aluno.';
