"""
Cobertura ampla do app.py: helpers puros, rotas Gemini (mock), funções de
agregação/intervenção (mock do banco), guardas 'sem banco' e happy-paths via
httpx/ASGI. Sem rede e sem Supabase real.
"""
import json
from datetime import datetime, date, timezone, timedelta
from types import SimpleNamespace

import httpx
import pytest

import app as app_mod


# --------------------------------------------------------------------------- fakes
def _match(router, q, default=None):
    if callable(router):
        return router(q)
    if isinstance(router, dict):
        for k, v in router.items():
            if k in q:
                return v
        return default
    return router if router is not None else default


class FakeConn:
    """Conn asyncpg falso: roteia respostas por trecho do SQL e grava execute()."""
    def __init__(self, fetchrow=None, fetch=None, fetchval=None, execute="OK"):
        self.r_row, self.r_fetch, self.r_val, self.r_exec = fetchrow, fetch, fetchval, execute
        self.executed = []

    def transaction(self):
        class _Tx:
            async def __aenter__(s): return None
            async def __aexit__(s, *a): return False
        return _Tx()

    async def fetchrow(self, q, *a): return _match(self.r_row, q)
    async def fetch(self, q, *a): return _match(self.r_fetch, q, [])
    async def fetchval(self, q, *a): return _match(self.r_val, q, 0)

    async def execute(self, q, *a):
        self.executed.append((q, a))
        return _match(self.r_exec, q, "OK")


class FakePool:
    def __init__(self, conn):
        self._c = conn

    def acquire(self):
        c = self._c
        class _Acq:
            async def __aenter__(s): return c
            async def __aexit__(s, *a): return False
        return _Acq()


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_mod.app), base_url="http://test")


def _set_state(pool=None, thompson=None, modelo=None, scaler=None):
    app_mod.app.state.pool = pool
    app_mod.app.state.thompson = thompson
    app_mod.app.state.modelo = modelo
    app_mod.app.state.scaler = scaler


# ============================================================ helpers puros
def test_extrair_json_cru():
    assert app_mod.extrair_json('{"a": 1}') == {"a": 1}


def test_extrair_json_com_cercas():
    assert app_mod.extrair_json('```json\n[1, 2, 3]\n```') == [1, 2, 3]


def test_montar_prompt_com_e_sem_hobbies():
    assert "Futebol" in app_mod.montar_prompt("q", ["Futebol"])
    assert "nenhum hobby informado" in app_mod.montar_prompt("q", [])


def test_to_date():
    assert app_mod._to_date("2026-07-19") == app_mod.date(2026, 7, 19)
    assert app_mod._to_date("") is None
    assert app_mod._to_date("data-ruim") is None


def test_tendencia():
    assert app_mod._tendencia([1]) == "sem_dados"
    assert app_mod._tendencia([5, 5, 5, 5]) == "estavel"
    assert app_mod._tendencia([1, 2, 3, 4], "sobe") == "melhorando"
    assert app_mod._tendencia([4, 3, 2, 1], "sobe") == "piorando"
    assert app_mod._tendencia([4, 3, 2, 1], "desce") == "melhorando"


def test_analise_regras_faixas():
    assert "ótima" in app_mod._analise_regras({"atencao": 80}, [])[0]
    assert "melhorar" in app_mod._analise_regras({"atencao": 60}, [])[0]
    assert "baixa" in app_mod._analise_regras({"atencao": 30}, [])[0]
    frases = app_mod._analise_regras(
        {"atencao": 80},
        [{"materia": "MAT", "acerto": 90}, {"materia": "HIS", "acerto": 40}],
    )
    assert any("MAT" in f for f in frases) and any("HIS" in f for f in frases)


def test_status_e_distribuicao():
    assert app_mod._status_atencao(None) is None
    assert app_mod._status_atencao(0.3) == "risco"
    assert app_mod._status_atencao(0.6) == "atencao"
    assert app_mod._status_atencao(0.9) == "bem"
    d = app_mod._distribuicao_status([0.3, 0.6, 0.9, None])
    assert d == {"bem": 1, "atencao": 1, "risco": 1}


