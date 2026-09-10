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


@pytest.fixture(autouse=True)
def _limpa_streak():
    app_mod._ESTADO_STREAK.clear()   # debounce por sessão é in-memory -> isola os testes
    yield


# ============================================================ helpers puros
def test_extrair_json_cru():
    assert app_mod.extrair_json('{"a": 1}') == {"a": 1}


def test_extrair_json_com_cercas():
    assert app_mod.extrair_json('```json\n[1, 2, 3]\n```') == [1, 2, 3]


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
    assert app_mod.vetor_para_modelo(feats) == [float(i) for i in range(len(app_mod.FEATURE_ORDER))]


async def test_dados_grafico_com_banco():
    conn = FakeConn(fetch=[{"hobby": "Jogos", "n": 5}, {"hobby": "Música", "n": 3}])
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/api/dados-grafico")
    body = r.json()
    assert body["labels"] == ["Jogos", "Música"] and body["valores"] == [5, 3]


async def test_dados_grafico_demo_sem_banco():
    _set_state(pool=None)                     # sem banco -> modo demonstração
    async with _client() as c:
        r = await c.get("/api/dados-grafico")
    assert r.json()["demo"] is True


def test_turma_rotulo():
    assert app_mod._turma_rotulo(3, "manhã") == "3º ano · manhã"
    assert app_mod._turma_rotulo(None, "x") == "—"


def test_status_atencao():
    assert app_mod._status_atencao(None) is None
    assert app_mod._status_atencao(0.3) == "risco"
    assert app_mod._status_atencao(0.6) == "atencao"
    assert app_mod._status_atencao(0.8) == "bem"


def test_distribuicao_status():
    assert app_mod._distribuicao_status([0.3, 0.6, 0.8, None]) == {"bem": 1, "atencao": 1, "risco": 1}


# ---------------------------------------------- helpers de cache de questões
async def test_buscar_cache_limite_zero():
    assert await app_mod._buscar_cache(FakeConn(fetch=[]), "u", "mat", "tem", 2, "jogos", 0) == []


async def test_buscar_cache_monta_query_com_hobbie_e_exclusao():
    conn = FakeConn(fetch=[])                 # sem linhas -> [] (monta a query mesmo assim)
    r = await app_mod._buscar_cache(conn, "u", "mat", "tem", 2, "jogos", 5, excluir=["id1"])
    assert r == []


async def test_marcar_vistas_com_ids():
    conn = FakeConn()
    await app_mod._marcar_vistas(conn, "u", [{"questao_id": "q1"}, {"sem_id": 1}])
    assert any("questoes_vistas" in q for q, _ in conn.executed)


async def test_marcar_vistas_sem_ids():
    conn = FakeConn()
    await app_mod._marcar_vistas(conn, "u", [{"sem_id": 1}])   # nenhum id -> não executa
    assert conn.executed == []


async def test_resetar_vistas_antigas():
    conn = FakeConn()
    await app_mod._resetar_vistas_antigas(conn, "u", "mat", "tem", 2)
    assert any("delete from questoes_vistas" in q for q, _ in conn.executed)


# ============================================================ rotas Gemini (mock)
async def test_gerar_questao_ok(monkeypatch):
    questao = {"q": "?", "opts": ["a", "b", "c", "d", "e"], "ans": 0}
    _set_state(pool=None)   # sem banco -> pula cache, gera direto no Gemini (mock)
    monkeypatch.setattr(app_mod, "chamar_gemini", lambda p: json.dumps(questao))
    async with _client() as c:
        r = await c.post("/gerar-questao", json={"materia": "MAT", "tema": "t"})
    body = r.json()
    assert r.status_code == 200
    assert len(body["porque_erradas"]) == 5 and body["explicacao"] == ""  # normalizado


async def test_gerar_questao_erro(monkeypatch):
    def boom(p): raise RuntimeError("x")
    _set_state(pool=None)   # sem banco -> pula cache, vai direto ao Gemini (que falha)
    monkeypatch.setattr(app_mod, "chamar_gemini", boom)
    async with _client() as c:
        r = await c.post("/gerar-questao", json={"materia": "MAT", "tema": "t"})
    assert r.status_code == 502


