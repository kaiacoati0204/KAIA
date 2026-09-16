"""Consentimento do responsável — quem é menor, quando a coleta pode acontecer, e o CPF."""
from datetime import date

import pytest

import consentimento as c

HOJE = date(2026, 9, 15)


def test_menor_conta_o_aniversario_do_dia():
    assert c.e_menor(date(2010, 9, 16), HOJE) is True       # faz 18 amanhã
    assert c.e_menor(date(2008, 9, 15), HOJE) is False      # fez 18 hoje
    assert c.e_menor(None, HOJE) is None                    # não sei ≠ é maior


def test_sem_aceite_do_responsavel_nao_ha_coleta_de_menor():
    menor = date(2011, 3, 2)
    assert c.coleta_permitida(menor, None, hoje=HOJE) is False
    assert c.coleta_permitida(menor, "pendente", hoje=HOJE) is False
    assert c.coleta_permitida(menor, "recusado", hoje=HOJE) is False
    assert c.coleta_permitida(menor, "aprovado", hoje=HOJE) is True
    assert c.coleta_permitida(date(2004, 1, 1), None, hoje=HOJE) is True     # maior de idade


def test_data_desconhecida_so_passa_fora_do_modo_estrito():
    """contas antigas/de teste não travam o dev; no beta com aluno real, estrito=True"""
    assert c.coleta_permitida(None, None, estrito=False, hoje=HOJE) is True
    assert c.coleta_permitida(None, None, estrito=True, hoje=HOJE) is False


def test_cpf_confere_os_digitos_verificadores():
    assert c.cpf_valido("529.982.247-25")
    assert not c.cpf_valido("529.982.247-26")
    assert not c.cpf_valido("111.111.111-11")
    assert not c.cpf_valido("")


def test_hash_de_cpf_exige_segredo_e_nao_devolve_o_cpf(monkeypatch):
    """sha256 puro de CPF quebra por força bruta — sem o segredo, é melhor falhar"""
    monkeypatch.delenv("KAIA_CPF_PEPPER", raising=False)
    with pytest.raises(RuntimeError):
        c.hash_cpf("529.982.247-25")
    monkeypatch.setenv("KAIA_CPF_PEPPER", "segredo-de-teste")
    h = c.hash_cpf("529.982.247-25")
    assert len(h) == 64 and "52998224725" not in h
    assert h == c.hash_cpf("52998224725")                   # pontuação não muda o hash
    monkeypatch.setenv("KAIA_CPF_PEPPER", "outro-segredo")
    assert h != c.hash_cpf("529.982.247-25")                # segredo diferente, hash diferente


def test_aceite_so_vale_com_nome_cpf_e_parentesco():
    assert c.validar_aceite("Maria Souza", "529.982.247-25", "mãe") == (True, None)
    assert c.validar_aceite("Ana", "529.982.247-25", "mãe")[0] is False
    assert c.validar_aceite("Maria Souza", "111.111.111-11", "mãe")[0] is False
    assert c.validar_aceite("Maria Souza", "529.982.247-25", "tio")[0] is False


def test_token_do_link_e_imprevisivel():
    tokens = {c.novo_token() for _ in range(50)}
    assert len(tokens) == 50 and all(len(t) >= 32 for t in tokens)