def test_turma_rotulo():
    assert app_mod._turma_rotulo(3, "manhã") == "3º ano · manhã"
    assert app_mod._turma_rotulo(None, "x") == "—"


def test_demo_aluno():
    demo = app_mod._demo_aluno("x@y.com")
    assert demo["demo"] is True and len(demo["series"]) == 10
    assert demo["resumo"]["dias_com_dados"] == 10


def test_vetor_para_modelo_ordena():
    feats = {n: float(i) for i, n in enumerate(app_mod.FEATURE_ORDER)}
    assert app_mod.vetor_para_modelo(feats) == [float(i) for i in range(15)]


# ============================================================ rotas Gemini (mock)
async def test_perguntar_vazio():
    async with _client() as c:
        r = await c.post("/perguntar", json={"pergunta": "  "})
    assert r.status_code == 400


async def test_perguntar_ok(monkeypatch):
    monkeypatch.setattr(app_mod, "chamar_gemini", lambda p: "resposta X")
    async with _client() as c:
        r = await c.post("/perguntar", json={"pergunta": "oi", "hobbies": ["RPG"]})
    assert r.status_code == 200 and r.json()["resposta"] == "resposta X"


async def test_perguntar_erro(monkeypatch):
    def boom(p): raise RuntimeError("falhou")
    monkeypatch.setattr(app_mod, "chamar_gemini", boom)
    async with _client() as c:
        r = await c.post("/perguntar", json={"pergunta": "oi"})
    assert r.status_code == 502


async def test_gerar_questao_ok(monkeypatch):
    questao = {"q": "?", "opts": ["a", "b", "c", "d", "e"], "ans": 0}
    monkeypatch.setattr(app_mod, "chamar_gemini", lambda p: json.dumps(questao))
    async with _client() as c:
        r = await c.post("/gerar-questao", json={"materia": "MAT", "tema": "t"})
    body = r.json()
    assert r.status_code == 200
    assert len(body["porque_erradas"]) == 5 and body["explicacao"] == ""  # normalizado


async def test_gerar_questao_erro(monkeypatch):
    def boom(p): raise RuntimeError("x")
    monkeypatch.setattr(app_mod, "chamar_gemini", boom)
    async with _client() as c:
        r = await c.post("/gerar-questao", json={"materia": "MAT", "tema": "t"})
    assert r.status_code == 502


# ============================================================ guardas 'sem banco'
@pytest.mark.parametrize("metodo,rota,kwargs", [
    ("get", "/anotacoes?aluno_id=a&tema=t", {}),
    ("put", "/anotacoes", {"json": {"aluno_id": "a", "tema": "t", "elementos": []}}),
    ("get", "/perfil/estatisticas?aluno_id=a", {}),
    ("get", "/intervencao/pendente?session_id=s", {}),
    ("post", "/intervencao/feedback",
     {"json": {"session_id": "s", "intervention_type": "nudge_refoco", "reward": 1.0}}),
    ("post", "/sessions", {"json": {"user_id": "u"}}),
    ("post", "/sessions/abc/end", {}),
    ("post", "/events", {"json": {"session_id": "s", "event_type": "tab_change", "payload": {}}}),
    ("post", "/perfil", {"json": {"user_id": "u"}}),
    ("post", "/seed/aluno-teste", {}),
    ("get", "/perfil?email=a@b.com", {}),
    ("get", "/responsavel/painel?email=a@b.com", {}),
])
async def test_guarda_sem_banco(metodo, rota, kwargs):
    _set_state(pool=None)
    async with _client() as c:
        r = await getattr(c, metodo)(rota, **kwargs)
    assert r.status_code == 503


async def test_responsavel_aluno_demo_sem_banco():
    _set_state(pool=None)
    async with _client() as c:
        r = await c.get("/responsavel/aluno", params={"email": "x@y.com"})
    assert r.status_code == 200 and r.json()["demo"] is True


