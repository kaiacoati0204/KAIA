"""
Modelo 1 — risco de perda de foco nas próximas questões.

Prevê a chance de um evento OBJETIVO de perda de foco (saída da KaIA >= 30 s, questão marcada
pela regra DTS, abandono, probe "vagando/fora") nas próximas HORIZONTE_QUESTOES questões, usando
SÓ o que aconteceu antes do momento de decidir. Não tenta ler mente vagando.

A mesma função de features roda no gerador sintético, no treino com dado real e no servidor:
se cada lugar calculasse de um jeito, o modelo aprenderia uma régua e seria usado com outra.
Sem modelo treinado (ou se ele não vencer as regras), quem decide são as regras de reserva.
"""
import math
import pickle
from pathlib import Path
from statistics import mean, pstdev

HORIZONTE_QUESTOES = 3
FORA_EVENTO_S = 30.0         # mesmo corte da medição
RAPIDA_FRACAO = 0.3          # abaixo de 30% do tempo esperado de leitura = rápida demais
JANELA_RECENTE = 5           # últimas respostas que contam como "recente"
SEM_EVENTO_MIN = 60.0        # teto de "minutos desde o último evento" quando não houve nenhum

FEATURES_RISCO = [
    "minutos_sessao", "estudo_dia_min", "n_respondidas", "frac_rapidas_recentes",
    "irregularidade_recente", "queda_acerto_recente", "eventos_na_sessao",
    "min_desde_ultimo_evento", "dificuldade_recente",
]

MODELO_RISCO_PATH = Path(__file__).resolve().parent.parent / "ml" / "models" / "modelo_risco.pkl"


def evento_objetivo(tipo, payload):
    """Perda de foco MEDIDA, sem autorrelato: saiu da KaIA, abandonou ou a regra DTS marcou.

    Separado do probe de propósito: a recompensa do bandit só pode contar ISTO. Se ela contasse o
    probe, o bandit seria premiado por uma medida que depende do aluno declarar o próprio estado,
    e a parte improvável (ler estado interno) voltaria por dentro da função de recompensa.
    """
    if tipo == "tab_change":
        return (not payload.get("interno")
                and float(payload.get("tempo_fora_foco_s") or 0) >= FORA_EVENTO_S)
    return tipo in ("desengajamento_regra", "question_abandon")


def regra_por_lentidao(tipo, payload):
    """A regra DTS disparou pelo lado LENTO?

    Ela marca tempo fora do ritmo nos dois sentidos: rápido demais (chute) e lento demais.
    O plano se-então pede ao aluno, de propósito, que vá mais devagar ("releio antes de
    marcar") — então o braço pacote_foco empurra o aluno justo para o lado que a regra pune,
    e seria penalizado por ter sido obedecido. Na RECOMPENSA do bandit isso não pode contar.
    No rótulo do Modelo 1 continua contando: lá não existe braço para enviesar.
    """
    return tipo == "desengajamento_regra" and "lento" in str(payload.get("motivo", ""))


def evento_autorrelato(tipo, payload):
    """O aluno DISSE que estava vagando/fora. Serve de rótulo do Modelo 1, nunca de recompensa."""
    return tipo == "probe_atencao" and payload.get("estado") in ("distraido", "muito_distraido")


def evento_perda_foco(tipo, payload):
    """Objetivo OU autorrelato — rótulo do Modelo 1 e a feature de eventos na sessão. Aqui o probe
    entra: ele é insumo e alvo, não prêmio. Mesmos critérios da view eventos_perda_foco."""
    return evento_objetivo(tipo, payload) or evento_autorrelato(tipo, payload)


def _rapida(p):
    rt, lim = p.get("tempo_resposta_ms"), p.get("limite_leitura_ms")   # limite vem em SEGUNDOS
    return bool(rt and lim and rt > 0 and lim > 0 and rt < RAPIDA_FRACAO * lim * 1000)


def _tempo_relativo(p):
    rt, lim = p.get("tempo_resposta_ms"), p.get("limite_leitura_ms")
    return math.log(rt / (lim * 1000)) if rt and lim and rt > 0 and lim > 0 else None


