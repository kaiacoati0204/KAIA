# Benchmark de latência — GET /diagnose

- **Data/hora da medição:** 2026-07-22 17:26 (horário local)
- **Método:** [tests/benchmark_latencia.py](../tests/benchmark_latencia.py) — 1 sessão de teste, 11 eventos sintéticos (5 tipos), espera de 35 s pelo scheduler, **20 chamadas consecutivas** ao `GET /diagnose`. Sessão encerrada e removida do banco ao fim (sem resíduo).
- **Amostra:** 20 requisições.

## Resultado (ms)

| Métrica | Valor |
| --- | --- |
| mínimo | 88.8 |
| média | 99.6 |
| mediana | 98.5 |
| **p95** | **102.1** |
| máximo | 127.8 |

## Ambiente

- **Banco:** Supabase Postgres, região **sa-east-1** (Transaction Pooler, `statement_cache_size=0`).
- **Modelo:** RandomForest v1 (`n_estimators=100`, `max_depth=10`, `random_state=42`), carregado **uma vez no startup** (não por request).
- **Backend:** FastAPI + uvicorn, Python 3.11.9, scikit-learn 1.7.1.
- **Cliente do benchmark:** mesma máquina do servidor (localhost → servidor; servidor → Supabase pela internet).

## Análise — onde está o gargalo

O tempo é **dominado pelas idas ao banco (rede)**, não pelo modelo:

- **Modelo (inferência):** desprezível. O RF + scaler já estão em memória (startup); prever 1 linha custa da ordem de **1–3 ms**.
- **Banco (Supabase sa-east-1):** cada `/diagnose` chama `montar_features_sessao`, que faz **~4 consultas sequenciais** (sessão, eventos, taxa de abandono, contagem de intervenções). Cada consulta é um round-trip de rede até o pooler em sa-east-1. Com ~20–25 ms por ida-e-volta, 4 consultas ≈ **80–100 ms** — exatamente a faixa medida.

Ou seja: a latência é **I/O-bound (rede/DB)**, não CPU/modelo-bound. A média de ~100 ms é essencialmente a soma dos round-trips das 4 queries.

## Conclusão — meta < 200 ms

✅ **Meta atingida com folga.** Média **99.6 ms** e **p95 102.1 ms**, ambos bem abaixo dos 200 ms. Mesmo o pior caso (127.8 ms) fica dentro da meta. O `/diagnose` está adequado para uso interativo.

## Próximos passos (otimização — não urgente, meta já batida)

Se no futuro a meta apertar (ex.: < 50 ms) ou o volume crescer, os caminhos são atacar os round-trips ao banco:

1. **Reduzir o nº de queries** em `montar_features_sessao` — juntar as ~4 consultas em 1 (CTEs / `union all` num único round-trip) cortaria a maior parte da latência.
2. **Cache curto das features por sessão** (ex.: 5–10 s) — evita recomputar tudo em chamadas seguidas próximas.
3. **Proximidade de rede** — hospedar o backend na mesma região do Supabase (sa-east-1) reduz o RTT de cada query.
4. **Connection pooling já está ok** (pool asyncpg reutilizado); manter.

Enquanto a meta for 200 ms, nenhuma dessas otimizações é necessária.
