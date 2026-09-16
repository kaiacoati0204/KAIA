# -*- coding: utf-8 -*-
"""
Modelo 2 (bandit de prevenção) — simulação de checagem. Etapa 1.

Não treina nada: o bandit aprende no uso. A simulação confere três coisas antes do beta:
1. ele acha o melhor apoio em poucas centenas de rodadas (dá para aprender no tamanho do beta);
2. a recompensa por QUESTÃO não premia o braço que só faz o aluno estudar menos;
3. a média bruta por braço engana, e a estimativa com peso pela probabilidade (IPW) não —
   por isso toda escolha registra a probabilidade usada (Rafferty 2019; Liao 2020).

Uso:
    python ml/simular_bandit_prevencao.py
"""
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "..", "Backend"))
from bandit_prevencao import BRACOS, BanditPrevencao, recompensa_rodada  # noqa: E402

RODADAS = 400            # ordem de grandeza de um beta pequeno
QUESTOES_RODADA = 10

# Dois mundos com a MESMA taxa de eventos para a pausa; muda só se o aluno volta e completa.
# O bandit tem que escolher diferente nos dois: a pausa vale quando ajuda a seguir estudando,
# não quando só encurta a sessão.
MUNDOS = {
    "pausa corta a rodada (o aluno não volta)": ({
        "nada":        {"taxa": 0.12, "questoes": QUESTOES_RODADA, "abandono": 0.10},
        "pacote_foco": {"taxa": 0.07, "questoes": QUESTOES_RODADA, "abandono": 0.06},
        "pausa_curta": {"taxa": 0.05, "questoes": 4,               "abandono": 0.08},
    }, "pacote_foco"),
    "pausa devolve o aluno inteiro": ({
        "nada":        {"taxa": 0.12, "questoes": QUESTOES_RODADA, "abandono": 0.10},
        "pacote_foco": {"taxa": 0.07, "questoes": QUESTOES_RODADA, "abandono": 0.06},
        "pausa_curta": {"taxa": 0.05, "questoes": QUESTOES_RODADA, "abandono": 0.08},
    }, "pausa_curta"),
}


def rodada(mundo, braco, rng):
    m = mundo[braco]
    abandonou = rng.random() < m["abandono"]
    respondidas = rng.integers(2, m["questoes"] + 1) if abandonou else m["questoes"]
    eventos = rng.binomial(respondidas, m["taxa"])
    return recompensa_rodada(int(eventos), int(respondidas), abandonou), int(respondidas)


def simular(mundo, rng):
    b = BanditPrevencao(semente=int(rng.integers(1e9)))
    escolhas, registros = [], []
    for _ in range(RODADAS):
        braco, prob = b.escolher()
        r, respondidas = rodada(mundo, braco, rng)
        b.atualizar(braco, r)
        escolhas.append(braco)
        if r is not None:
            registros.append((braco, prob, r, respondidas))
    return b, escolhas, registros


def estimativas(registros):
    """Média bruta (enviesada pelo próprio bandit) x IPW (cada rodada pesa 1/prob da escolha)."""
    out = {}
    n = len(registros)
    for braco in BRACOS:
        do_braco = [(p, r) for b, p, r, _ in registros if b == braco]
        bruta = float(np.mean([r for _, r in do_braco])) if do_braco else float("nan")
        ipw = float(sum(r / p for p, r in do_braco) / n) if n else float("nan")
        out[braco] = (bruta, ipw)
    return out


def rodar_mundo(nome, mundo, esperado, rng):
    ultimas, medias_questoes, finais = [], {b: [] for b in BRACOS}, {b: [] for b in BRACOS}
    est_acc = {b: ([], []) for b in BRACOS}
    for _ in range(30):                                     # 30 betas simulados
        b, escolhas, registros = simular(mundo, rng)
        ultimas.append(escolhas[-100:])
        p = b.probabilidades()
        for i, braco in enumerate(BRACOS):
            finais[braco].append(float(p[i]))
            medias_questoes[braco].extend([q for bb, _, _, q in registros if bb == braco])
        for braco, (bruta, ipw) in estimativas(registros).items():
            est_acc[braco][0].append(bruta)
            est_acc[braco][1].append(ipw)

    print(f"\n== {nome} ==")
    print("braço          escolhas nas últimas 100   prob. final   recompensa média   IPW")
    for braco in BRACOS:
        frac = np.mean([e.count(braco) / 100 for e in ultimas])
        bruta, ipw = np.mean(est_acc[braco][0]), np.mean(est_acc[braco][1])
        print(f"{braco:<14} {frac:>18.2f}   {np.mean(finais[braco]):>11.2f}   {bruta:>16.3f}   {ipw:.3f}")

    melhor = max(BRACOS, key=lambda b: np.mean([e.count(b) for e in ultimas]))
    minimo = min(np.mean(finais[b]) for b in BRACOS)
    print(f"mais escolhido no fim: {melhor}  (esperado: {esperado})")
    print("questões por rodada:", {b: round(float(np.mean(v)), 1) for b, v in medias_questoes.items()})
    print(f"nenhum braço some: probabilidade mínima {minimo:.2f}")
    return melhor == esperado and minimo >= 0.1 - 1e-6


def main():
    rng = np.random.default_rng(11)
    print(f"{RODADAS} rodadas x 30 simulações por mundo")
    ok = all(rodar_mundo(nome, mundo, esperado, rng) for nome, (mundo, esperado) in MUNDOS.items())
    print("\nSIMULAÇÃO: confere o mecanismo, não mede efeito. O efeito real vem do grupo controle.")
    if not ok:
        print("FALHOU: o bandit escolheu o braço errado em algum mundo.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
