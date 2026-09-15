"""Avaliação do modelo (ml/avaliar.py): kappa, proporção real e separação por aluno."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml"))
from avaliar import na_proporcao, relatorio, separar_por_aluno  # noqa: E402

CLASSES = ["engajado", "distraido", "muito_distraido"]


def test_kappa_zero_para_chute_e_um_para_perfeito():
    y = [0, 1, 2] * 10
    assert relatorio(y, y, CLASSES)["kappa"] == 1.0
    assert abs(relatorio(y, [0] * 30, CLASSES)["kappa"]) < 1e-9


def test_separar_por_aluno_nao_poe_o_mesmo_aluno_nos_dois_lados():
    alunos = np.repeat([f"a{i}" for i in range(10)], 4)
    X = pd.DataFrame({"f": range(40)})
    y = np.tile([0, 1, 2, 0], 10)
    tr, te = separar_por_aluno(X, y, alunos)
    assert len(te) and not set(alunos[tr]) & set(alunos[te])


def test_separar_por_aluno_com_poucos_alunos_nao_separa():
    X = pd.DataFrame({"f": range(8)})
    assert separar_por_aluno(X, np.zeros(8), ["a"] * 4 + ["b"] * 4) is None


def test_na_proporcao_derruba_a_precisao_da_classe_rara():
    yt = [0] * 100 + [1] * 100
    yp = [1] * 10 + [0] * 90 + [1] * 100
    r = na_proporcao(yt, yp, ["eng", "dis"], {"eng": 0.9, "dis": 0.1})
    assert r["por_classe"]["dis"]["precision"] == 0.526
