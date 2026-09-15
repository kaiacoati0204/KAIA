# -*- coding: utf-8 -*-
"""
Avaliação reutilizável do modelo de atenção — a MESMA função roda na base SINTÉTICA
(gerar_base_v2) e nos rótulos REAIS do probe (treinar_com_probe), sem código novo.

`relatorio`: acurácia, por classe, matriz de confusão e baseline majoritário.
`cv_agrupada`: CV AGRUPADA por aluno (nenhum aluno em treino E teste) — evita o
vazamento que infla a métrica e mede generalização pra aluno nunca visto; média ± desvio.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, cohen_kappa_score, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit, StratifiedGroupKFold


def relatorio(y_true, y_pred, classes, y_score=None):
    """Métricas de um conjunto já predito. `classes` = nomes na ordem 0..n-1.
    `y_score` (probs N x classes, opcional) liga o Brier (calibração; 0 = perfeito,
    2 = péssimo). Só é significativo no dado REAL; no sintético é ruído."""
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
        # acerto descontada a sorte (0 = chutar, 1 = perfeito). Kuvar et al. 2023: detectores
        # testados em pessoas fora do treino ficam em 0,15–0,45; log de interação ~0,36–0,38.
        "kappa": float(cohen_kappa_score(y_true, y_pred, labels=labels)) if len(set(y_true)) > 1 else None,
        "matriz_confusao": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "classification_report": classification_report(
            y_true, y_pred, labels=labels, target_names=classes,
            output_dict=True, zero_division=0),
    }
    if y_score is not None and len(y_true):
        ys = np.asarray(y_score, dtype=float)
        if ys.ndim == 2 and ys.shape[1] == len(classes):
            onehot = np.eye(len(classes))[y_true]
            d["brier"] = float(np.mean(np.sum((ys - onehot) ** 2, axis=1)))
    return d


def na_proporcao(y_true, y_pred, classes, proporcao):
    """Precisão/recall/F1 por classe como se o teste tivesse a proporção `proporcao`
    ({classe: fração}), repesando cada exemplo. Base balanceada esconde o alarme falso:
    com 9% de dispersão real, Dias da Silva et al. viram o RF com F1 0 na classe rara."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    labels = list(range(len(classes)))
    contagem = np.bincount(y_true, minlength=len(classes))
    peso_classe = [proporcao[c] / contagem[i] if contagem[i] else 0.0 for i, c in enumerate(classes)]
    pesos = np.array([peso_classe[t] for t in y_true])
    rep = classification_report(y_true, y_pred, labels=labels, target_names=classes,
                                sample_weight=pesos, output_dict=True, zero_division=0)
    return {"proporcao": proporcao,
            "por_classe": {c: {k: round(rep[c][k], 3) for k in ("precision", "recall", "f1-score")}
                           for c in classes}}


def separar_por_aluno(X, y, grupos, test_size=0.3, min_alunos=3):
    """Treino/teste sem nenhum aluno dos dois lados (índices de linha). O mesmo aluno nos
    dois infla a métrica: o modelo reconhece a pessoa, não o estado.
    Devolve None se houver menos de `min_alunos` alunos — aí não dá para medir generalização."""
    grupos = np.asarray(grupos)
    if len(np.unique(grupos)) < min_alunos:
        return None
    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=42)
    return next(gss.split(X, y, grupos))


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
