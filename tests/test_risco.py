"""Modelo 1 — features sem vazamento, rótulo, regras de reserva e fallback."""
from datetime import datetime, timedelta, timezone

import pytest

import risco

T0 = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)


def _resp(min_, rt_ms, lim_s=40, acertou=True, nivel=3):
    return (T0 + timedelta(minutes=min_), "question_answer",
            {"tempo_resposta_ms": rt_ms, "limite_leitura_ms": lim_s, "acertou": acertou,
             "nivel_dificuldade": nivel})


def test_probe_nao_conta_como_evento_objetivo():
    """a recompensa do bandit usa evento_objetivo; se o probe entrasse aqui, o autorrelato
    voltaria a decidir o aprendizado"""
    probe = ("probe_atencao", {"estado": "muito_distraido"})
    assert risco.evento_autorrelato(*probe) and not risco.evento_objetivo(*probe)
    assert risco.evento_perda_foco(*probe)                          # mas vale como rótulo
    saida = ("tab_change", {"tempo_fora_foco_s": 45})
    assert risco.evento_objetivo(*saida) and not risco.evento_autorrelato(*saida)


def test_evento_perda_foco_segue_os_criterios_da_medicao():
    assert risco.evento_perda_foco("tab_change", {"tempo_fora_foco_s": 45})
    assert not risco.evento_perda_foco("tab_change", {"tempo_fora_foco_s": 12})          # curta
    assert not risco.evento_perda_foco("tab_change", {"tempo_fora_foco_s": 90, "interno": True})
    assert risco.evento_perda_foco("question_abandon", {})
    assert risco.evento_perda_foco("probe_atencao", {"estado": "distraido"})
    assert not risco.evento_perda_foco("probe_atencao", {"estado": "engajado"})


def test_features_nao_enxergam_o_futuro():
    evs = [_resp(1, 30000), _resp(2, 30000),
           (T0 + timedelta(minutes=5), "tab_change", {"tempo_fora_foco_s": 200})]
    f = risco.features_do_momento(evs, T0, T0 + timedelta(minutes=3))
    assert f["eventos_na_sessao"] == 0 and f["n_respondidas"] == 2


def test_features_rapidas_e_queda_de_acerto():
    evs = ([_resp(i, 30000, acertou=True) for i in range(5)]
           + [_resp(5 + i, 5000, acertou=False) for i in range(5)])          # 5 s num enunciado de 40 s
    f = risco.features_do_momento(evs, T0, T0 + timedelta(minutes=11), estudo_dia_min=100)
    assert f["frac_rapidas_recentes"] == 1.0
    assert f["queda_acerto_recente"] == 0.5
    assert f["estudo_dia_min"] == 100 and f["minutos_sessao"] == 11
    assert list(f) == risco.FEATURES_RISCO


def test_rotulo_futuro_so_dentro_do_horizonte():
    agora = T0 + timedelta(minutes=10)
    evs = [_resp(11, 30000), _resp(12, 30000), _resp(13, 30000),
           (T0 + timedelta(minutes=14), "question_abandon", {})]
    assert risco.rotulo_futuro(evs, agora) == 0                           # veio depois da 3ª resposta
    evs.insert(1, (T0 + timedelta(minutes=11, seconds=30), "desengajamento_regra", {}))
    assert risco.rotulo_futuro(evs, agora) == 1


def test_regras_ficam_entre_0_e_1_e_sobem_com_os_fatores():
    base = dict.fromkeys(risco.FEATURES_RISCO, 0.0)
    base["min_desde_ultimo_evento"] = 60.0
    assert risco.risco_por_regras(base) == 0.0
    cheio = dict(base, minutos_sessao=40, estudo_dia_min=120, frac_rapidas_recentes=0.6,
                 queda_acerto_recente=0.4, eventos_na_sessao=2, min_desde_ultimo_evento=5)
    assert risco.risco_por_regras(cheio) == 1.0


def test_sem_modelo_as_regras_decidem(tmp_path):
    assert risco.carregar_modelo(tmp_path / "nao_existe.pkl") is None
    f = dict.fromkeys(risco.FEATURES_RISCO, 0.0)
    f["minutos_sessao"] = 30
    assert risco.prever_risco(f, None) == (0.2, "regras")


def test_regras_somam_pontos_mesmo_com_valores_numpy():
    """numpy: True + True == True (OU logico). Sem int(), o escore ficava preso em 0 ou 0,2
    e as regras pareciam muito piores do que sao na comparacao contra o modelo."""
    np = pytest.importorskip("numpy")
    cheio = dict.fromkeys(risco.FEATURES_RISCO, np.float64(0.0))
    cheio.update(minutos_sessao=np.float64(40), estudo_dia_min=np.float64(120),
                 frac_rapidas_recentes=np.float64(0.6), queda_acerto_recente=np.float64(0.4),
                 eventos_na_sessao=np.float64(2), min_desde_ultimo_evento=np.float64(5))
    assert risco.risco_por_regras(cheio) == 1.0


def test_regra_por_lentidao_so_pega_o_lado_lento():
    """o plano pede para ir devagar; se o lado lento contasse na recompensa, pacote_foco
    seria punido por ter sido obedecido"""
    lento = ("desengajamento_regra", {"motivo": "acerto recente 20% e tempo lento demais (+3.1 sigma)"})
    rapido = ("desengajamento_regra", {"motivo": "acerto recente 20% e tempo rapido demais (-3.1 sigma)"})
    assert risco.regra_por_lentidao(*lento) and not risco.regra_por_lentidao(*rapido)
    # nos dois casos continua sendo evento para o RÓTULO do Modelo 1
    assert risco.evento_objetivo(*lento) and risco.evento_objetivo(*rapido)
    assert not risco.regra_por_lentidao("tab_change", {"tempo_fora_foco_s": 60})
