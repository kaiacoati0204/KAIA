"""Testes unitários das funções de agregação de features (mock do banco)."""
import json
import pickle
from datetime import datetime, timezone, timedelta
from pathlib import Path

import app as app_mod

ROOT = Path(__file__).resolve().parents[1]


class FakeConn:
    """Conn asyncpg falso: roteia a resposta por um trecho do SQL."""
    def __init__(self, session_row, eventos, abandono, iv=0, sess_count=1):
        self._s, self._ev, self._ab, self._iv, self._sc = (
            session_row, eventos, abandono, iv, sess_count)

    async def fetchrow(self, q, *a):
        return self._ab if "abandonadas" in q else self._s

    async def fetch(self, q, *a):
        return self._ev

    async def fetchval(self, q, *a):
        return self._iv if "interventions" in q else self._sc


def _ev(tipo, payload):
    return {"event_type": tipo, "payload": json.dumps(payload)}


async def test_distracao_score_formula():
    start = datetime.now(timezone.utc) - timedelta(minutes=30)
    eventos = ([_ev("tab_change", {"tempo_fora_foco_s": 120.0})]
               + [_ev("tab_change", {"tempo_fora_foco_s": 0.0}) for _ in range(4)]  # 5 tab_change
               + [_ev("click_outside", {}) for _ in range(3)])                       # 3 cliques
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, eventos,
                    {"abandonadas": 0, "total": 1})
    feats = await app_mod.montar_features_sessao(conn, "sid")
    tff_norm = min(max((120.0 - app_mod.TFF_MIN) / (app_mod.TFF_MAX - app_mod.TFF_MIN), 0.0), 1.0)
    esperado = 5 * 0.4 + 3 * 0.3 + tff_norm * 0.3
    assert feats["mudancas_aba"] == 5 and feats["cliques_fora_area_estudo"] == 3
    assert abs(feats["tempo_fora_foco_s"] - 120.0) < 1e-9
    assert abs(feats["distracao_score"] - esperado) < 1e-9


async def test_produtividade_zero_divisao():
    start = datetime.now(timezone.utc)   # duração ~0 -> clamp (1e-6) evita divisão por zero
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, [],
                    {"abandonadas": 0, "total": 1})
    feats = await app_mod.montar_features_sessao(conn, "sid")   # não deve lançar
    assert feats["produtividade"] == 0.0


async def test_features_ordem():
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, [],
                    {"abandonadas": 0, "total": 1})
    feats = await app_mod.montar_features_sessao(conn, "sid")
    scaler = pickle.load(open(ROOT / "ml" / "artifacts" / "scaler.pkl", "rb"))
    assert list(feats.keys()) == app_mod.FEATURE_ORDER == list(scaler.feature_names_in_)
    assert len(app_mod.vetor_para_modelo(feats)) == 15
