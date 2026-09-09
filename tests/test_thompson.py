"""Testes unitários do Thompson Sampling (sem banco, sem rede)."""
from thompson import ThompsonSampling, INTERVENCOES


def _ts(tmp_path):
    return ThompsonSampling(params_path=tmp_path / "p.json", seed=42)


def test_elegibilidade_engajado(tmp_path):
    assert _ts(tmp_path).elegiveis("engajado", 5) == []   # engajado não intervém (poda)


def test_elegibilidade_distraido(tmp_path):
    # 120 min de estudo (>= 90) -> alerta_fadiga liberado. Conjunto-alvo do distraído.
    assert set(_ts(tmp_path).elegiveis("distraido", 120)) == {
        "auto_monitoramento", "micro_refoco", "checkpoint", "reancoragem", "alerta_fadiga"}


def test_alerta_fadiga_bloqueado(tmp_path):
    # pouco tempo de estudo no dia (< 90 min) -> alerta_fadiga bloqueado
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


def test_select_com_recencia(tmp_path):
    # penalizar o recém-usado não pode quebrar nem retornar algo fora dos elegíveis
    escolha = _ts(tmp_path).select("distraido", 120, evitar=["checkpoint"])
    assert escolha in INTERVENCOES


def test_persistencia(tmp_path):
    ts = _ts(tmp_path)
    ts.update("pausa_ativa", 1.0)
    ts.update("pausa_ativa", 0.5)
    ts2 = ThompsonSampling(params_path=tmp_path / "p.json", seed=42)   # recarrega do disco
    assert ts2.params["pausa_ativa"] == ts.params["pausa_ativa"]


def test_muito_distraido(tmp_path):
    assert set(_ts(tmp_path).elegiveis("muito_distraido", 120)) == {
        "troca_atividade", "pausa_ativa", "alerta_fadiga"}


def test_reconstruir_equivale_a_replay_dos_updates(tmp_path):
    """Reconstruir do banco tem de dar o MESMO estado que aplicar os updates um a um.

    É o que garante que o disco pode sumir (Render grátis não tem disco persistente)
    sem o bandit perder o que aprendeu."""
    passo_a_passo = _ts(tmp_path)
    for r in (1.0, 1.0, 0.0, 0.5):
        passo_a_passo.update("checkpoint", r)

    do_banco = ThompsonSampling(params_path=tmp_path / "outro.json", seed=42)
    do_banco.reconstruir({"checkpoint": (2.5, 4)})       # soma dos rewards, quantidade

    assert do_banco.params["checkpoint"] == passo_a_passo.params["checkpoint"]
    assert do_banco.params["checkpoint"]["alpha"] == 3.5   # 1 + 2.5
    assert do_banco.params["checkpoint"]["beta"] == 2.5    # 1 + (4 - 2.5)


def test_reconstruir_ignora_braco_aposentado(tmp_path):
    ts = _ts(tmp_path)
    ts.reconstruir({"nudge_refoco": (9.0, 9), "pausa_ativa": (1.0, 2)})
    assert "nudge_refoco" not in ts.params                # tipo antigo não ressuscita
    assert ts.params["pausa_ativa"]["alpha"] == 2.0


def test_reconstruir_nao_grava_em_disco(tmp_path):
    """O banco é a fonte da verdade; o arquivo é cache. Reconstruir não pode escrever."""
    alvo = tmp_path / "p.json"
    ts = ThompsonSampling(params_path=alvo, seed=42)
    ts.reconstruir({"checkpoint": (3.0, 4)})
    assert not alvo.exists()
