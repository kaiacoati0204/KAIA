# LLM Council — KaIA: onde um avaliador cutucaria

**Data:** 10 de setembro de 2026
**Composição:** 5 conselheiros independentes · 3 revisões cruzadas anônimas · 1 síntese

---

## Pergunta original

> Projeto escolar de criar uma startup, ensino médio. Exigência: a IA tem que ser central E construída por nós, não API. Temos dois modelos próprios: (1) um Random Forest que classifica atenção em engajado / distraído / muito distraído a partir de 23 features de comportamento (tempo de resposta, mouse, troca de aba), treinado SÓ em base sintética que nós mesmos geramos — um revisor externo mostrou que a acurácia é um botão: mudando o ruído do gerador ela vai de 0,90 a 0,86; (2) um Thompson Sampling implementado do zero que escolhe entre 7 intervenções e aprende com desfecho objetivo. O produto usa a API do Gemini para gerar questões, mas isso não conta como "IA nossa". Zero dado de aluno real coletado até agora. Onde um avaliador cutucaria isso? O que está fraco?

## Contexto acrescentado ao enquadramento

Do workspace: produto já no ar (deploy no Render), foco declarado em TEA/TDAH, features internas relativizadas ao baseline do próprio aluno em desvios-padrão, avaliação com holdout + CV agrupada por aluno + Brier + matriz de confusão. Números por par: 0,95 para "saiu da tela" (praticamente medição direta) e ~0,86 para o par difícil engajado × distraído; literatura com dado real em 0,60–0,75. Reward do bandit por desfecho objetivo, com micro-randomized trial implementado. Probe de autorrelato gravando estado declarado + vetor de features do instante, sem dados ainda. Flag do A/B não configurada em produção. Mercado: 449 edtechs no Brasil, ENEM com 4,8 milhões de inscritos, incumbentes capitalizados (Descomplica, Filadd).

O Outsider recebeu uma versão reduzida, sem jargão e sem números internos — por desenho, ele responde com contexto zero.

---

# Rodada 1 — respostas independentes

## O Contrarian

O número é um botão, e o revisor já provou. No instante em que alguém abre o gerador, o 0,86 morre. Pior: a validação cruzada agrupada por aluno é teatro — os "alunos" também são sintéticos, sorteados da mesma distribuição. Você não validou generalização entre pessoas, validou entre sementes. O Random Forest não aprendeu atenção; aprendeu a inverter as equações que vocês escreveram. Acurácia aqui mede fidelidade à própria hipótese.

Tire o par fácil e sobra pouco. 0,95 para "saiu da tela" é tautologia — visibilitychange é um evento booleano do navegador, não precisa de floresta aleatória. O core de IA real é o par engajado × distraído, onde a literatura com dado REAL fica em 0,60-0,75 e vocês têm zero evidência. O gap entre 0,86 e 0,70 não é conquista, é o tamanho da dívida.

O beta não te salva — ele te expõe. Features internas são relativas ao baseline do próprio aluno, com cold-start de ~3 sessões em 0σ. Ou seja: durante quase todo o beta o classificador roda cego, com metade do vetor zerado. E 5 pessoas contra 7 braços + controle no Thompson Sampling é ruído puro: o bandit vai convergir para alguma coisa e vai *parecer* que aprendeu. "Voltou a responder em 3 min" também acontece sozinho — regressão à média. Com esse n, o controle não detecta nada.

A pergunta que mata: arranque o RF e o bandit. O produto ainda gera questão, ainda adapta dificuldade, ainda funciona? Se sim, a IA de vocês é acessório e o motor é o Gemini — exatamente o que a escola proibiu.

E o pior: vocês declaram foco em TEA/TDAH sem um único usuário neurodivergente testado, inferindo estado mental interno de movimento de mouse — cuja linha de base muda justamente nessa população. Isso não é diferencial, é passivo.

## O First Principles Thinker

A pergunta errada é "onde cutucam o Random Forest". A pergunta certa é: *o que o RF prova?*

