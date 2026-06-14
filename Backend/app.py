from contextlib import asynccontextmanager
from datetime import datetime, date, timezone
import os
import re
import json

import asyncpg
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

# --- Inicialização ------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")



# --- Pool asyncpg (criado no startup, fechado no shutdown) --------------------
# statement_cache_size=0 é OBRIGATÓRIO no pooler transaction (pgbouncer) do
# Supabase: o modo transaction não suporta prepared statements.
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(
        DATABASE_URL,
        statement_cache_size=0,
        min_size=1,
        max_size=5,
    )
    print("[KaIA] Pool de conexão com o Supabase criado.")

    # Scheduler: agrega features das sessões ativas a cada 30s
    scheduler = AsyncIOScheduler()
    scheduler.add_job(job_agregacao, "interval", seconds=30, args=[app], id="agg_features")
    scheduler.start()
    print("[KaIA] Scheduler de agregação iniciado (a cada 30s).")

    yield

    scheduler.shutdown(wait=False)
    await app.state.pool.close()
    print("[KaIA] Pool encerrado.")


app = FastAPI(title="KaIA Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # libera o frontend (file:// ou localhost)
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================= HELPERS GEMINI =============================================
def chamar_gemini(prompt):
    """Faz uma chamada ao Gemini e devolve o texto da resposta (ou levanta erro)."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-2.5-flash:generateContent?key={API_KEY}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(url, json=body, timeout=30)
    data = response.json()
    candidatos = data.get("candidates")
    if not candidatos:
        raise ValueError(f"Resposta inesperada do Gemini: {data}")
    return candidatos[0]["content"]["parts"][0]["text"]


def extrair_json(texto):
    """Extrai JSON mesmo quando vem dentro de cercas markdown ```json ... ```."""
    m = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
    if m:
        texto = m.group(1)
    return json.loads(texto.strip())


def montar_prompt(pergunta, hobbies):
    lista_hobbies = ", ".join(hobbies) if hobbies else "nenhum hobby informado"
    return f"""
Responda:
    - de forma clara
    - em português
    - usando explicações simples
    - usando exemplos

Utilize destes hobbies do aluno para personalizar a explicação: {lista_hobbies}

Pergunta: {pergunta}
"""


# ================== API: PERGUNTAR (chat livre) ==============================
@app.post("/perguntar")
def perguntar(dados: dict = Body(default={})):
    pergunta = (dados.get("pergunta") or "").strip()
    hobbies = dados.get("hobbies", [])

    if not pergunta:
        return JSONResponse({"resposta": "Nenhuma pergunta foi enviada."}, status_code=400)

    try:
        resposta = chamar_gemini(montar_prompt(pergunta, hobbies))
        return {"resposta": resposta}
    except requests.exceptions.RequestException as e:
        print("[KaIA] Erro de conexão com o Gemini:", e)
        return JSONResponse({"resposta": "Erro ao conectar com a IA."}, status_code=502)
    except Exception as e:
        print("[KaIA] Erro ao ler resposta do Gemini:", e)
        return JSONResponse({"resposta": "A IA retornou um formato inesperado."}, status_code=502)


# ================== API: PERGUNTA-IA (prompt cru, usada nos hobbies) =========
@app.post("/pergunta-ia")
def pergunta_ia(dados: dict = Body(default={})):
    prompt = (dados.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"respostaDaIA": "Nenhum prompt enviado."}, status_code=400)
    try:
        resposta = chamar_gemini(prompt)
        return {"respostaDaIA": resposta}
    except Exception as e:
        print("[KaIA] erro /pergunta-ia:", e)
        return JSONResponse({"respostaDaIA": "Erro ao conectar com a IA."}, status_code=502)


# ================== API: TEMAS de uma matéria ===============================
@app.post("/temas")
def temas(dados: dict = Body(default={})):
    materia = dados.get("materia", "")
    prompt = (
        f"Liste exatamente 6 temas de estudo de {materia} para o ensino médio "
        "brasileiro. Responda APENAS com um array JSON de strings, sem texto extra."
    )
    try:
        lista = extrair_json(chamar_gemini(prompt))
        if not isinstance(lista, list):
            lista = []
        return {"temas": lista}
    except Exception as e:
        print("[KaIA] erro /temas:", e)
        return JSONResponse(
            {"temas": [], "erro": "Não foi possível carregar os temas."}, status_code=502
        )


# ================== API: GERAR QUESTÃO objetiva =============================
@app.post("/gerar-questao")
def gerar_questao(dados: dict = Body(default={})):
    materia = dados.get("materia", "")
    tema = dados.get("tema", "")
    hobbies = dados.get("hobbies", [])
    lista = ", ".join(hobbies) if hobbies else "nenhum"
    prompt = f"""
Crie UMA questão objetiva de múltipla escolha sobre "{tema}" ({materia}) para o
ensino médio. Personalize o enunciado usando, se possível, estes hobbies do
aluno: {lista}.
Responda APENAS com JSON no formato EXATO:
{{"q": "enunciado da questão", "opts": ["a", "b", "c", "d", "e"], "ans": 0}}
onde "ans" é o índice (0 a 4) da alternativa correta.
"""
    try:
        questao = extrair_json(chamar_gemini(prompt))
        return questao
    except Exception as e:
        print("[KaIA] erro /gerar-questao:", e)
        return JSONResponse({"erro": "Não foi possível gerar a questão."}, status_code=502)


# ================== AGREGAÇÃO: session_events -> session_features ===========
async def agregar_features(pool, session_id):
    """Lê os eventos dos últimos 30s de uma sessão, calcula as features da
    janela e grava uma linha em session_features. Todas as colunas são NOT NULL,
    então o que não tiver evento na janela vira 0."""
    async with pool.acquire() as conn:
        sess = await conn.fetchrow(
            "select session_start_ts from sessions where session_id = $1::uuid",
            session_id,
        )
        if sess is None:
            return  # sessão não existe (nada a agregar)

        linhas = await conn.fetch(
            """
            select event_type, payload
            from session_events
            where session_id = $1::uuid and ts >= now() - interval '30 seconds'
            """,
            session_id,
        )
        # sessoes_no_dia / horario fallback vêm do session_start da sessão
        start_ev = await conn.fetchrow(
            """
            select payload from session_events
            where session_id = $1::uuid and event_type = 'session_start'
            order by ts limit 1
            """,
            session_id,
        )

        # payload (jsonb) volta como string no asyncpg → parse
        evs = [(r["event_type"], json.loads(r["payload"])) for r in linhas]

        def do_tipo(t):
            return [p for et, p in evs if et == t]

        tab = do_tipo("tab_change")
        scroll = do_tipo("scroll_burst")
        teclas = do_tipo("keystroke_pause")
        cliques = do_tipo("click_outside")
        respostas = do_tipo("question_answer")

        px = [float(p.get("px_s") or 0) for p in scroll]
        tr = [float(p.get("tempo_resposta_ms") or 0) for p in respostas]

        mudancas_aba = len(tab)
        tempo_fora_foco_s = sum(float(p.get("tempo_fora_foco_s") or 0) for p in tab)
        velocidade_scroll_px_s = (sum(px) / len(px)) if px else 0.0
        pausas_digitacao_s = sum(float(p.get("duracao_s") or 0) for p in teclas)
        cliques_fora_area_estudo = len(cliques)
        tempo_resposta_ms = (sum(tr) / len(tr)) if tr else 0.0
        acertos_questoes = sum(1 for p in respostas if p.get("acertou") is True)
        # placeholder: sem sinal de dificuldade nos eventos ainda.
        # A coluna tem CHECK (1..5), então usamos 1 (base) — 0 seria rejeitado.
        nivel_dificuldade_atividade = 1

        sessoes_no_dia = 0
        if start_ev:
            feats = (json.loads(start_ev["payload"]) or {}).get("features") or {}
            sessoes_no_dia = int(feats.get("sessoes_no_dia") or 0)

        horario_inicio = sess["session_start_ts"].time()

        await conn.execute(
            """
            insert into session_features
                (session_id, horario_inicio, sessoes_no_dia, tempo_resposta_ms,
                 velocidade_scroll_px_s, pausas_digitacao_s, cliques_fora_area_estudo,
                 mudancas_aba, tempo_fora_foco_s, acertos_questoes,
                 nivel_dificuldade_atividade, window_ts)
            values ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now())
            """,
            session_id, horario_inicio, sessoes_no_dia, tempo_resposta_ms,
            velocidade_scroll_px_s, pausas_digitacao_s, cliques_fora_area_estudo,
            mudancas_aba, tempo_fora_foco_s, acertos_questoes, nivel_dificuldade_atividade,
        )
    print(f"[KaIA Features] {session_id} | aba:{mudancas_aba} scroll:{velocidade_scroll_px_s:.0f} "
          f"acertos:{acertos_questoes}")


async def job_agregacao(app):
    """Roda a cada 30s: agrega features de toda sessão com evento nos últimos 35s."""
    pool = app.state.pool
    async with pool.acquire() as conn:
        ativas = await conn.fetch(
            """
            select distinct session_id from session_events
            where ts >= now() - interval '35 seconds'
            """
        )
    for r in ativas:
        try:
            await agregar_features(pool, str(r["session_id"]))
        except Exception as e:
            print("[KaIA] erro ao agregar", r["session_id"], ":", e)
    if ativas:
        print(f"[KaIA] Agregação rodou para {len(ativas)} sessão(ões) ativa(s).")


# ================== API: SESSIONS (abre uma nova sessão) ====================
class SessionIn(BaseModel):
    session_id: Optional[str] = None   # uuid gerado no frontend; se ausente, o banco gera
    user_id: Optional[str] = None      # MVP sem Auth: gerado se ausente
    platform: str = "web"
    app_version: str = "mvp-0.1"


@app.post("/sessions")
async def criar_sessao(body: SessionIn, request: Request):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            insert into sessions (session_id, user_id, session_start_ts, platform, app_version)
            values (coalesce($1::uuid, gen_random_uuid()),
                    coalesce($2::uuid, gen_random_uuid()),
                    now(), $3, $4)
            on conflict (session_id) do nothing
            returning session_id, user_id
            """,
            body.session_id, body.user_id, body.platform, body.app_version,
        )
        # session_id já existia → ON CONFLICT não retorna; busca a linha existente
        if row is None:
            row = await conn.fetchrow(
                "select session_id, user_id from sessions where session_id = $1::uuid",
                body.session_id,
            )

    print("[KaIA Sessão]", row["session_id"])
    return {
        "status": "ok",
        "session_id": str(row["session_id"]),
        "user_id": str(row["user_id"]),
    }


