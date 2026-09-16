# Método do beta — atenção e foco

Como o sistema de atenção vai ser testado, e **quando desistir de cada parte**. Os números estão
aqui antes de existir dado real: é o histórico do git que prova que não foram escolhidos depois
para justificar o resultado. Foi a falta disso que fez meio ano ser gasto numa ideia que não dava
para provar.

Contexto do sistema: `Backend/risco.py` (Modelo 1), `Backend/bandit_prevencao.py` (Modelo 2),
`ml/gerar_risco.py`, `ml/simular_bandit_prevencao.py`, `ml/medir_dano_probe.py`.

---

## 1. Antes de coletar qualquer coisa

Bloqueia tudo. Nenhum evento de atenção é coletado de um aluno sem:

- **Consentimento do responsável registrado** — quem consentiu, quando, e para quê. O beta é com
  menores; isto não é formalidade, é condição.
- **Recusa possível sem perder a plataforma.** Quem não consente usa a KaIA sem a parte de
  atenção: sem probe, sem intervenção, e os eventos de foco não são gravados.
- **Minimização.** Só os eventos da lista: resposta de questão (tempo, acerto, nível), saída da
  aba (duração, se foi para outra aba da KaIA), abandono, ociosidade, probe, e a decisão de
  intervenção. **Não** coletamos conteúdo de tela, câmera, microfone, nem o que é digitado fora
  das respostas.
- **Prazo de deleção definido** e um caminho para apagar os dados de um aluno a pedido.
- **Texto honesto** no consentimento: a KaIA faz *leitura de atenção/foco* a partir de
  comportamento na plataforma. Não é avaliação clínica e não diagnostica nada.

Painéis de responsável seguem ocultos no beta, então nada disso vira relatório sobre o aluno para
terceiros ainda.

## 2. O primeiro teste é humano, não de modelo (3 semanas)

Antes de ligar Modelo 1 ou Modelo 2. Com **10 a 15 alunos** com consentimento, ~3 sessões cada,
usando só a instrumentação que já existe.

Uma pergunta: **os alunos engajam, e o probe não faz mal?**

O que registrar: probe respondido x pulado; quantas vezes "eu já estava focado" é apertado;
eventos objetivos por aluno-sessão; e `python ml/medir_dano_probe.py`.

Se o comportamento humano que sustenta o resto não estiver lá, nada abaixo importa — e isso custa
3 semanas descobrir, não 6 meses.

## 3. Como o efeito é medido — o controle é o braço "nada"

**Não** há grupo de alunos que passa o beta sem apoio. O braço `nada` do bandit é o controle, com
piso de 10% de chance por pausa. Assim a comparação é dentro do mesmo aluno e **sorteada por
pausa**, o cansaço de fim de sessão cai igual nos dois lados, e ninguém fica sem ajuda o beta
inteiro.

Por que não pré/pós (rodada N-1 contra N): a rodada N é sempre mais tarde, e a atenção cai com o
tempo na tarefa (Farley 2013). O apoio pareceria pior do que é, por um viés sistemático.

Por que não A/B 50/50 por aluno: num beta pequeno não tem poder (precisaria de centenas de alunos
por meses) e deixar metade dos alunos TEA/TDAH sem apoio é feio.

A média bruta por braço **não** vale como resultado: o bandit escolhe mais quem vai bem. Comparar
sempre contra `nada`, pesando pela probabilidade registrada em cada escolha.

## 4. Critérios de abandono

Cada critério tem um **piso de N**: abaixo dele o número não é lido, nem para matar nem para
salvar. Sem isso o critério vira leitura de borra de café.

| peça | mata quando | piso de N | o que fica no lugar |
|---|---|---|---|
| Probe como rótulo/recompensa | > 50% dos probes pulados | 40 probes | rótulo só por evento objetivo; probe vira opcional |
| Gatilhos de reação | "já estava focado" em > 40% das intervenções | 30 intervenções | subir os cortes (30 s → 60 s) ou desligar a reação |
| Modelo 1 | AUC < 0,65 no dado real do braço `nada` | 200 momentos e 40 eventos | as regras de reserva decidem (já é o padrão) |
| Modelo 1 (versão fraca) | não superar as regras em 0,03 de AUC | idem | as regras — mais simples ganha empate |
| Modelo 2 | intervalo de 90% do melhor braço ainda cobre o de `nada` | 200 rodadas avaliadas | fixar o apoio mais barato; prevenção = não provada |
| Parte reativa | < 1 evento objetivo por aluno-sessão | 30 aluno-sessões | só prevenção; não há o que reagir |
| Probe (dano) | acerto depois do probe pior em > 10 pontos | 20 sessões | frequência do probe pela metade; se persistir, só voluntário |
| Personalização por aluno | — | — | já está fora do beta: o bandit aprende a média do grupo (Schmucker 2025) |

## 4.1 Limiar do gatilho — medido, não chutado

