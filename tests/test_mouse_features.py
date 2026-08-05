"""Testes da transformação mouse_track -> 4 features (Incremento B)."""
import pytest
from mouse_features import features_mouse, CHAVES


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