# ---------------------------------------------- few-shot (questões reais)
async def test_gerar_no_gemini_injeta_exemplo_real(monkeypatch):
    capturado = {}
    def fake(prompt):
        capturado["p"] = prompt
        return json.dumps([{"q": "?", "opts": ["a", "b", "c", "d", "e"], "ans": 0}])
    monkeypatch.setattr(app_mod, "chamar_gemini", fake)
    exemplos = [{"enunciado": "ENUNCIADO_REAL_XYZ", "alternativas": list("abcde"), "gabarito": 1}]
    await app_mod._gerar_no_gemini(1, "PORT", "Português", "Sintaxe", None, 3, exemplos=exemplos)
    assert "ENUNCIADO_REAL_XYZ" in capturado["p"] and "questões REAIS" in capturado["p"]


async def test_gerar_no_gemini_injeta_evitar(monkeypatch):
    # Anti-repetição: enunciados já existentes entram no prompt p/ o modelo divergir.
    capturado = {}
    def fake(prompt):
        capturado["p"] = prompt
        return json.dumps([{"q": "?", "opts": list("abcde"), "ans": 0}])
    monkeypatch.setattr(app_mod, "chamar_gemini", fake)
    await app_mod._gerar_no_gemini(1, "HIS", "História", "Revolução", None, 3,
                                   evitar=["QUESTAO_JA_EXISTE_ABC"])
    assert "QUESTAO_JA_EXISTE_ABC" in capturado["p"] and "JÁ EXISTEM" in capturado["p"]


async def test_exemplos_similares_pgvector(monkeypatch):
    # Retrieval dinâmico: embedding ok + linha do pgvector -> exemplo no formato certo.
    monkeypatch.setattr(app_mod, "_embed", lambda t: [0.1] * app_mod.EMBED_DIM)
    class FakeConn:
        async def fetch(self, *a):
            return [{"enunciado": "REAL_SIMILAR",
                     "alternativas": '["a","b","c","d","e"]', "gabarito": 2}]
    r = await app_mod._exemplos_similares(FakeConn(), "HIS", "Revolução")
    assert r and r[0]["enunciado"] == "REAL_SIMILAR" and r[0]["alternativas"] == list("abcde")


async def test_exemplos_similares_sem_embedding_none(monkeypatch):
    # Sem embedding (falha/cota) -> None -> caller cai nos exemplos few-shot fixos.
    monkeypatch.setattr(app_mod, "_embed", lambda t: None)
    assert await app_mod._exemplos_similares(object(), "HIS", "Revolução") is None


def test_exemplos_few_shot_materia_de_conta_vazio(monkeypatch):
    monkeypatch.setattr(app_mod, "_EXEMPLOS_FEW_SHOT", {"PORT": [
        {"enunciado": "E1", "alternativas": list("abcde"), "gabarito": 2}]})
    assert app_mod._exemplos_few_shot("MAT") == []   # matéria sem entrada -> []


def test_exemplos_few_shot_traz_da_materia(monkeypatch):
    monkeypatch.setattr(app_mod, "_EXEMPLOS_FEW_SHOT", {"PORT": [
        {"enunciado": "E1", "alternativas": list("abcde"), "gabarito": 2}]})
    r = app_mod._exemplos_few_shot("PORT")
    assert len(r) == 1 and r[0]["enunciado"] == "E1"


async def test_gerar_questao_buffer_por_niveis(monkeypatch):
    # /gerar-questao com distribuição -> gera por FAIXA e combina o buffer.
    chamadas = []
    async def fake_banda(conn, user_id, materia, nome, tema, hobbie, nivel, n):
        chamadas.append((nivel, n))
        return [{"q": f"nv{nivel}", "opts": list("abcde"), "ans": 0, "nivel": nivel} for _ in range(n)]
    monkeypatch.setattr(app_mod, "_montar_banda", fake_banda)
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.post("/gerar-questao", json={"materia": "PORT", "tema": "t",
                                                 "distribuicao": {"1": 2, "2": 3}})
    body = r.json()
    assert r.status_code == 200 and len(body["questoes"]) == 5   # 2 + 3
    assert set(chamadas) == {(1, 2), (2, 3)}


