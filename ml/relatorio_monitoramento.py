# -*- coding: utf-8 -*-
"""
Monitoramento contínuo do modelo — lê os rótulos do probe (probe_labels) ao longo
do tempo e mostra a acurácia do modelo ATUAL por SEMANA, pra pegar se o desempenho
derrapa (drift). Análogo do relatorio_bandit, mas pro modelo. Fica PRONTO — hoje
vazio até haver probes.

Offline. Precisa de DATABASE_URL (Backend/.env). Rodar na raiz:
    python ml/relatorio_monitoramento.py
"""
import os
import sys
import json
import pickle
import asyncio
from pathlib import Path
from collections import defaultdict

import pandas as pd
from dotenv import load_dotenv
import asyncpg

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

from gerar_base_v2 import FEATURE_ORDER, ESTADOS, MODELO_PATH, SCALER_PATH  # noqa: E402
from avaliar import relatorio  # noqa: E402


async def _carregar():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return None
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        rows = await conn.fetch(
            "select estado, features, created_at from probe_labels order by created_at")
    finally:
        await conn.close()
    return rows


def main():
    rows = asyncio.run(_carregar())
    if rows is None:
        return
    if not rows:
        print("Nenhum probe ainda. Fica pronto — rode depois de coletar.")
        return

    modelo = pickle.load(open(MODELO_PATH, "rb"))
    scaler = pickle.load(open(SCALER_PATH, "rb"))

    X, y, semanas = [], [], []
    for r in rows:
        feats = r["features"]
        if isinstance(feats, str):
            feats = json.loads(feats)
        try:
            X.append([float(feats[k]) for k in FEATURE_ORDER])
            y.append(ESTADOS.index(r["estado"]))
            semanas.append(r["created_at"].strftime("%G-S%V"))   # ano-Ssemana ISO
        except (KeyError, ValueError, TypeError):
            continue

    Xs = pd.DataFrame(scaler.transform(pd.DataFrame(X, columns=FEATURE_ORDER)), columns=FEATURE_ORDER)
    pred = modelo.predict(Xs)

    geral = relatorio(y, pred, ESTADOS)
    print(f"\n== Monitoramento — {geral['n']} probes | acurácia real geral: {geral['acuracia']:.3f} "
          f"(baseline {geral['baseline_majoritario']:.3f}) ==")

    por_semana = defaultdict(lambda: [0, 0])   # semana -> [acertos, total]
    for sem, yr, pr in zip(semanas, y, pred):
        por_semana[sem][0] += int(yr == pr)
        por_semana[sem][1] += 1

    print(f"\n{'semana':<12}{'probes':>8}{'acurácia':>10}")
    for sem in sorted(por_semana):
        a, n = por_semana[sem]
        print(f"{sem:<12}{n:>8}{a / n:>10.3f}")
    print("\n(queda ao longo das semanas = modelo derrapando -> re-treinar com o probe.)")


if __name__ == "__main__":
    main()
