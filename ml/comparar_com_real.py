# -*- coding: utf-8 -*-
"""
Compara o RITMO de resposta da nossa base sintética com uma base REAL de uso.

Por que: o gerador inventa como o tempo de resposta se comporta ao longo de uma sessão. Se a
forma dessa sequência estiver errada, features sequenciais (rapido_colado_lento) não aprendem
nada — e a gente não saberia, porque o dado é nosso.

As quatro medidas são calculadas do MESMO jeito nos dois lados. O tempo real é convertido para
sigma da régua DO PRÓPRIO ALUNO antes de tudo, que é a escala em que o gerador e o serving
trabalham — comparar milissegundos com sigma não diria nada.

  1. autocorrelação lag-1 do log do tempo   -> quanta inércia uma questão passa para a seguinte
  2. % de respostas acima de +2 sigma       -> lapsos (lento demais)
  3. % de respostas abaixo de -2 sigma      -> pressa (o lado do chute)
  4. % de pares VIZINHOS rápido-com-lento   -> rapido_colado_lento (Baker 2007)

NÃO altera o gerador. Só mede.

Uso (na raiz do projeto):
    python ml/comparar_com_real.py [caminho_do_csv]

Base esperada: ASSISTments 2009-2010 skill builder (user_id, order_id, ms_first_response).
Não versionada — ver ml/dados_externos/ no .gitignore.
"""
import math
import os
import random
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

CSV_PADRAO = os.path.join(BASE, "dados_externos", "skill_builder_data.csv")
MIN_RESPOSTAS = 10        # abaixo disso a régua do aluno não existe
N_JANELA = 7              # = N_QUESTOES_REF do gerador: a janela que ele simula
CORTE_SIGMA = 2.0         # mesmo do serving (app.py::_contagens_ritmo)
RT_MIN_MS, RT_MAX_MS = 500, 30 * 60 * 1000    # 0,5 s a 30 min: fora disso é log quebrado


def medidas(sequencias):
    """As quatro medidas, dadas listas de z (já em sigma da régua do aluno)."""
    autos, n_resp, lapsos, rapidas, n_pares, colados = [], 0, 0, 0, 0, 0
    for z in sequencias:
        if len(z) < 3:
            continue
        a, b = np.array(z[:-1]), np.array(z[1:])
        if a.std() > 1e-9 and b.std() > 1e-9:
            autos.append(float(np.corrcoef(a, b)[0, 1]))
        tipo = [1 if v > CORTE_SIGMA else -1 if v < -CORTE_SIGMA else 0 for v in z]
        n_resp += len(tipo)
        lapsos += tipo.count(1)
        rapidas += tipo.count(-1)
        n_pares += len(tipo) - 1
        colados += sum(1 for x, y in zip(tipo, tipo[1:]) if x * y == -1)
    return {
        "autocorr_lag1": float(np.mean(autos)) if autos else float("nan"),
        "pct_lentas": 100.0 * lapsos / max(n_resp, 1),
        "pct_rapidas": 100.0 * rapidas / max(n_resp, 1),
        "pct_pares_colados": 100.0 * colados / max(n_pares, 1),
        "_n_alunos": len(autos), "_n_respostas": n_resp,
    }


def sequencias_reais(caminho):
    """[[z, z, ...], ...] — uma lista por aluno, na ORDEM em que ele respondeu."""
    df = pd.read_csv(caminho, usecols=["user_id", "order_id", "ms_first_response"],
                     encoding="latin-1", low_memory=False)
    df = df.dropna()
    df = df[(df["ms_first_response"] >= RT_MIN_MS) & (df["ms_first_response"] <= RT_MAX_MS)]
    df = df.sort_values(["user_id", "order_id"])
    df["lrt"] = np.log(df["ms_first_response"])
    saida = []
    for _, g in df.groupby("user_id", sort=False):
        if len(g) < MIN_RESPOSTAS:
            continue
        mu, sd = g["lrt"].mean(), g["lrt"].std()
        if not sd or sd < 1e-9:
            continue
        saida.append(((g["lrt"] - mu) / sd).tolist())      # sigma da régua DELE
    return saida