Você escreveu um gerador, escreveu um decodificador do gerador, e mediu se o decodificador recupera os parâmetros que você mesmo escolheu. Isso não é um modelo de atenção — é um teste de consistência interna do seu próprio script. O revisor já mostrou o truque: acurácia é um botão. Não existe defesa técnica para isso. Não tente melhorar o número; qualquer número que você produzir vem do mesmo lugar.

Reconstruindo do zero:

**Uma das três classes não é classificação.** "Saiu da tela" o navegador te entrega — é um `if`, não IA. Então o seu modelo real é binário (engajado × mind-wandering), o problema é o difícil, e a literatura com dado real diz 0,60–0,75. Seu 0,86 sintético está *acima* do estado da arte real — isso é a evidência mais forte de que ele mede ficção. Um avaliador que leu um paper mata a defesa em trinta segundos.

**O que de fato é IA construída por vocês é o Thompson Sampling.** É o único componente que aprende de dado real, sem base fabricada, com controle randomizado. Vocês o trataram como acessório do RF. Está invertido: o bandit é o core, o classificador é uma feature de entrada dele — e substituível por uma regra.

**E o ativo real não é nenhum modelo: é o probe.** Vetor de features + autorrelato do instante é o único dataset que ninguém no mercado tem. Descomplica não tem. É isso que se defende.

Vire a métrica: pare de contar usuários no beta, conte **probes rotulados**. A meta do beta não é "funcionou" — é ~200 probes. Com dado real, apresente 0,68 honesto. Vale mais que 0,90 inventado.

## O Expansionist

O avaliador vai cutucar o número sintético — e nisso ele tem razão. Mas o buraco maior é que vocês estão vendendo o ativo errado.

**O ativo não é a Random Forest. É o probe.** Vocês construíram uma máquina de rotular mind-wandering interno em ambiente real, com vetor de features carimbado no instante do autorrelato. Isso é o gargalo da literatura inteira, e vocês têm o pipeline montado. A RF sintética é só o prior de cold-start. Um avaliador atento vai perguntar "cadê o dado real?" — a resposta forte não é defender o 0,86, é mostrar o **plano numérico de coleta**: 5 alunos × N sessões × probes por sessão = X rótulos até a data Y, e a meta declarada de bater 0,75 (o teto da literatura) no par difícil. Alvo falsificável vale mais que acurácia inflada.

**Segundo ponto subvalorizado: o Thompson Sampling com MRT é agnóstico de domínio.** Ele não sabe que é ENEM. É uma camada de atenção que recebe sinal de comportamento web e devolve intervenção otimizada. Brigar por gerador de questão contra Descomplica é briga perdida — eles têm capital e catálogo. Ninguém entre as 449 tem camada de atenção própria. O produto grande é **SDK/API de foco vendido para as outras edtechs**, não mais um simulado.

**Terceiro: a relativização ao baseline do próprio aluno é exatamente o que torna a coisa válida para TEA/TDAH** — o modelo não compara neurodivergente com neurotípico. Isso é diferencial de pesquisa e abre porta institucional: escola, sala de recurso, relatório para família/PEI. Mercado B2B com ciclo de compra real, não adolescente pagando assinatura.

**E o negativo é publicável.** Se o modelo real der 0,68 e o sintético 0,86, isso é um achado honesto sobre o custo de treinar em dado gerado — e um projeto escolar que produz achado honesto ganha de um que produz número bonito.

## O Outsider

Sou leigo no assunto, e é justamente aí que dói. Três coisas me travam ao ler isso:

**1. O modelo aprendeu o script, não o aluno.** Vocês escreveram as regras que geram os dados e treinaram um classificador nesses dados. Os 90% dizem "meu gerador é previsível" — não "eu detecto atenção". A prova é o próprio revisor: se girar um botão de ruído muda o número, o número é uma configuração, não uma medição. Um avaliador vai perguntar "90% de acerto comparado com o quê?" e não existe resposta, porque nenhum aluno real jamais disse se estava distraído.

