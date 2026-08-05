# -*- coding: utf-8 -*-
"""
Incremento C — passo 1: gerador sintético v2 + treino (OFFLINE).

Desenho aprovado:
- internas RELATIVAS (desvio do baseline do aluno, em sigma); externas/contexto ABSOLUTAS.
- INTENSIDADE LATENTE z por sessão: as internas sobem/descem juntas (co-variação).
- ruído gaussiano + sobreposição -> acurácia-alvo ~80-90% (NÃO 1.0).
- dificuldade × estado modula tempo_resposta e erros.
- blip externo ocasional (10-15%) no engajado E distraído (ambos "presentes");
  muito_distraído = frequente + longo. -> engajado vs distraído só pelas INTERNAS.
- mouse: simula o BRUTO e passa pela MESMA features_mouse da produção (consistência),
  relativizado pelo baseline de mouse do aluno.

NÃO mexe na produção: salva como modelo_rf_v2.pkl / scaler_v2.pkl / metricas_v2.json.
"""
import os, sys, json, math, random, statistics
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import pickle

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "..", "Backend"))
from mouse_features import features_mouse

random.seed(42); np.random.seed(42)

ESTADOS = ["engajado", "distraido", "muito_distraido"]
FEATURE_ORDER = [
    # internas (relativas ao aluno)
    "variabilidade_tempo_resposta", "contagem_lapsos_rt", "tempo_resposta_ms",
    "tempo_iniciacao_resposta_ms", "tempo_dwell_sem_responder_s", "tempo_ocioso_s",
    "velocidade_mouse_media", "variabilidade_velocidade_mouse", "flips_cursor_xy",
    "entropia_trajetoria_mouse", "erros_sem_offtask", "tendencia_desempenho_sessao",
    # externas (absolutas)
    "mudancas_aba", "tempo_fora_foco_s", "cliques_fora_area_estudo", "taxa_abandono_sessao",
    # contexto (absolutas)
    "nivel_dificuldade_atividade", "duracao_sessao_min", "hora_do_dia", "tempo_estudo_acumulado_dia_min",
]
MOUSE_KEYS = ["velocidade_mouse_media", "variabilidade_velocidade_mouse",
              "entropia_trajetoria_mouse", "flips_cursor_xy"]

# desvio-alvo (em sigma) das internas geradas direto; engajado=baseline=0
# deslocamentos MENORES + episódios fracos deixam engajado↔distraído genuinamente fuzzy
DESVIO = {
    "variabilidade_tempo_resposta": {"engajado": 0, "distraido": 0.9, "muito_distraido": 0.5},
    "tempo_resposta_ms":            {"engajado": 0, "distraido": 0.8, "muito_distraido": 0.4},
    "tempo_iniciacao_resposta_ms":  {"engajado": 0, "distraido": 0.8, "muito_distraido": 0.8},
    "tempo_dwell_sem_responder_s":  {"engajado": 0, "distraido": 0.8, "muito_distraido": 0.3},
    "tempo_ocioso_s":               {"engajado": 0, "distraido": 1.0, "muito_distraido": -0.4},
    "tendencia_desempenho_sessao":  {"engajado": 0, "distraido": -0.45, "muito_distraido": -0.25},
}
CONTAGEM = {  # médias de contagens (Poisson) por estado
    "contagem_lapsos_rt": {"engajado": 0.3, "distraido": 1.8, "muito_distraido": 0.9},
    "erros_sem_offtask":  {"engajado": 0.2, "distraido": 1.0, "muito_distraido": 0.4},
}

# ---- mouse ----
def gerar_track(erratic, n):
    if n < 2:
        return []
    track, t = [], 0
    x, y = random.uniform(200, 800), random.uniform(200, 500)
    ang = random.uniform(-math.pi, math.pi)
    for _ in range(n):
        t += random.randint(80, 140)
        ang += random.gauss(0, 0.25 + erratic * 0.7)          # + erratic -> + entropia/flips
        vel = max(40, random.gauss(280 + erratic * 90, 90 + erratic * 160))
        passo = vel * 0.1
        x += passo * math.cos(ang); y += passo * math.sin(ang)
        track.append([t, round(x), round(y)])
    return track

def baseline_mouse(erratic_base):
    """Baseline de mouse do aluno (features do estado engajado dele)."""
    fs = [features_mouse(gerar_track(erratic_base, random.randint(30, 60))) for _ in range(8)]
    base = {}
    for k in MOUSE_KEYS:
        vals = [f[k] for f in fs]
        base[k] = (statistics.mean(vals), statistics.pstdev(vals) or 1.0)
    return base

# ---- geração de uma sessão ----
def gerar_aluno():
    return {"erratic_base": random.uniform(0.3, 1.0),
            "distraibilidade": random.uniform(0.0, 1.0)}