async def test_dados_grafico_demo_sem_banco():
    _set_state(pool=None)
    async with _client() as c:
        r = await c.get("/api/dados-grafico")
    assert r.status_code == 200 and "labels" in r.json()


async def test_health():
    async with _client() as c:
        r = await c.get("/")
    assert r.status_code == 200 and r.json()["status"]


# ============================================================ happy-paths (mock pool)
async def test_sessions_ok():
    conn = FakeConn(fetchrow={"insert into sessions": {"session_id": "s1", "user_id": "u1"}})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/sessions", json={"user_id": "u1"})
    assert r.status_code == 200 and r.json()["session_id"] == "s1"


async def test_sessions_end_ok():
    ini = datetime.now(timezone.utc) - timedelta(minutes=5)
    fim = datetime.now(timezone.utc)
    conn = FakeConn(fetchrow={"update sessions": {"session_start_ts": ini, "session_end_ts": fim}})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/sessions/abc/end")
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_sessions_end_ignorado():
    conn = FakeConn(fetchrow={"update sessions": None})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/sessions/abc/end")
    assert r.json()["status"] == "ignorado"


async def test_events_ok():
    conn = FakeConn(fetchrow={"insert into session_events": {"event_id": "e1"}})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/events", json={"session_id": "s", "event_type": "tab_change", "payload": {}})
    assert r.status_code == 200 and r.json()["event_id"] == "e1"


async def test_perfil_post_sem_user_id():
    _set_state(pool=None)
    async with _client() as c:
        r = await c.post("/perfil", json={})
    assert r.status_code == 400


async def test_perfil_post_ok():
    conn = FakeConn(execute="INSERT 0 1")
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/perfil", json={"user_id": "11111111-1111-1111-1111-111111111111",
                                          "perfil": {"email": "a@b.com", "hobbies": ["X"]}})
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_get_perfil_ok():
    row = {"user_id": "u1", "email": "a@b.com", "nome": "Ana", "role": "aluno",
           "escola_id": None, "turma_id": None, "hobbies": '["X"]'}
    conn = FakeConn(fetchrow={"FROM perfis": row})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/perfil", params={"email": "a@b.com"})
    assert r.status_code == 200 and r.json()["role"] == "aluno" and r.json()["hobbies"] == ["X"]


async def test_get_perfil_404():
    conn = FakeConn(fetchrow={"FROM perfis": None})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/perfil", params={"email": "nao@existe.com"})
    assert r.status_code == 404


async def test_intervencao_pendente_ok():
    row = {"intervention_id": "iv1", "intervention_type": "nudge_refoco",
           "triggered_at": datetime.now(timezone.utc)}
    conn = FakeConn(fetchrow={"from interventions": row})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/intervencao/pendente", params={"session_id": "s"})
    assert r.json()["pendente"]["intervention_type"] == "nudge_refoco"


async def test_intervencao_pendente_vazio():
    conn = FakeConn(fetchrow={"from interventions": None})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/intervencao/pendente", params={"session_id": "s"})
    assert r.json()["pendente"] is None


async def test_intervencao_feedback_tipo_invalido():
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.post("/intervencao/feedback",
                         json={"session_id": "s", "intervention_type": "xxx", "reward": 1.0})
    assert r.status_code == 400


async def test_intervencao_feedback_ok():
    conn = FakeConn(fetchrow={"update interventions": {"intervention_id": "iv1"}})
    up = []
    thompson = SimpleNamespace(update=lambda t, r: up.append((t, r)))
    _set_state(pool=FakePool(conn), thompson=thompson)
    async with _client() as c:
        r = await c.post("/intervencao/feedback",
                         json={"session_id": "s", "intervention_type": "nudge_refoco", "reward": 1.0})
    assert r.status_code == 200 and r.json()["reward"] == 1.0
    assert up == [("nudge_refoco", 1.0)]   # bandit atualizado


