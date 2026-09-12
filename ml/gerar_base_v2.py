# -*- coding: utf-8 -*-
"""
Incremento C — passo 1: gerador sintético v2 + treino (OFFLINE).

Internas RELATIVAS (sigma do baseline do aluno), externas/contexto ABSOLUTAS. Intensidade
latente z por sessão faz as internas co-variarem; ruído + sobreposição miram ~80-90% (NÃO
1.0); dificuldade × estado modula tempo_resposta e erros. Blip externo ocasional (10-15%)
em engajado E distraído, muito_distraído = frequente e longo: engajado vs distraído só pelas
INTERNAS. Mouse: simula o BRUTO, passa pela MESMA features_mouse da produção e relativiza
pelo baseline de mouse do aluno.

NÃO mexe na produção: salva como modelo_rf_v2.pkl / scaler_v2.pkl / metricas_v2.json.
"""
import os, sys, json, math, random, statistics
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import pickle

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)                              # p/ importar avaliar (mesma pasta)
sys.path.insert(0, os.path.join(BASE, "..", "Backend"))
from mouse_features import features_mouse
from avaliar import relatorio, cv_agrupada

random.seed(42); np.random.seed(42)

ESTADOS = ["engajado", "distraido", "muito_distraido"]
FEATURE_ORDER = [
    # internas (relativas ao aluno)
    "variabilidade_tempo_resposta", "contagem_lapsos_rt", "tempo_resposta_ms",
    "tempo_iniciacao_resposta_ms", "tempo_dwell_sem_responder_s", "tempo_ocioso_s",
    "velocidade_mouse_media", "variabilidade_velocidade_mouse", "flips_cursor_xy",
    "entropia_trajetoria_mouse", "erros_sem_offtask", "tendencia_desempenho_sessao",
    # externas (absolutas)
    "mudancas_aba", "tempo_fora_foco_s", "maior_ausencia_unica_s",
    "cliques_fora_area_estudo", "taxa_abandono_sessao",
    # ritmo (absolutas) — FORMA da imobilidade, nao o total: separa leitura densa
    # (muitos blocos medios) de mente vagando/ausencia (um bloco longo).
    "maior_bloco_parado_s", "n_blocos_parados",
    # contexto (absolutas)
    "nivel_dificuldade_atividade", "duracao_janela_min", "hora_do_dia", "tempo_estudo_acumulado_dia_min",
]
MOUSE_KEYS = ["velocidade_mouse_media", "variabilidade_velocidade_mouse",
              "entropia_trajetoria_mouse", "flips_cursor_xy"]

# ESCALA E LIMITES — espelham Backend/app.py (_esc, _sigma). Mudar os dois JUNTOS:
# se o gerador relativiza numa escala e o serving noutra, um sigma da base e um sigma
# da producao nao sao o mesmo objeto, e o modelo aprende a ler a regua errada.
SIGMA_PISO = 0.14
SIGMA_TETO = 4.0

def _esc(v):
    """log1p: distribuicao de tempo/velocidade e assimetrica a direita."""
    return math.log1p(max(0.0, float(v)))

def _sigma(bruto, mu, sd):
    return round(max(-SIGMA_TETO, min(SIGMA_TETO, (bruto - mu) / max(abs(sd), SIGMA_PISO))), 3)

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
# ==== UNIDADE DE OBSERVACAO: JANELA, NAO SESSAO ==============================
# Cada linha e uma JANELA de ~JANELA_MIN min num estado, nao a sessao inteira: o serving
# pergunta "como esta AGORA" e a base antiga (UM rotulo por sessao) nao tinha aluno que
# dispersa e volta. Descasamento treino/serving na unidade de observacao, nao numa feature,
# por isso escapou das auditorias. Contagens/tempos valem para DUR_REF min (escalam por dur/DUR_REF).
DUR_REF = 10.0     # = JANELA_MIN do Backend/app.py; mudar os dois JUNTOS

