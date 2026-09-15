# -*- coding: utf-8 -*-
"""
Usa os rótulos REAIS do probe (tabela probe_labels) para VALIDAR e RE-TREINAR o v2.
SEMPRE mede o modelo ATUAL no real (o número honesto); com >= LIMIAR_RETREINO rótulos
re-treina HÍBRIDO (sintético + real com peso maior) e salva — o real domina ao crescer.

Offline/manual. Precisa de DATABASE_URL (mesmo banco do backend). Rode na raiz:
    python ml/treinar_com_probe.py

`probe_labels` já está no schema versionado (supabase/migrations/*_remote_schema.sql).
"""
import os
import sys
import json
import asyncio
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report
from dotenv import load_dotenv
import asyncpg

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))                        # p/ importar avaliar/gerar_base_v2
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

from gerar_base_v2 import (  # noqa: E402
    construir_base, treinar_e_salvar, FEATURE_ORDER, ESTADOS, MODELO_PATH, SCALER_PATH, METRICAS_PATH)
from avaliar import relatorio  # noqa: E402

LIMIAR_RETREINO = 40   # abaixo disso: só valida (pouco dado real -> re-treinar overfita)


async def carregar_rotulos():
    """Lê probe_labels -> (X DataFrame, y array) na ordem das features do modelo."""
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return None
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        rows = await conn.fetch("select estado, features, coalesce(user_id::text, session_id::text) as aluno "
                                "from probe_labels")
    finally:
        await conn.close()

    X, y, alunos = [], [], []
    for r in rows:
        feats = r["features"]
        if isinstance(feats, str):
            feats = json.loads(feats)
        try:
            X.append([float(feats[k]) for k in FEATURE_ORDER])
            y.append(ESTADOS.index(r["estado"]))
            alunos.append(r["aluno"])
        except (KeyError, ValueError, TypeError):
            continue
    return pd.DataFrame(X, columns=FEATURE_ORDER, dtype=float), np.array(y), np.array(alunos)


def validar_modelo_atual(Xr, yr):
    """Métricas do modelo ATUAL (o do disco) nos rótulos reais — o número honesto.
    Mesma avaliar() da base sintética: acurácia + baseline + matriz de confusão."""
    modelo = pickle.load(open(MODELO_PATH, "rb"))
    scaler = pickle.load(open(SCALER_PATH, "rb"))
    Xs = pd.DataFrame(scaler.transform(Xr), columns=FEATURE_ORDER)
    rel = relatorio(yr, modelo.predict(Xs), ESTADOS, y_score=modelo.predict_proba(Xs))
    print(f"\n== modelo ATUAL nos {len(yr)} rótulos reais ==")
    if json.load(open(METRICAS_PATH, encoding="utf-8")).get("n_real"):
        print("AVISO: o modelo atual já treinou com rótulos reais — esta medida está inflada.")
    print(f"acurácia real: {rel['acuracia']:.3f}   (baseline majoritário: {rel['baseline_majoritario']:.3f})")
    if rel.get("kappa") is not None:
        print(f"kappa: {rel['kappa']:.3f}   (barra da literatura, pessoas fora do treino: 0,15–0,45)")
    for c in ESTADOS:
        print(f"  {c:16s} precisão {rel['classification_report'][c]['precision']:.3f}  "
              f"recall {rel['classification_report'][c]['recall']:.3f}")
    if "brier" in rel:
        print(f"calibração (brier, 0=perfeito): {rel['brier']:.3f}")
    print("matriz de confusão (linha=real, col=previsto) ->", ESTADOS)
    for linha in rel["matriz_confusao"]:
        print("  ", linha)
    return rel["acuracia"]


def main():
    res = asyncio.run(carregar_rotulos())
    if res is None:
        return
    Xr, yr, alunos = res
    n = len(yr)
    print(f"rótulos reais coletados: {n}")
    if n == 0:
        print("Nenhum probe ainda. O modelo segue 100% sintético (rode depois de coletar).")
        return

    validar_modelo_atual(Xr, yr)

    if n < LIMIAR_RETREINO:
        print(f"\n< {LIMIAR_RETREINO} rótulos: só validação por ora (poucos dados p/ re-treinar "
              f"sem overfit). Faltam ~{LIMIAR_RETREINO - n}.")
        return

    print(f"\n>= {LIMIAR_RETREINO}: re-treinando HÍBRIDO (sintético + real up-weighted)...")
    Xb, yb, _ = construir_base()
    _, acc, _, n_real_te = treinar_e_salvar(Xb, yb, X_real=Xr, y_real=yr, grupos_real=alunos)
    alvo = " (real, alunos fora do treino)" if n_real_te else " (sintético — menos de 3 alunos com probe)"
    print(f"novo modelo salvo. acurácia no teste{alvo}: {acc:.3f}")


if __name__ == "__main__":
    main()