def gerar_sessao(estado, aluno, base_mouse):
    z = random.uniform(0.1, 1.5)                 # intensidade latente; perto de 0 = episódio fraco (parece engajado)
    dif = random.randint(1, 5)
    # ~15% dos muito são "leves": o aluno saiu tão de leve que o COMPORTAMENTO parece presente.
    # O rótulo continua muito_distraído, mas as features não têm assinatura → o modelo às vezes
    # erra e NADA dá 100% (o realista). estado_efetivo (ef) gera as features; o rótulo é o `estado`.
    # fronteira distraído↔muito borrada nos DOIS sentidos (nada fica separável demais):
    #  - alguns muito são "leves" e parecem distraído (saiu de leve, sem assinatura)
    #  - alguns distraído são "pesados" e parecem muito (lapsou E trocou de aba umas vezes)
    ef = estado
    if estado == "muito_distraido" and random.random() < 0.08:
        ef = "distraido"
    elif estado == "distraido" and random.random() < 0.05:
        ef = "muito_distraido"

    f = {}
    # internas relativas geradas direto (sigma); z faz co-variar
    for nome, m in DESVIO.items():
        val = m[ef] * z + random.gauss(0, 0.8)
        if nome == "tempo_resposta_ms":
            val += 0.30 * (dif - 3)               # dificuldade -> mais lento que o normal
        f[nome] = round(val, 3)

    # contagens (Poisson), com efeito de dificuldade nos erros
    lam_l = CONTAGEM["contagem_lapsos_rt"][ef] * (0.6 + 0.4 * z)
    f["contagem_lapsos_rt"] = int(np.random.poisson(max(0.01, lam_l)))
    lam_e = CONTAGEM["erros_sem_offtask"][ef] * (0.7 + 0.15 * (dif - 3))
    f["erros_sem_offtask"] = int(np.random.poisson(max(0.01, lam_e)))

    # mouse: simula bruto -> features_mouse -> relativiza pelo baseline do aluno
    if ef == "engajado":
        erratic, n = aluno["erratic_base"] + random.gauss(0, 0.1), random.randint(30, 70)
    elif ef == "distraido":
        erratic, n = aluno["erratic_base"] + 0.32 * z, random.randint(30, 70)
    else:                                        # muito_distraído: pouca mexida
        erratic, n = aluno["erratic_base"], random.randint(3, 10)
    mf = features_mouse(gerar_track(max(0.05, erratic), n))
    for k in MOUSE_KEYS:
        mu, sd = base_mouse[k]
        f[k] = round((mf[k] - mu) / sd, 3)

    # externas absolutas — muito_distraído = frequente+longo; presente (eng/dist) = blip ocasional
    if ef == "muito_distraido":
        f["mudancas_aba"] = max(2, int(np.random.poisson(4)))
        f["tempo_fora_foco_s"] = round(max(15, random.gauss(60, 30)), 1)
        f["cliques_fora_area_estudo"] = int(np.random.poisson(3))
    else:
        blip = random.random() < 0.13
        f["mudancas_aba"] = 1 if blip else 0
        f["tempo_fora_foco_s"] = round(random.uniform(2, 10), 1) if blip else 0.0
        f["cliques_fora_area_estudo"] = 1 if random.random() < 0.10 else 0
    f["taxa_abandono_sessao"] = round(min(1.0, max(0.0, aluno["distraibilidade"] + random.gauss(0, 0.1))), 3)

    # contexto absolutas
    f["nivel_dificuldade_atividade"] = dif
    dist_ctx = {"engajado": 0, "distraido": 1, "muito_distraido": 1}[ef]
    f["duracao_sessao_min"] = round(max(3, random.gauss(18 + 4 * dist_ctx, 8)), 1)
    f["hora_do_dia"] = round(min(23.9, max(7, random.gauss(15 + 3 * dist_ctx, 4))), 2)
    f["tempo_estudo_acumulado_dia_min"] = round(max(0, random.gauss(40 + 20 * dist_ctx, 30)), 1)
    return f

# ---- monta a base ----
N_ALUNOS, POR_ESTADO = 40, 220
alunos = [dict(a, base_mouse=baseline_mouse(a["erratic_base"])) for a in (gerar_aluno() for _ in range(N_ALUNOS))]

X, y = [], []
for estado in ESTADOS:
    for _ in range(POR_ESTADO):
        al = random.choice(alunos)
        feats = gerar_sessao(estado, al, al["base_mouse"])
        X.append([feats[k] for k in FEATURE_ORDER])
        y.append(ESTADOS.index(estado))

X, y = np.array(X, float), np.array(y)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
scaler = StandardScaler().fit(Xtr)
modelo = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, class_weight="balanced")
modelo.fit(scaler.transform(Xtr), ytr)
acc = accuracy_score(yte, modelo.predict(scaler.transform(Xte)))

# salva OFFLINE (não toca no v1)
with open(os.path.join(BASE, "models", "modelo_rf_v2.pkl"), "wb") as fp: pickle.dump(modelo, fp)
with open(os.path.join(BASE, "artifacts", "scaler_v2.pkl"), "wb") as fp: pickle.dump(scaler, fp)
rep = classification_report(yte, modelo.predict(scaler.transform(Xte)), target_names=ESTADOS, output_dict=True)
with open(os.path.join(BASE, "artifacts", "metricas_v2.json"), "w", encoding="utf-8") as fp:
    json.dump({"versao": "v2", "acuracia": acc, "n": len(X), "feature_order": FEATURE_ORDER,
               "classification_report": rep}, fp, indent=2, ensure_ascii=False)

print(f"acuracia teste: {acc:.3f}  (alvo ~0,80-0,90)")
imp = sorted(zip(FEATURE_ORDER, modelo.feature_importances_), key=lambda t: -t[1])
print("top importancias:")
for n, v in imp[:8]:
    print(f"  {v*100:5.1f}%  {n}")
