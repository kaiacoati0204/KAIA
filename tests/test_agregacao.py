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
        if "select ts from session_events" in q:
            # _inicio_janela pergunta os ts das ultimas respostas para esticar a janela.
            # Devolve poucos: a janela fica no tamanho nominal, sem esticar.
            return [{"ts": datetime.now(timezone.utc) - timedelta(minutes=1)}]
        if "from sessions s" in q:
            return self._passadas      # baseline entre-sessões, filtrado por matéria
        if "session_events" in q:
            return self._ev
        return self._passadas

    async def fetchval(self, q, *a):
        if "payload->>'materia'" in q:
            return "MAT"               # matéria da sessão atual (filtro do baseline)
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
    assert len(app_mod.vetor_para_modelo(feats)) == len(app_mod.FEATURE_ORDER)


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


# ==================================================== janela de leitura
async def test_janela_exclui_ausencia_antiga():
    """O defeito que isto corrige: as externas eram acumuladores sobre a sessão inteira
    (soma, máximo, contagem) e nunca desciam — 42% do peso do modelo travado depois de
    qualquer ausência longa. A janela só olha o passado recente."""
    start = datetime.now(timezone.utc) - timedelta(minutes=40)
    antigos = [_ev("tab_change", {"tempo_fora_foco_s": 360.0})]      # saiu 6 min, la atras
    recentes = [_ev("question_answer", {"tempo_resposta_ms": 21000, "acertou": True,
                                        "nivel_dificuldade": 3, "mouse_track": []})
                for _ in range(4)]

    class ConnJanela(FakeConn):
        """Filtra por ts como o Postgres faria: o `desde` chega como 2º parâmetro."""
        async def fetch(self, q, *a):
            if "select ts from session_events" in q:
                return [{"ts": datetime.now(timezone.utc) - timedelta(minutes=2)}]
            if "session_events" in q:
                return recentes if len(a) > 1 else antigos + recentes
            return self._passadas

    conn = ConnJanela({"user_id": "u", "session_start_ts": start},
                      antigos + recentes, {"abandonadas": 0, "total": 1})
    f = await app_mod.montar_features_sessao(conn, "sid")
    assert f["tempo_fora_foco_s"] == 0          # a ausencia ficou fora da janela
    assert f["maior_ausencia_unica_s"] == 0.0
    assert f["mudancas_aba"] == 0
    assert f["duracao_janela_min"] <= app_mod.JANELA_MIN + 0.1


async def test_janela_limitada_pelo_inicio_da_sessao():
    """Sessão de 2 min não pode reportar janela de 10 — é o que mantém o warm-up
    das intervenções funcionando."""
    start = datetime.now(timezone.utc) - timedelta(minutes=2)
    conn = FakeConn({"user_id": "u", "session_start_ts": start}, [],
                    {"abandonadas": 0, "total": 1})
    f = await app_mod.montar_features_sessao(conn, "sid")
    assert 1.5 <= f["duracao_janela_min"] <= 2.5


# ============================================ baseline dentro da sessão
def _resp(acertou, rt):
    return {"acertou": acertou, "tempo_resposta_ms": rt, "tempo_iniciacao_resposta_ms": 400,
            "tempo_ocioso_s": 4, "tempo_dwell_sem_responder_s": 2, "nivel_dificuldade": 3,
            "mouse_track": [[0, 0, 0], [9, 4, 700], [20, 11, 1500]]}


def test_baseline_na_sessao_precisa_de_acertos():
    """Errar não serve de régua de 'engajado' — pode ser justamente a dispersão."""
    evs = [("question_answer", _resp(False, 20000)) for _ in range(6)]
    assert app_mod._baseline_na_sessao(evs) is None


def test_baseline_na_sessao_forma_a_regua():
    evs = [("question_answer", _resp(True, rt)) for rt in (18000, 20000, 22000, 21000, 19000)]
    base = app_mod._baseline_na_sessao(evs)
    assert base is not None
    mu, sd = base["tempo_resposta_ms"]
    assert 18000 < mu < 22000 and sd > 0


def test_baseline_na_sessao_descarta_extremos():
    """Uma questão muito lenta no começo não pode virar a régua do aluno."""
    normais = [_resp(True, rt) for rt in (20000, 21000, 19000)]
    com_outlier = [("question_answer", p) for p in
                   ([_resp(True, 400000)] + normais + [_resp(True, 1000)])]
    base = app_mod._baseline_na_sessao(com_outlier)
    mu, _ = base["tempo_resposta_ms"]
    assert 18000 < mu < 23000        # os extremos (400s e 1s) ficaram de fora


# ================================================ travas do sigma
def test_sigma_tem_piso_no_desvio():
    """Régua feita de poucas respostas parecidas tem desvio quase zero. Sem piso,
    qualquer diferença vira sigma absurdo — foi visto em teste real: +182 sigma."""
    assert app_mod._sigma(95000, 20000, 400) <= app_mod.SIGMA_TETO


def test_sigma_respeita_o_teto_nos_dois_lados():
    assert app_mod._sigma(10 ** 9, 20000, 5000) == app_mod.SIGMA_TETO
    assert app_mod._sigma(-10 ** 9, 20000, 5000) == -app_mod.SIGMA_TETO


def test_sigma_normal_passa_intacto():
    """O caso comum não pode ser distorcido pelas travas."""
    assert abs(app_mod._sigma(25000, 20000, 5000) - 1.0) < 1e-6


async def test_regua_da_sessao_tem_prioridade_sobre_o_historico():
    """A régua da própria sessão vem primeiro: casa com a matéria por construção, e
    existe desde a primeira sessão. O histórico entra só quando ainda não há acertos
    suficientes na sessão atual."""
    start = datetime.now(timezone.utc) - timedelta(minutes=30)
    # 5 acertos ANTES da janela -> a régua da sessão se forma
    antes = [_ev("question_answer", {"tempo_resposta_ms": rt, "acertou": True,
                                     "nivel_dificuldade": 3, "mouse_track": []})
             for rt in (20000, 21000, 19000, 20500, 21500)]
    dentro = [_ev("question_answer", {"tempo_resposta_ms": 95000, "acertou": False,
                                      "nivel_dificuldade": 3, "mouse_track": []})]

    historico_absurdo = []   # se o histórico fosse usado, não haveria nada aqui

    class ConnPrioridade(FakeConn):
        async def fetch(self, q, *a):
            if "select ts from session_events" in q:
                return [{"ts": datetime.now(timezone.utc) - timedelta(minutes=2)}]
            if "from sessions s" in q:
                return historico_absurdo        # histórico VAZIO de propósito
            if "session_events" in q:
                return dentro if (len(a) > 1 and "ts >=" in q) else antes
            return historico_absurdo

    conn = ConnPrioridade({"user_id": "u", "session_start_ts": start},
                          antes + dentro, {"abandonadas": 0, "total": 1})
    f = await app_mod.montar_features_sessao(conn, "sid")
    # sem histórico nenhum, as internas ainda saem != 0 -> veio da régua da sessão
    assert f["tempo_resposta_ms"] != 0.0
    assert app_mod.leitura_confiavel(f) is True
