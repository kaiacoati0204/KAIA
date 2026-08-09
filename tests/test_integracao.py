"""Testes de INTEGRAÇÃO contra um Postgres REAL (não FakeConn).

Opt-in: só rodam se KAIA_TEST_DATABASE_URL apontar para um Postgres com a migration
já aplicada (o CI faz isso; localmente, aponte para um banco de teste). Sem a
variável, são PULADOS — a suíte unitária continua rodando normal.

Valor: exercitam autorização REAL entre usuários e o fluxo real de dados
(sessão -> evento -> ownership -> isolamento por token), pegando bugs de
integração que os mocks escondem — como o 403 de ownership que quebrava a
cadeia de intervenção.
"""
import os

import asyncpg
import httpx
import pytest
import pytest_asyncio

import app as app_mod

TEST_DB = os.getenv("KAIA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DB, reason="defina KAIA_TEST_DATABASE_URL (Postgres com a migration aplicada)")

# Dois alunos distintos (UUIDs fixos).
A = "aaaaaaaa-0000-0000-0000-00000000000a"
B = "bbbbbbbb-0000-0000-0000-00000000000b"

_LIMPAR = "truncate perfis, sessions, session_events, anotacoes restart identity cascade"


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=3, statement_cache_size=0)
    async with p.acquire() as c:
        await c.execute(_LIMPAR)
        await c.execute(
            "insert into perfis (user_id, email, nome) "
            "values ($1::uuid,'a@test','Alice'),($2::uuid,'b@test','Bob')", A, B)
    app_mod.app.state.pool = p
    app_mod.app.state.thompson = None
    app_mod.app.state.modelo = None
    app_mod.app.state.scaler = None
    yield p
    await p.close()
    app_mod.app.state.pool = None


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_mod.app), base_url="http://test")


def _como(user_id):
    """Faz o app enxergar `user_id` como dono do token (sub verificado)."""
    app_mod.app.dependency_overrides[app_mod.usuario_autenticado] = lambda: user_id
    app_mod.app.dependency_overrides[app_mod.usuario_identidade] = lambda: {"sub": user_id, "email": None}


async def test_ownership_de_sessao_real(pool):
    # A cria uma sessão e registra evento na PRÓPRIA sessão.
    _como(A)
    async with _client() as c:
        sid = (await c.post("/sessions", json={})).json()["session_id"]
        r = await c.post("/events", json={"session_id": sid, "event_type": "tab_change", "payload": {}})
        assert r.status_code == 200

    # B tenta injetar evento / espiar a sessão de A -> 403 (ownership REAL no banco).
    _como(B)
    async with _client() as c:
        assert (await c.post("/events", json={"session_id": sid, "event_type": "tab_change", "payload": {}})).status_code == 403
        assert (await c.get(f"/intervencao/pendente?session_id={sid}")).status_code == 403

    # A consulta a própria sessão -> 200 (sem intervenção pendente).
    _como(A)
    async with _client() as c:
        r = await c.get(f"/intervencao/pendente?session_id={sid}")
        assert r.status_code == 200 and r.json()["pendente"] is None


async def test_perfil_isolado_por_token(pool):
    _como(A)
    async with _client() as c:
        ra = (await c.get("/perfil")).json()
    _como(B)
    async with _client() as c:
        rb = (await c.get("/perfil")).json()
    assert ra["user_id"] == A and ra["nome"] == "Alice"
    assert rb["user_id"] == B and rb["nome"] == "Bob"   # cada um só enxerga o próprio


async def test_anotacoes_isoladas_por_token(pool):
    # A salva anotação no tema "Sintaxe" (aluno_id do corpo é IGNORADO — usa o token).
    _como(A)
    async with _client() as c:
        r = await c.put("/anotacoes", json={"aluno_id": "forjado", "tema": "Sintaxe",
                                            "elementos": [{"tipo": "texto", "txt": "regencia"}]})
        assert r.status_code == 200
    # B pede o mesmo tema -> VAZIO (a anotação é de A, não vaza).
    _como(B)
    async with _client() as c:
        assert (await c.get("/anotacoes?tema=Sintaxe")).json()["elementos"] == []
    # A pede -> vê a própria.
    _como(A)
    async with _client() as c:
        ra = (await c.get("/anotacoes?tema=Sintaxe")).json()
        assert len(ra["elementos"]) == 1 and ra["elementos"][0]["txt"] == "regencia"
