"""Testes de integração do endpoint /diagnose (httpx + ASGI, sem servidor real)."""
import pickle
from pathlib import Path

import httpx

import app as app_mod

ROOT = Path(__file__).resolve().parents[1]
MODELO = pickle.load(open(ROOT / "ml" / "models" / "modelo_rf_v2.pkl", "rb"))
SCALER = pickle.load(open(ROOT / "ml" / "artifacts" / "scaler_v2.pkl", "rb"))

# Vetor de 20 features v2 (perfil "distraído"): internas em sigma, externas/contexto brutas.
FEATS_VALIDAS = {
    "variabilidade_tempo_resposta": 0.8, "contagem_lapsos_rt": 2.0, "tempo_resposta_ms": 0.7,
    "tempo_iniciacao_resposta_ms": 0.6, "tempo_dwell_sem_responder_s": 0.0, "tempo_ocioso_s": 0.9,
    "velocidade_mouse_media": -0.2, "variabilidade_velocidade_mouse": 0.3, "flips_cursor_xy": 0.4,
    "entropia_trajetoria_mouse": 0.5, "erros_sem_offtask": 1.0, "tendencia_desempenho_sessao": -0.4,
    "mudancas_aba": 1.0, "tempo_fora_foco_s": 6.0, "cliques_fora_area_estudo": 1.0, "taxa_abandono_sessao": 0.3,
    "nivel_dificuldade_atividade": 3.0, "duracao_sessao_min": 20.0, "hora_do_dia": 21.0,
    "tempo_estudo_acumulado_dia_min": 50.0,
}


class _FakeConn:
    # dono da sessão = "test-user" (mesmo do stub de auth) -> passa o ownership.
    async def fetchval(self, q, *a): return "test-user"


class _Acq:
    async def __aenter__(self): return _FakeConn()
    async def __aexit__(self, *a): return False


class FakePool:
    def acquire(self): return _Acq()


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_mod.app), base_url="http://test")


def _prep(modelo=MODELO, scaler=SCALER):
    app_mod.app.state.pool = FakePool()
    app_mod.app.state.modelo = modelo
    app_mod.app.state.scaler = scaler
    # /diagnose exige JWT válido; nos testes trocamos a dependência por um stub.
    app_mod.app.dependency_overrides[app_mod.usuario_autenticado] = lambda: "test-user"


async def test_diagnose_sem_session_id():
    _prep(object(), object())
    async with _client() as c:
        r = await c.get("/diagnose")
    assert r.status_code == 422


async def test_diagnose_session_inexistente(monkeypatch):
    _prep(object(), object())
    async def fake(conn, sid):
        return None
    monkeypatch.setattr(app_mod, "montar_features_sessao", fake)
    async with _client() as c:
        r = await c.get("/diagnose", params={"session_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 404


async def test_diagnose_retorna_campos(monkeypatch):
    _prep()
    async def fake(conn, sid):
        return dict(FEATS_VALIDAS)
    monkeypatch.setattr(app_mod, "montar_features_sessao", fake)
    async with _client() as c:
        r = await c.get("/diagnose", params={"session_id": "abc"})
    assert r.status_code == 200
    body = r.json()
    for campo in ("session_id", "estado", "score", "timestamp"):
        assert campo in body


async def test_estado_valido(monkeypatch):
    _prep()
    async def fake(conn, sid):
        return dict(FEATS_VALIDAS)
    monkeypatch.setattr(app_mod, "montar_features_sessao", fake)
    async with _client() as c:
        r = await c.get("/diagnose", params={"session_id": "abc"})
    assert r.json()["estado"] in {"engajado", "distraido", "muito_distraido"}


async def test_diagnose_sessao_de_outro():
    _prep()
    # token de OUTRO usuário: a sessão (dono "test-user") não é dele -> 403.
    app_mod.app.dependency_overrides[app_mod.usuario_autenticado] = lambda: "outro-user"
    async with _client() as c:
        r = await c.get("/diagnose", params={"session_id": "abc"})
    assert r.status_code == 403


async def test_diagnose_sem_modelo():
    _prep(modelo=None, scaler=None)          # modelo não carregou -> 503
    async with _client() as c:
        r = await c.get("/diagnose", params={"session_id": "abc"})
    assert r.status_code == 503


async def test_diagnose_sem_banco():
    _prep()
    app_mod.app.state.pool = None            # sem pool -> 503 _SEM_BANCO
    async with _client() as c:
        r = await c.get("/diagnose", params={"session_id": "abc"})
    assert r.status_code == 503