# O ZERO DO SIGMA: contra o que o serving compara.
# A regua do serving e feita so das questoes que o aluno ACERTOU (_baseline_na_sessao /
# _baseline_aluno): o zero pende para o engajado, mas nao puro (da para acertar disperso).
# Quanto pende sai de Bayes com os acertos do DTS (Chen et al., 2021: engajado 71,8%,
# desengajado 18,5%) sobre uma mistura tipica — derivado; se o artigo mudar, muda junto.
ESTUDO_TIPICO = {"engajado": 0.60, "distraido": 0.30, "muito_distraido": 0.10}
ACERTO_DTS = {"engajado": 0.718, "distraido": 0.185, "muito_distraido": 0.185}
_post = {e: ESTUDO_TIPICO[e] * ACERTO_DTS[e] for e in ESTADOS}
_tot = sum(_post.values())
MISTURA_HISTORICO = {e: round(v / _tot, 3) for e, v in _post.items()}

# Desloca DESVIO para o centro da mistura: derivado, nao escolhido a mao.
for _nome, _m in DESVIO.items():
    _centro = sum(_m[_e] * _p for _e, _p in MISTURA_HISTORICO.items())
    for _e in list(_m):
        _m[_e] = round(_m[_e] - _centro, 3)

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

def _perfil_mouse(aluno, ef, z=0.8, imovel=False):
    """(erratic, n) do trajeto BRUTO por estado — usado no baseline e na sessao."""
    if ef == "muito_distraido":
        return aluno["erratic_base"], random.randint(3, 10)
    if imovel:
        return aluno["erratic_base"], random.randint(4, 14)
    if ef == "distraido":
        return aluno["erratic_base"] + 0.32 * z, random.randint(30, 70)
    return aluno["erratic_base"] + random.gauss(0, 0.1), random.randint(30, 70)


def baseline_mouse(aluno):
    """Baseline de mouse do aluno: media/desvio na escala de comparacao (_esc) sobre a
    MISTURA_HISTORICO — a mesma que o serving ve ao filtrar por acerto."""
    fs = []
    for _ in range(8):
        ef = random.choices(list(MISTURA_HISTORICO), weights=list(MISTURA_HISTORICO.values()))[0]
        imovel = ef != "muito_distraido" and random.random() < 0.15
        er, n = _perfil_mouse(aluno, ef, imovel=imovel)
        fs.append(features_mouse(gerar_track(max(0.05, er), n)))
    base = {}
    for k in MOUSE_KEYS:
        vals = [_esc(f[k]) for f in fs]
        base[k] = (statistics.mean(vals), statistics.pstdev(vals))
    return base

# ---- geração de uma sessão ----
def gerar_aluno():
    return {"erratic_base": random.uniform(0.3, 1.0),
            # taxa de abandono real e assimetrica: quase todo mundo abandona pouco,
            # poucos abandonam muito. uniform(0,1) dava media 0,47 — implausivel.
            "distraibilidade": random.betavariate(1.6, 4.0)}

