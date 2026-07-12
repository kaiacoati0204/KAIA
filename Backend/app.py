from contextlib import asynccontextmanager
from datetime import datetime, date, timezone, timedelta
import os
import re
import json
import uuid

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
# Aceita os dois nomes: API_KEY (prod/CI) ou CHAVE_ACESSO (.env local).
API_KEY = os.getenv("API_KEY") or os.getenv("CHAVE_ACESSO")
DATABASE_URL = os.getenv("DATABASE_URL")

# Aluno "anônimos" sentinela: usado quando o /events precisa auto-criar uma
# sessão sem conhecer o aluno (satisfaz a FK sessions.user_id -> perfis.user_id).
ANON_USER = "00000000-0000-0000-0000-000000000000"

# Resposta padrão quando o servidor está sem banco (pool = None).
_SEM_BANCO = JSONResponse(
    {"erro": "Banco de dados indisponível. Configure DATABASE_URL no .env (string do Supabase)."},
    status_code=503,
)



# --- Pool asyncpg (criado no startup, fechado no shutdown) --------------------
# statement_cache_size=0 é OBRIGATÓRIO no pooler transaction (pgbouncer) do
# Supabase: o modo transaction não suporta prepared statements.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pool tolerante a falha: se DATABASE_URL não estiver setada ou o banco
    # estiver inacessível, o servidor SOBE mesmo assim (pool = None). As rotas
    # que dependem do banco respondem 503 com mensagem clara, e as de IA (Gemini)
    # seguem funcionando. Isso evita o crash de startup em dev sem Supabase.
    app.state.pool = None
    if not DATABASE_URL:
        print("[KaIA] AVISO: DATABASE_URL não definida no .env — subindo SEM banco. "
              "As rotas de dados (sessions/events/perfil/responsavel) ficarão indisponíveis.")
    else:
        try:
            app.state.pool = await asyncpg.create_pool(
                DATABASE_URL,
                statement_cache_size=0,
                min_size=1,
                max_size=5,
                timeout=8,            # connect timeout: falha rápido se a porta estiver bloqueada
                command_timeout=15,
            )
            print("[KaIA] Pool de conexão com o Supabase criado.")
        except Exception as e:
            print("[KaIA] AVISO: não foi possível conectar ao banco — subindo SEM banco:", e)

    # Garante o aluno anônimo (alvo da FK no fallback do /events).
    # Tolerante a falha: em ambiente sem schema (ex: CI com Postgres vazio) o
    # servidor ainda sobe — só não cria o anônimo.
    if app.state.pool is not None:
        try:
            async with app.state.pool.acquire() as conn:
                await conn.execute(
                    "insert into perfis (user_id, email) values ($1::uuid, 'anonimo') on conflict (user_id) do nothing",
                    ANON_USER,
                )
        except Exception as e:
            print("[KaIA] aviso: não foi possível garantir o aluno anônimo:", e)

    # Scheduler: agrega features das sessões ativas a cada 30s.
    # Só inicia se houver banco — o job de agregação depende do pool.
    scheduler = None
    if app.state.pool is not None:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(job_agregacao, "interval", seconds=30, args=[app], id="agg_features")
        scheduler.start()
        print("[KaIA] Scheduler de agregação iniciado (a cada 30s).")

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
    if app.state.pool is not None:
        await app.state.pool.close()
        print("[KaIA] Pool encerrado.")


