"""
Features de mouse (Incremento B): transforma o mouse_track bruto capturado no
front — [[dt_ms, x, y], ...] — nas 4 features do modelo v2.

Função pura (sem estado, sem I/O): é chamada pela agregação (Incremento C) e
testável isoladamente. Guardar o trajeto bruto e computar aqui deixa recalcular
sem re-coletar.
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
def blocos_parados(track, dur_ms, limiar_s=LIMIAR_BLOCO_S):
    """Blocos de imobilidade de UMA questão a partir dos buracos do trajeto.
    O listener só amostra em mousemove: o vão entre duas amostras JA E o tempo
    parado. Conta tambem da abertura ate a 1a amostra e da ultima ate a resposta.
    Retorna (maior_bloco_s, n_blocos) contando so os >= limiar_s."""
    if dur_ms is None or dur_ms <= 0:
        return (0.0, 0)
    marcos = [0.0]
    for a in (track or []):
        if a and a[0] is not None:
            t = float(a[0])
            if 0.0 <= t <= dur_ms:
                marcos.append(t)
    marcos.append(float(dur_ms))
    marcos.sort()
    blocos = [(b - a) / 1000.0 for a, b in zip(marcos, marcos[1:]) if (b - a) / 1000.0 >= limiar_s]
    return (round(max(blocos), 1) if blocos else 0.0, len(blocos))

