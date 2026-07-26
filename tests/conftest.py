"""Fixtures compartilhadas dos testes."""
import pytest

import app as app_mod


@pytest.fixture(autouse=True)
def _bypass_auth():
    """As rotas protegidas exigem JWT válido. Nos testes, trocamos a dependência
    usuario_autenticado por um stub (evita precisar de token real/rede)."""
    app_mod.app.dependency_overrides[app_mod.usuario_autenticado] = lambda: "test-user"
    yield
    app_mod.app.dependency_overrides.pop(app_mod.usuario_autenticado, None)
