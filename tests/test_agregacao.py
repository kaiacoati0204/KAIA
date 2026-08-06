"""Testes unitários da agregação de features v2 (mock do banco)."""
import json
import pickle
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

import app as app_mod

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _limpa_cache():
    app_mod._BASELINE_CACHE.clear()   # baseline por aluno é cacheado -> isola os testes
    yield


class FakeConn:
    """Conn asyncpg falso: roteia a resposta por um trecho do SQL.

    Sem sessões passadas -> baseline em cold-start (internas = 0)."""
    def __init__(self, session_row, eventos, abandono, passadas=None, estudo_min=0):
        self._s, self._ev, self._ab = session_row, eventos, abandono
        self._passadas, self._estudo = passadas or [], estudo_min
        self.executed = []

    async def fetchrow(self, q, *a):
        return self._ab if "abandonadas" in q else self._s

    async def fetch(self, q, *a):
        if "session_events" in q:
            return self._ev
        return self._passadas          # baseline: sessões passadas encerradas

    async def fetchval(self, q, *a):
        if "extract(epoch" in q:
            return self._estudo
        if "user_id" in q:
            return (self._s or {}).get("user_id")
        return 0

    async def execute(self, q, *a):
        self.executed.append((q, a))
        return "OK"


def _ev(tipo, payload):
    return {"event_type": tipo, "payload": json.dumps(payload)}


async def test_externas_contadas_e_coldstart_zero():
    start = datetime.now(timezone.utc) - timedelta(minutes=20)
    eventos = ([_ev("tab_change", {"tempo_fora_foco_s": 30.0})]
               + [_ev("tab_change", {"tempo_fora_foco_s": 5.0}) for _ in range(2)]   # 3 tab_change
               + [_ev("click_outside", {}) for _ in range(4)]                        # 4 cliques
               + [_ev("question_answer", {"tempo_resposta_ms": 8000, "acertou": True,
                                          "nivel_dificuldade": 3, "mouse_track": []})])
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, eventos,
                    {"abandonadas": 0, "total": 1})
    feats = await app_mod.montar_features_sessao(conn, "sid")

    # externas: contagens brutas
    assert feats["mudancas_aba"] == 3
    assert feats["cliques_fora_area_estudo"] == 4
    assert abs(feats["tempo_fora_foco_s"] - 40.0) < 1e-6
    # cold-start (sem sessões passadas) -> todas as internas relativas = 0
    for k in app_mod.INTERNAS_RELATIVAS:
        assert feats[k] == 0.0
    assert feats["contagem_lapsos_rt"] == 0
    # contexto: nível vem da média das respostas
    assert feats["nivel_dificuldade_atividade"] == 3


async def test_sessao_sem_respostas_nao_quebra():
    start = datetime.now(timezone.utc)     # duração ~0 -> clamp evita divisão por zero
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, [],
                    {"abandonadas": 0, "total": 1})
    feats = await app_mod.montar_features_sessao(conn, "sid")   # não deve lançar
    assert feats["erros_sem_offtask"] == 0
    assert feats["nivel_dificuldade_atividade"] == app_mod.NIVEL_DIFICULDADE_PADRAO


async def test_features_ordem():
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, [],
                    {"abandonadas": 0, "total": 1})
    feats = await app_mod.montar_features_sessao(conn, "sid")
    scaler = pickle.load(open(ROOT / "ml" / "artifacts" / "scaler_v2.pkl", "rb"))
    assert list(feats.keys()) == app_mod.FEATURE_ORDER == list(scaler.feature_names_in_)
    assert len(app_mod.vetor_para_modelo(feats)) == 20


async def test_baseline_relativiza_internas():
    # >= MIN_SESSOES_BASELINE sessões passadas -> baseline construído (caminho de
    # relativização + contagem_lapsos_rt exercitados, ao contrário do cold-start).
    start = datetime.now(timezone.utc) - timedelta(minutes=15)
    eventos = [_ev("question_answer", {
        "tempo_resposta_ms": 5000 + i * 1500, "acertou": i % 2 == 0, "nivel_dificuldade": 2,
        "tempo_iniciacao_resposta_ms": 400, "tempo_ocioso_s": 3,
        "mouse_track": [[0, 0, 0], [100, 50, 20], [200, 90, 10], [300, 120, 60]]})
        for i in range(4)]
    passadas = [{"session_id": f"s{i}"} for i in range(app_mod.MIN_SESSOES_BASELINE)]
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, eventos,
                    {"abandonadas": 1, "total": 4}, passadas=passadas, estudo_min=75.0)
    feats = await app_mod.montar_features_sessao(conn, "sid")
    assert isinstance(feats["tempo_resposta_ms"], float)        # sigma, não bruto
    assert feats["contagem_lapsos_rt"] >= 0
    assert feats["erros_sem_offtask"] == 2                      # i=1,3 erraram
    assert feats["tempo_estudo_acumulado_dia_min"] == 75.0
    assert feats["taxa_abandono_sessao"] == 0.25
    assert list(feats.keys()) == app_mod.FEATURE_ORDER