# ============================================================ guardas 'sem banco'
@pytest.mark.parametrize("metodo,rota,kwargs", [
    ("get", "/anotacoes?aluno_id=a&tema=t", {}),
    ("put", "/anotacoes", {"json": {"aluno_id": "a", "tema": "t", "elementos": []}}),
    ("get", "/perfil/estatisticas?aluno_id=a", {}),
    ("get", "/intervencao/pendente?session_id=s", {}),
    ("post", "/intervencao/feedback",
     {"json": {"session_id": "s", "intervention_type": "checkpoint", "reward": 1.0}}),
    ("post", "/sessions", {"json": {"user_id": "u"}}),
    ("post", "/sessions/abc/end", {}),
    ("post", "/events", {"json": {"session_id": "s", "event_type": "tab_change", "payload": {}}}),
    ("post", "/perfil", {"json": {"user_id": "u"}}),
    ("get", "/perfil?email=a@b.com", {}),
    ("get", "/responsavel/painel?email=a@b.com", {}),
    # entrou quando o fallback offline saiu: sem banco o dashboard passou a
    # responder 503 como as demais, em vez de montar a página com xlsx.
    ("get", "/dashboard/dados", {}),
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


# ============================================================ autorização (item 1)
# O conftest stubba a auth em todos os testes; aqui REMOVEMOS o stub para exercer
# o caminho real "sem token -> 401" (que roda antes de qualquer JWKS, offline).
@pytest.mark.parametrize("rota", [
    "/perfil",
    "/dashboard/dados",
    "/diagnose?session_id=abc",
    "/questoes/hoje",
    "/perfil/estatisticas",
])
async def test_rota_protegida_sem_token_401(rota):
    app_mod.app.dependency_overrides.pop(app_mod.usuario_autenticado, None)
    app_mod.app.dependency_overrides.pop(app_mod.usuario_identidade, None)
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.get(rota)
    assert r.status_code == 401


async def test_perfil_post_ignora_user_id_do_cliente():
    # IDOR fechado: o upsert usa o sub do TOKEN, não o user_id que o cliente manda.
    conn = FakeConn(execute="INSERT 0 1")
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/perfil", json={"user_id": "atacante",
                                          "perfil": {"email": "a@b.com"}})
    assert r.status_code == 200
    up = [args for (q, args) in conn.executed if "insert into perfis" in q]
    assert up and str(up[0][0]) == "test-user"   # dono = token, não "atacante"


async def test_anotacoes_put_ignora_aluno_id_do_cliente():
    conn = FakeConn(execute="INSERT 0 1")
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.put("/anotacoes", json={"aluno_id": "atacante", "tema": "t",
                                            "elementos": [{"tipo": "texto", "txt": "x"}]})
    assert r.status_code == 200
    up = [args for (q, args) in conn.executed if "insert into anotacoes" in q]
    assert up and str(up[0][0]) == "test-user" and up[0][1] == "t"  # dono=token, tema=corpo


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
    conn = FakeConn(fetchrow={"insert into session_events": {"event_id": "e1"}},
                    fetchval={"user_id from sessions": "test-user"})   # dono = usuário do token (passa ownership)
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/events", json={"session_id": "s", "event_type": "tab_change", "payload": {}})
    assert r.status_code == 200 and r.json()["event_id"] == "e1"


async def test_events_bloqueia_sessao_de_outro():
    # Evento numa sessão que pertence a OUTRO usuário -> 403 (ownership).
    conn = FakeConn(fetchval={"user_id from sessions": "outro-user"})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/events", json={"session_id": "s", "event_type": "tab_change", "payload": {}})
    assert r.status_code == 403


async def test_perfil_post_usa_token():
    # Sem user_id no body: a identidade (dono do upsert) vem do token.
    conn = FakeConn(execute="INSERT 0 1")
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/perfil", json={})
    assert r.status_code == 200 and r.json()["status"] == "ok"


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


async def test_get_perfil_por_user_id():
    row = {"user_id": "u1", "email": "a@b.com", "nome": "Ana", "role": "aluno",
           "escola_id": None, "turma_id": None, "hobbies": '["X"]'}
    conn = FakeConn(fetchrow={"FROM perfis": row})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/perfil", params={"user_id": "11111111-1111-1111-1111-111111111111"})
    assert r.status_code == 200 and r.json()["user_id"] == "u1"