def gerar_sessao(estado, aluno, base_mouse):
    z = random.uniform(0.1, 1.5)                 # intensidade latente; perto de 0 = episódio fraco (parece engajado)
    dif = random.randint(1, 5)
    # Fronteira distraído↔muito borrada nos dois sentidos (8% e 5%), pra nada dar 100%:
    # ef gera as features, o rótulo continua sendo `estado`.
    ef = estado
    if estado == "muito_distraido" and random.random() < 0.08:
        ef = "distraido"
    elif estado == "distraido" and random.random() < 0.05:
        ef = "muito_distraido"

    # dur em torno da janela do serving; a cauda curta cobre o comeco de sessao.
    # hora/acum independem do rotulo, senao o modelo usaria o relogio como prova.
    dur = round(min(max(2.0, random.gauss(9.0, 2.6)), 12.0), 1)
    hora = min(23.9, max(7, random.gauss(17, 4)))
    acum = max(dur, random.gauss(53, 30))          # o dia inclui esta sessao
    fator = dur / DUR_REF

    # Fadiga (hora tardia + muito estudo acumulado) INTENSIFICA o episodio; nao
    # decide qual e. E o papel legitimo do contexto: modulador, nao evidencia.
    fadiga = 0.5 * min(1.0, max(0.0, (hora - 14) / 9)) + 0.5 * min(1.0, acum / 120)
    z *= 0.85 + 0.30 * fadiga

    f = {}
    # internas relativas geradas direto (sigma); z faz co-variar
    for nome, m in DESVIO.items():
        val = m[ef] * z + random.gauss(0, 0.8)
        if nome == "tempo_resposta_ms":
            val += 0.30 * (dif - 3)               # dificuldade -> mais lento que o normal
        f[nome] = round(val, 3)

    # PAPEL: resolve a conta no caderno/papel. Fica ocioso (mouse parado, aba visivel)
    # E concentrado. Sem esse contraexemplo o engajado nunca nasce com ocioso alto, e
    # o modelo trata ociosidade como prova de dispersao — em Exatas isso e o padrao.
    papel = ef == "engajado" and random.random() < 0.16
    if papel:
        f["tempo_ocioso_s"] = round(random.gauss(1.1, 0.4), 3)
        f["tempo_dwell_sem_responder_s"] = round(random.gauss(0.5, 0.3), 3)
        f["tempo_resposta_ms"] = round(random.gauss(0.6, 0.4), 3)

    # CHUTE RAPIDO: clicar qualquer coisa pra fechar a meta diaria. Responde MUITO
    # mais rapido que o normal E erra — desengajamento, nao concentracao. A tabela
    # DESVIO so modela ficar mais LENTO, entao o caso passava por engajado.
    chute = ef == "distraido" and random.random() < 0.15
    if chute:
        f["tempo_resposta_ms"] = round(random.gauss(-1.8, 0.5), 3)
        f["tempo_iniciacao_resposta_ms"] = round(random.gauss(-1.5, 0.5), 3)
        f["tempo_dwell_sem_responder_s"] = round(random.gauss(-1.1, 0.4), 3)
        f["tendencia_desempenho_sessao"] = round(random.gauss(-0.9, 0.4), 3)

    # contagens (Poisson), com efeito de dificuldade nos erros
    lam_l = CONTAGEM["contagem_lapsos_rt"][ef] * (0.6 + 0.4 * z) * fator
    if chute:
        lam_l *= 0.15                            # nao ha lapso: ele nem para pra pensar
    f["contagem_lapsos_rt"] = int(np.random.poisson(max(0.01, lam_l)))
    lam_e = CONTAGEM["erros_sem_offtask"][ef] * (0.7 + 0.15 * (dif - 3)) * fator
    if chute:
        lam_e *= 4.0                             # e o erro e a assinatura do chute
    f["erros_sem_offtask"] = int(np.random.poisson(max(0.01, lam_e)))

    # mouse: bruto -> features_mouse -> relativiza pelo baseline do aluno. LEITURA DENSA:
    # parte das presentes fica quase imovel (enunciado longo, hiperfoco); sem esse contraexemplo
    # o modelo aprende "mouse parado = ausente" — as externas e que separam leitor de ausente.
    if ef == "engajado":
        imovel = random.random() < 0.18          # leitura densa de enunciado longo
    elif ef == "distraido":
        imovel = not chute and random.random() < 0.12   # mente vagando de olhar parado
    else:
        imovel = False
    erratic, n = _perfil_mouse(aluno, ef, z, imovel)
    mf = features_mouse(gerar_track(max(0.05, erratic), n))
    for k in MOUSE_KEYS:
        mu, sd = base_mouse[k]
        f[k] = _sigma(_esc(mf[k]), mu, sd)

    # externas absolutas: muito_distraído = frequente+longo; presente (eng/dist) = blip ocasional.
    # Ausencias geradas UMA A UMA (soma e maximo coerentes). ~45% dos muito_distraido saem UMA
    # vez e ficam (abre a rede social e some); sem isso o modelo so aprende a CONTAR saidas.
    if ef == "muito_distraido":
        unica = random.random() < 0.45
        n_aus = max(1, int(np.random.poisson(1.2 if unica else 4 * fator)))
        frac = min(max(0.02, random.gauss(0.05, 0.025)) * (2.2 if unica else 1.0), 0.80)
        pesos = [random.random() + 0.05 for _ in range(n_aus)]
        if unica:
            pesos[0] += 4.0                      # uma ida domina o tempo fora
        soma = sum(pesos)
        ausencias = [frac * dur * 60 * w / soma for w in pesos]
        f["cliques_fora_area_estudo"] = int(np.random.poisson(3 * fator))
    else:
        n_aus = int(np.random.poisson(0.13 * fator))     # risco por minuto, nao por sessao
        ausencias = [random.uniform(2, 10) for _ in range(n_aus)]
        f["cliques_fora_area_estudo"] = int(np.random.poisson(0.10 * fator))
    f["mudancas_aba"] = len(ausencias)
    f["tempo_fora_foco_s"] = round(sum(ausencias), 1)
    f["maior_ausencia_unica_s"] = round(max(ausencias), 1) if ausencias else 0.0

    # Ritmo: leitura densa = MUITOS blocos medios; vagando/ausente = UM bloco longo.
    if ef == "muito_distraido":
        n_blocos = max(1, int(np.random.poisson(1.4 * fator)))
        maior_bloco = max(f["maior_ausencia_unica_s"], random.gauss(90, 40))
    elif imovel and ef == "distraido":
        n_blocos = max(1, int(np.random.poisson(1.8 * fator)))
        maior_bloco = max(20.0, random.gauss(120, 45))
    elif imovel:                                 # engajado lendo enunciado longo
        n_blocos = max(2, int(np.random.poisson(5.0 * fator)))
        maior_bloco = max(15.0, random.gauss(45, 18))
    else:                                        # mouse ativo
        n_blocos = int(np.random.poisson(0.6 * fator))
        maior_bloco = max(15.0, random.gauss(20, 6)) if n_blocos else 0.0
    f["maior_bloco_parado_s"] = round(min(maior_bloco, 0.9 * dur * 60), 1)
    f["n_blocos_parados"] = n_blocos
    f["taxa_abandono_sessao"] = round(min(1.0, max(0.0, aluno["distraibilidade"] + random.gauss(0, 0.1))), 3)

    # contexto absolutas
    f["nivel_dificuldade_atividade"] = dif
    f["duracao_janela_min"] = dur
    f["hora_do_dia"] = round(hora, 2)
    f["tempo_estudo_acumulado_dia_min"] = round(acum, 1)
    # A base so contem o que o serving consegue emitir: ele corta o sigma em SIGMA_TETO.
    for k in DESVIO:
        f[k] = round(max(-SIGMA_TETO, min(SIGMA_TETO, f[k])), 3)
    return f