# ============================================================ agregação/intervenção (direto)
async def test_agregar_features_grava():
    start = datetime.now(timezone.utc)
    eventos = [
        {"event_type": "tab_change", "payload": json.dumps({"tempo_fora_foco_s": 10})},
        {"event_type": "click_outside", "payload": json.dumps({})},
        {"event_type": "question_answer", "payload": json.dumps({"acertou": True, "tempo_resposta_ms": 3000})},
    ]
    conn = FakeConn(
        fetchrow={"session_start_ts from sessions": {"session_start_ts": start},
                  "event_type = 'session_start'": None},
        fetch={"from session_events": eventos},
    )
    await app_mod.agregar_features(FakePool(conn), "sid")
    assert any("insert into session_features" in q for q, _ in conn.executed)


async def test_agregar_features_sessao_inexistente():
    conn = FakeConn(fetchrow={"session_start_ts from sessions": None})
    await app_mod.agregar_features(FakePool(conn), "sid")   # não deve gravar
    assert conn.executed == []


async def test_encerrar_sessoes_ociosas_sem_banco():
    fake_app = SimpleNamespace(state=SimpleNamespace(pool=None))
    await app_mod.encerrar_sessoes_ociosas(fake_app)   # não lança


async def test_encerrar_sessoes_ociosas_fecha():
    conn = FakeConn(execute="UPDATE 2")
    fake_app = SimpleNamespace(state=SimpleNamespace(pool=FakePool(conn)))
    await app_mod.encerrar_sessoes_ociosas(fake_app)   # loga 2 fechadas


async def test_job_agregacao(monkeypatch):
    chamadas = {"agg": 0, "int": 0}
    async def fake_agg(pool, sid): chamadas["agg"] += 1
    async def fake_int(app, sid): chamadas["int"] += 1
    monkeypatch.setattr(app_mod, "agregar_features", fake_agg)
    monkeypatch.setattr(app_mod, "rodar_intervencao", fake_int)
    conn = FakeConn(fetch={"from session_events": [{"session_id": "s1"}, {"session_id": "s2"}]})
    fake_app = SimpleNamespace(state=SimpleNamespace(pool=FakePool(conn)))
    await app_mod.job_agregacao(fake_app)
    assert chamadas == {"agg": 2, "int": 2}


async def test_rodar_intervencao_sem_thompson():
    fake_app = SimpleNamespace(state=SimpleNamespace(thompson=None, modelo=1, scaler=1))
    await app_mod.rodar_intervencao(fake_app, "sid")   # retorna cedo, sem erro


async def test_rodar_intervencao_engajado(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "engajado", "score": 0.9, "feats": {"sessoes_no_dia": 1}}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    conn = FakeConn()
    thompson = SimpleNamespace(select=lambda e, s: "nudge_refoco")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert conn.executed == []   # engajado não intervém


async def test_rodar_intervencao_dispara(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.9, "feats": {"sessoes_no_dia": 3}}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}})
    thompson = SimpleNamespace(select=lambda e, s: "nudge_refoco")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert any("insert into interventions" in q for q, _ in conn.executed)


async def test_rodar_intervencao_cooldown(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.9, "feats": {"sessoes_no_dia": 3}}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    agora = datetime.now(timezone.utc)
    conn = FakeConn(fetchrow={"from interventions": {"n": 1, "ultima": agora}})  # recém-disparada
    thompson = SimpleNamespace(select=lambda e, s: "nudge_refoco")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert conn.executed == []   # cooldown bloqueia


# ============================================================ dashboard offline (base sintética)
def test_dashboard_offline_base_sintetica():
    resultado = app_mod._dashboard_offline()   # lê o xlsx real -> _agregar_base_sintetica
    assert resultado is not None


# ============================================================ /temas (Gemini + cache)
async def test_temas_cache_hit():
    conn = FakeConn(fetchrow={"from temas_cache": {"temas": '["Álgebra", "Geometria"]'}})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/temas", json={"materia": "MAT"})
    assert r.status_code == 200 and r.json()["fonte"] == "cache"


