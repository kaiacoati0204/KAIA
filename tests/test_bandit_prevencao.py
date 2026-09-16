"""Modelo 2 — probabilidades travadas, registro da probabilidade e recompensa por questão."""
import bandit_prevencao as bp


def test_probabilidades_ficam_travadas_mesmo_com_braco_dominante():
    b = bp.BanditPrevencao(semente=1)
    for _ in range(200):
        b.atualizar("pacote_foco", 1.0)
        b.atualizar("nada", 0.0)
        b.atualizar("pausa_curta", 0.0)
    p = b.probabilidades()
    assert abs(p.sum() - 1) < 1e-9
    assert p.min() >= bp.PROB_MIN - 1e-9 and p.max() <= bp.PROB_MAX + 1e-9


def test_escolha_devolve_a_probabilidade_usada():
    b = bp.BanditPrevencao(semente=2)
    braco, prob = b.escolher()
    assert braco in bp.BRACOS and bp.PROB_MIN - 1e-9 <= prob <= bp.PROB_MAX + 1e-9


def test_atualizar_ignora_rodada_sem_avaliacao():
    b = bp.BanditPrevencao()
    b.atualizar("nada", None)
    assert b.params["nada"] == [1.0, 1.0]
    b.atualizar("nada", 0.8)
    assert b.params["nada"] == [1.8, 1.2]


def test_recompensa_nao_premia_encurtar_nem_maratonar():
    """rodada curta e limpa perde da rodada completa; acima da meta a recompensa para de subir"""
    assert bp.recompensa_rodada(eventos_objetivos=1, respondidas=10, abandonou=False) == 0.8
    curta = bp.recompensa_rodada(eventos_objetivos=0, respondidas=4, abandonou=False)
    assert curta < bp.recompensa_rodada(eventos_objetivos=1, respondidas=10, abandonou=False)
    assert bp.recompensa_rodada(eventos_objetivos=0, respondidas=30, abandonou=False) == 1.0
    assert bp.recompensa_rodada(eventos_objetivos=0, respondidas=10, abandonou=True) == 0.0
    assert bp.recompensa_rodada(eventos_objetivos=0, respondidas=2, abandonou=False) is None


def test_o_que_aprendeu_sobrevive_ao_reinicio(tmp_path):
    """sem persistência o bandit voltava a Beta(1,1) a cada restart e nunca aprendia nada"""
    caminho = tmp_path / "params.json"
    b = bp.BanditPrevencao(semente=1, params_path=caminho)
    b.atualizar("pacote_foco", 1.0)
    b.atualizar("pacote_foco", 1.0)
    assert caminho.exists()                                   # atualizar já grava
    assert bp.BanditPrevencao(params_path=caminho).params["pacote_foco"] == [3.0, 1.0]


def test_arquivo_corrompido_nao_derruba_o_app(tmp_path):
    caminho = tmp_path / "params.json"
    caminho.write_text("{isso nao e json", encoding="utf-8")
    assert bp.BanditPrevencao(params_path=caminho).params["nada"] == [1.0, 1.0]


def test_reconstroi_do_banco_quando_o_disco_some(tmp_path):
    """no plano grátis do Render o disco some na hibernação; a verdade são os eventos"""
    b = bp.BanditPrevencao(semente=1)
    b.reconstruir({"pacote_foco": (8.0, 10), "nada": (3.0, 10)})
    assert b.params["pacote_foco"] == [9.0, 3.0]              # 1+8 e 1+(10-8)
    assert b.params["nada"] == [4.0, 8.0]
    assert b.params["pausa_curta"] == [1.0, 1.0]              # sem dado, segue na priori


def test_controle_tem_piso_maior_para_sobrar_comparacao():
    """com piso de 10% sobrariam ~7 pausas de controle num beta pequeno e nada seria comparável"""
    b = bp.BanditPrevencao(semente=4)
    for _ in range(300):                       # pacote_foco domina de longe
        b.atualizar("pacote_foco", 1.0)
        b.atualizar("nada", 0.0)
    p = b.probabilidades()
    i_nada = bp.BRACOS.index("nada")
    assert p[i_nada] >= bp.PISO_CONTROLE - 1e-9      # o controle não some
    assert p[bp.BRACOS.index("pacote_foco")] <= bp.PROB_MAX + 1e-9
    assert abs(p.sum() - 1) < 1e-9
