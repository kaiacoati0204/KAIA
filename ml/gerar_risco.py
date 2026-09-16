# -*- coding: utf-8 -*-
"""
Modelo 1 (risco de perda de foco) — gerador sintético SEQUENCIAL + treino. Etapa 1.

Simula sessões questão a questão e usa a MESMA features_do_momento do servidor (Backend/risco.py)
para montar a base, então sintético e serving medem com a mesma régua. Treina uma regressão
logística e compara com as regras de reserva, validando com alunos fora do treino.

O sintético só faz o modelo NASCER funcionando no beta. Nenhum número daqui é resultado: os
parâmetros são hipóteses ancoradas nas pesquisas (PARAMETROS) e o teste de verdade é no dado real
do grupo controle (Etapas 3-4). Se o modelo não vencer as regras, NÃO é salvo e as regras decidem.

Uso:
    python ml/gerar_risco.py
"""
import json
import math
import os
import pickle
import random
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "..", "Backend"))
import risco  # noqa: E402

random.seed(7)
np.random.seed(7)

# ==== PARÂMETROS (hipóteses ancoradas; ajustar com o dado real na Etapa 3) ====
PARAMETROS = {
    # chance-base de começar a se desengajar a cada questão (logit); ~2-3% por questão
    "logit_base": (-3.6, "hipótese; calibrar com a taxa real de eventos do controle"),
    # tempo na tarefa aumenta a perda de foco (Farley 2013: atenção -0,18 por bloco de 5 min;
    # meta-análise Zanesco 2025 confirma o efeito). Traduzido como +0,18 no logit a cada 5 min.
    "por_5min": (0.18, "Farley et al. 2013; Zanesco et al. 2025"),
    "por_hora_estudo_dia": (0.35, "hipótese: cansaço acumulado no dia"),
    "evento_anterior": (0.45, "Mills et al. 2014: desistências anteriores entraram no modelo final"),
    # dificuldade em U: fácil e difícil demais aumentam a dispersão
    "dificuldade_u": (0.20, "Mills et al. 2013; Seli et al. 2018; Dias da Silva 2020"),
    # antes do evento: respostas rápidas demais e ritmo irregular
    "chance_rapida_desengajando": (0.55, "Mills et al. 2014: páginas lidas em < 5 s"),
    "irregularidade_desengajando": (0.75, "Bastian & Sackur 2013: variabilidade antes do relato"),
    # ruído que o mundo real tem: saída de aba para consultar e resposta rápida de quem sabe
    "saida_consulta_por_questao": (0.02, "Wilcox & Pollock 2019: saídas curtas e de consulta"),
    "rapida_legitima": (0.05, "hipótese: questão fácil ou conhecida"),
}
P = {k: v[0] for k, v in PARAMETROS.items()}

N_ALUNOS = 160
SESSOES_POR_ALUNO = (2, 6)
MODELO_PATH = risco.MODELO_RISCO_PATH
METRICAS_PATH = os.path.join(BASE, "artifacts", "metricas_risco.json")


def _sig(x):
    return 1.0 / (1.0 + math.exp(-x))


def gerar_aluno():
    return {"vies": random.gauss(0, 0.5),                  # uns se dispersam mais que outros
            "velocidade": math.exp(random.gauss(0, 0.25)),  # ritmo de leitura próprio
            "acerto": min(0.9, max(0.35, random.gauss(0.65, 0.12)))}


def gerar_sessao(aluno, inicio, estudo_dia_min):
    """Uma sessão como lista de (ts, tipo, payload), no mesmo formato dos eventos reais."""
    evs = [(inicio, "session_start", {})]
    t = inicio
    n_questoes = random.randint(10, 40)
    eventos_prev, desengajando = 0, 0
    for _ in range(n_questoes):
        nivel = random.randint(1, 5)
        lim_s = random.randint(40, 300) / 3.3 + 5                 # mesma conta do front (em segundos)
        minutos = (t - inicio).total_seconds() / 60.0
        logit = (P["logit_base"] + aluno["vies"]
                 + P["por_5min"] * minutos / 5
                 + P["por_hora_estudo_dia"] * (estudo_dia_min + minutos) / 60
                 + P["evento_anterior"] * min(eventos_prev, 3)
                 + P["dificuldade_u"] * (nivel - 3) ** 2)
        if not desengajando and random.random() < _sig(logit):
            desengajando = random.randint(1, 3)                  # sinais aparecem 1-3 questões antes

        esperado = lim_s * 1000 * aluno["velocidade"] * (1 + 0.08 * (nivel - 3))
        if desengajando:
            if random.random() < P["chance_rapida_desengajando"]:
                rt = esperado * random.uniform(0.08, 0.28)
            else:
                rt = esperado * math.exp(random.gauss(0.3, P["irregularidade_desengajando"]))
            acertou = random.random() < aluno["acerto"] * 0.5
        else:
            rapida = random.random() < P["rapida_legitima"]
            rt = esperado * (random.uniform(0.15, 0.3) if rapida else math.exp(random.gauss(0, 0.3)))
            acertou = random.random() < aluno["acerto"] - 0.06 * (nivel - 3)
        rt = max(1500.0, rt)
        t = t + timedelta(milliseconds=rt)
        evs.append((t, "question_answer", {"tempo_resposta_ms": round(rt), "limite_leitura_ms": round(lim_s),
                                           "acertou": acertou, "nivel_dificuldade": nivel}))

        if random.random() < P["saida_consulta_por_questao"]:   # ruído: saiu para consultar
            fora = random.uniform(10, 60)
            t = t + timedelta(seconds=fora)
            evs.append((t, "tab_change", {"tempo_fora_foco_s": round(fora, 1), "interno": False}))

        if desengajando:
            desengajando -= 1
            if desengajando == 0:                               # o episódio vira evento objetivo
                eventos_prev += 1
                sorteio = random.random()
                if sorteio < 0.15:
                    evs.append((t + timedelta(seconds=5), "question_abandon", {}))
                    break
                if sorteio < 0.75:
                    fora = random.uniform(35, 400)
                    t = t + timedelta(seconds=fora)
                    evs.append((t, "tab_change", {"tempo_fora_foco_s": round(fora, 1), "interno": False}))
                else:
                    evs.append((t + timedelta(seconds=1), "desengajamento_regra", {}))
    return evs