async def test_get_perfil_usa_token_sem_perfil():
    # Identidade vem do token (não de query param). Sem perfil correspondente -> 404.
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.get("/perfil")
    assert r.status_code == 404


async def test_intervencao_pendente_ok():
    row = {"intervention_id": "iv1", "intervention_type": "checkpoint",
           "triggered_at": datetime.now(timezone.utc)}
    conn = FakeConn(fetchrow={"from interventions": row},
                    fetchval={"user_id from sessions": "test-user"})   # sessão é do usuário do token
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/intervencao/pendente", params={"session_id": "s"})
    assert r.json()["pendente"]["intervention_type"] == "checkpoint"


async def test_intervencao_pendente_vazio():
    conn = FakeConn(fetchrow={"from interventions": None},
                    fetchval={"user_id from sessions": "test-user"})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/intervencao/pendente", params={"session_id": "s"})
    assert r.json()["pendente"] is None


async def test_intervencao_pendente_sessao_de_outro():
    conn = FakeConn(fetchval={"user_id from sessions": "outro-user"})   # sessão de outro -> 403
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/intervencao/pendente", params={"session_id": "s"})
    assert r.status_code == 403


async def test_intervencao_feedback_tipo_invalido():
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.post("/intervencao/feedback",
                         json={"session_id": "s", "intervention_type": "xxx", "reward": 1.0})
    assert r.status_code == 400


async def test_intervencao_feedback_ok():
    conn = FakeConn(fetchrow={"update interventions": {"intervention_id": "iv1"}},
                    fetchval={"user_id from sessions": "test-user"})   # sessão do usuário do token
    up = []
    thompson = SimpleNamespace(update=lambda t, r: up.append((t, r)))
    _set_state(pool=FakePool(conn), thompson=thompson)
    async with _client() as c:
        r = await c.post("/intervencao/feedback",
                         json={"session_id": "s", "intervention_type": "checkpoint", "reward": 1.0})
    assert r.status_code == 200 and r.json()["reward"] == 1.0
    assert up == [("checkpoint", 1.0)]   # bandit atualizado


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


async def test_rodar_intervencao_sem_baseline(monkeypatch):
    """Cold-start / sessão sem resposta: não intervém e não fecha reward."""
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.9, "feats": _feats_ok(), "confiavel": False}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    conn = FakeConn()
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert conn.executed == []


def test_registrar_falha_geracao(capsys):
    """Conta por dia e sobe o tom do log ao passar do alerta."""
    app_mod._FALHAS_GERACAO.clear()
    assert app_mod._registrar_falha_geracao("teste") == 1
    assert "info" in capsys.readouterr().out
    for _ in range(app_mod.FALHAS_GERACAO_ALERTA - 2):
        app_mod._registrar_falha_geracao("teste")
    capsys.readouterr()
    n = app_mod._registrar_falha_geracao("teste")
    assert n == app_mod.FALHAS_GERACAO_ALERTA
    assert "AVISO" in capsys.readouterr().out
    app_mod._FALHAS_GERACAO.clear()


def test_embed_usa_cache(monkeypatch):
    """Mesma frase não volta pra API — era o que estourava a cota do embedding."""
    app_mod._EMBED_CACHE.clear()
    chamadas = []

    class _R:
        def json(self):
            chamadas.append(1)
            return {"embedding": {"values": [0.1] * app_mod.EMBED_DIM}}

    monkeypatch.setattr(app_mod.requests, "post", lambda *a, **k: _R())
    for _ in range(5):
        app_mod._embed("Historia: Segunda Guerra")
    app_mod._embed("Biologia: Genetica")
    assert len(chamadas) == 2          # 6 pedidos, 2 temas distintos
    app_mod._EMBED_CACHE.clear()


