"""Fixtures compartilhadas dos testes."""
import subprocess
import sys
from pathlib import Path

import pytest

# O modelo v2 é regenerável (fora do git). Se faltar (CI limpo, clone novo),
# gera com seed fixa ANTES de qualquer teste importar/carregar o .pkl.
_ROOT = Path(__file__).resolve().parents[1]
if not ((_ROOT / "ml" / "artifacts" / "scaler_v2.pkl").exists()
        and (_ROOT / "ml" / "models" / "modelo_rf_v2.pkl").exists()):
    subprocess.run([sys.executable, str(_ROOT / "ml" / "gerar_base_v2.py")],
                   check=True, cwd=str(_ROOT))

import app as app_mod


@pytest.fixture(autouse=True)
def _bypass_auth():
    """As rotas protegidas exigem JWT válido. Nos testes, trocamos a dependência
    usuario_autenticado por um stub (evita precisar de token real/rede)."""
    app_mod.app.dependency_overrides[app_mod.usuario_autenticado] = lambda: "test-user"
    yield
    app_mod.app.dependency_overrides.pop(app_mod.usuario_autenticado, None)