@app.post("/sessions/{session_id}/end")
async def encerrar_sessao(session_id: str, request: Request):
    """Marca o fim da sessão (session_end_ts). Idempotente: só grava se ainda
    estiver aberta (end is null)."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            update sessions set session_end_ts = now()
            where session_id = $1::uuid and session_end_ts is null
            returning session_start_ts, session_end_ts
            """,
            session_id,
        )
    if row is None:
        # sessão inexistente ou já encerrada — não é erro
        return {"status": "ignorado"}
    dur = (row["session_end_ts"] - row["session_start_ts"]).total_seconds()
    print("[KaIA Sessão encerrada]", session_id, f"{dur:.0f}s")
    return {"status": "ok", "session_id": session_id, "duracao_s": round(dur, 1)}


# ================== API: EVENTS (ingestão de eventos de atenção) =============
class EventIn(BaseModel):
    session_id: str
    event_type: str
    payload: dict = {}
    ts: Optional[str] = None   # ISO 8601 vindo do frontend; default = now() no banco


@app.post("/events")
async def receber_evento(body: EventIn, request: Request):
    pool = request.app.state.pool
    payload_json = json.dumps(body.payload, ensure_ascii=False)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Garante a sessão pai (FK session_events.session_id -> sessions).
            # O frontend dispara eventos sem criar a sessão antes; isso evita
            # violação de FK e mantém a ingestão simples e robusta.
            await conn.execute(
                """
                insert into sessions (session_id, user_id, session_start_ts, platform, app_version)
                values ($1::uuid, gen_random_uuid(), now(), 'web', 'mvp-0.1')
                on conflict (session_id) do nothing
                """,
                body.session_id,
            )
            # ts = now() do BANCO (autoritativo). NÃO usamos body.ts do frontend:
            # o relógio do navegador pode estar defasado e quebraria a janela de
            # tempo do job de agregação (session_features). Eventos chegam em
            # tempo real (fetch por evento), então now() ≈ hora do evento.
            ev = await conn.fetchrow(
                """
                insert into session_events (session_id, event_type, payload, ts)
                values ($1::uuid, $2, $3::jsonb, now())
                returning event_id
                """,
                body.session_id, body.event_type, payload_json,
            )

    print("[KaIA Event]", body.event_type, body.session_id)
    return {"status": "ok", "event_id": str(ev["event_id"])}