**2. O buraco lógico: como um mouse enxerga alguém viajando na maionese?** Trocar de aba, tudo bem, dá pra ver. Mas "distraído" olhando fixo pra tela, quieto, parado — pra mim isso é indistinguível de alguém lendo com atenção. Se o próprio modelo confunde os dois, a plataforma vai interromper quem estava concentrado. Num público TEA/TDAH, interromper à toa não é neutro: quebra o foco que vocês querem proteger. Qual é o custo do alarme falso, e vocês mediram?

**3. O bandit não vai aprender nada com 5 pessoas.** 7 opções, punhado de usuários — não dá pra ele descobrir o que funciona; na prática é sorteio com nome bonito. Pior: se o "deu certo" da intervenção for julgado pelo modelo do item 1, uma IA está aprendendo com o palpite da outra IA. Ninguém checou nada com a realidade.

**Uma pergunta desconfortável:** se eu apagar os dois modelos, o produto ainda gera questões e ainda funciona? Se sim, a IA de vocês é enfeite e o motor é o Gemini — exatamente o que a escola proibiu.

O beta de 5 pessoas é ouro. Perguntem na tela: "você estava focado agora?" e comparem com o que o modelo chutou.

## O Executor

**A ferida aberta não é o modelo, é a operação.** A flag do A/B desligada em produção não é bug, é sintoma: você não tem checagem de configuração. Segunda de manhã, antes de qualquer coisa: (1) ligar a var; (2) criar um `/health` que devolve as flags críticas ligadas/desligadas e olhar isso antes de cada sessão de beta. Um avaliador que perguntar "como vocês sabem que o experimento estava rodando naquele dia?" vai receber silêncio.

**Faça a conta de amostra antes de rodar o beta.** 5 alunos, 7 braços + controle = 8 células. Você não vai concluir nada sobre qual intervenção é melhor. Corta para 2 ou 3 braços agora — os com respaldo mais forte. Thompson Sampling continua sendo "modelo próprio construído do zero"; ninguém tira ponto por ter 3 braços. Com 7 você entrega ruído com cara de resultado.

**BROMP só existe se tiver gente.** Pergunta prática: quem senta e codifica, quantos minutos, em quantas sessões? Se não houver um nome e um horário, é wishlist. Versão executável: grava a tela do aluno, um colega codifica depois em ciclo de 20s, dois codificadores em ~20% da amostra pra ter kappa. Isso cabe no ano letivo. BROMP ao vivo, com 5 alunos e alunos de EM como observadores, não cabe.

**Teste a cadeia de dado você mesmo, hoje.** Sente, use a plataforma 20 min, e confirme no banco: probe gravou label + vetor de features + coluna de trigger, tudo alinhado no tempo. Descobrir que o probe grava o vetor errado depois do beta = ano perdido.

**Pare de citar acurácia.** 0,903 vs 0,856 girando um botão significa que o número não é seu — é do gerador. Congele a seed, e diga "hipótese sintética, validação pendente". Um avaliador respeita isso; ele não respeita 0,90 sem dado.

**Ensaie a demo.** Sem aluno real, o que ele vê na tela?

---

# Rodada 2 — revisão por pares (anônima)

**Mapeamento revelado:** A = Expansionist · B = Contrarian · C = Executor · D = First Principles · E = Outsider

## Revisor 1

**1. Mais forte: D.** É a única que troca a pergunta ("o que o RF prova?") e entrega o golpe verificável: 0,86 sintético *acima* do estado da arte real (0,60–0,75) é prova de que o número mede ficção, não competência. E inverte a arquitetura corretamente — o bandit é o único componente que aprende de dado real, logo é o core; o classificador é feature de entrada, substituível por regra. B chega perto e tem o melhor detalhe técnico (CV agrupada por "alunos" sintéticos = validação entre sementes, não entre pessoas), mas é só demolição.

**2. Maior ponto cego: A.** É a única que não encara "apague os dois modelos — o produto ainda funciona?". Compensa a fragilidade com pivô de negócio (SDK de foco para edtechs, "resultado negativo é publicável") — nada disso responde ao avaliador. Pior: propõe meta de 0,75 no par difícil sem notar que 5 alunos em cold-start de 3 sessões não produzem nem amostra para medir isso.