async def test_baseline_cache_reusa():
    start = datetime.now(timezone.utc)
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, [], {"abandonadas": 0, "total": 1})
    b1 = await app_mod._baseline_aluno(conn, "u", "sid")
    b2 = await app_mod._baseline_aluno(conn, "u", "sid")   # 2ª chamada -> cache hit
    assert b1 is b2                                         # cold-start: None cacheado


async def test_capturar_probe_grava():
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    eventos = [_ev("question_answer", {"tempo_resposta_ms": 6000, "acertou": True,
                                       "nivel_dificuldade": 2, "mouse_track": []})]
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, eventos,
                    {"abandonadas": 0, "total": 1})
    await app_mod._capturar_probe(conn, "sid", {"estado": "distraido"})
    assert any("insert into probe_labels" in q for q, _ in conn.executed)


async def test_capturar_probe_estado_invalido_ignora():
    conn = FakeConn({"user_id": "u", "session_start_ts": datetime.now(timezone.utc)}, [],
                    {"abandonadas": 0, "total": 1})
    await app_mod._capturar_probe(conn, "sid", {"estado": "banana"})   # rótulo inválido
    assert conn.executed == []


def test_inclinacao():
    assert app_mod._inclinacao([]) == 0.0
    assert app_mod._inclinacao([1.0]) == 0.0
    assert app_mod._inclinacao([0.0, 1.0, 2.0]) > 0            # desempenho subindo
    assert app_mod._inclinacao([2.0, 1.0, 0.0]) < 0            # caindo


def test_internos_brutos_sem_resposta_none():
    assert app_mod._internos_brutos([("tab_change", {})]) is None


_MODELO = pickle.load(open(ROOT / "ml" / "models" / "modelo_rf_v2.pkl", "rb"))
_SCALER = pickle.load(open(ROOT / "ml" / "artifacts" / "scaler_v2.pkl", "rb"))


async def test_predizer_estado_ponta_a_ponta():
    # montar_features + scaler + modelo v2 de verdade (sem mock por cima).
    start = datetime.now(timezone.utc) - timedelta(minutes=12)
    eventos = ([_ev("question_answer", {"tempo_resposta_ms": 6000, "acertou": True,
                                        "nivel_dificuldade": 2, "mouse_track": []})]
               + [_ev("tab_change", {"tempo_fora_foco_s": 5.0})])
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, eventos,
                    {"abandonadas": 0, "total": 1})
    res = await app_mod.predizer_estado(_MODELO, _SCALER, conn, "sid")
    assert res["estado"] in {"engajado", "distraido", "muito_distraido"}
    assert 0.0 <= res["score"] <= 1.0
    assert set(res["feats"]) == set(app_mod.FEATURE_ORDER)


async def test_predizer_estado_sem_modelo():
    conn = FakeConn({"user_id": "u", "session_start_ts": datetime.now(timezone.utc)}, [],
                    {"abandonadas": 0, "total": 1})
    assert await app_mod.predizer_estado(None, None, conn, "sid") is None


async def test_predizer_estado_sessao_inexistente():
    conn = FakeConn(None, [], {"abandonadas": 0, "total": 1})   # sessão não existe
    assert await app_mod.predizer_estado(_MODELO, _SCALER, conn, "sid") is None


def test_internos_brutos_agrega():
    evs = [("question_answer", {"tempo_resposta_ms": 4000, "acertou": True, "nivel_dificuldade": 3,
                                "tempo_iniciacao_resposta_ms": 300, "tempo_ocioso_s": 2,
                                "tempo_dwell_sem_responder_s": 1.0, "mouse_track": []}),
           ("question_answer", {"tempo_resposta_ms": 8000, "acertou": False, "nivel_dificuldade": 3,
                                "tempo_iniciacao_resposta_ms": 500, "tempo_ocioso_s": 4,
                                "tempo_dwell_sem_responder_s": 3.0, "mouse_track": []})]
    raw = app_mod._internos_brutos(evs)
    assert raw["tempo_resposta_ms"] == 6000.0
    assert raw["tempo_dwell_sem_responder_s"] == 2.0     # média de 1.0 e 3.0
    assert raw["_erros"] == 1
    assert raw["_rts"] == [4000.0, 8000.0]
    assert raw["_niveis"] == [3, 3]