def sequencias_do_gerador(modulo, n_sessoes=660):
    """Reconstrói a sequência que o gerador produziria. Na versão antiga não existe sequência:
    as contagens eram Poisson independentes, então o que se mede é o efeito delas."""
    seqs = []
    alunos = [dict(a, base_mouse=modulo.baseline_mouse(a))
              for a in (modulo.gerar_aluno() for _ in range(40))]
    tem_seq = hasattr(modulo, "_sequencia_rt")
    for i in range(n_sessoes):
        estado = modulo.ESTADOS[i % len(modulo.ESTADOS)]
        al = random.choice(alunos)
        f = modulo.gerar_sessao(estado, al, al["base_mouse"])
        if tem_seq:
            seqs.append(modulo._sequencia_rt(f["tempo_resposta_ms"],
                                             f["variabilidade_tempo_resposta"], N_JANELA))
        else:
            seqs.append(_reconstruir_antigo(f))
    return seqs, tem_seq


def _reconstruir_antigo(f, n=N_JANELA):
    """Versão antiga: as contagens vinham de Poissons separados. Devolve uma sequência
    COMPATÍVEL com elas (as lentas e as rápidas nas posições que o sorteio implicaria),
    para as porcentagens serem comparáveis. A ordem é arbitrária — que é o problema."""
    z = [0.0] * n
    pos = list(range(n))
    random.shuffle(pos)
    for p in pos[:min(int(f.get("contagem_lapsos_rt", 0)), n)]:
        z[p] = CORTE_SIGMA + 0.5
    livres = [p for p in pos if z[p] == 0.0]
    for p in livres[:min(int(f.get("contagem_rapidas_rt", 0)), len(livres))]:
        z[p] = -CORTE_SIGMA - 0.5
    return z


def main():
    caminho = sys.argv[1] if len(sys.argv) > 1 else CSV_PADRAO
    if not os.path.exists(caminho):
        print(f"base real não encontrada: {caminho}")
        return 1
    random.seed(42)
    np.random.seed(42)

    print(f"lendo {os.path.basename(caminho)} ...")
    reais = sequencias_reais(caminho)
    # A autocorrelação amostral é enviesada para BAIXO em série curta (~ -1/n). O gerador
    # produz janelas de N_JANELA respostas; medir o real em séries de 155 e o sintético em
    # séries de 7 compararia coisas diferentes. Por isso as duas linhas: a longa dá o valor
    # verdadeiro (é dele que sai o AR_RITMO), a picada dá o que é justo comparar.
    reais_picados = [z[i:i + N_JANELA] for z in reais
                     for i in range(0, len(z) - N_JANELA + 1, N_JANELA)]
    linhas = [("REAL (sessão inteira)", medidas(reais)),
              (f"REAL (janelas de {N_JANELA})", medidas(reais_picados))]

    import gerar_base_v2
    seqs, tem = sequencias_do_gerador(gerar_base_v2)
    linhas.append((f"SINTÉTICO ({'sequencial' if tem else 'sorteado'})", medidas(seqs)))

    print(f"\n{'':28} {'autocorr':>9} {'% lentas':>9} {'% rápidas':>10} {'% colados':>10}")
    for nome, m in linhas:
        print(f"{nome:28} {m['autocorr_lag1']:9.3f} {m['pct_lentas']:9.2f} "
              f"{m['pct_rapidas']:10.2f} {m['pct_pares_colados']:10.2f}")
    print(f"\nreal: {linhas[0][1]['_n_alunos']} alunos, "
          f"{linhas[0][1]['_n_respostas']} respostas")
    print()
    print(f"AR_RITMO deve ficar perto de {linhas[0][1]['autocorr_lag1']:.2f} "
          f"(a sessão inteira dá o valor sem viés de série curta).")
    print(f"As % comparam-se com a linha 'janelas de {N_JANELA}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