**3. Todos erraram:** ninguém tocou em **menores + LGPD/consentimento** — inferir estado mental de adolescentes, rotulados como TEA/TDAH, sem termo dos responsáveis; é a pergunta que encerra a banca. E ninguém questionou o **probe como instrumento**: três respostas o elegem como "o ativo real" sem notar que ele é reativo (perguntar quebra o foco que se mede) e que autorrelato metacognitivo é justamente pouco confiável nessa população. O ativo não foi validado.

## Revisor 2

**1. Mais forte: D.** É a única que reenquadra em vez de só atacar: nomeia o que o RF realmente mede (consistência interna do próprio gerador), mostra que 0,86 sintético *acima* do estado da arte real é evidência contra, e inverte a arquitetura — bandit no centro, classificador como feature substituível por regra. Fecha com meta falsificável (~200 probes, não "usuários"). B e E chegam ao mesmo diagnóstico; D entrega a defesa. C é o melhor complemento operacional.

**2. Maior ponto cego: A.** Chama a RF de "prior de cold-start" e salta para vender SDK de atenção a outras edtechs — sem um único rótulo real, não existe ativo a licenciar. Ignora o que B, C e E veem: 5 alunos × 8 células é ruído, e o cold-start de 3 sessões deixa o modelo cego durante quase todo o beta. Vende "negativo é publicável" para uma banca escolar que vai ler como "não funciona".

**3. O que os cinco perderam:** (a) **LGPD e menores** — dados comportamentais de adolescentes, inferência de estado mental, público com marcador de neurodivergência: consentimento dos pais, base legal, retenção. Um avaliador do ensino médio pergunta isso antes de perguntar de acurácia. (b) **O probe não é ground truth neutro** — perguntar interrompe, e autorrelato de mind-wandering é justamente o que a metacognição em TEA/TDAH mede mal. Pior: o probe é ele próprio uma interrupção, contaminando o reward do bandit.

## Revisor 3

**1. Mais forte: B.** É a única que ataca a peça que ninguém viu: a validação cruzada agrupada por aluno é entre *sementes*, não entre pessoas — isso derruba o argumento de generalização antes mesmo do debate sobre ruído. Soma o cold-start (~3 sessões em 0σ) tornando o beta inteiro cego, e a regressão à média contaminando o reward do bandit. D é o melhor complemento estratégico ("0,86 sintético acima do SOTA real é prova de ficção"; bandit é o core, RF é feature de entrada).

**2. Maior ponto cego: A.** É a única que não desmonta o número — trata o 0,86 como defensável e pula para pitch (SDK para edtechs, porta institucional). Ignora que, com cold-start, os ~5 alunos do beta mal produzem features internas válidas, e sua própria conta "5 × N sessões = X rótulos" nunca testa viabilidade. Vender antes de ter medida é exatamente o que o avaliador vai cutucar.

**3. Todos erraram em dois pontos:**
- **LGPD e menores.** Coleta de comportamento de adolescentes, com marcador de TEA/TDAH (dado sensível), sem consentimento parental documentado. Um avaliador jurídico mata o projeto sem tocar em ML.
- **Validade do rótulo.** Todos tratam o probe como verdade. Probe é reativo (interromper para perguntar altera o foco) e autorrelato de mind-wandering em adolescente é ruidoso — existe teto de acurácia. "200 probes" não resolve isso; exige medir concordância teste-reteste.

---

# Rodada 3 — veredito do chairman

## Onde o conselho concorda

Cinco conselheiros e três revisores convergiram em cinco pontos. Trate-os como fatos, não opiniões.

**1. O número 0,86 é indefensável e já foi derrubado.** Não porque seja baixo, mas porque é uma configuração, não uma medição. Vocês escreveram o gerador e escreveram o decodificador do gerador; a acurácia mede consistência interna do script. O detalhe mais letal (só o Contrarian viu): a validação cruzada agrupada por aluno é **validação entre sementes**, não entre pessoas — os "alunos" saem da mesma distribuição. O argumento de generalização cai antes mesmo do debate sobre ruído.

