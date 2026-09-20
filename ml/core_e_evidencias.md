# O core de atenção da KaIA — definição e evidências

Definido em 2026-09-17. Este documento existe para que cada afirmação sobre o core tenha uma
fonte ao lado, e para separar o que é **achado de pesquisa** do que é **propriedade do desenho**
e do que é **inferência nossa**. Critérios de abandono e método do beta: `ml/metodo_beta.md`.

---

## 1. O core, em uma frase

> A KaIA **detecta** desengajamento por evidência medida e age no momento; e **prevê** risco de
> perda de foco para oferecer apoio antes, na pausa natural entre rodadas.

Duas camadas, dois padrões de evidência, dois momentos:

| | camada reativa | camada preventiva |
|---|---|---|
| dispara com | evidência **medida** (fato) | **previsão** de evento observável |
| age quando | na hora | na pausa entre rodadas |
| custo de errar | moderado | ~zero (tela opcional) |
| papel | **recuperar** | **prevenir** |

**A regra que organiza as duas:** quanto mais caro agir, mais certa a evidência tem que ser.
Ação cara exige fato; ação barata admite previsão. É por isso que o gatilho reativo **não usa
modelo** — ele age sobre o que o navegador registrou.

**Como as duas conversam:** se a camada reativa agiu nos últimos 5 minutos, a pausa seguinte
passa em branco — duas telas em poucos minutos cansam, e a ação da reativa mexe no desfecho que
vira recompensa da preventiva. Quando alguma escapa, o evento de recompensa registra quantas
reativas caíram na janela, para a análise separar depois.

---

## 2. O problema é real e medido

- Em observação de estudantes estudando, eles passaram em média **9,65 de cada 15 minutos**
  efetivamente estudando — mais de um terço do tempo se perde.
- Mente vagando ocupa **30% a 50%** dos pensamentos; em aprendizagem online, **43%** das sondagens.
- A atenção cai com o tempo na tarefa: meta-análise com **68 estudos e mais de 10 mil
  participantes**, independente de a tarefa ser fácil ou difícil.
- No Brasil, **um em cada três** estudantes relata dificuldade de concentração em sala.
- TDAH: **3% a 6%** em estudos nacionais e internacionais (rastreios escolares acham mais, mas são
  rastreio de sintomas, não diagnóstico).

---

## 3. Evidências da camada REATIVA (detectar e agir no momento)

**O gatilho não precisa de validação — é fato.** Saída da aba com duração, abandono de questão e
ociosidade são registrados pelo navegador e pelo banco. Não há estimativa envolvida.

**A regra de desengajamento segue o DTS** (Chen et al., 2021): exige três condições juntas — bom
desempenho na sessão inteira, queda de acerto recente, e tempo fora do próprio ritmo. Uma só não
basta: questão difícil derruba o acerto, e pausa para pensar estica o tempo.

**Agir depois do comportamento tem efeito forte.** Na meta-análise de intervenções em sala para
alunos com sintomas de TDAH, as intervenções **consequentes** (reagir) ficaram entre as de maior
efeito — com a ressalva de que funcionam melhor em **crianças mais novas** e com professor.

**Apoiar quem volta funciona.** A literatura de interrupção mostra que **pistas salientes de
retomada reduzem o atraso de retomada** — o que sustenta a ideia de acolher o aluno que
retorna em vez de só registrar que ele saiu.

**Entregar no momento da necessidade é a premissa validada da área** de intervenções adaptativas
no momento oportuno (Klasnja et al., 2015).

**E o custo de errar é medido, com critério escrito:** o botão "eu já estava focado" dá a taxa de
alarme falso, e acima de 40% os gatilhos são declarados ruído (ver `metodo_beta.md`).

---

## 4. Evidências da camada PREVENTIVA (prever e agir antes)

### Achados de pesquisa

**Precorreção é prática baseada em evidência, do pré-escolar ao ENSINO MÉDIO.** Lembrar o aluno
do comportamento esperado antes da atividade, dizendo o que pode ser difícil e qual é a resposta
certa. É a definição exata do que a tela faz.

**Plano "se-então" bate meta genérica.** Gollwitzer & Sheeran: **94 testes, d = 0,65** (adultos).
Em crianças: **42 estudos, 52 tamanhos de efeito, N = 12.957, g = 0,31** (idade média 10,7), com
efeito maior nos mais novos. **Expectativa honesta para adolescente: ~0,3, não 0,65.**

**O mecanismo não é vigilância — é resposta pré-decidida.** Especificar a situação-gatilho de
antemão torna a resposta automática quando a situação chega. É por isso que funciona no momento em
que a força de vontade já acabou: ela deixa de ser necessária.

**Funciona entregue por TELA, sem adulto.** Experimento de campo em três cursos da HarvardX:
prompt de planejamento aumentou a conclusão em **29%** e o pagamento por certificado em 40% — com
efeito **maior em alunos matriculados em escolas tradicionais**. Era a hipótese mais frágil do
desenho, e é o achado mais importante do documento.

