# -*- coding: utf-8 -*-
"""
Confere a leitura de atenção contra evidência que NÃO depende de introspecção.

O probe (autorrelato) é ruidoso: mind-wandering é justo quando o aluno não se monitora,
e há viés de responder o que soa certo. Três análises sem perguntar nada ao aluno valem
pela CONVERGÊNCIA — se o probe discordar das outras duas, o problema é o probe.

  1. TESTE A/B      — a leitura SERVE? (causal; precisa de KAIA_AB_TESTE=1)
  2. VALIDADE PRED. — a leitura SIGNIFICA algo? (custo zero, só análise)
  3. ESTADO INDUZIDO— quanto o PROBE erra? (precisa de sessões ?induzido=...)

Offline/manual. Precisa de DATABASE_URL (mesmo banco do backend). Rode na raiz:
    python ml/validar_real.py

Onde faltar amostra, o script diz que faltou em vez de inventar número.
"""
import os
import sys
import json
import asyncio
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
import asyncpg

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

from gerar_base_v2 import FEATURE_ORDER, ESTADOS, MODELO_PATH, SCALER_PATH  # noqa: E402

MIN_AMOSTRA = 15          # abaixo disso qualquer diferença é ruído; não reporta
QUESTOES_DEPOIS = 5       # janela da validade preditiva
LATENCIA_MIN_MS = 800     # clique mais rápido que isso não é introspecção


# ==== INFRA ====
def _carregar_modelo():
    try:
        return pickle.load(open(MODELO_PATH, "rb")), pickle.load(open(SCALER_PATH, "rb"))
    except FileNotFoundError:
        print("modelo/scaler ausentes — rode `python ml/gerar_base_v2.py` antes.")
        return None, None


def _prever(modelo, scaler, feats_list):
    """Roda o modelo sobre features já gravadas (probe_labels.features)."""
    linhas, validos = [], []
    for i, feats in enumerate(feats_list):
        if isinstance(feats, str):
            feats = json.loads(feats)
        try:
            linhas.append([float(feats[k]) for k in FEATURE_ORDER])
            validos.append(i)
        except (KeyError, ValueError, TypeError):
            continue      # probe de antes de uma feature nova: ignora em vez de chutar
    if not linhas:
        return np.array([]), []
    X = pd.DataFrame(linhas, columns=FEATURE_ORDER)
    Xs = pd.DataFrame(scaler.transform(X), columns=FEATURE_ORDER)
    return modelo.predict(Xs), validos


def _secao(titulo):
    print("\n" + "=" * 68)
    print(titulo)
    print("=" * 68)


def _sem_dado(o_que, n):
    print(f"  sem amostra suficiente ({n} < {MIN_AMOSTRA}) — {o_que}")


# ==== 1. TESTE A/B ====
async def ab_teste(conn):
    """Compara recuperação do grupo CONTROLE (detectado, não intervido) com a do
    grupo que recebeu intervenção. Se a leitura fosse chute, os dois se recuperariam
    igual — não se ajuda quem já estava bem."""
    _secao("1. TESTE A/B — a leitura serve para alguma coisa?")
    try:
        rows = await conn.fetch(
            "select intervention_type, reward, estado_antes, estado_depois "
            "from interventions where reward is not null")
    except Exception as e:
        print("  tabela interventions indisponível:", e)
        return

    ctrl = [r for r in rows if r["intervention_type"] == "controle_ab"]
    trat = [r for r in rows if r["intervention_type"] != "controle_ab"]
    print(f"  controle: {len(ctrl)} intervenções medidas | tratamento: {len(trat)}")
    if len(ctrl) < MIN_AMOSTRA or len(trat) < MIN_AMOSTRA:
        _sem_dado("ligue KAIA_AB_TESTE=1 e colete mais", min(len(ctrl), len(trat)))
        return

    def _resumo(rs):
        rec = np.mean([1.0 if r["estado_depois"] == "engajado" else 0.0 for r in rs])
        return float(np.mean([r["reward"] for r in rs])), float(rec)

    r_c, rec_c = _resumo(ctrl)
    r_t, rec_t = _resumo(trat)
    print(f"  reward medio      controle {r_c:.3f} | tratamento {r_t:.3f}  (delta {r_t - r_c:+.3f})")
    print(f"  voltou a engajar  controle {rec_c:.1%} | tratamento {rec_t:.1%}  (delta {rec_t - rec_c:+.1%})")
    if rec_t - rec_c > 0.05:
        print("  -> tratamento recupera mais: a leitura acerta QUEM precisava de ajuda.")
    elif abs(rec_t - rec_c) <= 0.05:
        print("  -> sem diferença: ou a leitura não discrimina, ou a intervenção não ajuda.")
    else:
        print("  -> controle recupera MAIS: investigar (intervenção atrapalhando?).")