MODELO_PATH = os.path.join(BASE, "models", "modelo_rf_v2.pkl")
SCALER_PATH = os.path.join(BASE, "artifacts", "scaler_v2.pkl")
METRICAS_PATH = os.path.join(BASE, "artifacts", "metricas_v2.json")
N_ALUNOS, POR_ESTADO = 40, 220


def construir_base(n_alunos=N_ALUNOS, por_estado=POR_ESTADO):
    """Base sintética v2 -> (X DataFrame nomeado, y array, grupos por aluno)."""
    alunos = [dict(a, base_mouse=baseline_mouse(a))
              for a in (gerar_aluno() for _ in range(n_alunos))]
    X, y, grupos = [], [], []
    for estado in ESTADOS:
        for _ in range(por_estado):
            gi = random.randrange(len(alunos))       # id do aluno (p/ CV agrupada)
            al = alunos[gi]
            feats = gerar_sessao(estado, al, al["base_mouse"])
            X.append([feats[k] for k in FEATURE_ORDER])
            y.append(ESTADOS.index(estado))
            grupos.append(gi)
    # DataFrame nomeado -> scaler/modelo guardam feature_names_in_ (valida a ordem no serving)
    return pd.DataFrame(X, columns=FEATURE_ORDER, dtype=float), np.array(y), np.array(grupos)


def _treinar_fold(Xtr, ytr):
    """Treina scaler + RF v2 do zero (usado na CV agrupada de avaliar.cv_agrupada)."""
    sc = StandardScaler().fit(Xtr)
    m = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, class_weight="balanced")
    m.fit(pd.DataFrame(sc.transform(Xtr), columns=FEATURE_ORDER), ytr)
    return m, sc


