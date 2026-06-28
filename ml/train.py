"""
Treina o baseline (v1) do classificador de engajamento do KaIA.

RandomForestClassifier sobre os dados já pré-processados pelo notebook
(ml/preprocessing.ipynb), avalia no conjunto de teste e salva o modelo
e as métricas. Tudo com random_state=42 para reprodutibilidade.

Uso:
    python ml/train.py
"""
import json
import pickle
import time
from pathlib import Path

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

RANDOM_STATE = 42
ARTIFACTS = Path(__file__).parent / "artifacts"
MODELS = Path(__file__).parent / "models"

# Ordem dos rótulos conforme o encoding do notebook: engajado=0, distraido=1, muito_distraido=2
LABELS = [0, 1, 2]
TARGET_NAMES = ["engajado", "distraido", "muito_distraido"]


def load_pkl(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def main():
    # --- Carrega dados de treino ---
    X_train = load_pkl(ARTIFACTS / "X_train.pkl")
    y_train = load_pkl(ARTIFACTS / "y_train.pkl")

    # --- Treina ---
    modelo = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        random_state=RANDOM_STATE,
        class_weight="balanced",
    )
    inicio = time.perf_counter()
    modelo.fit(X_train, y_train)
    tempo_treino = time.perf_counter() - inicio

    # --- Salva o modelo ---
    MODELS.mkdir(exist_ok=True)
    modelo_path = MODELS / "modelo_rf_v1.pkl"
    with open(modelo_path, "wb") as f:
        pickle.dump(modelo, f)
    print(f"[OK] Modelo treinado em {tempo_treino:.3f}s e salvo em {modelo_path}")

    # --- Avalia no teste ---
    X_test = load_pkl(ARTIFACTS / "X_test.pkl")
    y_test = load_pkl(ARTIFACTS / "y_test.pkl")
    y_pred = modelo.predict(X_test)

    acuracia = accuracy_score(y_test, y_pred)
    report_dict = classification_report(
        y_test, y_pred, labels=LABELS, target_names=TARGET_NAMES, output_dict=True
    )
    report_txt = classification_report(
        y_test, y_pred, labels=LABELS, target_names=TARGET_NAMES
    )
    matriz = confusion_matrix(y_test, y_pred, labels=LABELS)

    print(f"\n=== Acuracia geral: {acuracia:.4f} ===\n")
    print("=== Classification report ===")
    print(report_txt)
    print("=== Matriz de confusao (linhas=real, colunas=previsto) ===")
    print("           " + "  ".join(f"{n[:8]:>8}" for n in TARGET_NAMES))
    for nome, linha in zip(TARGET_NAMES, matriz):
        print(f"{nome:>16} " + "  ".join(f"{v:>8}" for v in linha))

    # --- Salva métricas ---
    metricas = {
        "versao": "v1",
        "modelo": "RandomForestClassifier",
        "parametros": {
            "n_estimators": 100,
            "max_depth": 10,
            "random_state": RANDOM_STATE,
            "class_weight": "balanced",
        },
        "tempo_treino_s": round(tempo_treino, 3),
        "acuracia": acuracia,
        "classification_report": report_dict,
        "matriz_confusao": matriz.tolist(),
        "labels": TARGET_NAMES,
    }
    metricas_path = ARTIFACTS / "metricas_v1.json"
    with open(metricas_path, "w", encoding="utf-8") as f:
        json.dump(metricas, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Metricas salvas em {metricas_path}")


if __name__ == "__main__":
    main()