app = FastAPI(title="KaIA Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
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
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    platform: str = "web"
    app_version: str = "mvp-0.1"


@app.post("/sessions")
async def criar_sessao(body: SessionIn, request: Request):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    user_id = body.user_id or str(uuid.uuid4())
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Garante o aluno em `perfis` ANTES da sessão (FK sessions.user_id
            # -> perfis.user_id). Cria um perfil mínimo; o /perfil enriquece depois.
            await conn.execute(
                "insert into perfis (user_id) values ($1::uuid) on conflict (user_id) do nothing",
                user_id,
            )
            row = await conn.fetchrow(
                """
                insert into sessions (session_id, user_id, session_start_ts, platform, app_version)
                values (coalesce($1::uuid, gen_random_uuid()), $2::uuid, now(), $3, $4)
                on conflict (session_id) do nothing
                returning session_id, user_id
                """,
                body.session_id, user_id, body.platform, body.app_version,
            )
            # session_id já existia → ON CONFLICT não retorna; busca a existente
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
    if pool is None:
        return _SEM_BANCO
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
    if pool is None:
        return _SEM_BANCO
    payload_json = json.dumps(body.payload, ensure_ascii=False)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Garante a sessão pai (FK session_events.session_id -> sessions).
            # Fallback: se o evento chegar antes do /sessions, cria a sessão com
            # o aluno ANÔNIMO (satisfaz a FK sessions.user_id -> perfis). No fluxo
            # normal o /sessions já criou a sessão com o user_id real do aluno.
            await conn.execute(
                """
                insert into sessions (session_id, user_id, session_start_ts, platform, app_version)
                values ($1::uuid, $2::uuid, now(), 'web', 'mvp-0.1')
                on conflict (session_id) do nothing
                """,
                body.session_id, ANON_USER,
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
    if pool is None:
        return _SEM_BANCO
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


# ================== API: RESPONSÁVEL (estatísticas do aluno) ================
def _tendencia(valores, melhor_quando="sobe"):
    """Compara a média da 1ª metade da série com a da 2ª metade e devolve
    'melhorando' | 'piorando' | 'estavel' | 'sem_dados'. `melhor_quando` diz se
    valores MAIORES são bons ('sobe', ex: acertos) ou ruins ('desce', ex: aba)."""
    vals = [float(v) for v in valores if v is not None]
    if len(vals) < 2:
        return "sem_dados"
    meio = len(vals) // 2
    ini = sum(vals[:meio]) / max(meio, 1)
    fim = sum(vals[meio:]) / max(len(vals) - meio, 1)
    if abs(fim - ini) < 1e-9:
        return "estavel"
    subiu = fim > ini
    bom = subiu if melhor_quando == "sobe" else not subiu
    return "melhorando" if bom else "piorando"


def _demo_aluno(email):
    """Resposta de exemplo (sem banco) para o painel funcionar nesta rede.
    Série de 10 dias com tendência de melhora. Marcado com demo=True."""
    hoje = datetime.now(timezone.utc).date()
    series = []
    for d in range(10):
        frac = d / 9
        dia = hoje - timedelta(days=(9 - d))
        acertos = round(1 + frac * 6)              # 1 -> 7
        distracao = round(8 - frac * 6)            # 8 -> 2
        series.append({
            "dia": dia.isoformat(),
            "acertos": acertos,
            "tempo_resposta_ms": round(4000 - frac * 1500),
            "mudancas_aba": max(distracao - 1, 0),
            "tempo_fora_foco_s": round((distracao - 1) * 8.0, 1),
            "cliques_fora": 1 if distracao > 0 else 0,
            "distracao": distracao,
            "janelas": 5,
        })
    resumo = {
        "dias_com_dados": len(series),
        "total_acertos": sum(s["acertos"] for s in series),
        "tendencia_acertos": _tendencia([s["acertos"] for s in series], "sobe"),
        "tendencia_foco": _tendencia([s["distracao"] for s in series], "desce"),
    }
    return {
        "demo": True,
        "aluno": {
            "user_id": "00000000-0000-0000-0000-0000000000de",
            "email": email,
            "hobbies": ["Futebol", "Música", "Jogos"],
            "sequencia_dias_estudo": 10,
            "sessoes_no_dia": 1,
            "data_prova": (hoje + timedelta(days=30)).isoformat(),
            "ultima_sessao_ts": None,
        },
        "series": series,
        "resumo": resumo,
    }


@app.get("/responsavel/aluno")
async def stats_aluno(request: Request, email: Optional[str] = None, user_id: Optional[str] = None):
    """Painel do responsável: resolve o aluno por e-mail (ou user_id) e devolve a
    evolução diária das features de atenção/desempenho + uma leitura de tendência
    (o filho está melhorando?)."""
    if not email and not user_id:
        return JSONResponse({"erro": "Informe o e-mail (ou user_id) do aluno."}, status_code=400)

    pool = request.app.state.pool
    if pool is None:
        return _demo_aluno(email or "demo@kaia.com")
    async with pool.acquire() as conn:
        if not user_id:
            row = await conn.fetchrow(
                "select user_id from perfis where lower(email) = lower($1)", email
            )
            if row is None:
                return JSONResponse({"erro": "Aluno não encontrado."}, status_code=404)
            user_id = str(row["user_id"])

        aluno = await conn.fetchrow(
            """
            select user_id, email, hobbies, sequencia_dias_estudo, sessoes_no_dia,
                   data_prova, ultima_sessao_ts
            from perfis where user_id = $1::uuid
            """,
            user_id,
        )
        if aluno is None:
            return JSONResponse({"erro": "Aluno não encontrado."}, status_code=404)

        linhas = await conn.fetch(
            """
            select date(sf.window_ts)               as dia,
                   sum(sf.acertos_questoes)         as acertos,
                   avg(sf.tempo_resposta_ms)        as tempo_resposta_ms,
                   sum(sf.mudancas_aba)             as mudancas_aba,
                   sum(sf.tempo_fora_foco_s)        as tempo_fora_foco_s,
                   sum(sf.cliques_fora_area_estudo) as cliques_fora,
                   avg(sf.velocidade_scroll_px_s)   as scroll_px_s,
                   count(*)                         as janelas
            from session_features sf
            join sessions s on s.session_id = sf.session_id
            where s.user_id = $1::uuid
            group by date(sf.window_ts)
            order by dia
            """,
            user_id,
        )

    series = []
    for r in linhas:
        # distração agregada por dia: nº de trocas de aba + cliques fora da área
        distracao = int(r["mudancas_aba"] or 0) + int(r["cliques_fora"] or 0)
        series.append({
            "dia": r["dia"].isoformat(),
            "acertos": int(r["acertos"] or 0),
            "tempo_resposta_ms": round(float(r["tempo_resposta_ms"] or 0)),
            "mudancas_aba": int(r["mudancas_aba"] or 0),
            "tempo_fora_foco_s": round(float(r["tempo_fora_foco_s"] or 0), 1),
            "cliques_fora": int(r["cliques_fora"] or 0),
            "distracao": distracao,
            "janelas": int(r["janelas"] or 0),
        })

    hobbies = aluno["hobbies"]
    if isinstance(hobbies, str):
        try:
            hobbies = json.loads(hobbies)
        except (ValueError, TypeError):
            hobbies = []

    resumo = {
        "dias_com_dados": len(series),
        "total_acertos": sum(s["acertos"] for s in series),
        "tendencia_acertos": _tendencia([s["acertos"] for s in series], "sobe"),
        "tendencia_foco": _tendencia([s["distracao"] for s in series], "desce"),
    }

    return {
        "aluno": {
            "user_id": str(aluno["user_id"]),
            "email": aluno["email"],
            "hobbies": hobbies or [],
            "sequencia_dias_estudo": aluno["sequencia_dias_estudo"],
            "sessoes_no_dia": aluno["sessoes_no_dia"],
            "data_prova": aluno["data_prova"].isoformat() if aluno["data_prova"] else None,
            "ultima_sessao_ts": aluno["ultima_sessao_ts"].isoformat() if aluno["ultima_sessao_ts"] else None,
        },
        "series": series,
        "resumo": resumo,
    }


# ================== SEED: aluno de TESTE (para visualizar os gráficos) ======
# Cria/atualiza um aluno fixo (teste@kaia.com) e popula ~10 dias de
# session_features com uma tendência de MELHORA (acertos sobem, distração cai),
# para que o painel do responsável mostre gráficos com dados. Idempotente.
# Uso: POST /seed/aluno-teste  -> depois busque por "teste@kaia.com" no painel.
SEED_USER_ID = "11111111-1111-1111-1111-111111111111"
SEED_EMAIL = "teste@kaia.com"


@app.post("/seed/aluno-teste")
async def seed_aluno_teste(request: Request):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO

    hobbies = ["Futebol", "Música", "Jogos"]
    dias = 10
    agora = datetime.now(timezone.utc)
    prova = (agora + timedelta(days=30)).date()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1) Perfil do aluno
            await conn.execute(
                """
                insert into perfis (user_id, email, hobbies, data_prova,
                    ambiente_dispositivo, sequencia_dias_estudo, sessoes_no_dia,
                    ultimo_dia_estudo, ultima_sessao_ts, updated_at)
                values ($1::uuid, $2, $3::jsonb, $4, 'web', $5, 1, current_date, now(), now())
                on conflict (user_id) do update set
                    email = excluded.email,
                    hobbies = excluded.hobbies,
                    data_prova = excluded.data_prova,
                    sequencia_dias_estudo = excluded.sequencia_dias_estudo,
                    updated_at = now()
                """,
                SEED_USER_ID, SEED_EMAIL, json.dumps(hobbies, ensure_ascii=False), prova, dias,
            )

            # Limpa dados antigos do aluno de teste (idempotência)
            await conn.execute(
                """
                delete from session_features
                where session_id in (select session_id from sessions where user_id = $1::uuid)
                """,
                SEED_USER_ID,
            )
            await conn.execute("delete from sessions where user_id = $1::uuid", SEED_USER_ID)

            # 2) Sessões + features por dia (dia mais antigo -> hoje)
            JANELAS = 5
            total_janelas = 0
            for d in range(dias):
                dia = agora - timedelta(days=(dias - 1 - d))
                session_id = str(uuid.uuid4())
                inicio = dia.replace(hour=19, minute=0, second=0, microsecond=0)

                await conn.execute(
                    """
                    insert into sessions (session_id, user_id, session_start_ts,
                        session_end_ts, platform, app_version)
                    values ($1::uuid, $2::uuid, $3, $4, 'web', 'seed')
                    """,
                    session_id, SEED_USER_ID, inicio, inicio + timedelta(minutes=25),
                )

                frac = d / max(dias - 1, 1)            # 0.0 -> 1.0 (progresso)
                acertos = round(1 + frac * 6)          # 1 -> 7 acertos/dia
                distracao = round(8 - frac * 6)        # 8 -> 2 (cai = melhora)

                for j in range(JANELAS):
                    window_ts = inicio + timedelta(seconds=30 * j)
                    acertou = 1 if j < acertos else 0
                    trocas_aba = 1 if j < distracao else 0
                    cliques_fora = 1 if (distracao - JANELAS) > j else 0
                    await conn.execute(
                        """
                        insert into session_features
                            (session_id, horario_inicio, sessoes_no_dia, tempo_resposta_ms,
                             velocidade_scroll_px_s, pausas_digitacao_s, cliques_fora_area_estudo,
                             mudancas_aba, tempo_fora_foco_s, acertos_questoes,
                             nivel_dificuldade_atividade, window_ts)
                        values ($1::uuid, $2, 1, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        """,
                        session_id, window_ts.time(),
                        4000 - frac * 1500,            # tempo de resposta cai (mais rápido)
                        150.0, 2.0, cliques_fora, trocas_aba, trocas_aba * 8.0,
                        acertou, 1 + round(frac * 2), window_ts,
                    )
                    total_janelas += 1

    print(f"[KaIA Seed] aluno de teste {SEED_EMAIL}: {dias} dias, {total_janelas} janelas.")
    return {
        "status": "ok",
        "email": SEED_EMAIL,
        "user_id": SEED_USER_ID,
        "dias": dias,
        "janelas": total_janelas,
        "dica": f"Abra o painel do responsável e busque por: {SEED_EMAIL}",
    }


# ================== API: DADOS DO GRÁFICO DE HOBBIES ========================
# Conta quantas vezes cada hobby aparece nos perfis (coluna jsonb `hobbies`) e
# devolve no formato { labels: [...], valores: [...] } que o Chart.js espera.
@app.get("/api/dados-grafico")
async def dados_grafico(request: Request):
    pool = request.app.state.pool
    if pool is None:
        # Modo demonstração (sem banco): dados de exemplo só para a UI funcionar.
        return {
            "labels": ["Futebol", "Música", "Jogos", "Leitura", "Desenho"],
            "valores": [15, 22, 8, 11, 6],
            "demo": True,
        }
    async with pool.acquire() as conn:
        linhas = await conn.fetch(
            """
            select hb as hobby, count(*) as n
            from perfis, jsonb_array_elements_text(hobbies) as hb
            where jsonb_typeof(hobbies) = 'array'
            group by hb
            order by n desc, hb
            """
        )
    return {
        "labels": [r["hobby"] for r in linhas],
        "valores": [int(r["n"]) for r in linhas],
    }


# ================== API: DADOS DO DASHBOARD =================================
# Duas fontes possíveis, nesta ordem de prioridade:
#   1) data/KaIA_Base_Sintetica.xlsx  → base EXPERIMENTAL (600 sessões, 1 linha
#      por sessão, com as features de atenção e o rótulo `target`). O backend
#      AGREGA essa base nos blocos que o dashboard consome.
#   2) Backend/dados_dashboard.xlsx   → planilha manual (uma aba por bloco),
#      criada por `python gerar_planilha_dashboard.py`.
# Se nenhuma existir, o frontend cai no fallback de demonstração (script.js).
#
# ATENÇÃO: a base sintética NÃO tem dados financeiros. Os blocos `mrr_mensal`,
# `metas_fase` e `saude_financeira` (aba FINANCEIRO) não são emitidos aqui —
# o frontend preenche esses com o demo. Isso é intencional e sinalizado na UI.
BASE_SINTETICA = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "KaIA_Base_Sintetica.xlsx")
)
DASHBOARD_XLSX = os.path.join(os.path.dirname(__file__), "dados_dashboard.xlsx")