def treinar_e_salvar(X, y, grupos=None, X_real=None, y_real=None, peso_real=6.0):
    """Treina o RF v2 e salva os artefatos. Rótulos REAIS (probe), se vierem,
    entram no TREINO com peso maior e o TESTE passa a ser o real segregado.
    `grupos` (id do aluno) liga a CV agrupada (só na base pura sintética).
    Retorna (modelo, acc, rep, n_real_teste)."""
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    peso, n_real_teste = None, 0
    if X_real is not None and len(X_real):
        estratif = y_real if len(set(y_real)) > 1 and len(X_real) >= 6 else None
        Xr_tr, Xr_te, yr_tr, yr_te = train_test_split(
            X_real, y_real, test_size=0.3, random_state=42, stratify=estratif)
        n_sint = len(Xtr)
        Xtr = pd.concat([Xtr, Xr_tr], ignore_index=True)
        ytr = np.concatenate([ytr, yr_tr])
        peso = np.concatenate([np.ones(n_sint), np.full(len(Xr_tr), peso_real)])
        if len(Xr_te):                       # avalia no REAL segregado
            Xte, yte, n_real_teste = Xr_te, yr_te, len(Xr_te)

    scaler = StandardScaler().fit(Xtr)
    Xtr_s = pd.DataFrame(scaler.transform(Xtr), columns=FEATURE_ORDER)
    Xte_s = pd.DataFrame(scaler.transform(Xte), columns=FEATURE_ORDER)
    modelo = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, class_weight="balanced")
    modelo.fit(Xtr_s, ytr, sample_weight=peso)

    # acc + por classe + confusão + baseline + brier (calibração)
    rel = relatorio(yte, modelo.predict(Xte_s), ESTADOS, y_score=modelo.predict_proba(Xte_s))
    acc = rel["acuracia"]
    cv = None
    if grupos is not None and X_real is None:              # CV agrupada só na base pura
        try:
            cv = cv_agrupada(X, y, grupos, _treinar_fold)
        except Exception as e:
            cv = {"media": None, "desvio": None, "por_fold": [], "obs": f"CV falhou: {e}"}

    with open(MODELO_PATH, "wb") as fp: pickle.dump(modelo, fp)
    with open(SCALER_PATH, "wb") as fp: pickle.dump(scaler, fp)
    with open(METRICAS_PATH, "w", encoding="utf-8") as fp:
        json.dump({"versao": "v2", "acuracia": acc, "n": len(X),
                   "n_real": int(len(X_real)) if X_real is not None else 0,
                   "n_real_teste": n_real_teste, "feature_order": FEATURE_ORDER,
                   "cv_agrupada_por_aluno": cv, "holdout": rel}, fp, indent=2, ensure_ascii=False)
    return modelo, acc, rel["classification_report"], n_real_teste


if __name__ == "__main__":
    Xb, yb, gb = construir_base()
    modelo, acc, _, _ = treinar_e_salvar(Xb, yb, grupos=gb)
    m = json.load(open(METRICAS_PATH, encoding="utf-8"))
    cv = m.get("cv_agrupada_por_aluno") or {}
    print(f"holdout acuracia: {acc:.3f}  (alvo ~0,80-0,90)")
    if cv.get("media") is not None:
        folds = [round(a, 3) for a in cv["por_fold"]]
        print(f"CV agrupada por aluno: {cv['media']:.3f} +/- {cv['desvio']:.3f}  folds={folds}")
    print(f"baseline (chute majoritario): {m['holdout']['baseline_majoritario']:.3f}")
    if "brier" in m["holdout"]:
        print(f"brier (calibracao; 0=perfeito, so vale no real): {m['holdout']['brier']:.3f}")
    print("matriz de confusao (linha=real, col=previsto) ->", ESTADOS)
    for linha in m["holdout"]["matriz_confusao"]:
        print("  ", linha)
    print("top importancias:")
    for n, v in sorted(zip(FEATURE_ORDER, modelo.feature_importances_), key=lambda t: -t[1])[:8]:
        print(f"  {v*100:5.1f}%  {n}")
