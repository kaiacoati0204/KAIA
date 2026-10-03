# Os modelos da KaIA — o que cada um decide

Guia para quem vai **auditar** os modelos. Para o porquê das escolhas e a base de
pesquisa, ver [`core_e_evidencias.md`](core_e_evidencias.md); para o método do beta e os
critérios de abandono, [`metodo_beta.md`](metodo_beta.md).

> ## Leia isto antes de qualquer número
>
> **Todos os modelos foram treinados em base SINTÉTICA.** As métricas em
> `artifacts/metricas_*.json` medem se o modelo recuperou a função do próprio gerador —
> **não** desempenho com aluno real. O campo `n_real` do RF v2 está em `0` e a `fonte` do
> Modelo 1 é `sintetico`. Nenhum número aqui é evidência de eficácia.
>
> O que existe de dado real: 9 sessões, 51 respostas, 10 rótulos de autorrelato
> (8 `engajado`, 1 `distraido`, 1 `muito_distraido`). É pouco para validar qualquer coisa,
> e esse é o estado declarado, não um descuido.

---

## Os três modelos autorais

| | arquivo | o que decide | status |
|---|---|---|---|
| **Modelo 1** | [`../Backend/risco.py`](../Backend/risco.py) | risco de perda de foco nas próximas 3 questões; decidiria **se** oferecer apoio na pausa | em **sombra** — nunca cruzou o limiar em sessão real |
| **Modelo 2** | [`../Backend/bandit_prevencao.py`](../Backend/bandit_prevencao.py) | **qual** apoio oferecer na pausa (`nada` vs `pacote_foco`) | sem dados de aprendizado até 02/10/2026 |
| **Reativo** | [`../Backend/thompson.py`](../Backend/thompson.py) | qual das 7 intervenções mostrar quando um gatilho medido dispara | nunca disparou em sessão real (bug de freio, corrigido em 01/10) |

E um quarto, **fora do core**:

| | arquivo | o que faz |
|---|---|---|
| **RF v2** | serving em `../Backend/app.py` (`montar_features_sessao`) | classifica 3 estados de atenção a partir de 27 features. **Pesquisa: não decide nada.** Abandonado como decisor em 15/09/2026 — sem câmera o teto publicado de detecção de mente vagando é kappa ≈ 0,21, e o rótulo (autorrelato) é impreciso justamente nos episódios sem meta-consciência, então não dá para distinguir modelo ruim de régua ruim |

**O gatilho da camada reativa nunca usa modelo.** Ele age sobre fato medido: saída da aba
≥ 30 s, regra DTS (três condições juntas) ou ociosidade incomum. A regra que organiza as
duas camadas é *quanto mais cara a ação, mais certa a evidência precisa ser* — a reativa
interrompe, então exige fato; a preventiva oferece uma tela opcional, então admite previsão.

---

## Reproduzir em três comandos

```bash
pip install -r requirements.txt
python ml/gerar_base_v2.py     # base sintética + treina o RF v2 (seed fixa) -> models/ e artifacts/
python ml/gerar_risco.py       # base sintética + treina o Modelo 1; só salva se vencer as regras
```

Rode **na raiz do projeto**, não dentro de `ml/`. Os `.pkl` não são versionados (binário,
reproduzível); as `metricas_*.json` são, de propósito — são o resultado.

Sem `models/modelo_rf_v2.pkl` + `artifacts/scaler_v2.pkl` o backend sobe, mas `/diagnose`
responde 503.

---

## O que olhar em cada métrica

**`artifacts/metricas_v2.json`** (RF v2) — tem `cv_agrupada_por_aluno` (agrupada **por
aluno**, não aleatória: sessões do mesmo aluno não podem cair nos dois lados), `holdout`
com kappa, matriz de confusão e Brier, e `na_proporcao_tipica`, que reavalia na proporção
realista de classes em vez da balanceada do treino. `procedencia` diz de que commit e de
que versão de biblioteca o número saiu.

**`artifacts/metricas_risco.json`** (Modelo 1) — os campos que importam são
`vence_regras` (o modelo supera as regras de reserva?) e `sinais_ok` (os coeficientes têm
o sinal que a teoria prevê?). Ambos `true` hoje, com AUC 0,776 contra 0,711 das regras —
**em sintético**. É o critério da escada de promoção `fixo → regra → modelo`: o modelo só
assume a decisão depois de vencer as regras **no dado real**, o que ainda não aconteceu.

---

## Scripts por função

| script | para quê |
|---|---|
| `gerar_base_v2.py` | base sintética + treino do RF v2 |
| `gerar_risco.py` | base sintética + treino do Modelo 1 |
| `treinar_com_probe.py` | mede o RF v2 contra os rótulos **reais** do probe e re-treina híbrido |
| `simular_bandit_prevencao.py` | confere o mecanismo do Modelo 2 antes do beta (não mede efeito) |
| `relatorio_prevencao.py` | leitura honesta do beta: sempre contra o braço `nada`, ponderando por 1/prob (IPW) — a média bruta por braço mistura efeito com seleção |
| `relatorio_bandit.py` / `relatorio_monitoramento.py` | acompanhamento da camada reativa |
| `validar_real.py` / `comparar_com_real.py` | confronto com dado real |
| `item_analysis.py` | qualidade das questões (p-value, correlação ponto-bisserial) |
| `medir_dano_probe.py` | custo de interromper o aluno com o probe |

Os que precisam de banco pedem `DATABASE_URL`, e no sandbox `KAIA_DB_SCHEMA=teste`.

---

## Limitações conhecidas, por honestidade

1. **Tudo sintético.** Ver o aviso no topo.
2. **O Modelo 1 nunca decidiu nada.** Previu risco entre 0,18 e 0,32 contra um limiar de
   0,40 em todas as sessões reais. Quem acionou a prevenção foi o modo `fixo`.
3. **O rótulo do Modelo 1 trata fim de sessão como "não desengajou"** (`rotulo_futuro`
   devolve 0 quando a sessão acaba antes de 3 respostas). O aluno que para de estudar é o
   desengajamento máximo e entra como 0 — e a prevenção age justamente na fronteira onde
   as sessões terminam. Correção pendente.
4. **O limiar de 0,40 contradiz a regra da arquitetura.** Se o custo de errar na
   preventiva é ~zero, o limiar ótimo é perto de zero. Pendente: tirar o limiar e usar o
   Modelo 1 como **moderador** ("o efeito é maior quando o risco previsto é alto?").
5. **`tempo_dwell_sem_responder_s` satura em `SIGMA_TETO = 4.0`** em quase todos os probes
   reais — a feature perdeu resolução.
6. **A recompensa do Modelo 2 mede a rodada seguinte**, que no uso real observado (uma
   rodada por sessão) não existe: voltou nula em 4 de 4 casos.
7. **Um dado externo que pesa contra a tese de personalização:** Kizilcec, Reich, Yeomans
   et al., PNAS 2020 — 250 mil alunos, ~250 cursos — acharam que ML para escolher qual
   intervenção para qual aluno **não superou** dar a mesma para todos. Está registrado em
   `core_e_evidencias.md` e é a principal ameaça ao valor do Modelo 2.