def test_pot_acha_opcao_pega_a_mais_proxima():
    """Distrator plausível fica PERTO de propósito — "a primeira dentro da tolerância"
    escolhia o distrator quando a certa vinha depois. Caso real: 50/196 = 25,51%."""
    opts = ["25,0%", "20,4%", "33,3%", "75,0%", "25,5%"]
    assert app_mod._pot_acha_opcao(50 / 196 * 100, opts) == 4     # 25,5 e não 25,0
    assert app_mod._pot_acha_opcao(20.0, ["10", "20", "30"]) == 1
    assert app_mod._pot_acha_opcao(7.77, ["10", "20", "30"]) is None


def test_pot_descarta_quando_o_resultado_nao_e_alternativa():
    """Perto nao basta: media ponderada 7,3 com 7,2 e 7,4 na lista nao tem gabarito.

    Achado a mao no teste do impostor — com a tolerancia de 3% de antes, as duas
    ficavam dentro e uma delas virava resposta certa."""
    assert app_mod._pot_acha_opcao(7.3, ["7.6", "7.0", "7.2", "7.4", "7.8"]) is None
    # combustao do metanol: a conta da -647,5 e a mais proxima e -638
    assert app_mod._pot_acha_opcao(
        -647.5, ["-915", "-726", "-638", "-1020", "-805"]) is None
    # arredondamento de exibicao continua passando
    assert app_mod._pot_acha_opcao(22 / 3, ["7.33", "8.00", "6.50"]) == 0


def test_pot_descarta_alternativa_ambigua():
    """Duas opcoes praticamente iguais ao resultado: o numero nao escolhe uma."""
    assert app_mod._pot_acha_opcao(10.0, ["10.0", "10.02", "30"]) is None


def test_questao_utilizavel():
    """Barreira estrutural: pega o que passou na avaliação com os professores."""
    ok_completar = {"q": "O ritual representa, para seus adeptos, a",
                    "opts": ["manutenção de memória.", "contestação étnica.", "imolação.",
                             "legitimação.", "promissão."]}
    ok_pergunta = {"q": "Qual é a quantidade mínima de água, em litro?",
                   "opts": ["50", "60", "80", "140", "150"]}
    # enunciado fecha em frase completa e as alternativas são fragmentos: ficou sem pergunta
    sem_pergunta = {"q": "O DIP atuou na censura e na promoção da imagem do governo.",
                    "opts": ["controle sindical.", "mercantilização.", "diversificação.",
                             "privatização.", "cerceamento."]}
    repetidas = {"q": "Pergunta?", "opts": ["a", "A", "b", "c", "d"]}
    vazia = {"q": "Pergunta?", "opts": ["a", "", "b", "c", "d"]}
    curta = {"q": "Pergunta?", "opts": ["a", "b", "c"]}
    assert app_mod._questao_utilizavel(ok_completar) is True
    assert app_mod._questao_utilizavel(ok_pergunta) is True
    assert app_mod._questao_utilizavel(sem_pergunta) is False
    assert app_mod._questao_utilizavel(repetidas) is False
    assert app_mod._questao_utilizavel(vazia) is False
    assert app_mod._questao_utilizavel(curta) is False


def test_leitura_confiavel():
    feats = {n: 0.0 for n in app_mod.FEATURE_ORDER}
    assert app_mod.leitura_confiavel(feats) is False       # internas todas zeradas
    feats["duracao_janela_min"] = 20.0                     # externa não conta
    assert app_mod.leitura_confiavel(feats) is False
    # sem baseline, off-task externo ainda se lê: as absolutas não dependem dele
    assert app_mod.leitura_confiavel(feats, "muito_distraido") is True
    assert app_mod.leitura_confiavel(feats, "distraido") is False
    assert app_mod.leitura_confiavel(feats, "engajado") is False
    feats["tempo_resposta_ms"] = 0.4                       # uma interna basta
    assert app_mod.leitura_confiavel(feats) is True
    assert app_mod.leitura_confiavel(feats, "distraido") is True