**Planos que especificam QUANDO preveem conclusão** — e só 25% dos alunos fazem isso
espontaneamente, o que justifica a tela induzir especificidade.

**Automonitoramento com devolução funciona com TDAH** (Harris 2005; Estrapala 2022), em estudos de
sala de aula.

**Antecedente é melhor que consequente em alunos MAIS VELHOS** — a mesma meta-análise de TDAH em
sala. Nosso público é adolescente; a evidência aponta para prevenção.

**Personalizado bate genérico** — meta-análise de mensagens adaptadas: **57 estudos, N = 58.454,
r = 0,074**. Pequeno mas consistente. E o megaestudo do PNAS (140 mil professores, ~3 milhões de
alunos) achou que mensagens referenciando dados específicos da pessoa rendiam mais que genéricas.

**A arquitetura prever-e-intervir tem efeito moderado em educação** — meta-análise de intervenções
baseadas em análise de aprendizagem (2025): melhora clara em aquisição de conhecimento.

**E o formato do produto já é, por construção, uma intervenção de atenção.** Testes intercalados
durante o estudo reduzem a mente vagando (Szpunar, Kahn & Schacter, PNAS) — e a KaIA é uma
sequência de questões com feedback imediato. A prevenção age **em cima** de uma base já favorável.

> **Correção (20/09/2026):** este item já foi escrito aqui como "corta pela metade" e "a mais forte
> que existe". A replicação de 2022 (*Interpolated testing and content pretesting as interventions
> to reduce task-unrelated thoughts during a video lecture*, PMID 35348931) achou redução
> **significativa mas de efeito pequeno, e sem apoio de fator de Bayes**. Continua positivo;
> não é o efeito grande que a primeira leitura sugeria. **Não dizer "pela metade".**

### E a PREVISÃO em si — o que sustenta prever, não prevenir

A camada preventiva tem duas afirmações separadas: que **o apoio ajuda** (acima) e que **dá para
prever**. Esta é a segunda.

**Lapso de atenção é previsível a partir do ritmo do próprio sujeito.** Paradigma de laboratório
em malha fechada: o sistema acompanha os tempos de resposta, calcula limites **intrasujeito**,
dispara uma sondagem quando o padrão entra na assinatura de lapso — e a pessoa confirma acima do
acaso. É o mesmo mecanismo da nossa régua em σ. Ressalva: tarefa monótona, estímulos de segundos.

**A assinatura é responder rápido e regular demais** (piloto automático), não lento. Bate com o que
medimos no ASSISTments: nas janelas de pior acerto o que sobe é a **% de rápidas** (1,27 → 2,19),
não a de lentas.

**A diferença de tempo entre respostas VIZINHAS prevê**, com aumento abrupto de variabilidade
durando 2,5–10 s antes do relato. Nomeia duas features nossas de uma vez: a estrutura sequencial e
`variabilidade_tempo_resposta`.

**Tem hora para começar.** O próprio DTS (Chen et al., 2021 — de onde vem a nossa regra) reporta que
em lição de 20 questões a mente começa a vagar entre a **11ª e a 15ª**. Nossas rodadas têm 10, e a
pausa cai na borda. *(Conferir a frase no PDF antes de citar em banca — veio de resumo.)*

**Reduzir dispersão proativamente é categoria existente**, não invenção nossa: *proactive mind
wandering reduction* (PALE 2014). Lá o método é outro — ajustar dificuldade e aposta do texto por
traços medidos do aluno, sem mostrar nada a ele. Mais perto da nossa dificuldade adaptativa que do
plano se-então.

**O que NÃO existe:** prever evento observável de desengajamento **3 questões à frente, por log de
interação, em app de estudo**. Lapso previsível por ritmo é laboratório; prever desengajamento por
log e intervir é educação em horizonte de semanas. Nossa combinação fica no vão entre os dois.

### Propriedades do desenho (não precisam de validação)

**Piso zero.** Uma tela opcional numa fronteira não pode quebrar raciocínio, porque na fronteira
não há raciocínio em curso. O que é validado é o outro lado: o **custo de quebrar** — atraso de
retomada, omissões e erros de sequência, com o mecanismo sendo dano à **memória de onde se estava**,
não aos recursos de atenção.

**Fronteira não é só o fim da rodada.** O custo medido do Bailey & Konstan (2006) é de interromper
**durante** a tarefa: 2x mais erros, 3–27% mais tempo, até 106% mais irritação. Entre duas tarefas
quaisquer o custo cai — e o intervalo entre responder uma questão e abrir a próxima é fronteira.
Por isso card nenhum abre no meio de uma questão, nem no instante em que a próxima aparece (começar
já é "durante"): o lugar é **depois da explicação da resposta**, com a tarefa encerrada e a seguinte
ainda não iniciada.

**Resolve a tensão da receptividade.** A tensão é documentada: carga cognitiva alta aumenta a
necessidade de apoio e **reduz a receptividade ao mesmo tempo**. Agir na fronteira desfaz isso.