No sintético, o escore das regras separa bem: 0,0 → 18% de eventos; 0,4 → 50%; 0,6 → 68%; 0,8 → 80%.
Escolher o corte é escolher entre alcance e precisão:

| limiar | dispara em | eventos no grupo disparado |
|---|---|---|
| 0,2 | 64% das pausas | 44% |
| **0,4** | **32%** | **59%** |
| 0,6 | 14% | 71% |

No beta o recurso escasso é **dado**: 0,6 daria ~10 ofertas no total, insuficiente para comparar
qualquer coisa. Por isso o padrão é **0,4** (`KAIA_PREVENCAO_LIMIAR`). Com mais alunos, subir.

## 4.2 Tamanhos de efeito esperados — corrigidos para a nossa idade

Números gerais de meta-análise costumam vir de adultos. Para o nosso público eles encolhem:

| ingrediente | número citado | número para a nossa idade |
|---|---|---|
| plano se-então | d = 0,65 (adultos, 94 testes) | **g = 0,31** (crianças, 42 estudos, N = 12.957, idade média 10,7) — adolescente entre os dois |
| micro-pausa | d = 0,16 em desempenho (ns) | **d = −0,09 em tarefas cognitivas** (ns) — questão de ENEM é tarefa cognitiva |
| mindfulness | g = 0,77 em sintomas | 7 estudos, I² = 82%, viés de publicação, follow-up g = 0,34 com IC incluindo zero |

Consequências: **não prometa d = 0,65** para o plano; e **não espere que `pausa_curta` melhore o
que medimos** — a evidência dela é de fadiga e vigor, e em tarefa cognitiva o efeito de
desempenho chega a ser levemente negativo.

## 5. Como falar do que foi medido — as frases exatas

Três afirmações que parecem inofensivas e não sobrevivem a uma pergunta cética:

| não diga | diga |
|---|---|
| "personaliza para cada aluno" | "aprende o que funciona para o grupo, e personaliza conforme o uso cresce" |
| "grupo controle" | "pausas em que nada foi oferecido, sorteadas, no mesmo aluno" |
| "nossa IA tem AUC 0,78" | "no dado sintético o modelo fica acima das regras; no real, ainda não sabemos" |

O braço `nada` **não é "nada"**: o aluno continua com o modal de rodada, o probe e a camada
reativa. É "sem apoio preventivo", e é assim que deve ser descrito.

E o gatilho: **quem decide se oferece é a REGRA** (`KAIA_PREVENCAO_GATILHO=regra`). O Modelo 1
roda em modo sombra — calcula, registra, não afeta ninguém. Dizer que "a IA decide quando" é
falso hoje; o que a IA faz e nenhuma regra faz é **descobrir qual apoio funciona**.

## 5.1 O que ESTE beta valida — e o que não valida

Escrito em destaque porque é a armadilha mais provável, e ela não é estatística: é de expectativa.

> **Este beta valida que o sistema funciona de ponta a ponta. Ele NÃO valida que a intervenção
> funciona.** Com 6 a 12 alunos e algumas centenas de pausas, nenhuma comparação entre braços
> terá poder estatístico — nem com todos os ajustes de desenho.

O risco não é a equipe não saber disso. É alguém de fora (banca, investidor, ou a própria equipe
sob pressão de prazo) pegar um número que saiu do bandit e tratar como conclusão.

## 5.2 Confundimentos conhecidos, e o que foi feito

| confundimento | situação |
|---|---|
| **regra pune lentidão, e o plano pede lentidão** | **corrigido**: eventos da regra pelo lado "lento" não contam na recompensa (contam no rótulo do Modelo 1, onde não há braço para enviesar) |
| **`pausa_curta` tem imunidade a saída de aba** (o sensor é suspenso durante a pausa) | **aberto** — é uma vantagem artificial do braço; soma-se à evidência fraca dele (d = −0,09 em tarefa cognitiva) e é o principal argumento para tirá-lo do beta |
| **carryover entre pausas consecutivas** | derivável do log: todos os eventos têm sessão, aluno e horário, então "braço anterior" e "rodadas desde a última oferta" se reconstroem na análise |
| **abandono logo após a oferta vale 0** | o evento `motivo_saida` ("bati minha meta" vs "cansei") permite separar depois quem parou satisfeito de quem largou |
| **proxy da recompensa** | o evento de recompensa grava também acertos, respondidas e conclusão da rodada — se o bandit melhorar a recompensa sem mexer nesses, era proxy errado |

## 6. O que nunca pode ser dito como resultado

- Número de dado sintético (AUC do `gerar_risco.py`, qualquer saída do `simular_bandit_prevencao.py`).
- Média bruta de braço do bandit sem comparar com `nada`.
- Métrica de momento em que houve intervenção, usada para validar o Modelo 1 — validação só nos
  momentos do braço `nada` (van Geloven 2020).
- Qualquer coisa que soe como "a KaIA detecta distração" ou "diagnostica". O que ela faz é reagir a
  comportamento medido e testar qual apoio ajuda.
