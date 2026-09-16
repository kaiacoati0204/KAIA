"""Testes da transformação mouse_track -> 4 features (Incremento B)."""
import pytest
from mouse_features import features_mouse, parado_apos_leitura, CHAVES


def test_vazio_ou_curto_da_zeros():
    for track in ([], [[0, 0, 0]]):
        f = features_mouse(track)
        assert set(f) == set(CHAVES)
        assert all(v == 0 or v == 0.0 for v in f.values())


def test_linha_reta_constante():
    # move 100px pra direita a cada 100ms → 1000 px/s, sem variar direção
    track = [[0, 0, 0], [100, 100, 0], [200, 200, 0], [300, 300, 0]]
    f = features_mouse(track)
    assert f["velocidade_mouse_media"] == pytest.approx(1000.0)
    assert f["variabilidade_velocidade_mouse"] == pytest.approx(0.0)  # ritmo constante
    assert f["entropia_trajetoria_mouse"] == pytest.approx(0.0)       # sempre a mesma direção
    assert f["flips_cursor_xy"] == 0                                   # sem reversões


def test_zigzag_gera_flips():
    # x sempre cresce (sem flip em x); y sobe/desce/sobe → 2 reversões em y
    track = [[0, 0, 0], [100, 100, 50], [200, 200, 0], [300, 300, 50]]
    f = features_mouse(track)
    assert f["flips_cursor_xy"] == 2
    assert f["entropia_trajetoria_mouse"] > 0                          # direções variadas


def test_ritmo_variavel_tem_variabilidade():
    # velocidades diferentes entre segmentos → variabilidade > 0
    track = [[0, 0, 0], [100, 100, 0], [150, 400, 0]]  # 1000 px/s, depois 6000 px/s
    f = features_mouse(track)
    assert f["variabilidade_velocidade_mouse"] > 0


def test_pula_dt_zero_sem_erro():
    # duas amostras no mesmo ms não podem quebrar (÷0)
    track = [[0, 0, 0], [0, 50, 50], [100, 100, 100]]
    f = features_mouse(track)          # não levanta exceção
    assert set(f) == set(CHAVES)


# ==== IMOBILIDADE COM A RÉGUA DA LEITURA ====
# O mesmo bloco parado é leitura ou dispersão dependendo de QUANDO cai. Sem enunciado,
# o corte fixo de 15 s trata os dois igual (Mills & D'Mello 2015).


def test_parado_durante_a_leitura_nao_conta():
    """enunciado de 60 s, aluno parado 40 s lendo e responde em 50 s: nada suspeito"""
    assert parado_apos_leitura([[0, 0, 0], [40000, 10, 10]], 50000, 60) == (0.0, 0.0)


def test_parado_depois_da_leitura_conta_so_o_excedente():
    """enunciado de 30 s; parado de 0 a 90 s. Só os 60 s posteriores à leitura contam."""
    seg, frac = parado_apos_leitura([[90000, 10, 10]], 90000, 30)
    assert seg == 60.0 and frac == 1.0          # todo o tempo pós-leitura ficou parado


def test_fracao_usa_so_o_tempo_pos_leitura():
    # enunciado 20 s, resposta em 120 s (100 s de janela suspeita); mexeu aos 70 s.
    # Blocos: 0-70 (contribui 50 s depois dos 20) e 70-120 (50 s) = 100 s de 100 s.
    seg, frac = parado_apos_leitura([[70000, 5, 5]], 120000, 20)
    assert seg == 100.0 and frac == 1.0
    # agora com movimento de verdade no meio: 30 amostras espalhadas → quase nada parado
    track = [[t, t % 7, t % 5] for t in range(0, 120000, 4000)]
    seg2, frac2 = parado_apos_leitura(track, 120000, 20)
    assert seg2 == 0.0 and frac2 == 0.0


def test_sem_enunciado_ou_resposta_rapida_devolve_zero():
    assert parado_apos_leitura([[10, 1, 1]], 50000, None) == (0.0, 0.0)
    assert parado_apos_leitura([[10, 1, 1]], 0, 30) == (0.0, 0.0)
    assert parado_apos_leitura([], 10000, 30) == (0.0, 0.0)      # respondeu antes da leitura