# ================== API: PERFIL (login + hobbies, upsert em `perfis`) ========
# Atributos ESTÁVEIS do aluno (1 linha por user_id). A tabela user_profiles
# guarda features AGREGADAS/derivadas e é populada depois pelo pipeline de ML.
def _to_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


@app.post("/perfil")
async def perfil(request: Request, dados: dict = Body(default={})):
    user_id = dados.get("user_id")
    if not user_id:
        # sem identidade estável não há como fazer upsert
        return JSONResponse({"status": "ignorado", "motivo": "sem user_id"}, status_code=400)

    p = dados.get("perfil") or {}
    email = p.get("email") or dados.get("email") or None
    hobbies = p.get("hobbies") or dados.get("hobbies") or []
    ambiente = p.get("ambiente_dispositivo")
    seq = int(p.get("sequencia_dias_estudo") or 0)
    sess_dia = int(p.get("sessoes_no_dia") or 0)

    # ultima_sessao_ts vem como epoch em ms → timestamptz
    ult_ts = None
    raw_ts = p.get("ultima_sessao_ts")
    if raw_ts:
        try:
            ult_ts = datetime.fromtimestamp(float(raw_ts) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            ult_ts = None

    pool = request.app.state.pool
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                insert into perfis (user_id, email, hobbies, data_prova, ambiente_dispositivo,
                    sequencia_dias_estudo, sessoes_no_dia, ultimo_dia_estudo, ultima_sessao_ts, updated_at)
                values ($1::uuid, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, now())
                on conflict (user_id) do update set
                    email                 = coalesce(excluded.email, perfis.email),
                    hobbies               = excluded.hobbies,
                    data_prova            = coalesce(excluded.data_prova, perfis.data_prova),
                    ambiente_dispositivo  = coalesce(excluded.ambiente_dispositivo, perfis.ambiente_dispositivo),
                    sequencia_dias_estudo = excluded.sequencia_dias_estudo,
                    sessoes_no_dia        = excluded.sessoes_no_dia,
                    ultimo_dia_estudo     = coalesce(excluded.ultimo_dia_estudo, perfis.ultimo_dia_estudo),
                    ultima_sessao_ts      = coalesce(excluded.ultima_sessao_ts, perfis.ultima_sessao_ts),
                    updated_at            = now()
                """,
                user_id, email, json.dumps(hobbies, ensure_ascii=False),
                _to_date(p.get("data_prova")), ambiente, seq, sess_dia,
                _to_date(p.get("ultimo_dia_estudo")), ult_ts,
            )
    except Exception as e:
        print("[KaIA] Erro ao gravar perfil:", e)
        return JSONResponse({"status": "erro"}, status_code=500)

    print("[KaIA Perfil upsert]", email or user_id)
    return {"status": "ok"}


# ================== HEALTHCHECK =============================================
@app.get("/")
def health():
    return {"status": "KaIA backend no ar"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