# Rótulos amigáveis para o `target` (mantém a ordem verde → amarelo → vermelho,
# que é a mesma ordem das cores do gráfico de rosca no frontend).
_TARGETS = [("engajado", "Engajado"), ("distraido", "Distraído"), ("muito_distraido", "Muito distraído")]

# Sinais de dispersão exibidos como barras: rótulo -> coluna da base.
# Cada um vira "intensidade média" = média / máximo observado (0–100%).
_SINAIS = [
    ("Trocas de aba",        "mudancas_aba"),
    ("Cliques fora da área", "cliques_fora_area_estudo"),
    ("Pausas de digitação",  "pausas_digitacao_s"),
    ("Velocidade de scroll", "velocidade_scroll_px_s"),
]


def _agregar_base_sintetica(df):
    """Transforma a base (1 linha = 1 sessão) nos blocos que o dashboard espera."""
    total = len(df)
    pct = lambda n: round(100.0 * n / total, 1) if total else 0.0

    df = df.copy()
    df["hora"] = df["horario_estudo"].dt.hour
    df["dia"] = df["horario_estudo"].dt.date

    # --- sessões por hora + "alertas" (sessões muito distraídas) ---
    por_hora = df.groupby("hora").size()
    alertas_hora = df[df["target"] == "muito_distraido"].groupby("hora").size()
    sessoes_hora = [
        {"hora": f"{h}h", "sessoes": int(por_hora.get(h, 0)), "alertas": int(alertas_hora.get(h, 0))}
        for h in range(24)
    ]

    # --- distribuição de perfis (ocupa o slot do gráfico de "planos") ---
    perfis = [{"plano": str(k), "percentual": pct(v)} for k, v in df["perfil"].value_counts().items()]

    # --- sessões mais recentes ---
    recentes = df.sort_values("horario_estudo", ascending=False).head(6)
    alunos_recentes = [
        {
            "aluno": str(r.session_id),
            "plano": str(r.perfil),
            "foco": f"{int(r.acertos_questoes)}/10",
            "tema": str(r.tipo_atividade),
        }
        for r in recentes.itertuples()
    ]

    # --- sessões com maior dispersão viram os "alertas recentes" ---
    nivel = {"muito_distraido": "vermelho", "distraido": "amarelo", "engajado": "verde"}
    piores = df.sort_values(["mudancas_aba", "tempo_fora_foco_s"], ascending=False).head(4)
    alertas_recentes = [
        {
            "nivel": nivel.get(r.target, "amarelo"),
            "mensagem": f"{r.session_id} — {int(r.mudancas_aba)} trocas de aba · {r.tempo_fora_foco_s:.0f}s fora de foco",
            "tempo": str(r.perfil),
        }
        for r in piores.itertuples()
    ]

    # --- sessões por dia: iniciadas vs. concluídas (1 - taxa de abandono) ---
    por_dia = df.groupby("dia").agg(
        iniciadas=("session_id", "size"), abandono=("taxa_abandono_sessao", "mean")
    )
    sessoes_dia = [
        {
            "data": d.strftime("%d/%m"),
            "iniciadas": int(r.iniciadas),
            "concluidas": int(round(r.iniciadas * (1 - r.abandono))),
        }
        for d, r in por_dia.iterrows()
    ]

    # --- tipos de atividade (ocupa o slot de "temas estudados") ---
    # Rótulos legíveis: a base guarda em snake_case (video_aula, exercicios).
    rotulos = {
        "leitura": "Leitura", "exercicios": "Exercícios", "simulado": "Simulado",
        "video_aula": "Vídeo-aula", "quiz": "Quiz",
    }
    atividades = [
        {"tema": rotulos.get(str(k), str(k)), "sessoes": int(v)}
        for k, v in df["tipo_atividade"].value_counts().items()
    ]

    # --- distribuição do target ---
    cont = df["target"].value_counts()
    distribuicao = [{"faixa": rot, "percentual": pct(int(cont.get(chave, 0)))} for chave, rot in _TARGETS]

    # --- sinais de dispersão: média relativa ao pico observado ---
    eventos = []
    for rotulo, col in _SINAIS:
        pico = float(df[col].max())
        media = float(df[col].mean())
        eventos.append({"tipo": rotulo, "percentual": round(100.0 * media / pico) if pico else 0})

    # --- engajamento (%) por hora ---
    eng = df.assign(_e=(df["target"] == "engajado").astype(int)).groupby("hora")["_e"].mean() * 100
    foco_hora = [{"hora": f"{h}h", "foco": round(float(eng.get(h, 0.0)), 1)} for h in range(24)]

    # --- KPIs (a aba FINANCEIRO não é emitida: a base não tem receita) ---
    p_eng = pct(int(cont.get("engajado", 0)))
    p_dis = pct(int(cont.get("distraido", 0)))
    p_mui = pct(int(cont.get("muito_distraido", 0)))
    kpis = [
        {"view": "geral", "icone": "layers", "rotulo": "SESSÕES ANALISADAS", "valor": f"{total}",
         "subtexto": "base sintética"},
        {"view": "geral", "icone": "smile", "rotulo": "ENGAJAMENTO", "valor": f"{p_eng}%",
         "subtexto": "sessões rotuladas engajado", "cor": "verde"},
        {"view": "geral", "icone": "check", "rotulo": "ACERTOS MÉDIOS",
         "valor": f"{df['acertos_questoes'].mean():.1f}/10".replace(".", ","), "subtexto": "por sessão"},
        {"view": "geral", "icone": "alert", "rotulo": "ABANDONO MÉDIO",
         "valor": f"{df['taxa_abandono_sessao'].mean()*100:.0f}%", "subtexto": "taxa média da sessão",
         "cor": "vermelho"},

        {"view": "sessoes", "icone": "clock", "rotulo": "DURAÇÃO MÉDIA",
         "valor": f"{df['duracao_sessao_min'].mean():.0f} min", "subtexto": "por sessão"},
        {"view": "sessoes", "icone": "list", "rotulo": "TEMPO DE RESPOSTA",
         "valor": f"{df['tempo_resposta_ms'].mean()/1000:.1f}s".replace(".", ","), "subtexto": "média por questão"},
        {"view": "sessoes", "icone": "target", "rotulo": "DIFICULDADE MÉDIA",
         "valor": f"{df['nivel_dificuldade_atividade'].mean():.1f}/5".replace(".", ","), "subtexto": "nível da atividade"},
        {"view": "sessoes", "icone": "calendar", "rotulo": "DIAS COBERTOS",
         "valor": f"{df['dia'].nunique()}", "subtexto": "período da base"},

        {"view": "atencao", "icone": "smile", "rotulo": "ENGAJADO", "valor": f"{p_eng}%",
         "subtexto": "do total de sessões", "cor": "verde"},
        {"view": "atencao", "icone": "meh", "rotulo": "DISTRAÍDO", "valor": f"{p_dis}%",
         "subtexto": "do total de sessões", "cor": "amarelo"},
        {"view": "atencao", "icone": "frown", "rotulo": "MUITO DISTRAÍDO", "valor": f"{p_mui}%",
         "subtexto": "do total de sessões", "cor": "vermelho"},
        {"view": "atencao", "icone": "bolt", "rotulo": "TEMPO FORA DE FOCO",
         "valor": f"{df['tempo_fora_foco_s'].mean():.0f}s", "subtexto": "média por sessão"},
    ]

    return {
        "fonte": "base_sintetica",
        "total_sessoes": total,
        "periodo": f"{df['dia'].min():%d/%m/%Y} — {df['dia'].max():%d/%m/%Y}",
        "kpis": kpis,
        "sessoes_hora": sessoes_hora,
        "planos": perfis,
        "alunos_recentes": alunos_recentes,
        "alertas_recentes": alertas_recentes,
        "sessoes_14dias": sessoes_dia,
        "temas_estudados": atividades,
        "distribuicao_foco": distribuicao,
        "eventos_tipo": eventos,
        "foco_hora": foco_hora,
    }