**É falseável.** Sorteio da ação por ponto de decisão é metodologia estabelecida (ensaios
micro-randomizados). Validar só nos momentos não tratados evita medir a própria intervenção
(van Geloven 2020).

### Inferência nossa (sem validação)

**"O aluno leva o plano para a prova."** Plausível pelo mecanismo do se-então, mas **não há estudo**
mostrando transferência de um plano feito num app para uma prova. Hipótese, não evidência.

---

## 5. Os problemas — e por que nenhum impede o core de funcionar

| problema | por que não impede |
|---|---|
| **efeito modesto (~0,3)** | o custo de entrega é ~zero; pequeno entregue centenas de vezes num semestre soma, e você **mede o tamanho** |
| **habituação** | o bandit varia por construção (nenhum braço trava em 100%) e o relatório detecta queda por ordem de exposição |
| **o aluno pode não aceitar** | medido em 1–2 semanas, e existe rota de fuga com evidência **melhor**: assistência/dificuldade adaptativa (d = 0,505 / −0,428) e sinalização (g = 0,53), nenhuma das duas pedindo nada ao aluno |
| **quem mais precisa é quem menos clica** | o menos resolvido; resposta parcial é registrar quem descarta e tratar diferente, e a rota que não pede nada |
| **preventiva só age na fronteira** | o meio da rodada é coberto pela camada reativa, que usa **fato**, não previsão |
| **a recompensa é proxy** | inspecionável: dois buracos já achados e corrigidos (premiava estudar menos; punia o plano por pedir lentidão) |
| **pouco dado no beta** | impede a **afirmação**, não a ideia. O sorteio por pausa dentro do aluno é o desenho mais econômico disponível |
| **o Modelo 1 pode empatar com as regras** | a tese não depende dele: a **regra decide** e ele roda em modo sombra, sendo avaliado sem afetar ninguém |
| **"personaliza por aluno" ainda é média do grupo** | frase corrigida; a personalização hierárquica existe mas, nessa escala, se comporta quase como global |

**O padrão:** nenhum desses é "impossível de saber". Todos têm número e data. O único problema
fatal — alvo sem gabarito — sobrou apenas no RF de mente vagando, que está fora do caminho crítico.

---

## 5.1 Candidatos para depois do beta

**Pré-teste — o mais promissor.** Perguntar sobre o conteúdo **antes** de estudá-lo reduz a
dispersão **e** melhora o aprendizado do que foi pré-testado (Pan, Sana, Schmidt & Bjork 2020;
replicado em 2022 no mesmo estudo que enfraqueceu o teste intercalado). Funciona intercalado ou
todo no começo. Na KaIA: uma questão do tema antes da rodada, marcada como pré-teste e fora da
nota. **Custo de interrupção zero** — não é tela, é a própria tarefa. Encaixa na regra do core sem
tensão nenhuma.

**Precorreção no meio da rodada.** O plano se-então numa fronteira entre questões, quando o risco
dispara, em vez de só na pausa das 10. Exige o gatilho promovido de `fixo` para `regra` — sem corte
de risco ele apareceria 10 vezes por rodada.

**Anotação ligada ao estudo.** Reduz dispersão, mas **só** para quem tem pouco conhecimento prévio
e anota bem; não deu efeito no nível do grupo. O caderno existe e está solto do estudo. Pouco
retorno para o trabalho.

**Devolução do automonitoramento no momento certo.** Hoje ela agrega a sessão e aparece na pausa;
no I-Connect a devolução é imediata, logo após cada autoobservação. A nossa é uma versão mais fraca
do mecanismo com melhor evidência no ensino médio.

## 6. O que NÃO faz parte do core

**Detecção de mente vagando.** Fica como pesquisa e nunca decide nada. Motivo: sem sensor, o teto
publicado é kappa ≈ 0,21, e o rótulo (autorrelato) é impreciso justamente nos episódios sem
meta-consciência — então não há como distinguir "modelo ruim" de "régua ruim". As **features** do
RF continuam valendo; o que sai é o alvo.

**Interromper no meio da questão com base em previsão.** Proibido pelo desenho: reprova nas três
perguntas (há fio para cortar? a evidência é certa? o momento é receptivo?).

**Câmera ou webcam.** Desempenho fraco (F1 0,41–0,48 em sala), **pior para participantes negros e
indígenas**, e privacidade incompatível com menores — os próprios pesquisadores extraem features em
tempo real para não gravar crianças.

---

## 7. A frase para falar em voz alta

> O problema é real e medido: mais de um terço do tempo de estudo se perde, e a atenção cai com o
> tempo na tarefa de forma previsível. A KaIA age em duas camadas: **reage** ao desengajamento que
> dá para medir, e **antecipa** o risco para oferecer, na pausa, um plano pré-decidido para a
> dificuldade que aquele aluno está tendo. Os ingredientes têm evidência — precorreção validada até
> o ensino médio, planos se-então, e prompts de planejamento entregues por tela com +29% de
> conclusão em aluno de escola. O que ainda não sabemos é o tamanho do efeito na nossa combinação,
> e os critérios que nos fariam abandonar cada parte estão escritos e datados.