def construir_base():
    X, y, grupos = [], [], []
    for gi in range(N_ALUNOS):
        aluno = gerar_aluno()
        for _ in range(random.randint(*SESSOES_POR_ALUNO)):
            inicio = datetime(2026, 9, 1, 14, tzinfo=timezone.utc) + timedelta(days=random.randint(0, 60))
            estudo_dia = random.choice([0, 0, 20, 45, 90, 130])
            evs = gerar_sessao(aluno, inicio, estudo_dia)
            respostas = [ts for ts, tipo, _ in evs if tipo == "question_answer"]
            for ts in respostas[1:]:                             # momento de decidir = logo após cada resposta
                agora = ts + timedelta(milliseconds=1)
                f = risco.features_do_momento(evs, inicio, agora, estudo_dia)
                X.append([f[k] for k in risco.FEATURES_RISCO])
                y.append(risco.rotulo_futuro(evs, agora))
                grupos.append(gi)
    return np.array(X), np.array(y), np.array(grupos)


def _auc_regras(X):
    return np.array([risco.risco_por_regras(dict(zip(risco.FEATURES_RISCO, linha))) for linha in X])


def avaliar(X, y, grupos):
    """Validação separando alunos: modelo x regras, na proporção em que os eventos aparecem."""
    aucs_m, aucs_r, briers, prec_topo = [], [], [], []
    for tr, te in GroupKFold(n_splits=5).split(X, y, grupos):
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
        m.fit(X[tr], y[tr])
        p = m.predict_proba(X[te])[:, 1]
        aucs_m.append(roc_auc_score(y[te], p))
        aucs_r.append(roc_auc_score(y[te], _auc_regras(X[te])))
        briers.append(brier_score_loss(y[te], p))
        corte = np.quantile(p, 0.8)                             # os 20% de maior risco
        prec_topo.append(float(y[te][p >= corte].mean()))
    return {"auc_modelo": float(np.mean(aucs_m)), "auc_regras": float(np.mean(aucs_r)),
            "brier": float(np.mean(briers)), "precisao_top20": float(np.mean(prec_topo)),
            "taxa_eventos": float(y.mean())}


def main():
    X, y, grupos = construir_base()
    met = avaliar(X, y, grupos)
    modelo = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(X, y)
    coefs = dict(zip(risco.FEATURES_RISCO, map(float, modelo[-1].coef_[0])))

    # sanidade: o modelo tem que ganhar das regras e as direções têm que bater com as pesquisas
    esperado_positivo = ["minutos_sessao", "frac_rapidas_recentes", "eventos_na_sessao"]
    sinais_ok = all(coefs[k] > 0 for k in esperado_positivo)
    vence = met["auc_modelo"] > met["auc_regras"]

    print(f"linhas: {len(y)}  alunos: {N_ALUNOS}  taxa de eventos no horizonte: {met['taxa_eventos']:.3f}")
    print(f"AUC modelo {met['auc_modelo']:.3f}  x  AUC regras {met['auc_regras']:.3f}  (alunos fora do treino)")
    print(f"brier {met['brier']:.3f}  precisão nos 20% de maior risco {met['precisao_top20']:.3f}")
    print("coeficientes (padronizados):")
    for k, v in sorted(coefs.items(), key=lambda kv: -abs(kv[1])):
        print(f"  {v:+.3f}  {k}")
    print("SINTÉTICO: serve para o modelo nascer funcionando, não é resultado.")

    json.dump({"fonte": "sintetico", "metricas": met, "coeficientes": coefs, "sinais_ok": sinais_ok,
               "vence_regras": vence, "parametros": PARAMETROS, "features": risco.FEATURES_RISCO},
              open(METRICAS_PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    if not (sinais_ok and vence):
        print("NÃO SALVO: modelo não passou na sanidade — as regras continuam decidindo.")
        return 1
    with open(MODELO_PATH, "wb") as fp:
        pickle.dump({"modelo": modelo, "features": risco.FEATURES_RISCO, "fonte": "sintetico",
                     "horizonte_questoes": risco.HORIZONTE_QUESTOES}, fp)
    print(f"salvo em {MODELO_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