**2. Uma das três classes não é classificação.** `muito_distraído` = `visibilitychange`. O navegador entrega isso de graça. Tirando o par fácil, o problema real é binário — engajado × distraído — e a literatura com dado real vive em 0,60–0,75. Seu 0,86 sintético está **acima do estado da arte com humanos**, o que é evidência de que ele mede ficção. Um avaliador que leu um paper encerra essa defesa em trinta segundos.

**3. O beta de 5 pessoas não valida nada quantitativo.** 7 braços + controle = 8 células. Some o cold-start de ~3 sessões em 0σ: o classificador roda cego durante quase todo o beta. E "voltou a responder em 3 min" acontece sozinho — regressão à média. Qualquer gráfico saído daí é ruído com cara de resultado.

**4. A pergunta que mata a banca é a mesma para três conselheiros:** *"apague os dois modelos — o produto ainda funciona?"* Se sim, a IA é enfeite e o motor é a API de terceiro, exatamente o que a escola proibiu. Vocês precisam de uma resposta ensaiada, e ela não pode ser retórica.

**5. A flag desligada não é bug, é sintoma.** Não existe checagem de configuração. A pergunta "como vocês sabem que o experimento estava rodando naquele dia?" hoje recebe silêncio — e essa é uma falha de método, não de código.

## Onde o conselho diverge

**Qual é o núcleo: o classificador ou o bandit?** O First Principles diz que a arquitetura está invertida — o Thompson Sampling é o único componente que aprende de dado real, com randomização controlada, e o RF é feature de entrada substituível por regra. O Contrarian discorda por outro caminho: para ele o bandit com 5 pessoas também é "sorteio com nome bonito". Ambos têm razão em metades diferentes. O bandit é o componente **metodologicamente honesto** (aprende de desfecho objetivo real); é também **estatisticamente vazio** neste tamanho de amostra. A divergência é real porque uma resposta é sobre legitimidade e a outra sobre poder estatístico.

**Defender o 0,86 ou abandoná-lo?** O Expansionist trata o número como aceitável e parte para o pitch (SDK de atenção para outras edtechs). Os três revisores bateram nele por isso, e com razão: não dá para vender camada de atenção sem um único rótulo real. Mas o Expansionist acerta em algo que ninguém mais viu — a **relativização ao baseline do próprio aluno** é justamente o que torna a abordagem defensável para TEA/TDAH, porque não compara neurodivergente com neurotípico. Isso é argumento técnico de banca, não pitch.

**"Resultado negativo é publicável".** Expansionist diz que sintético 0,86 vs real 0,68 é achado honesto. O revisor 2 responde: uma banca escolar lê isso como "não funciona". Discordo do revisor. Bancas de projeto escolar premiam rigor quando ele é **apresentado como escolha**, não como desculpa. A diferença está inteiramente no enquadramento — e o enquadramento é trabalho de vocês, não do avaliador.

**Cortar para 3 braços agora (Executor) ou manter 7.** O Executor vence essa. Ninguém tira ponto por ter 3 braços; todo mundo tira ponto por 8 células com 5 pessoas.

## Pontos cegos que a revisão pegou

**Os cinco conselheiros erraram nos mesmos dois pontos.**

**LGPD e menores.** Nenhum dos cinco tocou nisso. Vocês inferem estado mental de adolescentes, rotulados como TEA/TDAH — isso é dado pessoal **sensível** (saúde) de menor de idade, no artigo 11 e no artigo 14 da LGPD. Sem termo de consentimento dos responsáveis, base legal declarada, política de retenção e finalidade, um avaliador com formação jurídica encerra o projeto **sem tocar em uma linha de ML**. Isso é anterior a qualquer discussão de acurácia. Vocês estão prestes a começar um beta com 5 pessoas — provavelmente colegas menores de idade — sem isso.

