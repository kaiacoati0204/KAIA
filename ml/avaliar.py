# -*- coding: utf-8 -*-
"""
Avaliação reutilizável do modelo de atenção — a MESMA função roda na base
SINTÉTICA (gerar_base_v2) e nos rótulos REAIS do probe (treinar_com_probe).
Assim, quando o probe tiver dado, a medição rica já roda automática, sem código novo.

Métricas:
- `relatorio`: acurácia, relatório por classe, MATRIZ DE CONFUSÃO e BASELINE
  majoritário (referência trivial — "sempre chutar a classe mais comum").
- `cv_agrupada`: cross-validation AGRUPADA por aluno (nenhum aluno em treino E
  teste ao mesmo tempo) — evita o vazamento que infla a métrica e mede a
  generalização pra alunos nunca vistos. Devolve média ± desvio entre os folds.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import StratifiedGroupKFold


def relatorio(y_true, y_pred, classes, y_score=None):
    """Métricas de um conjunto já predito. `classes` = nomes na ordem 0..n-1.
    `y_score` (probabilidades N x classes, opcional) liga o Brier (CALIBRAÇÃO):
    0 = perfeito, 2 = péssimo — diz se a confiança do modelo bate com a realidade.
    Só é significativo no dado REAL; no sintético é ruído."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    labels = list(range(len(classes)))
    if len(y_true):
        maj = int(np.bincount(y_true, minlength=len(classes)).argmax())   # classe mais comum
        baseline = float((y_true == maj).mean())                          # acerto do chute trivial
    else:
        baseline = 0.0
    d = {
        "n": int(len(y_true)),
        "acuracia": float(accuracy_score(y_true, y_pred)) if len(y_true) else 0.0,
        "baseline_majoritario": baseline,
        "matriz_confusao": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "classification_report": classification_report(
            y_true, y_pred, labels=labels, target_names=classes,
            output_dict=True, zero_division=0),
    }
    if y_score is not None and len(y_true):
        ys = np.asarray(y_score, dtype=float)
        if ys.ndim == 2 and ys.shape[1] == len(classes):
            onehot = np.eye(len(classes))[y_true]                         # rótulo real em one-hot
            d["brier"] = float(np.mean(np.sum((ys - onehot) ** 2, axis=1)))
    return d


def cv_agrupada(X, y, grupos, treinar_fold, n_splits=5):
    """CV estratificada e AGRUPADA por aluno: cada fold testa em alunos que o
    modelo NÃO viu no treino. `treinar_fold(Xtr, ytr) -> (modelo, scaler)` treina
    do zero. Retorna {media, desvio, por_fold}. Poucos alunos -> não roda."""
    y, grupos = np.asarray(y), np.asarray(grupos)
    n = min(n_splits, len(np.unique(grupos)))
    if n < 2:
        return {"media": None, "desvio": None, "por_fold": [], "obs": "poucos alunos p/ CV"}
    sgkf = StratifiedGroupKFold(n_splits=n, shuffle=True, random_state=42)
    accs = []
    for tr, te in sgkf.split(X, y, grupos):
        Xtr = X.iloc[tr] if hasattr(X, "iloc") else X[tr]
        Xte = X.iloc[te] if hasattr(X, "iloc") else X[te]
        modelo, scaler = treinar_fold(Xtr, y[tr])
        cols = list(X.columns) if hasattr(X, "columns") else None
        Xte_s = pd.DataFrame(scaler.transform(Xte), columns=cols)
        accs.append(float(accuracy_score(y[te], modelo.predict(Xte_s))))
    return {"media": float(np.mean(accs)), "desvio": float(np.std(accs)), "por_fold": accs}