async def test_rodar_intervencao_engajado(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "engajado", "score": 0.9, "feats": {"sessoes_no_dia": 1}, "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    conn = FakeConn()
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert conn.executed == []   # engajado não intervém


def _feats_ok():                                        # passa o warm-up (sessão >= 3 min)
    return {"duracao_janela_min": 10.0}


def _respostas(regs):
    return [{"payload": {"acertou": ok, "tempo_resposta_ms": rt}} for ok, rt in regs]


# Aluno errando as ultimas: o comportamento CONFIRMA a leitura de distracao.
_CORROBORA = _respostas([(True, 20000)] * 5 + [(False, 21000), (False, 20000), (False, 22000)])
# Aluno acertando no proprio ritmo: comportamento NAO confirma.
_NAO_CORROBORA = _respostas([(True, 20000), (True, 21000), (True, 19500),
                             (True, 20500), (True, 20000), (True, 21000)])


async def test_rodar_intervencao_dispara(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.9, "feats": _feats_ok(), "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "distraido", "n": 1}   # esta janela vira a 2ª (passa o debounce)
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 5},                  # já respondeu questões (warm-up ok)
                    fetch={"select payload": _CORROBORA})
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert any("insert into interventions" in q for q, _ in conn.executed)


async def test_distraido_nao_interrompe_aluno_que_vai_bem(monkeypatch):
    """O falso positivo caro: o modelo diz `distraido`, mas o aluno esta acertando no
    proprio ritmo. Sem 2a evidencia, nao interrompe."""
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.95, "feats": _feats_ok(), "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "distraido", "n": 1}
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 6},
                    fetch={"select payload": _NAO_CORROBORA})
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert not any("insert into interventions" in q for q, _ in conn.executed)


async def test_muito_distraido_nao_exige_corroboracao(monkeypatch):
    """Sair da aba e MEDICAO, nao inferencia — dispara sozinho."""
    async def fake_pred(m, s, conn, sid):
        return {"estado": "muito_distraido", "score": 0.9, "feats": _feats_ok(), "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "muito_distraido", "n": 1}
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 5},
                    fetch={"select payload": _NAO_CORROBORA})   # nao corrobora, e nao importa
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "pausa_ativa")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert any("insert into interventions" in q for q, _ in conn.executed)


async def test_rodar_intervencao_cooldown(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.9, "feats": _feats_ok(), "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "distraido", "n": 2}   # já passa o debounce
    agora = datetime.now(timezone.utc)
    conn = FakeConn(fetchrow={"from interventions": {"n": 1, "ultima": agora}},  # recém-disparada
                    fetchval={"question_answer": 5})
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert conn.executed == []   # cooldown bloqueia


async def test_rodar_intervencao_debounce(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.9, "feats": _feats_ok(), "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 5})
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")   # 1ª janela -> streak=1 < 2
    assert conn.executed == []                          # debounce bloqueia o blip


async def test_rodar_intervencao_score_baixo(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.4, "feats": _feats_ok(), "confiavel": True}   # < INTERV_SCORE_MIN
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "distraido", "n": 2}   # debounce já ok -> isola a confiança
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 5})
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert conn.executed == []                          # confiança baixa bloqueia


async def test_rodar_intervencao_warmup_sem_questao(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.9, "feats": _feats_ok(), "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "distraido", "n": 2}   # passa debounce/score
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 0})                  # nenhuma questão respondida ainda
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert conn.executed == []                          # sem 1ª questão -> não intervém


async def test_rodar_intervencao_warmup_cedo(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "distraido", "score": 0.9, "feats": {"duracao_janela_min": 1.0}, "confiavel": True}  # < 3 min
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "distraido", "n": 2}
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 5})                  # respondeu, mas cedo demais
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    assert conn.executed == []                          # timer segura mesmo com questão respondida


# O reward deixou de vir da transicao de estado (que era prevista pelo PROPRIO modelo
# de atencao, fazendo o bandit aprender da saida dele) e passou a vir do que o aluno FEZ.
@pytest.mark.parametrize("respostas,esperado", [
    ([], 0.0),                                   # nao voltou a responder
    ([True, True], 1.0),                         # voltou e acertou tudo
    ([False, False], 0.5),                       # voltou, errou tudo: retomar ja vale metade
    ([True, False], 0.75),                       # voltou, metade
    ([True, False, False, False], 0.625),
])
async def test_reward_objetivo(respostas, esperado):
    linhas = [{"payload": {"acertou": a}} for a in respostas]
    conn = FakeConn(fetch={"select payload": linhas})
    r = await app_mod.reward_objetivo(conn, "sid", "ini", "fim")
    assert r == esperado


