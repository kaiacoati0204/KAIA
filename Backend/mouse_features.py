"""
Features de mouse: mouse_track bruto do front ([[dt_ms, x, y], ...]) -> 4 features do v2.

Função pura, chamada pela agregação. Guardar o trajeto bruto e computar aqui deixa
recalcular sem re-coletar.
"""
import math
from statistics import mean, pstdev

CHAVES = (
    "velocidade_mouse_media",
    "variabilidade_velocidade_mouse",
    "entropia_trajetoria_mouse",
    "flips_cursor_xy",
)
LIMIAR_BLOCO_S = 15.0          # abaixo disso e pausa de leitura normal, nao imobilidade

_ZEROS = {"velocidade_mouse_media": 0.0, "variabilidade_velocidade_mouse": 0.0,
          "entropia_trajetoria_mouse": 0.0, "flips_cursor_xy": 0}


def _flips(deltas):
    """Nº de reversões de sinal na sequência (ignora zeros)."""
    c, ultimo = 0, 0
    for d in deltas:
        s = (d > 0) - (d < 0)           # sinal: 1, -1 ou 0
        if s != 0:
            if ultimo != 0 and s != ultimo:
                c += 1
            ultimo = s
    return c


def features_mouse(track):
    """track = lista de amostras [dt_ms, x, y] de UMA questão.
    Retorna dict com as 4 features. Trajeto insuficiente (<2 amostras ou sem
    segmentos válidos) → zeros."""
    if not track or len(track) < 2:
        return dict(_ZEROS)

    speeds, angles, dxs, dys = [], [], [], []
    for (t0, x0, y0), (t1, x1, y1) in zip(track, track[1:]):
        dt = (t1 - t0) / 1000.0
        if dt <= 0:                      # amostras no mesmo ms → pula (evita ÷0)
            continue
        dx, dy = x1 - x0, y1 - y0
        speeds.append(math.hypot(dx, dy) / dt)
        angles.append(math.atan2(dy, dx))
        dxs.append(dx)
        dys.append(dy)

    if not speeds:
        return dict(_ZEROS)

    # entropia das direções: 8 faixas de 45° → Shannon (0 = dirigido, log2(8)=3 = espalhado)
    K = 8
    bins = [0] * K
    for a in angles:
        bins[int(((a + math.pi) / (2 * math.pi)) * K) % K] += 1
    total = sum(bins)
    entropia = -sum((b / total) * math.log2(b / total) for b in bins if b)

    return {
        "velocidade_mouse_media":        round(mean(speeds), 2),
        "variabilidade_velocidade_mouse": round(pstdev(speeds) if len(speeds) > 1 else 0.0, 2),
        "entropia_trajetoria_mouse":     round(entropia, 3),
        "flips_cursor_xy":               _flips(dxs) + _flips(dys),
    }


# ==== RITMO DA IMOBILIDADE ====
def _lacunas(track, dur_ms):
    """Vaos entre amostras de mousemove, em ms, dentro de [0, dur_ms].
    O listener so amostra em mousemove: o vao entre duas amostras JA E o tempo parado.
    Conta tambem da abertura ate a 1a amostra e da ultima ate a resposta."""
    marcos = [0.0]
    for a in (track or []):
        if a and a[0] is not None:
            t = float(a[0])
            if 0.0 <= t <= dur_ms:
                marcos.append(t)
    marcos.append(float(dur_ms))
    marcos.sort()
    return list(zip(marcos, marcos[1:]))


def blocos_parados(track, dur_ms, limiar_s=LIMIAR_BLOCO_S):
    """Blocos de imobilidade de UMA questão.
    Retorna (maior_bloco_s, n_blocos) contando so os >= limiar_s."""
    if dur_ms is None or dur_ms <= 0:
        return (0.0, 0)
    blocos = [(b - a) / 1000.0 for a, b in _lacunas(track, dur_ms)
              if (b - a) / 1000.0 >= limiar_s]
    return (round(max(blocos), 1) if blocos else 0.0, len(blocos))


def parado_apos_leitura(track, dur_ms, limite_leitura_s, limiar_s=LIMIAR_BLOCO_S):
    """Imobilidade que sobrou DEPOIS do tempo esperado de leitura daquele enunciado.

    Mouse parado significa coisas opostas conforme QUANDO acontece: nos primeiros segundos
    e leitura (on-task); muito depois do texto ter acabado, e suspeito. O corte fixo de
    LIMIAR_BLOCO_S nao sabe o tamanho do enunciado - este sabe.
    Mills & D'Mello 2015 detectaram mente vagando SEM sensor usando tempo de leitura +
    dificuldade do texto (kappa 0,207): e a melhor via sem sensor conhecida.

    limite_leitura_s vem em SEGUNDOS (o campo do front chama-se limite_leitura_ms mas
    guarda segundos: palavras/3,3 + 5).
    Retorna (segundos parados apos a janela, fracao do tempo pos-janela que ficou parado).
    """
    if not dur_ms or dur_ms <= 0 or not limite_leitura_s or limite_leitura_s <= 0:
        return (0.0, 0.0)
    janela_ms = float(limite_leitura_s) * 1000.0
    pos_ms = float(dur_ms) - janela_ms
    if pos_ms <= 0:                      # respondeu antes de terminar a leitura esperada
        return (0.0, 0.0)
    parado_ms = 0.0
    for a, b in _lacunas(track, dur_ms):
        if (b - a) / 1000.0 < limiar_s:  # vao curto e pausa normal, nao imobilidade
            continue
        parado_ms += max(0.0, b - max(a, janela_ms))
    return (round(parado_ms / 1000.0, 1), round(min(1.0, parado_ms / pos_ms), 3))

