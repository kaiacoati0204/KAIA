"""Testes unitários do Thompson Sampling (sem banco, sem rede)."""
from thompson import ThompsonSampling, INTERVENCOES


def _ts(tmp_path):
    return ThompsonSampling(params_path=tmp_path / "p.json", seed=42)


def test_elegibilidade_engajado(tmp_path):
    assert _ts(tmp_path).elegiveis("engajado", 5) == []   # engajado não intervém (poda)


def test_elegibilidade_distraido(tmp_path):
    # 90 min de estudo (>= 60) -> alerta_fadiga liberado. Conjunto-alvo do distraído.
    assert set(_ts(tmp_path).elegiveis("distraido", 90)) == {
        "auto_monitoramento", "micro_refoco", "checkpoint", "reancoragem", "alerta_fadiga"}


def test_alerta_fadiga_bloqueado(tmp_path):
    # pouco tempo de estudo no dia (< 60 min) -> alerta_fadiga bloqueado
    assert "alerta_fadiga" not in _ts(tmp_path).elegiveis("distraido", 20)


def test_update_alpha_beta(tmp_path):
    ts = _ts(tmp_path)
    ts.update("checkpoint", 1.0)
    assert ts.params["checkpoint"] == {"alpha": 2.0, "beta": 1.0}   # só alpha subiu
    ts.update("checkpoint", 0.0)
    assert ts.params["checkpoint"] == {"alpha": 2.0, "beta": 2.0}   # só beta subiu


def test_update_reward_neutro(tmp_path):
    ts = _ts(tmp_path)
    ts.update("auto_monitoramento", 0.5)
    assert ts.params["auto_monitoramento"] == {"alpha": 1.5, "beta": 1.5}   # ambos +0.5


def test_select_retorna_elegivel(tmp_path):
    escolha = _ts(tmp_path).select("distraido", 3)
    assert escolha in INTERVENCOES


def test_persistencia(tmp_path):
    ts = _ts(tmp_path)
    ts.update("pausa_ativa", 1.0)
    ts.update("pausa_ativa", 0.5)
    ts2 = ThompsonSampling(params_path=tmp_path / "p.json", seed=42)   # recarrega do disco
    assert ts2.params["pausa_ativa"] == ts.params["pausa_ativa"]


def test_muito_distraido(tmp_path):
    assert set(_ts(tmp_path).elegiveis("muito_distraido", 90)) == {
        "troca_atividade", "pausa_ativa", "alerta_fadiga"}