async def test_reward_objetivo_aceita_payload_em_texto():
    """asyncpg devolve jsonb como str dependendo do driver — nao pode quebrar."""
    conn = FakeConn(fetch={"select payload": [{"payload": '{"acertou": true}'}]})
    assert await app_mod.reward_objetivo(conn, "sid", "ini", "fim") == 1.0


async def test_resolver_rewards_usa_desfecho_objetivo():
    up = []
    thompson = SimpleNamespace(update=lambda t, r: up.append((t, r)))
    pend = [{"intervention_id": "iid", "intervention_type": "checkpoint",
             "triggered_at": datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)}]
    conn = FakeConn(fetch={
        "select intervention_id": pend,
        "select payload": [{"payload": {"acertou": True}}, {"payload": {"acertou": True}}],
    })
    await app_mod.resolver_rewards(conn, thompson, "sid")
    assert up == [("checkpoint", 1.0)]
    assert any("update interventions" in q for q, _ in conn.executed)
    # a origem gravada diz de onde veio o numero — auditavel depois
    assert any("desfecho_objetivo" in q for q, _ in conn.executed)


async def test_resolver_rewards_sem_thompson():
    pend = [{"intervention_id": "iid", "intervention_type": "checkpoint",
             "triggered_at": datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)}]
    conn = FakeConn(fetch={"select intervention_id": pend})
    await app_mod.resolver_rewards(conn, None, "sid")                # sem bandit: nao faz nada
    assert conn.executed == []


def test_micro_randomizacao_e_por_decisao_nao_por_aluno():
    """Sorteio fixo por aluno dava n=5 num beta de 5 pessoas. Por decisao, cada aluno
    contribui com dezenas de unidades randomizadas."""
    sorteios = [app_mod._sorteio_micro_randomizado() for _ in range(400)]
    assert set(sorteios) == {"controle", "bandit"}
    prop = sorteios.count("controle") / len(sorteios)
    assert 0.4 < prop < 0.6                          # 50/50, com folga de amostragem


# ============================================================ /temas (lista fixa)
async def test_temas_fixo():
    _set_state(pool=None)   # nem toca no banco/IA
    async with _client() as c:
        r = await c.post("/temas", json={"materia": "MAT"})
    body = r.json()
    assert r.status_code == 200 and body["fonte"] == "fixo"
    assert body["temas"] == app_mod.TEMAS_FIXOS["MAT"] and len(body["temas"]) > 0


async def test_temas_materia_desconhecida():
    _set_state(pool=None)
    async with _client() as c:
        r = await c.post("/temas", json={"materia": "XYZ"})
    assert r.status_code == 404


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


async def test_perfil_estatisticas_usa_token_sem_dados():
    # Identidade vem do token (não de aluno_id). Sem dados -> 200 com desempenho vazio.
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.get("/perfil/estatisticas")
    assert r.status_code == 200 and r.json()["desempenho"] is None


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
        fetchval={"role from perfis": "professor"},   # chamador é responsável (passa o gate)
    )
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/responsavel/aluno", params={"email": "a@b.com"})
    body = r.json()
    assert r.status_code == 200 and body["aluno"]["email"] == "a@b.com"
    assert len(body["series"]) == 1 and body["resumo"]["dias_com_dados"] == 1


async def test_responsavel_aluno_nao_encontrado():
    conn = FakeConn(fetchrow={"lower(email)": None},
                    fetchval={"role from perfis": "professor"})   # passa o gate; alvo é que não existe
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/responsavel/aluno", params={"email": "nao@existe.com"})
    assert r.status_code == 404


async def test_responsavel_aluno_bloqueia_nao_responsavel():
    # Aluno comum tentando ver dados de outro aluno -> 403 (gate de role).
    conn = FakeConn(fetchval={"role from perfis": "aluno"})
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.get("/responsavel/aluno", params={"email": "outro@aluno.com"})
    assert r.status_code == 403


# ============================================================ /seed/aluno-teste
async def test_seed_aluno_teste_ok(monkeypatch):
    monkeypatch.setenv("KAIA_SEED_ATIVO", "1")   # rota de dev: só roda com a flag
    conn = FakeConn(execute="INSERT 0 1")
    _set_state(pool=FakePool(conn))
    async with _client() as c:
        r = await c.post("/seed/aluno-teste")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and body["janelas"] == 50