**O probe não é ground truth neutro.** Três conselheiros o elegeram como "o ativo real" e nenhum notou o problema: **perguntar interrompe**. O probe é ele próprio uma interrupção, portanto (a) contamina o estado que pretende medir, (b) contamina o reward do bandit, porque o probe compete com a intervenção pelo mesmo canal de atenção, e (c) autorrelato metacognitivo de mind-wandering é notoriamente ruidoso — em adolescente, mais ainda; na população que vocês visam, ainda mais. "200 probes" não resolve validade de instrumento. Só se resolve medindo concordância: probes pareados próximos, ou uma fração da amostra codificada por observação externa.

**Um terceiro, que só o Outsider chegou perto de nomear e ninguém desenvolveu:** o **custo do falso positivo**. Se o modelo confunde "lendo concentrado, quieto" com "viajando na maionese", a plataforma interrompe quem estava focado. Num público TEA/TDAH, isso quebra exatamente o foco que o produto promete proteger. Vocês não têm essa métrica, e ela é mais importante que acurácia agregada.

## A recomendação

**Parem de apresentar o Random Forest como a IA do projeto. Ele não é o ativo, é o passivo — e vocês só o neutralizam assumindo-o antes que o avaliador o levante.**

Concordo com o First Principles Thinker contra a maioria implícita, e vou além dele em um ponto.

O RF não deve ser removido nem "melhorado". Deve ser **reclassificado, em voz alta**: hipótese sintética com validação pendente, seed congelada, número não reivindicado. E o slide mais forte que vocês podem construir é o ataque do revisor externo transformado em achado próprio: *"varremos a constante de ruído do gerador — a acurácia anda de 0,903 a 0,856. É por isso que não reivindicamos esse número."* Quem mostra a própria sensibilidade não é atacado por ela; é creditado. Isso converte a maior vulnerabilidade do projeto no principal indicador de maturidade metodológica dele. Nenhum outro grupo de ensino médio vai fazer isso.

A IA construída por vocês que **sobrevive ao escrutínio** é o par Thompson Sampling + probe: política de decisão do zero, randomização por decisão, reward por desfecho objetivo, e um instrumento de rotulagem de mind-wandering em ambiente real com vetor de features carimbado no instante. Isso é o núcleo. O RF é entrada substituível — e vocês devem dizer isso antes de perguntarem.

A resposta ensaiada para *"apague os dois modelos, o produto funciona?"* é: **"funciona como um gerador de questões, que é a parte que não é nossa. O que é nosso é a camada que decide quando e como intervir, e ela não existe sem os dois. Por isso o beta mede probes, não usuários."** Aceitem a premissa e reposicionem — não neguem.

Três correções de escopo, sem discussão:
- **Corte para 3 braços.** 8 células com 5 pessoas é ruído com aparência de ciência.
- **Troquem a métrica do beta.** Não conte usuários; conte **probes rotulados**. Meta ~200, com uma fração pareada para medir concordância teste-reteste. Com dado real, apresentar **0,68 honesto vale mais que 0,90 inventado** — e é literalmente o que a literatura entrega.
- **Termo de consentimento dos responsáveis antes do primeiro probe gravado.** Dado sensível de menor. Isso não é burocracia, é a pergunta que encerra a banca.

E mantenham a linguagem do projeto: leitura de atenção/foco, nunca diagnóstico. Vocês já sabem disso; sob pressão de demo é o primeiro item que escapa.

## A primeira coisa a fazer

Antes de qualquer slide, antes de tocar no modelo: **ligue a flag do A/B em produção e use a própria plataforma por 20 minutos, confirmando no banco que cada probe gravou label + vetor de features + trigger alinhados no mesmo instante.**

Se essa cadeia estiver quebrada, o beta inteiro produz zero do único ativo que vocês realmente têm — e vocês só descobririam depois. Tudo o mais nesta recomendação depende desses 20 minutos.

---

## Ressalva metodológica

Os cinco conselheiros são o mesmo modelo (Claude) com enquadramentos diferentes, não modelos distintos. Isso reduz viés de enquadramento e de investimento na conversa; não elimina viés sistemático do modelo. Nenhum conselheiro teve acesso ao código ou rodou experimento — todos opinaram sobre a descrição fornecida. Para verificação de fatos e números, uma instância com acesso ao repositório é o instrumento adequado, não o conselho.
