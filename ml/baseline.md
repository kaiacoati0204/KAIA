# Baseline — Classificador de Engajamento KaIA

- **Data do treinamento:** 2026-06-28
- **Versão do modelo:** v1
- **Algoritmo:** `RandomForestClassifier` (scikit-learn 1.7.1)
- **Script:** [train.py](train.py)
- **Modelo salvo em:** `ml/models/modelo_rf_v1.pkl`
- **Métricas (JSON):** `ml/artifacts/metricas_v1.json`
- **Dados:** pré-processados por [preprocessing.ipynb](preprocessing.ipynb) — 480 amostras de treino / 120 de teste, 15 features, 3 classes balanceadas (split 80/20 estratificado).

## Parâmetros usados

| Parâmetro       | Valor        |
| --------------- | ------------ |
| n_estimators    | 100          |
| max_depth       | 10           |
| random_state    | 42           |
| class_weight    | `balanced`   |

Encoding do target: `engajado=0`, `distraido=1`, `muito_distraido=2`.

## Métricas

**Acurácia geral: 1.0000 (100%)**

| Classe            | Precisão | Recall | F1-score | Suporte |
| ----------------- | -------- | ------ | -------- | ------- |
| engajado          | 1.00     | 1.00   | 1.00     | 40      |
| distraido         | 1.00     | 1.00   | 1.00     | 40      |
| muito_distraido   | 1.00     | 1.00   | 1.00     | 40      |
| **accuracy**      |          |        | **1.00** | 120     |
| **macro avg**     | 1.00     | 1.00   | 1.00     | 120     |
| **weighted avg**  | 1.00     | 1.00   | 1.00     | 120     |

## Matriz de confusão

Linhas = classe real, colunas = classe prevista.

```
                  engajado  distraido  muito_distraido
engajado                40          0                0
distraido                0         40                0
muito_distraido          0          0               40
```

## Observações sobre o desempenho

- O modelo acertou **todas as 120 amostras de teste** (acurácia perfeita, zero erros na matriz de confusão).
- **Esse resultado NÃO deve ser lido como prova de qualidade do modelo.** Foi investigada a causa (ver abaixo); ela é a *natureza dos dados*, não um bug nem leakage clássico.
- **Não há target leakage das features engenheiradas.** `produtividade` (`acertos_questoes / duracao_sessao_min`) e `distracao_score` (média ponderada de `mudancas_aba`, `cliques_fora_area_estudo` e `tempo_fora_foco_s` normalizado) são derivadas de **outras variáveis comportamentais**, não da coluna `target`. Testes que confirmam:
  - Removendo **as duas** features engenheiradas, a acurácia **continua 100%** → elas não são a causa.
  - `produtividade` tem importância **0.0014** (praticamente inútil).
  - `distracao_score` é a feature mais importante (0.22), mas é legítima: combina justamente os sinais que definem distração.
- **Causa real: a base sintética é trivialmente separável.** Os dados (`KaIA_Base_Sintetica.xlsx`, 600 linhas) são gerados por `perfil` (Focado, Cansaço, Distraído Gradual, Distraído Imediato → target), com distribuições por classe que **mal se sobrepõem**. Evidência: features **cruas isoladas** já classificam quase perfeitamente — só `mudancas_aba` → 92.5%, só `tempo_fora_foco_s` → 94.2%, só `acertos_questoes` → 80.8%.
- O dataset é pequeno (600 amostras) e perfeitamente balanceado, o que reforça o ajuste fácil a um padrão simples. Tempo de treino desprezível (~0.09s), coerente com um problema fácil.
- **Conclusão:** este baseline serve como *sanity check* do pipeline (dados → treino → avaliação → persistência funcionando), **não** como estimativa realista do desempenho em produção. O número de produção só será conhecido com dados reais.

## Próximos passos (v2)

1. **Validar com dados reais** (prioridade máxima). A base sintética é separável demais para medir desempenho real. Substituir/complementar por sessões reais coletadas via Supabase (`session_features`) assim que houver volume suficiente — só então a acurácia será interpretável.
2. **Aumentar a sobreposição/ruído da base sintética** enquanto não há dados reais. O gerador atual produz perfis quase disjuntos; adicionar ruído e casos de fronteira tornaria o problema realista e o baseline informativo.
3. **Cross-validation estratificada** (k-fold, `random_state=42`) em vez de um único split, para estimar variância e não confiar em 120 amostras de teste.
4. **Comparar com um baseline ingênuo** (`DummyClassifier`) e com modelos alternativos (LogisticRegression, GradientBoosting) para ter referência de dificuldade real — sobre dados reais/ruidosos.
5. **Reavaliar features de baixa utilidade.** `produtividade` (imp. 0.0014), `nivel_dificuldade_atividade` e `sessoes_no_dia` (~0.0002) quase não contribuem; revisar se valem a pena ou se precisam ser reformuladas.
6. **Tuning de hiperparâmetros** (GridSearch/RandomizedSearch) só faz sentido depois de ter um conjunto de avaliação não-trivial — antes disso, otimizar é otimizar ruído.
