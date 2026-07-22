"""Testes de integração do endpoint /diagnose (httpx + ASGI, sem servidor real)."""
import pickle
from pathlib import Path

import httpx

import app as app_mod

ROOT = Path(__file__).resolve().parents[1]
MODELO = pickle.load(open(ROOT / "ml" / "models" / "modelo_rf_v1.pkl", "rb"))
SCALER = pickle.load(open(ROOT / "ml" / "artifacts" / "scaler.pkl", "rb"))

# Vetor de 15 features (perfil "distraído") na ordem que o modelo espera.
FEATS_VALIDAS = {
    "tempo_resposta_ms": 6000.0, "velocidade_scroll_px_s": 250.0, "pausas_digitacao_s": 4.0,
    "acertos_questoes": 4.0, "nivel_dificuldade_atividade": 1.0, "duracao_sessao_min": 35.0,
    "historico_intervencoes": 2.0, "taxa_abandono_sessao": 0.4, "mudancas_aba": 6.0,
    "tempo_fora_foco_s": 90.0, "cliques_fora_area_estudo": 7.0, "sessoes_no_dia": 3.0,
    "hora_do_dia": 21.0, "produtividade": 0.11, "distracao_score": 4.2,
}


class _Acq:
    async def __aenter__(self): return object()
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
