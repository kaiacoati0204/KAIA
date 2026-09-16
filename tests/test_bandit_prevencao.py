"""Modelo 2 — probabilidades travadas, registro da probabilidade e recompensa por questão."""
import pytest

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


def test_aluno_sem_historico_fica_identico_ao_grupo():
    """é isso que faz personalizar não poder ser pior que o global"""
    b = bp.BanditPrevencao(semente=7)
    for _ in range(50):
        b.atualizar("pacote_foco", 1.0)
        b.atualizar("nada", 0.0)
    for braco in bp.BRACOS:
        ef, g = b._efetivo(braco, "aluno-novo"), b.params[braco]
        assert ef[0] / sum(ef) == pytest.approx(g[0] / sum(g), abs=1e-9)


def test_aluno_com_historico_proprio_se_afasta_do_grupo():
    """o grupo diz que pacote_foco funciona; para ESTE aluno não — e só ele muda"""
    b = bp.BanditPrevencao(semente=8)
    for _ in range(80):
        b.atualizar("pacote_foco", 1.0)          # grupo: pacote_foco ótimo
    grupo_antes = list(b.params["pacote_foco"])
    for _ in range(60):
        b.atualizar("pacote_foco", 0.0, aluno="ana")   # para a Ana, não

    a, be = b._efetivo("pacote_foco", "ana")
    media_ana = a / (a + be)
    media_grupo = b.params["pacote_foco"][0] / sum(b.params["pacote_foco"])
    assert media_ana < media_grupo - 0.2                       # a Ana puxou para baixo
    outro = b._efetivo("pacote_foco", "joao")
    assert outro[0] / sum(outro) == pytest.approx(media_grupo, abs=1e-9)   # ninguém mais mudou
    # o grupo também registrou: as rodadas ruins da Ana entram no contador de "errado" dele
    assert b.params["pacote_foco"][1] > grupo_antes[1]


def test_no_primeiro_dia_nao_finge_confianca_que_nao_existe():
    """grupo sem dado nenhum: a priori não pode valer 20 observações imaginárias"""
    b = bp.BanditPrevencao(semente=9)
    assert b._efetivo("nada", "qualquer") == (1.0, 1.0)


def test_personalizacao_sobrevive_ao_reinicio(tmp_path):
    caminho = tmp_path / "p.json"
    b = bp.BanditPrevencao(semente=10, params_path=caminho)
    b.atualizar("pausa_curta", 1.0, aluno="ana")
    novo = bp.BanditPrevencao(params_path=caminho)
    assert novo.params_aluno["ana"]["pausa_curta"] == [2.0, 1.0]
    assert novo.params["pausa_curta"] == [2.0, 1.0]
