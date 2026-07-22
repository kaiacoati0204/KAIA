"""Testes unitários do Thompson Sampling (sem banco, sem rede)."""
from thompson import ThompsonSampling, INTERVENCOES


def _ts(tmp_path):
    return ThompsonSampling(params_path=tmp_path / "p.json", seed=42)


def test_elegibilidade_engajado(tmp_path):
    assert _ts(tmp_path).elegiveis("engajado", 5) == ["badge_foco"]


def test_elegibilidade_distraido(tmp_path):
    assert set(_ts(tmp_path).elegiveis("distraido", 3)) == {
        "nudge_refoco", "pausa_pomodoro", "mensagem_motivacional", "alerta_fadiga"}


def test_alerta_fadiga_bloqueado(tmp_path):
    assert "alerta_fadiga" not in _ts(tmp_path).elegiveis("distraido", 2)


def test_update_alpha_beta(tmp_path):
    ts = _ts(tmp_path)
    ts.update("nudge_refoco", 1.0)
    assert ts.params["nudge_refoco"] == {"alpha": 2.0, "beta": 1.0}   # só alpha subiu
    ts.update("nudge_refoco", 0.0)
    assert ts.params["nudge_refoco"] == {"alpha": 2.0, "beta": 2.0}   # só beta subiu


def test_update_reward_neutro(tmp_path):
    ts = _ts(tmp_path)
    ts.update("badge_foco", 0.5)
    assert ts.params["badge_foco"] == {"alpha": 1.5, "beta": 1.5}     # ambos +0.5


def test_select_retorna_elegivel(tmp_path):
    escolha = _ts(tmp_path).select("distraido", 3)
    assert escolha in INTERVENCOES


def test_persistencia(tmp_path):
    ts = _ts(tmp_path)
    ts.update("microlearning", 1.0)
    ts.update("microlearning", 0.5)
    ts2 = ThompsonSampling(params_path=tmp_path / "p.json", seed=42)   # recarrega do disco
    assert ts2.params["microlearning"] == ts.params["microlearning"]


def test_muito_distraido(tmp_path):
    assert set(_ts(tmp_path).elegiveis("muito_distraido", 3)) == {
        "troca_atividade", "pausa_ativa", "microlearning", "alerta_fadiga"}
