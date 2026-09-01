# SQL histórico — NÃO rode nada daqui

Estes arquivos foram as migrations avulsas aplicadas à mão no Supabase → SQL Editor
entre julho e agosto de 2026, antes de o schema passar a ser versionado.

**Todo o conteúdo deles já está dentro do snapshot de produção**
`supabase/migrations/20260809203146_remote_schema.sql`, que foi puxado do banco real
em 09/08/2026 — depois de todos eles terem sido aplicados. Esse snapshot é o **único
SQL que o CI aplica** (`.github/workflows/ci.yml`, job `migrations`, que roda
`supabase/migrations/*.sql` e falha no primeiro erro).

Ficam aqui só como referência histórica: mostram *quando* e *por que* cada pedaço do
schema nasceu, o que o snapshot (um dump plano) não conta.

## O que já está no snapshot

| Arquivo | O que criava | Onde está hoje no snapshot |
|---|---|---|
| `cache_questoes.sql` | `questoes_cache`, `questoes_vistas`, índices `ix_cache_busca` e `ix_vistas_aluno` | linhas 231, 252, 573, 608 |
| `probe_labels.sql` | `probe_labels` + índices por usuário e por data | linhas 183, 559, 566 |
| `interventions_reward_estado.sql` | colunas `estado_antes`, `estado_depois`, `reward_origem` | dentro do `CREATE TABLE public.interventions` |
| `0001_perfil_signup_termos.sql` | colunas `termos_aceite_ts`/`termos_versao` em `perfis`, função `criar_perfil_no_signup()` e trigger `on_auth_user_created` | colunas no `CREATE TABLE public.perfis`; função e trigger no fim do arquivo |

Este último vinha de `Backend/migrations/`, uma segunda pasta chamada "migrations" que
não era aplicada por ninguém e vivia sendo confundida com a do Supabase. A pasta foi
removida junto com esta consolidação.

## Por que não rodar

Rodar de novo num banco atual é, na melhor das hipóteses, inócuo — todos são
idempotentes (`if not exists` / `or replace`). O risco não é o erro, é a divergência:
mexer no schema por fora das migrations versionadas faz o snapshot deixar de descrever
o banco de verdade, que é exatamente o problema que a versionagem resolveu.

## Precisa mudar o schema?

Crie uma migration nova, **não edite o snapshot nem reaproveite os arquivos daqui**:

```bash
supabase migration new nome_curto     # cria supabase/migrations/<ts>_nome_curto.sql
```

Detalhes de recriação do banco, regeneração do snapshot e como o CI valida tudo estão
em [`supabase/README.md`](../../supabase/README.md).

> Nota: `Backend/limpar_sintetico.sql` **não** está aqui e continua ativo. Ele não é
> schema — apaga *dados* de seed (`app_version = 'seed-sintetico'`) e é para rodar
> quando entrarem alunos reais.