# ==== 2. VALIDADE PREDITIVA ====
async def validade_preditiva(conn, modelo, scaler):
    """A leitura de agora prevê o desempenho das próximas questões? Um estado mental
    real tem consequência observável; se não prevê nada, não está medindo estado."""
    _secao("2. VALIDADE PREDITIVA — a leitura prevê o que vem depois?")
    try:
        probes = await conn.fetch(
            "select session_id, estado, features, created_at from probe_labels order by created_at")
    except Exception as e:
        print("  tabela probe_labels indisponível:", e)
        return
    if len(probes) < MIN_AMOSTRA:
        _sem_dado("colete mais probes", len(probes))
        return

    pred, validos = _prever(modelo, scaler, [p["features"] for p in probes])
    if not validos:
        print("  nenhum probe compatível com o FEATURE_ORDER atual.")
        return

    linhas = []
    for k, i in enumerate(validos):
        p = probes[i]
        depois = await conn.fetch(
            "select payload from session_events where session_id = $1::uuid "
            "and event_type = 'question_answer' and ts > $2 order by ts limit $3",
            p["session_id"], p["created_at"], QUESTOES_DEPOIS)
        if not depois:
            continue
        pl = [d["payload"] if isinstance(d["payload"], dict) else json.loads(d["payload"]) for d in depois]
        acertos = [1.0 if q.get("acertou") else 0.0 for q in pl]
        rts = [float(q["tempo_resposta_ms"]) for q in pl if q.get("tempo_resposta_ms")]
        linhas.append({
            "modelo": ESTADOS[int(pred[k])],
            "autorrelato": p["estado"],
            "acerto_depois": float(np.mean(acertos)),
            "rt_depois_ms": float(np.mean(rts)) if rts else np.nan,
            "n": len(pl),
        })

    if len(linhas) < MIN_AMOSTRA:
        _sem_dado("poucos probes com questões respondidas depois", len(linhas))
        return
    df = pd.DataFrame(linhas)
    for col, nome in (("modelo", "LEITURA DO MODELO"), ("autorrelato", "AUTORRELATO (probe)")):
        print(f"\n  desempenho nas {QUESTOES_DEPOIS} questões seguintes, por {nome}:")
        g = df.groupby(col).agg(n=("n", "size"), acerto=("acerto_depois", "mean"),
                                rt_ms=("rt_depois_ms", "mean")).round(3)
        print("   " + g.to_string().replace("\n", "\n   "))
    print("\n  -> se 'distraido' NAO vier com acerto menor / RT maior, a leitura nao "
          "esta captando estado; compare as duas tabelas para ver quem discrimina melhor.")


# ==== 3. ESTADO INDUZIDO ====
async def estado_induzido(conn, modelo, scaler):
    """Sessões com rótulo dado por INSTRUÇÃO (?induzido=...). Única âncora que não
    depende do aluno saber o que sentiu — e por isso a única que mede o erro do probe."""
    _secao("3. ESTADO INDUZIDO — quanto o probe erra?")
    try:
        marcas = await conn.fetch(
            "select distinct on (session_id) session_id, payload from session_events "
            "where event_type = 'rotulo_induzido' order by session_id, ts")
    except Exception as e:
        print("  session_events indisponível:", e)
        return
    alvo = {}
    for m in marcas:
        pl = m["payload"] if isinstance(m["payload"], dict) else json.loads(m["payload"])
        if pl.get("estado") in ESTADOS:
            alvo[str(m["session_id"])] = pl["estado"]
    print(f"  sessões induzidas encontradas: {len(alvo)}")
    if not alvo:
        print("  rode sessões com ?induzido=engajado|distraido|muito_distraido na URL.")
        return

    probes = await conn.fetch(
        "select session_id, estado, features from probe_labels where session_id = any($1::uuid[])",
        list(alvo.keys()))
    if len(probes) < MIN_AMOSTRA:
        _sem_dado("poucos probes dentro das sessões induzidas", len(probes))
        return

    pred, validos = _prever(modelo, scaler, [p["features"] for p in probes])
    inst = [alvo[str(probes[i]["session_id"])] for i in validos]
    auto = [probes[i]["estado"] for i in validos]
    mod = [ESTADOS[int(pred[k])] for k in range(len(validos))]

    ac_probe = float(np.mean([a == i for a, i in zip(auto, inst)]))
    ac_modelo = float(np.mean([m == i for m, i in zip(mod, inst)]))
    print(f"  n = {len(inst)} probes em sessões de estado conhecido")
    print(f"  autorrelato bate com a instrução: {ac_probe:.1%}   <- taxa de acerto do PROBE")
    print(f"  modelo bate com a instrução:      {ac_modelo:.1%}")
    print("\n  instrução x autorrelato (linha = instruído, coluna = declarado):")
    print("   " + pd.crosstab(pd.Series(inst, name="instruido"),
                              pd.Series(auto, name="declarado")).to_string().replace("\n", "\n   "))
    print(f"\n  -> {1 - ac_probe:.0%} dos rótulos do probe contradizem a instrução. Esse é o "
          "teto de ruído do rótulo; não espere do modelo acurácia acima disso.")


# ==== QUALIDADE DO ROTULO ====
async def qualidade_probe(conn):
    """Filtra probe que não foi introspecção: clique rápido demais."""
    _secao("EXTRA — qualidade do rótulo (latência de resposta ao probe)")
    rows = await conn.fetch(
        "select payload from session_events where event_type = 'probe_atencao'")
    lats = []
    for r in rows:
        pl = r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"])
        if pl.get("latencia_ms") is not None:
            lats.append(float(pl["latencia_ms"]))
    if not lats:
        print("  nenhum probe com latencia_ms (campo novo — só vale para os coletados daqui pra frente).")
        return
    lats = np.array(lats)
    rapidos = float(np.mean(lats < LATENCIA_MIN_MS))
    print(f"  n = {len(lats)} | mediana {np.median(lats):.0f} ms")
    print(f"  respondidos em menos de {LATENCIA_MIN_MS} ms: {rapidos:.1%}")
    if rapidos > 0.20:
        print("  -> parcela alta de clique automático: considere descartar esses rótulos no treino.")


async def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return
    modelo, scaler = _carregar_modelo()
    if modelo is None:
        return
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        await ab_teste(conn)
        await validade_preditiva(conn, modelo, scaler)
        await estado_induzido(conn, modelo, scaler)
        await qualidade_probe(conn)
    finally:
        await conn.close()
    print("\nA leitura é confiável quando as três convergem. Se o probe discordar "
          "das outras duas, desconfie do probe — não do modelo.")


if __name__ == "__main__":
    asyncio.run(main())