async def test_seed_desativado_por_padrao(monkeypatch):
    monkeypatch.delenv("KAIA_SEED_ATIVO", raising=False)   # sem a flag -> 403
    _set_state(pool=FakePool(FakeConn()))
    async with _client() as c:
        r = await c.post("/seed/aluno-teste")
    assert r.status_code == 403


# ==================================================== corroboracao objetiva
def _fc(regs):
    """FakeConn com N eventos question_answer (acertou, tempo_resposta_ms)."""
    return FakeConn(fetch={"select payload": [
        {"payload": {"acertou": ok, "tempo_resposta_ms": rt}} for ok, rt in regs]})


async def test_corroboracao_exige_minimo_de_respostas():
    """Sem base de comparacao dentro da sessao, nao corrobora — e nao interrompe."""
    ok, _ = await app_mod._corroboracao_objetiva(_fc([(True, 20000)] * 3), "sid")
    assert ok is False


async def test_corroboracao_por_queda_de_acerto():
    regs = [(True, 20000)] * 5 + [(False, 21000), (False, 22000), (False, 20500)]
    ok, motivo = await app_mod._corroboracao_objetiva(_fc(regs), "sid")
    assert ok is True and "acerto" in motivo


async def test_corroboracao_por_tempo_fora_do_proprio_ritmo():
    # acertando, mas a ultima levou ordens de grandeza mais que o ritmo do aluno
    regs = [(True, 20000), (True, 21000), (True, 19500), (True, 20500), (True, 20000)]
    regs += [(True, 21000), (True, 20000), (True, 400000)]
    ok, motivo = await app_mod._corroboracao_objetiva(_fc(regs), "sid")
    assert ok is True and "tempo" in motivo


async def test_corroboracao_nega_quando_aluno_vai_bem():
    """O caso que mais importa: aluno acertando no proprio ritmo NAO pode ser
    interrompido por causa de uma leitura de atencao incerta."""
    regs = [(True, 20000), (True, 21000), (True, 19500), (True, 20500),
            (True, 20000), (True, 21000)]
    ok, _ = await app_mod._corroboracao_objetiva(_fc(regs), "sid")
    assert ok is False


async def test_regra_dispara_sem_o_modelo_de_atencao(monkeypatch):
    """O RF nao pode ser porta obrigatoria. Se ele disser `engajado` mas o comportamento
    acusar queda, a regra dispara sozinha — e o gatilho fica registrado como 'regra'."""
    async def fake_pred(m, s, conn, sid):
        return {"estado": "engajado", "score": 0.9, "feats": _feats_ok(), "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "engajado", "n": 1}
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 8},
                    fetch={"select payload": _CORROBORA})
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "checkpoint")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    inserts = [(q, a) for q, a in conn.executed if "insert into interventions" in q]
    assert inserts, "a regra deveria disparar mesmo com o RF dizendo engajado"
    assert "regra" in inserts[0][1]                       # gatilho gravado


async def test_gatilho_medicao_para_muito_distraido(monkeypatch):
    async def fake_pred(m, s, conn, sid):
        return {"estado": "muito_distraido", "score": 0.9, "feats": _feats_ok(), "confiavel": True}
    monkeypatch.setattr(app_mod, "predizer_estado", fake_pred)
    app_mod._ESTADO_STREAK["sid"] = {"estado": "muito_distraido", "n": 1}
    conn = FakeConn(fetchrow={"from interventions": {"n": 0, "ultima": None}},
                    fetchval={"question_answer": 5},
                    fetch={"select payload": _NAO_CORROBORA})
    thompson = SimpleNamespace(select=lambda e, s, evitar=(): "pausa_ativa")
    fake_app = SimpleNamespace(state=SimpleNamespace(
        thompson=thompson, modelo=1, scaler=1, pool=FakePool(conn)))
    await app_mod.rodar_intervencao(fake_app, "sid")
    inserts = [(q, a) for q, a in conn.executed if "insert into interventions" in q]
    assert inserts and "medicao" in inserts[0][1]