async def test_temas_ia_sem_cache(monkeypatch):
    monkeypatch.setattr(app_mod, "chamar_gemini", lambda p: '["T1", "T2", "T3"]')
    _set_state(pool=None)   # sem cache -> chama a IA
    async with _client() as c:
        r = await c.post("/temas", json={"materia": "MAT"})
    assert r.status_code == 200 and r.json()["fonte"] == "ia" and len(r.json()["temas"]) == 3


async def test_temas_erro(monkeypatch):
    def boom(p): raise RuntimeError("quota")
    monkeypatch.setattr(app_mod, "chamar_gemini", boom)
    _set_state(pool=None)
    async with _client() as c:
        r = await c.post("/temas", json={"materia": "MAT"})
    assert r.status_code == 502


# ============================================================ /anotacoes
async def test_anotacoes_get_ok():
    conn = FakeConn(fetchrow={"from anotacoes": {"elementos": '[{"tipo": "texto", "txt": "oi"}]'}})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/anotacoes", params={"aluno_id": "a", "tema": "t"})
    assert r.status_code == 200 and len(r.json()["elementos"]) == 1


async def test_anotacoes_get_faltando_param():
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.get("/anotacoes", params={"aluno_id": "a"})   # falta tema
    assert r.status_code == 400


async def test_anotacoes_put_ok():
    conn = FakeConn(execute="INSERT 0 1")
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.put("/anotacoes", json={"aluno_id": "a", "tema": "t",
            "elementos": [{"tipo": "texto", "txt": "x"}, {"tipo": "imagem"}]})
    assert r.status_code == 200 and r.json()["salvos"] == 1   # só o de texto


# ============================================================ /perfil/estatisticas
async def test_perfil_estatisticas_ok():
    base = {"atencao": 70, "acerto": 80, "min_semana": 120, "semanas": 4, "materias": 3, "linhas": 10}
    conn = FakeConn(
        fetchrow={"media_atencao": base, "session_features sf join": None},
        fetch={"group by materia": [{"materia": "MAT", "acerto": 90}]},
    )
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/perfil/estatisticas", params={"aluno_id": "u1"})
    body = r.json()
    assert r.status_code == 200 and body["desempenho"]["atencao"] == 70 and body["analise"]


async def test_perfil_estatisticas_sem_aluno_id():
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.get("/perfil/estatisticas", params={"aluno_id": ""})
    assert r.status_code == 400


# ============================================================ /responsavel/aluno (com banco)
async def test_responsavel_aluno_com_banco():
    aluno = {"user_id": "u1", "email": "a@b.com", "hobbies": '["X"]',
             "sequencia_dias_estudo": 5, "sessoes_no_dia": 1,
             "data_prova": date(2026, 8, 1), "ultima_sessao_ts": None}
    linha = {"dia": date(2026, 7, 1), "acertos": 3, "tempo_resposta_ms": 3000.0,
             "mudancas_aba": 2, "tempo_fora_foco_s": 10.0, "cliques_fora": 1,
             "scroll_px_s": 150.0, "janelas": 5}
    conn = FakeConn(
        fetchrow={"lower(email)": {"user_id": "u1"}, "sequencia_dias_estudo": aluno},
        fetch={"group by date": [linha]},
    )
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/responsavel/aluno", params={"email": "a@b.com"})
    body = r.json()
    assert r.status_code == 200 and body["aluno"]["email"] == "a@b.com"
    assert len(body["series"]) == 1 and body["resumo"]["dias_com_dados"] == 1


async def test_responsavel_aluno_nao_encontrado():
    conn = FakeConn(fetchrow={"lower(email)": None})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/responsavel/aluno", params={"email": "nao@existe.com"})
    assert r.status_code == 404


# ============================================================ /seed/aluno-teste
async def test_seed_aluno_teste_ok():
    conn = FakeConn(execute="INSERT 0 1")
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/seed/aluno-teste")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and body["janelas"] == 50
