"""Testes unitários da validação de JWT (caminhos de rejeição, sem rede)."""
import pytest
from fastapi import HTTPException

import auth


def test_token_ausente():
    # Token vazio é rejeitado antes de qualquer rede (401), em qualquer ambiente.
    with pytest.raises(HTTPException) as e:
        auth.verificar_token("")
    assert e.value.status_code == 401


def test_token_invalido_rejeitado():
    # Um token-lixo nunca passa: 401 se o JWKS está configurado (dev), 503 se
    # não está (CI sem Supabase). O que importa é que NÃO autentica.
    with pytest.raises(HTTPException) as e:
        auth.verificar_token("nao.e.um.jwt")
    assert e.value.status_code in (401, 503)


def test_bearer_extrai_token():
    class _Req:
        headers = {"Authorization": "Bearer abc.def.ghi"}
    assert auth._bearer(_Req()) == "abc.def.ghi"

    class _Sem:
        headers = {}
    assert auth._bearer(_Sem()) is None