@app.get("/dashboard/dados")
def dashboard_dados():
    try:
        import pandas as pd
    except ImportError:
        return JSONResponse(
            {"erro": "pandas não instalado. Rode: pip install -r requirements.txt"},
            status_code=500,
        )

    # 1) Base experimental (prioridade)
    if os.path.exists(BASE_SINTETICA):
        try:
            df = pd.read_excel(BASE_SINTETICA)
            return _agregar_base_sintetica(df)
        except Exception as e:
            print("[KaIA] erro ao agregar a base sintética:", e)
            return JSONResponse({"erro": "Não foi possível ler a base sintética."}, status_code=500)

    # 2) Planilha manual (uma aba por bloco)
    if os.path.exists(DASHBOARD_XLSX):
        try:
            planilhas = pd.read_excel(DASHBOARD_XLSX, sheet_name=None)
        except Exception as e:
            print("[KaIA] erro ao ler dados_dashboard.xlsx:", e)
            return JSONResponse({"erro": "Não foi possível ler a planilha."}, status_code=500)
        saida = {"fonte": "planilha_manual"}
        for nome, df in planilhas.items():
            if nome.startswith("_"):      # ignora abas auxiliares (ex: _LEIA-ME)
                continue
            df = df.where(pd.notnull(df), None)   # NaN → None (JSON válido)
            saida[nome] = df.to_dict(orient="records")
        return saida

    # 3) Nada encontrado → frontend usa o demo
    return {"vazio": True, "motivo": "nenhuma planilha encontrada"}


# ================== HEALTHCHECK =============================================
@app.get("/")
def health():
    return {"status": "KaIA backend no ar"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