def features_do_momento(eventos, inicio_sessao, agora, estudo_dia_min=0.0):
    """Features no instante `agora`. eventos = [(ts, tipo, payload)] da sessão; o que vier
    em `agora` ou depois é ignorado (sem vazamento do futuro)."""
    antes = [(ts, t, p) for ts, t, p in eventos if ts < agora]
    respostas = [p for _, t, p in antes if t == "question_answer"]
    recentes = respostas[-JANELA_RECENTE:]

    # rápidas demais e ritmo irregular antecedem desistência e mente vagando
    # Mills 2014: páginas lidas em < 5 s foi a feature dos 3 modelos de desistência;
    # Bastian & Sackur 2013: irregularidade do ritmo nas últimas 4-8 tentativas prevê o relato.
    rel = [r for r in map(_tempo_relativo, recentes) if r is not None]
    acertos = [1.0 if p.get("acertou") else 0.0 for p in respostas]
    acertos_rec = acertos[-JANELA_RECENTE:]
    niveis = [float(p["nivel_dificuldade"]) for p in recentes if p.get("nivel_dificuldade")]
    marcas = [ts for ts, t, p in antes if evento_perda_foco(t, p)]

    return {
        "minutos_sessao": round((agora - inicio_sessao).total_seconds() / 60.0, 2),
        "estudo_dia_min": float(estudo_dia_min or 0),
        "n_respondidas": len(respostas),
        "frac_rapidas_recentes": round(sum(map(_rapida, recentes)) / len(recentes), 3) if recentes else 0.0,
        "irregularidade_recente": round(pstdev(rel), 3) if len(rel) > 1 else 0.0,
        "queda_acerto_recente": round(mean(acertos) - mean(acertos_rec), 3) if acertos else 0.0,
        "eventos_na_sessao": len(marcas),
        "min_desde_ultimo_evento": (round(min(SEM_EVENTO_MIN, (agora - marcas[-1]).total_seconds() / 60.0), 2)
                                    if marcas else SEM_EVENTO_MIN),
        "dificuldade_recente": round(mean(niveis) - 3, 3) if niveis else 0.0,
    }


def rotulo_futuro(eventos, agora, horizonte=HORIZONTE_QUESTOES):
    """1 se houver perda de foco a partir de `agora` até a `horizonte`-ésima resposta seguinte
    (ou o fim da sessão, se ela acabar antes). É o rótulo do treino — nunca vira feature."""
    futuros = sorted((e for e in eventos if e[0] >= agora), key=lambda e: e[0])
    respostas = 0
    for _, t, p in futuros:
        if evento_perda_foco(t, p):
            return 1
        if t == "question_answer":
            respostas += 1
            if respostas >= horizonte:
                return 0
    return 0


# ==== REGRAS DE RESERVA ====
# decidem enquanto não há modelo que as vença
# Cada ponto é um fator com respaldo: tempo na tarefa (Farley 2013; meta-análise Zanesco 2025),
# cansaço no dia, rápidas demais (Mills 2014), queda de acerto (DTS) e evento recente.
def risco_por_regras(f):
    # int() em cada condicao: com valores vindos do numpy, True + True da True (soma de bool
    # no numpy e OU logico) e o escore ficava preso em 0 ou 0,2.
    pontos = (int(f["minutos_sessao"] >= 25)
              + int(f["estudo_dia_min"] >= 90)
              + int(f["frac_rapidas_recentes"] >= 0.4)
              + int(f["queda_acerto_recente"] >= 0.3)
              + int(f["eventos_na_sessao"] >= 1 and f["min_desde_ultimo_evento"] <= 10))
    return pontos / 5.0


def carregar_modelo(path=MODELO_RISCO_PATH):
    """{'modelo', 'features', 'fonte', ...} ou None se ainda não houver modelo treinado."""
    try:
        with open(path, "rb") as fp:
            art = pickle.load(fp)
    except (OSError, pickle.UnpicklingError, EOFError):
        return None
    return art if art.get("features") == FEATURES_RISCO else None   # feature mudou: modelo velho não serve


def prever_risco(f, artefato=None):
    """(risco 0..1, origem). Sem artefato válido, as regras decidem."""
    if artefato is None:
        return risco_por_regras(f), "regras"
    x = [[float(f[k]) for k in artefato["features"]]]
    return float(artefato["modelo"].predict_proba(x)[0][1]), artefato.get("fonte", "modelo")
