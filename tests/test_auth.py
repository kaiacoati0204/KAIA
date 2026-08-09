"""Testes unitários da validação de token (auth.py) — sem rede, sem JWKS.

Cobrem o parse do header Bearer e o caminho 'token ausente -> 401', que roda
ANTES de qualquer chamada ao JWKS (logo é determinístico e offline). O caminho
de token inválido depende do JWKS (rede) e fica de fora de propósito.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from auth import _bearer, verificar_token


def _req(headers):
    return SimpleNamespace(headers=headers)


def test_bearer_extrai_token():
    assert _bearer(_req({"Authorization": "Bearer abc.def.ghi"})) == "abc.def.ghi"


def test_bearer_case_insensitive_no_esquema():
    assert _bearer(_req({"Authorization": "bearer xyz"})) == "xyz"


def test_bearer_sem_header():
    assert _bearer(_req({})) is None


def test_bearer_esquema_errado():
    assert _bearer(_req({"Authorization": "Basic zzz"})) is None


def test_verificar_token_ausente_401():
    with pytest.raises(HTTPException) as e:
        verificar_token(None)
    assert e.value.status_code == 401


def test_verificar_token_vazio_401():
    with pytest.raises(HTTPException) as e:
        verificar_token("")
    assert e.value.status_code == 401
