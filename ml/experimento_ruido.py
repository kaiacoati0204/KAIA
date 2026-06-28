"""
EXPERIMENTO (não faz parte do baseline oficial v1).

Demonstra por que a acurácia de 100% do modelo v1 é enganosa: a base
sintética é separável demais. Aqui injetamos ruído gaussiano crescente
nas features (já padronizadas) para simular a ambiguidade de dados reais
e observar a acurácia cair para uma faixa realista.

Não toca em modelo_rf_v1.pkl, metricas_v1.json nem baseline.md.

Uso:
    python ml/experimento_ruido.py
"""
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

RANDOM_STATE = 42
ARTIFACTS = Path(__file__).parent / "artifacts"
TARGET_NAMES = ["engajado", "distraido", "muito_distraido"]
LABELS = [0, 1, 2]

# Níveis de ruído em desvios-padrão (features já estão padronizadas: std=1)
NIVEIS_RUIDO = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0]


def load_pkl(nome):
    with open(ARTIFACTS / f"{nome}.pkl", "rb") as f:
        return pickle.load(f)


def treina_avalia(X_train, y_train, X_test, y_test):
    modelo = RandomForestClassifier(
        n_estimators=100, max_depth=10,
        random_state=RANDOM_STATE, class_weight="balanced",
    )
    modelo.fit(X_train, y_train)
    y_pred = modelo.predict(X_test)
    return modelo, y_pred


def main():
    X_train = load_pkl("X_train")
    y_train = load_pkl("y_train")
    X_test = load_pkl("X_test")
    y_test = load_pkl("y_test")

    # RNG fixo para reprodutibilidade (random_state=42 em tudo)
    rng = np.random.default_rng(RANDOM_STATE)

    print("=== Acuracia vs. nivel de ruido injetado ===")
    print(f"{'sigma (desv-pad)':>16} | {'acuracia':>9}")
    print("-" * 30)
    resultados = {}
    for sigma in NIVEIS_RUIDO:
        # Ruído gaussiano N(0, sigma) somado a treino e teste (ruído inerente ao dado)
        Xtr = X_train + rng.normal(0, sigma, X_train.shape) if sigma > 0 else X_train
        Xte = X_test + rng.normal(0, sigma, X_test.shape) if sigma > 0 else X_test
        _, y_pred = treina_avalia(Xtr, y_train, Xte, y_test)
        acc = accuracy_score(y_test, y_pred)
        resultados[sigma] = (acc, y_pred)
        print(f"{sigma:>16.1f} | {acc:>9.4f}")

    # Detalhe para um nível "realista" intermediário (sigma=1.0)
    sigma_detalhe = 1.0
    _, y_pred = resultados[sigma_detalhe]
    print(f"\n=== Detalhe com ruido sigma={sigma_detalhe} (faixa realista) ===")
    print(classification_report(y_test, y_pred, labels=LABELS, target_names=TARGET_NAMES))
    print("Matriz de confusao (linha=real, coluna=previsto):")
    matriz = confusion_matrix(y_test, y_pred, labels=LABELS)
    print("           " + "  ".join(f"{n[:8]:>8}" for n in TARGET_NAMES))
    for nome, linha in zip(TARGET_NAMES, matriz):
        print(f"{nome:>16} " + "  ".join(f"{v:>8}" for v in linha))

    print("\nObs: nenhum arquivo do baseline v1 foi alterado. Este script e so demonstrativo.")


if __name__ == "__main__":
    main()
