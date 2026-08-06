from contextlib import asynccontextmanager
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
import os
import re
import json
import asyncio
import pickle
import uuid

import asyncpg
import pandas as pd
import requests

from statistics import mean, pstdev

from thompson import ThompsonSampling, INTERVENCOES
from auth import usuario_autenticado
from mouse_features import features_mouse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Body, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional

# --- Inicialização ------------------------------------------------------------
load_dotenv()
# Aceita os dois nomes: API_KEY (prod/CI) ou CHAVE_ACESSO (.env local).
API_KEY = os.getenv("API_KEY") or os.getenv("CHAVE_ACESSO")
DATABASE_URL = os.getenv("DATABASE_URL")

# Sessão sem NENHUM evento há mais de STALE_SESSAO_MIN minutos é encerrada pelo
# sweep do scheduler (evita lixo de abas esquecidas/travadas). Ajustável por env
# em produção sem tocar no código: STALE_SESSAO_MIN=30 no .env, por exemplo.
STALE_SESSAO_MIN = int(os.getenv("STALE_SESSAO_MIN", "15"))

ANON_USER = "00000000-0000-0000-0000-000000000000"

# Sigla → nome da matéria. Fonte única: o frontend manda a SIGLA (ex.: "QUI") e
# os prompts usam o NOME por extenso ("Química") — senão o Gemini teria que
# adivinhar a sigla. A sigla continua sendo a chave do cache (temas_cache) e da
# sessão. Para adicionar uma matéria, basta uma linha aqui + o card no frontend.
MATERIAS = {
    "MAT":  "Matemática",
    "PORT": "Português",
    "HIS":  "História",
    "GEO":  "Geografia",
    "BIO":  "Biologia",
    "FIS":  "Física",
    "QUI":  "Química",
    "ING":  "Inglês",
    "FIL":  "Filosofia",
    "SOC":  "Sociologia",
}

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

    # Carrega o modelo RF + scaler UMA única vez (não a cada request). O modelo
    # vive em ml/models/ e o scaler em ml/artifacts/. Tolerante a falha: se não
    # carregar, o /diagnose responde 503 e o resto do app segue funcionando.
    app.state.modelo = None
    app.state.scaler = None
    try:
        ROOT = Path(__file__).resolve().parent.parent
        with open(ROOT / "ml" / "models" / "modelo_rf_v2.pkl", "rb") as f:
            app.state.modelo = pickle.load(f)
        with open(ROOT / "ml" / "artifacts" / "scaler_v2.pkl", "rb") as f:
            app.state.scaler = pickle.load(f)
        print("[KaIA] Modelo RF v2 + scaler carregados no startup.")
    except Exception as e:
        print("[KaIA] AVISO: não foi possível carregar modelo/scaler:", e)

    # Thompson Sampling (bandit das 9 intervenções) — carrega params persistidos.
    try:
        app.state.thompson = ThompsonSampling()
        print("[KaIA] Thompson Sampling carregado (9 intervenções).")
    except Exception as e:
        app.state.thompson = None
        print("[KaIA] AVISO: não foi possível iniciar Thompson Sampling:", e)

    # Scheduler: agrega features das sessões ativas a cada 30s.
    # Só inicia se houver banco — o job de agregação depende do pool.
    scheduler = None
    if app.state.pool is not None:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(job_agregacao, "interval", seconds=30, args=[app], id="agg_features")
        # Sweep de sessões ociosas: mais leve, a cada 5 min.
        scheduler.add_job(encerrar_sessoes_ociosas, "interval", minutes=5, args=[app], id="sweep_sessoes")
        scheduler.start()
        print(f"[KaIA] Scheduler iniciado (agregação 30s · sweep de sessões ociosas 5min, "
              f"limiar {STALE_SESSAO_MIN}min).")

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
@app.post("/perguntar", dependencies=[Depends(usuario_autenticado)])
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


# ================== API: TEMAS de uma matéria ===============================
# Cache em `temas_cache` (materia PK, temas jsonb): a geração dos temas custa 1
# requisição ao Gemini (free tier: 20/dia). Cacheado, cada matéria gasta no
# máximo 1 chamada na vida — e a tela de temas passa a abrir instantânea.
@app.post("/temas", dependencies=[Depends(usuario_autenticado)])
async def temas(request: Request, refresh: bool = False, dados: dict = Body(default={})):
    materia = (dados.get("materia") or "").strip()
    pool = request.app.state.pool

    async def ler_cache():
        if pool is None or not materia:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow("select temas from temas_cache where materia = $1", materia)
        if not row:
            return None
        cache = row["temas"]
        if isinstance(cache, str):   # jsonb volta como string no asyncpg
            cache = json.loads(cache)
        return cache or None

    # 1) Cache hit → devolve sem tocar no Gemini (salvo ?refresh=true).
    if not refresh:
        cache = await ler_cache()
        if cache:
            return {"temas": cache, "fonte": "cache"}

    # 2) Miss (ou refresh) → chama a IA. run_in_threadpool: chamar_gemini é
    # bloqueante (requests) e a rota é async — não pode travar o event loop.
    # O prompt usa o NOME por extenso e pede os temas de MAIOR INCIDÊNCIA no
    # ENEM, em formato curto (≤4 palavras, sem parênteses) p/ caber no card.
    nome = MATERIAS.get(materia, materia)
    prompt = (
        f"Liste os 6 temas de {nome} de MAIOR INCIDÊNCIA na prova do ENEM e nos "
        "principais vestibulares brasileiros — os conteúdos que MAIS CAEM, não uma "
        "lista genérica da matéria.\n"
        "Regras de formato (siga à risca):\n"
        "- No máximo 4 palavras por tema.\n"
        "- SEM parênteses, SEM subtítulos, SEM exemplos ou listas dentro do tema.\n"
        "- Nomes curtos e diretos. Ex.: \"Estequiometria\", \"Análise Sintática\", "
        "\"Termoquímica\".\n"
        "Responda APENAS com um array JSON de 6 strings, sem texto extra."
    )
    try:
        lista = extrair_json(await run_in_threadpool(chamar_gemini, prompt))
        if not isinstance(lista, list) or not lista:
            raise ValueError("resposta sem lista de temas")
    except Exception as e:
        print("[KaIA] erro /temas:", e)
        # 2b) IA falhou, mas há cache antigo → devolve o cache (salva os testes
        # quando a quota do Gemini estoura).
        cache = await ler_cache()
        if cache:
            return {"temas": cache, "fonte": "cache_stale"}
        return JSONResponse(
            {"temas": [], "erro": "Não foi possível carregar os temas."}, status_code=502
        )

    # 3) Grava/atualiza o cache (best-effort: não derruba a resposta se falhar).
    if pool is not None and materia:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    insert into temas_cache (materia, temas, updated_at)
                    values ($1, $2::jsonb, now())
                    on conflict (materia) do update set
                        temas = excluded.temas, updated_at = now()
                    """,
                    materia, json.dumps(lista, ensure_ascii=False),
                )
        except Exception as e:
            print("[KaIA] aviso: não foi possível gravar o cache de temas:", e)

    return {"temas": lista, "fonte": "ia"}


# ================== API: ANOTAÇÕES (caderno do aluno por tema) ================
# Canvas de anotações da tela de estudo (Etapa 9a — só texto). Uma linha por
# (aluno_id, tema); os elementos ficam num array jsonb. Só o backend acessa a
# tabela `anotacoes` (RLS ligado, SEM policy para a anon key) — o isolamento por
# aluno é o `where aluno_id = $1` daqui. Sem Supabase Auth, é o mesmo modelo de
# confiança do resto do app: convém, não é segurança forte (ver Etapa 10).
@app.get("/anotacoes", dependencies=[Depends(usuario_autenticado)])
async def obter_anotacoes(request: Request, aluno_id: str = "", tema: str = ""):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    aluno_id, tema = aluno_id.strip(), tema.strip()
    if not aluno_id or not tema:
        return JSONResponse({"erro": "aluno_id e tema são obrigatórios."}, status_code=400)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "select elementos from anotacoes where aluno_id = $1 and tema = $2",
                aluno_id, tema,
            )
    except Exception as e:
        print("[KaIA] erro ao ler anotações:", e)
        return JSONResponse(
            {"elementos": [], "erro": "Falha ao carregar as anotações."}, status_code=502
        )
    elementos = row["elementos"] if row else []
    if isinstance(elementos, str):   # jsonb volta como string no asyncpg
        elementos = json.loads(elementos)
    return {"elementos": elementos or []}


class AnotacoesIn(BaseModel):
    aluno_id: str
    tema: str
    elementos: list = []


@app.put("/anotacoes", dependencies=[Depends(usuario_autenticado)])
async def salvar_anotacoes(body: AnotacoesIn, request: Request):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    aluno_id, tema = body.aluno_id.strip(), body.tema.strip()
    if not aluno_id or not tema:
        return JSONResponse({"erro": "aluno_id e tema são obrigatórios."}, status_code=400)
    # 9a é só texto: filtra defensivamente qualquer outro tipo. Imagem só entra
    # no 9b, junto com o pipeline de Storage (bucket + signed URL).
    elementos = [
        e for e in (body.elementos or [])
        if isinstance(e, dict) and e.get("tipo") == "texto"
    ]
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                insert into anotacoes (aluno_id, tema, elementos, atualizado)
                values ($1, $2, $3::jsonb, now())
                on conflict (aluno_id, tema) do update set
                    elementos = excluded.elementos, atualizado = now()
                """,
                aluno_id, tema, json.dumps(elementos, ensure_ascii=False),
            )
    except Exception as e:
        print("[KaIA] erro ao salvar anotações:", e)
        return JSONResponse({"ok": False, "erro": "Falha ao salvar."}, status_code=502)
    return {"ok": True, "salvos": len(elementos)}


# ================== API: ESTATÍSTICAS DO PERFIL (Etapa 4.1 Parte 2) ==========
# Modelo C (híbrido): BASE semanal (desempenho_semanal — cobertura ampla, 224/224)
# + COMPLEMENTO ao vivo (session_features, só quando há sessão) + análise curta
# baseada em REGRAS sobre os dados semanais (sem IA, sem placeholder).
def _analise_regras(base, por_materia):
    """Frases curtas e HONESTAS derivadas de desempenho_semanal (sem IA)."""
    frases = []
    at = base["atencao"]
    if at >= 70:
        frases.append(f"Sua atenção média está ótima: {at}%. Continue assim.")
    elif at >= 50:
        frases.append(f"Sua atenção média é {at}% — dá para melhorar com sessões mais curtas e focadas.")
    else:
        frases.append(f"Sua atenção média está baixa ({at}%). Tente blocos curtos com pausas guiadas.")

    if por_materia:
        melhor, pior = por_materia[0], por_materia[-1]
        frases.append(f"Seu melhor tema é {melhor['materia']}: {melhor['acerto']}% de acerto.")
        if len(por_materia) > 1 and pior["acerto"] < melhor["acerto"]:
            frases.append(f"Ponto de atenção: {pior['materia']} ({pior['acerto']}% de acerto) — vale revisar.")
    return frases


@app.get("/perfil/estatisticas", dependencies=[Depends(usuario_autenticado)])
async def perfil_estatisticas(request: Request, aluno_id: str = ""):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    aluno_id = aluno_id.strip()
    if not aluno_id:
        return JSONResponse({"erro": "aluno_id é obrigatório."}, status_code=400)

    try:
        async with pool.acquire() as conn:
            # BASE: agregado semanal (média de atenção/acerto, média de minutos/semana)
            base = await conn.fetchrow(
                """
                select round(avg(media_atencao) * 100)::int atencao,
                       round(avg(taxa_acerto)  * 100)::int acerto,
                       -- minutos POR SEMANA: soma de todas as matérias ÷ nº de semanas
                       round(sum(minutos_estudados)::numeric
                             / nullif(count(distinct semana), 0))::int min_semana,
                       count(distinct semana)  semanas,
                       count(distinct materia) materias,
                       count(*) linhas
                from desempenho_semanal where aluno_id = $1::uuid
                """,
                aluno_id,
            )
            por_materia = await conn.fetch(
                """
                select materia, round(avg(taxa_acerto) * 100)::int acerto
                from desempenho_semanal where aluno_id = $1::uuid
                group by materia order by acerto desc
                """,
                aluno_id,
            )
            # COMPLEMENTO: última sessão ao vivo (ou nada)
            ult = await conn.fetchrow(
                """
                select sf.tempo_resposta_ms, sf.velocidade_scroll_px_s, sf.mudancas_aba,
                       sf.tempo_fora_foco_s, sf.cliques_fora_area_estudo, sf.window_ts
                from session_features sf join sessions s on s.session_id = sf.session_id
                where s.user_id = $1::uuid order by sf.window_ts desc limit 1
                """,
                aluno_id,
            )
    except Exception as e:
        print("[KaIA] erro em /perfil/estatisticas:", e)
        return JSONResponse({"erro": "Falha ao carregar estatísticas."}, status_code=502)

    desempenho, analise = None, []
    if base and base["linhas"]:
        desempenho = {
            "atencao": base["atencao"], "acerto": base["acerto"],
            "min_semana": base["min_semana"], "semanas": base["semanas"],
            "materias": base["materias"],
        }
        analise = _analise_regras(base, [dict(r) for r in por_materia])

    ultima_sessao = None
    if ult:
        ultima_sessao = {
            "tempo_resposta_ms": ult["tempo_resposta_ms"],
            "velocidade_scroll_px_s": ult["velocidade_scroll_px_s"],
            "mudancas_aba": ult["mudancas_aba"],
            "tempo_fora_foco_s": ult["tempo_fora_foco_s"],
            "cliques_fora_area_estudo": ult["cliques_fora_area_estudo"],
            "quando": ult["window_ts"].strftime("%d/%m às %H:%M"),
        }

    return {"desempenho": desempenho, "ultima_sessao": ultima_sessao, "analise": analise}


# ================== API: GERAR QUESTÃO objetiva =============================
# ==== META DIÁRIA (questões respondidas hoje) ====
META_QUESTOES_DIA = 10

@app.get("/questoes/hoje", dependencies=[Depends(usuario_autenticado)])
async def questoes_hoje(request: Request, user_id: str = ""):
    """Conta as questões respondidas HOJE por um aluno (eventos question_answer),
    para a barra de meta diária da página de estudo."""
    pool = request.app.state.pool
    if pool is None:
        return {"respondidas_hoje": 0, "meta": META_QUESTOES_DIA}
    user_id = user_id.strip()
    if not user_id:
        return JSONResponse({"erro": "user_id é obrigatório."}, status_code=400)
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            """
            select count(*)
            from session_events se
            join sessions s on s.session_id = se.session_id
            where s.user_id = $1::uuid
              and se.event_type = 'question_answer'
              and se.ts::date = current_date
            """,
            user_id,
        )
    return {"respondidas_hoje": int(n or 0), "meta": META_QUESTOES_DIA}


# Alinha porque_erradas a opts (o frontend acessa por índice) e garante explicacao.
def _normalizar_questao(questao):
    opts = questao.get("opts") or []
    pe = questao.get("porque_erradas")
    if not isinstance(pe, list) or len(pe) != len(opts):
        questao["porque_erradas"] = [
            (pe[i] if isinstance(pe, list) and i < len(pe) else "")
            for i in range(len(opts))
        ]
    questao.setdefault("explicacao", "")
    return questao

# Formato EXATO de cada questão (string literal — as chaves NÃO são interpoladas).
_FORMATO_QUESTAO = (
    '{"q": "enunciado da questão", "opts": ["a", "b", "c", "d", "e"], "ans": 0,\n'
    '  "explicacao": "por que a alternativa correta é a correta (1 a 2 frases)",\n'
    '  "porque_erradas": ["por que a opção 0 está errada", "...opção 1...", "...", "...", "..."]}'
)

# Descrição da dificuldade por nível (1..5) para o prompt do Gemini (Parte 6).
_NIVEIS_DIF = {
    1: "muito fácil — conceito básico, direto ao ponto",
    2: "fácil",
    3: "médio, no padrão do ENEM",
    4: "difícil — exige interpretação e mais de um passo",
    5: "muito difícil — pegadinhas e raciocínio elaborado",
}

# Formato com a marca usa_hobbie (para o cache saber quais salvar com hobbie).
_FORMATO_QUESTAO_HOBBIE = (
    '{"q": "enunciado", "opts": ["a","b","c","d","e"], "ans": 0,\n'
    '  "explicacao": "por que a correta é a correta (1 a 2 frases)",\n'
    '  "porque_erradas": ["por que a opção 0 erra", "...", "...", "...", "..."],\n'
    '  "usa_hobbie": true}'
)

# Linha do cache -> formato que o frontend consome (inclui questao_id).
def _row_para_questao(row):
    return {
        "questao_id": str(row["questao_id"]),
        "q": row["enunciado"],
        "opts": json.loads(row["alternativas"]),
        "ans": row["resposta_correta"],
        "explicacao": row["explicacao"],
        "porque_erradas": json.loads(row["porque_erradas"]),
    }

# Só os campos que o frontend precisa (tira usa_hobbie e afins).
def _frontend_q(q):
    return {
        "q": q.get("q", ""),
        "opts": q.get("opts", []),
        "ans": q.get("ans", 0),
        "explicacao": q.get("explicacao", ""),
        "porque_erradas": q.get("porque_erradas", []),
    }

# Gera `n` questões no Gemini (roda em thread p/ não travar o loop). Com hobbie,
# instrui ~60% a usá-lo e a marcar "usa_hobbie" (Parte 5).
async def _gerar_no_gemini(n, materia, nome, tema, hobbie, nivel):
    dificuldade = _NIVEIS_DIF[max(1, min(nivel, 5))]
    if hobbie:
        proporcao = max(1, round(n * 0.6))
        formato = _FORMATO_QUESTAO_HOBBIE
        regra_hobbie = (
            f'- Use o hobbie "{hobbie}" no enunciado de aproximadamente {proporcao} das {n} '
            f'questões; nas outras, faça enunciados genéricos (sem citar o hobbie).\n'
            f'- Em CADA questão inclua o booleano "usa_hobbie" indicando se usou o hobbie.\n'
        )
    else:
        formato = _FORMATO_QUESTAO
        regra_hobbie = ''
    prompt = f"""
Crie {n} questões objetivas DIFERENTES de múltipla escolha sobre "{tema}" ({nome})
para o ensino médio.
Responda APENAS com um ARRAY JSON de {n} objetos, cada um no formato EXATO:
{formato}
Regras:
- "ans" é o índice (0 a 4) da alternativa correta.
- "porque_erradas" tem EXATAMENTE o tamanho e a ordem de "opts"; no índice da correta use "".
- As {n} questões devem ser distintas entre si (enunciados e focos diferentes).
- Dificuldade: nível {nivel}/5 ({dificuldade}) — calibre a esse nível.
{regra_hobbie}- Linguagem simples e acolhedora — o erro não é punição, é aprendizado.
"""
    try:
        dados_ia = extrair_json(await asyncio.to_thread(chamar_gemini, prompt))
        if isinstance(dados_ia, list):
            itens = dados_ia
        elif isinstance(dados_ia, dict) and "questoes" in dados_ia:
            itens = dados_ia["questoes"]
        elif isinstance(dados_ia, dict) and dados_ia.get("opts"):
            itens = [dados_ia]                      # resposta de questão única
        else:
            itens = []
        return [_normalizar_questao(q) for q in itens if isinstance(q, dict) and q.get("opts")]
    except Exception as e:
        print("[KaIA] erro Gemini /gerar-questao:", e)
        return []

# Busca no cache até `limite` questões (materia+tema+nivel+hobbie) NÃO vistas pelo
# aluno. `excluir`: ids já coletados nesta mesma chamada (evita duplicar no lote).
async def _buscar_cache(conn, user_id, materia, tema, nivel, hobbie, limite, excluir=None):
    if limite <= 0:
        return []
    params = [materia, tema, nivel]
    cond_hobbie = "c.hobbie is null"
    if hobbie is not None:
        params.append(hobbie)
        cond_hobbie = f"c.hobbie = ${len(params)}"
    params.append(user_id)
    uid = len(params)
    excl_sql = ""
    if excluir:
        params.append(list(excluir))
        excl_sql = f"and c.questao_id <> all(${len(params)}::uuid[])"
    params.append(limite)
    lim = len(params)
    rows = await conn.fetch(f"""
        select c.questao_id, c.enunciado, c.alternativas, c.resposta_correta, c.explicacao, c.porque_erradas
        from questoes_cache c
        where c.materia = $1 and c.tema = $2 and c.nivel = $3 and {cond_hobbie}
          and not exists (select 1 from questoes_vistas v
                          where v.aluno_id = ${uid}::uuid and v.questao_id = c.questao_id)
          {excl_sql}
        order by random() limit ${lim}
    """, *params)
    return [_row_para_questao(r) for r in rows]

# Salva no cache as questões geradas (Parte 4). Erro ao salvar NÃO bloqueia a entrega.
# usa_hobbie decide salvar com o hobbie ou como genérica (hobbie NULL) — Parte 5.
async def _salvar_no_cache(conn, materia, tema, nivel, hobbie_sessao, questoes):
    salvas = []
    for q in questoes:
        usou = bool(q.get("usa_hobbie")) if hobbie_sessao else False
        hob = hobbie_sessao if usou else None
        item = _frontend_q(q)
        try:
            qid = await conn.fetchval(
                """insert into questoes_cache
                     (materia, tema, nivel, hobbie, enunciado, alternativas,
                      resposta_correta, explicacao, porque_erradas)
                   values ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9::jsonb)
                   returning questao_id""",
                materia, tema, nivel, hob, item["q"], json.dumps(item["opts"]),
                item["ans"], item["explicacao"], json.dumps(item["porque_erradas"]))
            item["questao_id"] = str(qid)
        except Exception as e:
            print("[KaIA] erro ao salvar no cache:", e)   # entrega mesmo assim
        salvas.append(item)
    return salvas

# Marca as questões entregues como vistas pelo aluno (ignora as sem questao_id).
async def _marcar_vistas(conn, user_id, questoes):
    ids = [q["questao_id"] for q in questoes if q.get("questao_id")]
    if not ids:
        return
    try:
        await conn.execute(
            "insert into questoes_vistas (aluno_id, questao_id) "
            "select $1::uuid, x from unnest($2::uuid[]) as x on conflict do nothing",
            user_id, ids)
    except Exception as e:
        print("[KaIA] erro ao marcar vistas:", e)

# Esgotou as questões da combinação? Libera as vistas há +30 dias (Parte 7).
async def _resetar_vistas_antigas(conn, user_id, materia, tema, nivel):
    try:
        await conn.execute("""
            delete from questoes_vistas v
            using questoes_cache c
            where v.questao_id = c.questao_id and v.aluno_id = $1::uuid
              and c.materia = $2 and c.tema = $3 and c.nivel = $4
              and v.visto_em < now() - interval '30 days'
        """, user_id, materia, tema, nivel)
    except Exception as e:
        print("[KaIA] erro ao resetar vistas antigas:", e)


@app.post("/gerar-questao", dependencies=[Depends(usuario_autenticado)])
async def gerar_questao(request: Request, dados: dict = Body(default={})):
    materia = dados.get("materia", "")
    nome = MATERIAS.get(materia, materia)
    tema = dados.get("tema", "")
    hobbie = dados.get("hobbie") or None                 # singular; None = genérica
    user_id = (dados.get("user_id") or "").strip() or None
    # compat com o formato antigo (lista "hobbies"): usa o 1º como hobbie.
    if hobbie is None and isinstance(dados.get("hobbies"), list) and dados["hobbies"]:
        hobbie = dados["hobbies"][0]

    qtd_raw = dados.get("quantidade")
    lote = qtd_raw is not None
    try:
        n = max(1, min(int(qtd_raw), 10)) if lote else 1
    except (TypeError, ValueError):
        lote, n = True, 5
    try:
        nivel = max(1, min(int(dados.get("nivel", 3)), 5))
    except (TypeError, ValueError):
        nivel = 3

    pool = getattr(request.app.state, "pool", None)

    # Sem banco ou sem user_id: sem cache — gera tudo no Gemini (comportamento antigo).
    if pool is None or not user_id:
        entregues = [_frontend_q(q) for q in await _gerar_no_gemini(n, materia, nome, tema, hobbie, nivel)]
        if not entregues:
            return JSONResponse({"erro": "Não foi possível gerar a questão."}, status_code=502)
        return {"questoes": entregues} if lote else entregues[0]

    entregues = []
    try:
        async with pool.acquire() as conn:
            # 1) cache com o hobbie da vez
            if hobbie:
                entregues += await _buscar_cache(conn, user_id, materia, tema, nivel, hobbie, n)
            # 2) completa com genéricas (hobbie NULL)
            if len(entregues) < n:
                entregues += await _buscar_cache(conn, user_id, materia, tema, nivel, None, n - len(entregues))
            # 3) esgotou? libera as vistas antigas (>30d) e tenta o cache de novo (Parte 7).
            #    `excluir` os ids já coletados evita repetir a mesma questão no lote.
            if len(entregues) < n:
                await _resetar_vistas_antigas(conn, user_id, materia, tema, nivel)
                if hobbie:
                    ja = [q["questao_id"] for q in entregues if q.get("questao_id")]
                    entregues += await _buscar_cache(conn, user_id, materia, tema, nivel, hobbie, n - len(entregues), ja)
                if len(entregues) < n:
                    ja = [q["questao_id"] for q in entregues if q.get("questao_id")]
                    entregues += await _buscar_cache(conn, user_id, materia, tema, nivel, None, n - len(entregues), ja)
            # 4) ainda falta -> Gemini + salva no cache
            if n - len(entregues) > 0:
                novas = await _gerar_no_gemini(n - len(entregues), materia, nome, tema, hobbie, nivel)
                entregues += await _salvar_no_cache(conn, materia, tema, nivel, hobbie, novas)
            # 5) marca as entregues como vistas
            await _marcar_vistas(conn, user_id, entregues)
    except Exception as e:
        print("[KaIA] erro no cache /gerar-questao:", e)

    if not entregues:
        return JSONResponse({"erro": "Não foi possível gerar a questão."}, status_code=502)
    return {"questoes": entregues} if lote else entregues[0]


# Devolve ao pool as questões que o aluno recebeu mas NÃO usou (mudou de nível,
# trocou de tema ou encerrou) — remove de questoes_vistas (Parte 6). Ignora ids
# ausentes (questões de fallback/pré-cache).
@app.post("/questoes/devolver", dependencies=[Depends(usuario_autenticado)])
async def devolver_questoes(request: Request, dados: dict = Body(default={})):
    pool = request.app.state.pool
    if pool is None:
        return {"devolvidas": 0}
    user_id = (dados.get("user_id") or "").strip()
    ids = [x for x in (dados.get("questao_ids") or []) if x]
    if not user_id or not ids:
        return {"devolvidas": 0}
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "delete from questoes_vistas where aluno_id = $1::uuid and questao_id = any($2::uuid[])",
                user_id, ids)
        return {"devolvidas": len(ids)}
    except Exception as e:
        print("[KaIA] erro /questoes/devolver:", e)
        return {"devolvidas": 0}


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
        nivel_dificuldade_atividade = NIVEL_DIFICULDADE_PADRAO

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


async def encerrar_sessoes_ociosas(app):
    """Sweep: fecha sessões abertas sem evento há > STALE_SESSAO_MIN min, usando o
    ÚLTIMO evento como fim (não now(), para não inflar a duração). Idempotente e
    não toca em sessão com evento recente. Loga só quando fecha ≥1 (o silêncio já
    diz 'nada fechado'; assim não vira ruído a cada execução)."""
    pool = app.state.pool
    if pool is None:
        return
    async with pool.acquire() as conn:
        status = await conn.execute(
            """
            update sessions s set session_end_ts = coalesce(
                (select max(ts) from session_events e where e.session_id = s.session_id),
                s.session_start_ts)
            where s.session_end_ts is null
              and coalesce(
                (select max(ts) from session_events e where e.session_id = s.session_id),
                s.session_start_ts) < now() - ($1 || ' minutes')::interval
            """,
            str(STALE_SESSAO_MIN),
        )
    try:
        n = int(status.split()[-1])   # status = 'UPDATE N'
    except (ValueError, IndexError):
        n = 0
    if n:
        print(f"[KaIA] Sweep: {n} sessão(ões) ociosa(s) encerrada(s) "
              f"(> {STALE_SESSAO_MIN} min sem evento).")


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
        sid = str(r["session_id"])
        try:
            await agregar_features(pool, sid)
        except Exception as e:
            print("[KaIA] erro ao agregar", r["session_id"], ":", e)
        try:
            await rodar_intervencao(app, sid)
        except Exception as e:
            print("[KaIA] erro na intervenção", sid, ":", e)
    if ativas:
        print(f"[KaIA] Agregação rodou para {len(ativas)} sessão(ões) ativa(s).")


async def rodar_intervencao(app, session_id):
    """Após a agregação, decide via Thompson Sampling se dispara uma intervenção.
    Regras: só para estado distraido/muito_distraido, respeitando cooldown de
    INTERV_COOLDOWN_MIN e teto de INTERV_MAX_POR_SESSAO por sessão. Silencioso
    se a tabela interventions ainda não existir (Tarefa 4)."""
    thompson = app.state.thompson
    modelo, scaler = app.state.modelo, app.state.scaler
    if thompson is None or modelo is None or scaler is None:
        return

    async with app.state.pool.acquire() as conn:
        res = await predizer_estado(modelo, scaler, conn, session_id)
        if res is None:
            return
        # Reward implícito: fecha intervenções passadas cuja janela já expirou,
        # comparando o estado de então com o atual. Roda mesmo se agora está engajado
        # (o sucesso é justamente ter virado engajado).
        await resolver_rewards(conn, thompson, session_id, res["estado"])
        if res["estado"] not in ESTADOS_QUE_INTERVEM:
            return

        try:
            stats = await conn.fetchrow(
                """
                select count(*) as n, max(triggered_at) as ultima
                from interventions where session_id = $1::uuid
                """,
                session_id,
            )
        except Exception as e:
            print("[KaIA] tabela interventions indisponível (rode a Tarefa 4):", e)
            return

        n = stats["n"] or 0
        if n >= INTERV_MAX_POR_SESSAO:
            return
        if stats["ultima"] is not None:
            desde_min = (datetime.now(timezone.utc) - stats["ultima"]).total_seconds() / 60.0
            if desde_min < INTERV_COOLDOWN_MIN:
                return

        tempo_estudo_min = float(res["feats"].get("tempo_estudo_acumulado_dia_min") or 0)
        tipo = thompson.select(res["estado"], tempo_estudo_min)
        if not tipo:
            return

        await conn.execute(
            """
            insert into interventions (session_id, intervention_type, triggered_at, estado_antes)
            values ($1::uuid, $2, now(), $3)
            """,
            session_id, tipo, res["estado"],
        )
        print(f"[KaIA Intervenção] {session_id} estado={res['estado']} -> {tipo}")


async def resolver_rewards(conn, thompson, session_id, estado_atual):
    """Fecha intervenções cuja janela de medição já passou e que ainda não têm
    reward (o polegar tem prioridade: se o aluno já respondeu, reward != null e a
    linha é ignorada). Calcula o reward pela transição estado_antes -> estado_atual
    e atualiza o bandit. Silencioso se as colunas novas ainda não existirem."""
    if thompson is None:
        return
    try:
        pendentes = await conn.fetch(
            """
            select intervention_id, intervention_type, estado_antes
              from interventions
             where session_id = $1::uuid
               and reward is null
               and estado_antes is not null
               and triggered_at <= now() - make_interval(mins => $2::int)
            """,
            session_id, INTERV_JANELA_REWARD_MIN,
        )
    except Exception as e:
        print("[KaIA] colunas de reward ausentes (rode interventions_reward_estado.sql):", e)
        return

    for p in pendentes:
        reward = reward_por_transicao(p["estado_antes"], estado_atual)
        if reward is None:
            continue
        try:
            thompson.update(p["intervention_type"], reward)
            await conn.execute(
                """
                update interventions
                   set reward = $2, estado_depois = $3, reward_origem = 'auto_estado'
                 where intervention_id = $1
                """,
                p["intervention_id"], reward, estado_atual,
            )
            print(f"[KaIA Reward auto] {p['intervention_type']} {p['estado_antes']}->{estado_atual} r={reward}")
        except Exception as e:
            print("[KaIA] erro ao resolver reward", p["intervention_id"], ":", e)


# ============ FEATURES PARA O MODELO (vetor cumulativo por sessão) ==========
# O modelo RandomForest (ml/artifacts) foi treinado com 1 linha por SESSÃO
# INTEIRA. Logo, o vetor enviado ao modelo é calculado sobre a sessão toda
# (cumulativo), NÃO sobre a janela de 30s de session_features (que continua
# existindo apenas para o painel do responsável).

# Ordem EXATA esperada pelo modelo/scaler v2 (scaler_v2.feature_names_in_). NÃO altere.
# Mesma ordem do gerar_base_v2.py (ml/): internas relativas, externas e contexto absolutas.
FEATURE_ORDER = [
    # internas (relativas ao baseline do aluno, em sigma)
    "variabilidade_tempo_resposta", "contagem_lapsos_rt", "tempo_resposta_ms",
    "tempo_iniciacao_resposta_ms", "tempo_dwell_sem_responder_s", "tempo_ocioso_s",
    "velocidade_mouse_media", "variabilidade_velocidade_mouse", "flips_cursor_xy",
    "entropia_trajetoria_mouse", "erros_sem_offtask", "tendencia_desempenho_sessao",
    # externas (absolutas)
    "mudancas_aba", "tempo_fora_foco_s", "cliques_fora_area_estudo", "taxa_abandono_sessao",
    # contexto (absolutas)
    "nivel_dificuldade_atividade", "duracao_sessao_min", "hora_do_dia", "tempo_estudo_acumulado_dia_min",
]

# Internas expressas como DESVIO (sigma) do baseline do aluno; o resto é bruto.
# contagem_lapsos_rt/erros_sem_offtask são contagens (brutas), não relativizadas.
INTERNAS_RELATIVAS = (
    "variabilidade_tempo_resposta", "tempo_resposta_ms", "tempo_iniciacao_resposta_ms",
    "tempo_dwell_sem_responder_s", "tempo_ocioso_s", "tendencia_desempenho_sessao",
    "velocidade_mouse_media", "variabilidade_velocidade_mouse", "flips_cursor_xy",
    "entropia_trajetoria_mouse",
)
MIN_SESSOES_BASELINE = 3     # abaixo disso não dá pra personalizar -> desvio 0 (neutro)
BASELINE_TTL_S = 600         # cache do baseline por aluno (sessões passadas não mudam)
NIVEL_DIFICULDADE_PADRAO = 2  # fallback se a sessão ainda não tem resposta (CHECK 1..5)

# Mapeamento do rótulo (int) -> estado, conforme encoding do treino.
ESTADOS = ["engajado", "distraido", "muito_distraido"]  # 0, 1, 2

# Regras de disparo de intervenção (no scheduler de 30s).
INTERV_COOLDOWN_MIN = 3        # tempo mínimo entre intervenções da mesma sessão
INTERV_MAX_POR_SESSAO = 5      # teto de intervenções por sessão
ESTADOS_QUE_INTERVEM = ("distraido", "muito_distraido")
INTERV_JANELA_REWARD_MIN = 3   # minutos após a intervenção para medir a mudança de estado


def reward_por_transicao(estado_antes, estado_depois):
    """Reward implícito (0..1) pela transição de foco após a intervenção.
    engajado é o melhor; muito_distraido o pior (ordem em ESTADOS).
    Retorna None se algum estado for desconhecido (não resolve)."""
    if estado_antes not in ESTADOS or estado_depois not in ESTADOS:
        return None
    if estado_depois == "engajado":
        return 1.0                                     # re-focou de vez
    melhora = ESTADOS.index(estado_depois) - ESTADOS.index(estado_antes)
    if melhora < 0:
        return 0.5                                     # melhorou, mas não até engajado
    if melhora == 0:
        return 0.2                                     # ficou igual
    return 0.0                                         # piorou


async def _carregar_eventos(conn, session_id):
    """Eventos de UMA sessão como lista de (event_type, payload_dict)."""
    eventos = await conn.fetch(
        "select event_type, payload from session_events where session_id = $1::uuid",
        session_id,
    )
    return [(r["event_type"], json.loads(r["payload"])) for r in eventos]


def _inclinacao(ys):
    """Inclinação (mínimos quadrados) de ys vs. índice — tendência ao longo da sessão."""
    n = len(ys)
    if n < 2:
        return 0.0
    mx, my = (n - 1) / 2.0, sum(ys) / n
    den = sum((i - mx) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / den


def _internos_brutos(evs):
    """Valores BRUTOS das internas de UMA sessão (média/desvio por questão).
    NÃO relativiza — isso é feito depois contra o baseline do aluno.
    Retorna None se a sessão não tem nenhuma resposta (não serve de amostra)."""
    respostas = [p for et, p in evs if et == "question_answer"]
    if not respostas:
        return None
    rts = [float(p["tempo_resposta_ms"]) for p in respostas if p.get("tempo_resposta_ms") is not None]
    inis = [float(p["tempo_iniciacao_resposta_ms"]) for p in respostas if p.get("tempo_iniciacao_resposta_ms") is not None]
    ocio = [float(p.get("tempo_ocioso_s") or 0) for p in respostas]
    dwell = [float(p.get("tempo_dwell_sem_responder_s") or 0) for p in respostas]
    mfs = [features_mouse(p.get("mouse_track") or []) for p in respostas]  # mesma fn da base v2

    def _mm(k):
        vs = [m[k] for m in mfs]
        return mean(vs) if vs else 0.0

    acertos = [1.0 if p.get("acertou") else 0.0 for p in respostas]
    return {
        "variabilidade_tempo_resposta": pstdev(rts) if len(rts) > 1 else 0.0,
        "tempo_resposta_ms": mean(rts) if rts else 0.0,
        "tempo_iniciacao_resposta_ms": mean(inis) if inis else 0.0,
        "tempo_dwell_sem_responder_s": mean(dwell) if dwell else 0.0,   # hover nas alternativas sem responder
        "tempo_ocioso_s": mean(ocio) if ocio else 0.0,
        "tendencia_desempenho_sessao": _inclinacao(acertos),
        "velocidade_mouse_media": _mm("velocidade_mouse_media"),
        "variabilidade_velocidade_mouse": _mm("variabilidade_velocidade_mouse"),
        "flips_cursor_xy": _mm("flips_cursor_xy"),
        "entropia_trajetoria_mouse": _mm("entropia_trajetoria_mouse"),
        "_rts": rts,
        "_erros": sum(1 for a in acertos if a == 0.0),   # erros_sem_offtask (contagem bruta)
        "_niveis": [int(p.get("nivel_dificuldade") or NIVEL_DIFICULDADE_PADRAO) for p in respostas],
    }


_BASELINE_CACHE = {}   # user_id -> (baseline_dict|None, computed_at)


async def _baseline_aluno(conn, user_id, session_id):
    """Baseline ENTRE-SESSÕES do aluno: (média, desvio) BRUTO de cada interna
    sobre as sessões passadas encerradas. < MIN_SESSOES_BASELINE -> None
    (cold-start: sem histórico não dá pra personalizar -> desvios 0). Cacheado
    (BASELINE_TTL_S), pois sessões passadas não mudam."""
    chave = str(user_id)
    agora = datetime.now(timezone.utc)
    cache = _BASELINE_CACHE.get(chave)
    if cache and (agora - cache[1]).total_seconds() < BASELINE_TTL_S:
        return cache[0]

    rows = await conn.fetch(
        "select session_id from sessions where user_id = $1::uuid "
        "and session_end_ts is not null and session_id <> $2::uuid "
        "order by session_start_ts desc limit 20",
        user_id, session_id,
    )
    amostras, rts_pool = [], []
    for r in rows:
        raw = _internos_brutos(await _carregar_eventos(conn, r["session_id"]))
        if raw:
            amostras.append(raw)
            rts_pool += raw["_rts"]

    if len(amostras) < MIN_SESSOES_BASELINE:
        base = None
    else:
        base = {k: (mean([a[k] for a in amostras]), pstdev([a[k] for a in amostras]) or 1.0)
                for k in INTERNAS_RELATIVAS}
        base["_rt"] = (mean(rts_pool), pstdev(rts_pool) or 1.0) if len(rts_pool) > 1 else None
    _BASELINE_CACHE[chave] = (base, agora)
    return base


async def montar_features_sessao(conn, session_id):
    """Monta o dict das 20 features v2 (CUMULATIVO, sessão inteira). Internas
    relativizadas pelo baseline do aluno (desvio em sigma); externas/contexto
    brutas. Retorna na ordem FEATURE_ORDER, ou None se a sessão não existir."""
    sess = await conn.fetchrow(
        "select user_id, session_start_ts from sessions where session_id = $1::uuid",
        session_id,
    )
    if sess is None:
        return None

    evs = await _carregar_eventos(conn, session_id)
    tab = [p for et, p in evs if et == "tab_change"]
    cliques = [p for et, p in evs if et == "click_outside"]
    brutos = _internos_brutos(evs)
    base = await _baseline_aluno(conn, sess["user_id"], session_id)

    f = {}
    # internas relativas (desvio em sigma; cold-start ou sessão sem resposta -> 0)
    for k in INTERNAS_RELATIVAS:
        if brutos is None or base is None:
            f[k] = 0.0
        else:
            mu, sd = base[k]
            f[k] = round((brutos[k] - mu) / sd, 3)
    # contagens brutas (não relativizadas, como no gerador v2)
    if brutos and base and base.get("_rt"):
        limite = base["_rt"][0] + 2 * base["_rt"][1]         # RT típico do aluno + 2σ = lapso
        f["contagem_lapsos_rt"] = sum(1 for rt in brutos["_rts"] if rt > limite)
    else:
        f["contagem_lapsos_rt"] = 0
    f["erros_sem_offtask"] = brutos["_erros"] if brutos else 0

    # externas absolutas
    f["mudancas_aba"] = len(tab)
    f["tempo_fora_foco_s"] = round(sum(float(p.get("tempo_fora_foco_s") or 0) for p in tab), 1)
    f["cliques_fora_area_estudo"] = len(cliques)
    ab = await conn.fetchrow(
        """
        select count(*) filter (where session_end_ts is null and session_id <> $2::uuid) as abandonadas,
               count(*) as total
        from sessions
        where user_id = $1::uuid and session_start_ts >= now() - interval '7 days'
        """,
        sess["user_id"], session_id,
    )
    f["taxa_abandono_sessao"] = round((ab["abandonadas"] / ab["total"]) if ab and ab["total"] else 0.0, 3)

    # contexto absolutas
    f["nivel_dificuldade_atividade"] = round(mean(brutos["_niveis"])) if (brutos and brutos["_niveis"]) else NIVEL_DIFICULDADE_PADRAO
    agora = datetime.now(timezone.utc)
    f["duracao_sessao_min"] = round(max((agora - sess["session_start_ts"]).total_seconds() / 60.0, 1e-6), 2)
    local = datetime.now()
    f["hora_do_dia"] = round(local.hour + local.minute / 60.0, 2)
    f["tempo_estudo_acumulado_dia_min"] = round(float(await conn.fetchval(
        "select coalesce(sum(extract(epoch from (coalesce(session_end_ts, now()) - session_start_ts))) / 60.0, 0) "
        "from sessions where user_id = $1::uuid and date(session_start_ts) = current_date",
        sess["user_id"],
    ) or 0.0), 1)

    return {k: f[k] for k in FEATURE_ORDER}   # ordem exata do modelo


def vetor_para_modelo(feats):
    """Ordena o dict na ordem exata do treino (FEATURE_ORDER)."""
    return [float(feats[nome]) for nome in FEATURE_ORDER]


async def predizer_estado(modelo, scaler, conn, session_id):
    """Núcleo de predição compartilhado por /diagnose e pelo scheduler.
    Retorna dict {estado, score, feats} ou None se sessão/modelo indisponível."""
    if modelo is None or scaler is None:
        return None
    feats = await montar_features_sessao(conn, session_id)
    if feats is None:
        return None
    # DataFrame com as colunas na ordem do treino -> sem warning de feature names.
    Xdf = pd.DataFrame([vetor_para_modelo(feats)], columns=FEATURE_ORDER)
    Xs = pd.DataFrame(scaler.transform(Xdf), columns=FEATURE_ORDER)
    pred = int(modelo.predict(Xs)[0])
    proba = modelo.predict_proba(Xs)[0]
    score = float(proba[list(modelo.classes_).index(pred)])
    estado = ESTADOS[pred] if 0 <= pred < len(ESTADOS) else str(pred)
    return {"estado": estado, "score": score, "feats": feats}


# ================== API: DIAGNOSE (predição do estado via RF) ===============
# Protegido por JWT (Supabase Auth): exige Authorization: Bearer <token> válido.
@app.get("/diagnose")
async def diagnose(request: Request, session_id: str,
                   _uid: str = Depends(usuario_autenticado)):
    """Prediz o estado de atenção da sessão (engajado/distraido/muito_distraido)
    usando o RandomForest v2 carregado no startup. As features são o vetor
    CUMULATIVO da sessão (montar_features_sessao), na ordem exata do treino."""
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    modelo, scaler = request.app.state.modelo, request.app.state.scaler
    if modelo is None or scaler is None:
        return JSONResponse({"erro": "Modelo indisponível no servidor."}, status_code=503)

    async with pool.acquire() as conn:
        res = await predizer_estado(modelo, scaler, conn, session_id)
    if res is None:
        return JSONResponse({"erro": "Sessão não encontrada."}, status_code=404)

    return {
        "session_id": session_id,
        "estado": res["estado"],
        "score": round(res["score"], 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ================== API: INTERVENÇÃO (pendente + feedback) ===================
class FeedbackIn(BaseModel):
    session_id: str
    intervention_type: str
    reward: float                              # 0.0, 0.5 ou 1.0
    tempo_ate_aceitar_s: Optional[float] = None
    feedback_usuario: Optional[str] = None


@app.get("/intervencao/pendente", dependencies=[Depends(usuario_autenticado)])
async def intervencao_pendente(request: Request, session_id: str):
    """Frontend consulta a intervenção recém-disparada (sem reward ainda) nos
    últimos 5 min. É a 'flag' que substitui o WebSocket: o front faz polling."""
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                select intervention_id, intervention_type, triggered_at
                from interventions
                where session_id = $1::uuid and reward is null
                  and triggered_at >= now() - interval '5 minutes'
                order by triggered_at desc limit 1
                """,
                session_id,
            )
        except Exception:
            return {"pendente": None}
    if row is None:
        return {"pendente": None}
    return {"pendente": {
        "intervention_id": str(row["intervention_id"]),
        "intervention_type": row["intervention_type"],
        "triggered_at": row["triggered_at"].isoformat(),
    }}


@app.post("/intervencao/feedback", dependencies=[Depends(usuario_autenticado)])
async def intervencao_feedback(body: FeedbackIn, request: Request):
    """Recebe o feedback do aluno, grava o reward na intervenção mais recente
    (dessa sessão+tipo ainda sem reward) e atualiza o bandit (thompson.update)."""
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    if body.intervention_type not in INTERVENCOES:
        return JSONResponse({"erro": "intervention_type inválido."}, status_code=400)
    reward = min(max(float(body.reward), 0.0), 1.0)

    intervention_id = None
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                update interventions
                   set reward = $3,
                       reward_origem = 'explicito',
                       tempo_ate_aceitar_s = coalesce($4::double precision, tempo_ate_aceitar_s),
                       feedback_usuario    = coalesce($5::text, feedback_usuario)
                 where intervention_id = (
                       select intervention_id from interventions
                        where session_id = $1::uuid and intervention_type = $2 and reward is null
                        order by triggered_at desc limit 1
                 )
                returning intervention_id
                """,
                body.session_id, body.intervention_type, reward,
                body.tempo_ate_aceitar_s, body.feedback_usuario,
            )
            if row is not None:
                intervention_id = str(row["intervention_id"])
        except Exception as e:
            return JSONResponse(
                {"erro": f"tabela interventions indisponível: {e}"}, status_code=503
            )

    # Atualiza o bandit mesmo que não haja linha correspondente (feedback direto).
    thompson = request.app.state.thompson
    if thompson is not None:
        thompson.update(body.intervention_type, reward)

    return {
        "status": "ok",
        "intervention_id": intervention_id,
        "intervention_type": body.intervention_type,
        "reward": reward,
    }


# ================== API: SESSIONS (abre uma nova sessão) ====================
class SessionIn(BaseModel):
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    platform: str = "web"
    app_version: str = "mvp-0.1"


@app.post("/sessions", dependencies=[Depends(usuario_autenticado)])
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


@app.post("/events", dependencies=[Depends(usuario_autenticado)])
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
        # Probe = rótulo REAL do aluno -> vira exemplo supervisionado (fora da
        # transação: falhar aqui não pode derrubar a ingestão do evento).
        if body.event_type == "probe_atencao":
            await _capturar_probe(conn, body.session_id, body.payload)

    print("[KaIA Event]", body.event_type, body.session_id)
    return {"status": "ok", "event_id": str(ev["event_id"])}


async def _capturar_probe(conn, session_id, payload):
    """Grava (features NO MOMENTO, rótulo declarado) em probe_labels — o dataset
    real que tira o modelo do 100% sintético. Best-effort: erro não propaga
    (tabela pode não existir ainda, sessão sem respostas etc.)."""
    estado = (payload or {}).get("estado")
    if estado not in ESTADOS:
        return
    try:
        feats = await montar_features_sessao(conn, session_id)
        if feats is None:
            return
        uid = await conn.fetchval(
            "select user_id from sessions where session_id = $1::uuid", session_id)
        await conn.execute(
            "insert into probe_labels (session_id, user_id, estado, features) "
            "values ($1::uuid, $2, $3, $4::jsonb)",
            session_id, uid, estado, json.dumps(feats),
        )
    except Exception as e:
        print("[KaIA] erro ao capturar probe:", e)


# ================== API: PERFIL (login + hobbies, upsert em `perfis`) ========
# Atributos ESTÁVEIS do aluno (1 linha por user_id). A tabela user_profiles
# guarda features AGREGADAS/derivadas e é populada depois pelo pipeline de ML.
def _to_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


@app.post("/perfil", dependencies=[Depends(usuario_autenticado)])
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


@app.get("/responsavel/aluno", dependencies=[Depends(usuario_autenticado)])
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
# Rótulo curto do estado (predito pelo RF) para a coluna "Estado" das sessões recentes.
_EST_ROT = {"engajado": "Engajado", "distraido": "Distraído", "muito_distraido": "Muito distr."}
# Cor do "nível" de dispersão nos alertas recentes do dashboard.
_NIVEL_COR = {"muito_distraido": "vermelho", "distraido": "amarelo", "engajado": "verde"}

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
    nivel = _NIVEL_COR
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


async def _role_do_usuario(pool, user_id):
    """Papel do usuário (perfis.role) pelo user_id que o front envia. Retorna
    None se o id for inválido/inexistente."""
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval("select role from perfis where user_id = $1::uuid", user_id)
    except Exception:
        return None  # uuid malformado, etc. → tratado como não-admin


async def _agregar_supabase(conn, modelo, scaler):
    """Monta os blocos do dashboard a partir dos dados REAIS do Supabase.
    MEDIDO: contagens, médias de session_features, sessões por dia/hora, matérias.
    PREDITO: os blocos de 'target' (engajado/distraído) NÃO são medidos — o banco
    não guarda rótulo; são PREVISTOS pelo RandomForest (mesmo do /diagnose), por
    isso vêm marcados como predição no front. Financeiro não existe no banco → é
    omitido (o front cai no demo rotulado)."""
    from collections import defaultdict

    sessions = await conn.fetch(
        "select session_id, session_start_ts, session_end_ts from sessions order by session_start_ts")
    total = len(sessions)
    pct = lambda n: round(100.0 * n / total, 1) if total else 0.0
    media = lambda v: float(v) if v is not None else 0.0

    # --- RF por sessão (PREDIÇÃO) ---
    estado_por_sessao = {}
    if modelo is not None and scaler is not None:
        for s in sessions:
            res = await predizer_estado(modelo, scaler, conn, str(s["session_id"]))
            if res:
                estado_por_sessao[s["session_id"]] = res["estado"]
    preditas = len(estado_por_sessao)
    cont = defaultdict(int)
    for e in estado_por_sessao.values():
        cont[e] += 1
    pct_pred = lambda chave: round(100.0 * cont.get(chave, 0) / preditas, 1) if preditas else 0.0

    # --- sessões por hora + "muito distraído"/engajamento por hora (predição) ---
    sess_hora, muito_hora = defaultdict(int), defaultdict(int)
    eng_hora = defaultdict(lambda: [0, 0])  # [engajadas, total_preditas]
    for s in sessions:
        h = s["session_start_ts"].hour
        sess_hora[h] += 1
        est = estado_por_sessao.get(s["session_id"])
        if est is not None:
            eng_hora[h][1] += 1
            if est == "muito_distraido":
                muito_hora[h] += 1
            if est == "engajado":
                eng_hora[h][0] += 1
    sessoes_hora = [{"hora": f"{h}h", "sessoes": sess_hora.get(h, 0), "alertas": muito_hora.get(h, 0)}
                    for h in range(24)]
    foco_hora = [{"hora": f"{h}h",
                  "foco": round(100.0 * eng_hora[h][0] / eng_hora[h][1], 1) if eng_hora[h][1] else 0.0}
                 for h in range(24)]

    # --- médias de session_features (MEDIDO) ---
    f = await conn.fetchrow("""
        select avg(acertos_questoes) acertos, avg(tempo_resposta_ms) tresp,
               avg(nivel_dificuldade_atividade) dif, avg(tempo_fora_foco_s) fora
        from session_features""")

    # --- duração média + "sem término" (proxy de abandono) + dias cobertos ---
    dur = await conn.fetchrow("""
        select avg(extract(epoch from (session_end_ts - session_start_ts)) / 60.0) minutos,
               count(*) filter (where session_end_ts is null) sem_fim,
               count(distinct date(session_start_ts)) dias
        from sessions""")
    abandono_pct = round(100.0 * (dur["sem_fim"] or 0) / total) if total else 0

    # --- sinais de dispersão: média ÷ pico (MEDIDO) ---
    eventos = []
    for rotulo, col in _SINAIS:
        row = await conn.fetchrow(f"select avg({col}) m, max({col}) p from session_features")
        pico, m = media(row["p"]), media(row["m"])
        eventos.append({"tipo": rotulo, "percentual": round(100.0 * m / pico) if pico else 0})

    # --- sessões recentes (MEDIDO + estado predito) ---
    recentes = await conn.fetch("""
        select s.session_id, s.session_start_ts,
               (select avg(acertos_questoes) from session_features sf where sf.session_id = s.session_id) acertos,
               (select payload->>'materia' from session_events se
                 where se.session_id = s.session_id and se.event_type = 'session_start' limit 1) materia
        from sessions s order by s.session_start_ts desc limit 6""")
    alunos_recentes = [{
        "aluno": str(r["session_id"])[:8],
        "plano": _EST_ROT.get(estado_por_sessao.get(r["session_id"]), "—"),
        "foco": f"{r['acertos']:.0f}" if r["acertos"] is not None else "—",
        "tema": MATERIAS.get(r["materia"], r["materia"] or "—"),
    } for r in recentes]

    # --- sessões mais dispersas (MEDIDO) → cor pelo estado predito ---
    piores = await conn.fetch("""
        select s.session_id, s.session_start_ts,
               max(sf.mudancas_aba) aba, max(sf.tempo_fora_foco_s) fora
        from sessions s join session_features sf on sf.session_id = s.session_id
        group by s.session_id, s.session_start_ts
        order by aba desc nulls last, fora desc nulls last limit 4""")
    nivel = _NIVEL_COR
    alertas_recentes = [{
        "nivel": nivel.get(estado_por_sessao.get(r["session_id"]), "amarelo"),
        "mensagem": f"{str(r['session_id'])[:8]} — {int(r['aba'] or 0)} trocas de aba · {media(r['fora']):.0f}s fora de foco",
        "tempo": r["session_start_ts"].strftime("%d/%m %H:%M"),
    } for r in piores]

    # --- sessões por dia: iniciadas vs. concluídas (com session_end_ts) ---
    por_dia = await conn.fetch("""
        select date(session_start_ts) dia, count(*) iniciadas,
               count(*) filter (where session_end_ts is not null) concluidas
        from sessions group by 1 order by 1""")
    sessoes_dia = [{"data": r["dia"].strftime("%d/%m"), "iniciadas": r["iniciadas"],
                    "concluidas": r["concluidas"]} for r in por_dia]

    # --- matérias estudadas (de session_events; sigla → nome via MATERIAS) ---
    mats = await conn.fetch("""
        select payload->>'materia' sigla, count(*) n from session_events
        where event_type = 'session_start' and payload ? 'materia'
        group by 1 order by n desc""")
    materias_estudadas = [{"tema": MATERIAS.get(r["sigla"], r["sigla"] or "—"), "sessoes": r["n"]} for r in mats]

    # --- distribuição do target (PREDIÇÃO) ---
    distribuicao = [{"faixa": rot, "percentual": pct_pred(chave)} for chave, rot in _TARGETS]

    # --- alunos por escola (REAPROVEITA o slot da rosca 'planos'; ver nota) ---
    # NOTA DE CONCEITO: antes esta rosca era o "perfil de comportamento" do aluno
    # (persona da base sintética). O schema real NÃO tem persona de aluno, então
    # o slot passa a mostrar DISTRIBUIÇÃO ADMINISTRATIVA (alunos por escola). Se um
    # dia existir persona de aluno no banco, vale reverter para o significado antigo.
    escolas = await conn.fetch("""
        select coalesce(e.nome, case when p.escola_id is null then 'Sem escola'
                                     else 'Escola ' || left(p.escola_id::text, 4) end) nome,
               count(*) n
        from perfis p left join escolas e on e.escola_id = p.escola_id
        where p.role = 'aluno' group by 1 order by n desc""")
    total_al = sum(r["n"] for r in escolas) or 1
    alunos_escola = [{"plano": r["nome"], "percentual": round(100.0 * r["n"] / total_al, 1)} for r in escolas]

    kpis = [
        {"view": "geral", "icone": "layers", "rotulo": "SESSÕES ANALISADAS", "valor": f"{total}", "subtexto": "no Supabase"},
        {"view": "geral", "icone": "smile", "rotulo": "ENGAJAMENTO", "valor": f"{pct_pred('engajado')}%",
         "subtexto": "predição do modelo", "cor": "verde"},
        {"view": "geral", "icone": "check", "rotulo": "ACERTOS MÉDIOS",
         "valor": f"{media(f['acertos']):.1f}".replace(".", ","), "subtexto": "por janela de sessão"},
        {"view": "geral", "icone": "alert", "rotulo": "SEM TÉRMINO", "valor": f"{abandono_pct}%",
         "subtexto": "sessões sem fim registrado", "cor": "vermelho"},

        {"view": "sessoes", "icone": "clock", "rotulo": "DURAÇÃO MÉDIA", "valor": f"{media(dur['minutos']):.0f} min",
         "subtexto": "sessões concluídas"},
        {"view": "sessoes", "icone": "list", "rotulo": "TEMPO DE RESPOSTA",
         "valor": f"{media(f['tresp']) / 1000:.1f}s".replace(".", ","), "subtexto": "média por janela"},
        {"view": "sessoes", "icone": "target", "rotulo": "DIFICULDADE MÉDIA",
         "valor": f"{media(f['dif']):.1f}/5".replace(".", ","), "subtexto": "nível da atividade"},
        {"view": "sessoes", "icone": "calendar", "rotulo": "DIAS COBERTOS", "valor": f"{dur['dias'] or 0}",
         "subtexto": "com sessão registrada"},

        {"view": "atencao", "icone": "smile", "rotulo": "ENGAJADO", "valor": f"{pct_pred('engajado')}%",
         "subtexto": "predição do modelo", "cor": "verde"},
        {"view": "atencao", "icone": "meh", "rotulo": "DISTRAÍDO", "valor": f"{pct_pred('distraido')}%",
         "subtexto": "predição do modelo", "cor": "amarelo"},
        {"view": "atencao", "icone": "frown", "rotulo": "MUITO DISTRAÍDO", "valor": f"{pct_pred('muito_distraido')}%",
         "subtexto": "predição do modelo", "cor": "vermelho"},
        {"view": "atencao", "icone": "bolt", "rotulo": "TEMPO FORA DE FOCO", "valor": f"{media(f['fora']):.0f}s",
         "subtexto": "média por janela"},
    ]

    periodo = ""
    if total:
        periodo = f"{sessions[0]['session_start_ts']:%d/%m/%Y} — {sessions[-1]['session_start_ts']:%d/%m/%Y}"

    return {
        "fonte": "supabase",
        "total_sessoes": total,
        "sessoes_preditas": preditas,
        "amostra_pequena": total < 50,     # front avisa "amostra pequena" quando true
        "periodo": periodo,
        "kpis": kpis,
        "sessoes_hora": sessoes_hora,
        "planos": alunos_escola,           # slot reaproveitado: alunos por escola
        "alunos_recentes": alunos_recentes,
        "alertas_recentes": alertas_recentes,
        "sessoes_14dias": sessoes_dia,
        "temas_estudados": materias_estudadas,   # slot reaproveitado: matérias estudadas
        "distribuicao_foco": distribuicao,
        "eventos_tipo": eventos,
        "foco_hora": foco_hora,
    }


def _dashboard_offline():
    """Fallback SEM banco: base sintética (xlsx) → planilha manual → demo do front."""
    if os.path.exists(BASE_SINTETICA):
        try:
            df = pd.read_excel(BASE_SINTETICA)
            return _agregar_base_sintetica(df)
        except Exception as e:
            print("[KaIA] erro ao agregar a base sintética:", e)
            return JSONResponse({"erro": "Não foi possível ler a base sintética."}, status_code=500)

    if os.path.exists(DASHBOARD_XLSX):
        try:
            planilhas = pd.read_excel(DASHBOARD_XLSX, sheet_name=None)
        except Exception as e:
            print("[KaIA] erro ao ler dados_dashboard.xlsx:", e)
            return JSONResponse({"erro": "Não foi possível ler a planilha."}, status_code=500)
        saida = {"fonte": "planilha_manual"}
        for nome, df in planilhas.items():
            if nome.startswith("_"):
                continue
            df = df.where(pd.notnull(df), None)
            saida[nome] = df.to_dict(orient="records")
        return saida

    return {"vazio": True, "motivo": "nenhuma planilha encontrada"}


@app.get("/dashboard/dados", dependencies=[Depends(usuario_autenticado)])
async def dashboard_dados(request: Request):
    # --- Porteiro de acesso (Etapa 10) ---------------------------------------
    # SEGURANÇA: X-Kaia-User é a identidade que o FRONT AFIRMA sobre si (uuid do
    # localStorage). Sem senha/JWT, isto é CONVENIÊNCIA, não proteção: alguém
    # poderia enviar o uuid do admin e passar. O gate real só existirá com
    # Supabase Auth. Ainda assim, a decisão vem do BANCO (perfis.role), nunca de
    # e-mail hardcoded no código — é a estrutura correta, faltando só a credencial.
    pool = request.app.state.pool
    if pool is not None:
        user_id = request.headers.get("X-Kaia-User")
        if not user_id or await _role_do_usuario(pool, user_id) != "admin":
            return JSONResponse({"erro": "Acesso restrito ao dashboard interno."}, status_code=403)

        # Dados reais do Supabase (prioridade quando há banco).
        modelo, scaler = request.app.state.modelo, request.app.state.scaler
        try:
            async with pool.acquire() as conn:
                return await _agregar_supabase(conn, modelo, scaler)
        except Exception as e:
            print("[KaIA] erro ao agregar dados do Supabase:", e)
            # cai para o fallback offline (não derruba a página)

    # Sem banco (dev) ou erro na agregação → base sintética / planilha / demo.
    return _dashboard_offline()

# ========================================= PERFIL =============================================
# AUTH: a validação de JWT do Supabase existe em auth.py (dependência
# usuario_autenticado) e já protege o /diagnose. DÍVIDA: estender o Depends às
# demais rotas de dados — depende do frontend passar a enviar Authorization:
# Bearer <token> em todas as páginas (hoje várias não carregam o supabase-js).
@app.get("/perfil", dependencies=[Depends(usuario_autenticado)])
async def get_perfil(request: Request, email: str = None, user_id: str = None):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    if not user_id and not email:
        return JSONResponse(
            {"status": "erro", "motivo": "user_id ou email obrigatório"}, status_code=400
        )
    try:
        async with pool.acquire() as conn:
            if user_id:
                row = await conn.fetchrow(
                    """
                    SELECT user_id, email, hobbies, nome, role, escola_id, turma_id
                    FROM perfis WHERE user_id = $1::uuid
                    """,
                    user_id
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT user_id, email, hobbies, nome, role, escola_id, turma_id
                    FROM perfis WHERE lower(email) = lower($1)
                    """,
                    email
                )
        if not row:
            return JSONResponse({"status": "não encontrado"}, status_code=404)

        # hobbies é jsonb: o asyncpg devolve a STRING crua ('["Xadrez"]'), não a
        # lista. Sem este parse o front recebe "[]", que é truthy — e o aluno sem
        # hobbies nunca seria mandado para o onboarding.
        hobbies = row["hobbies"]
        if isinstance(hobbies, str):
            try:
                hobbies = json.loads(hobbies)
            except (ValueError, TypeError):
                hobbies = []

        return {
            "user_id": str(row["user_id"]),
            "email": row["email"],
            "nome": row["nome"],
            "role": row["role"],
            "escola_id": str(row["escola_id"]) if row["escola_id"] else None,
            "turma_id": str(row["turma_id"]) if row["turma_id"] else None,
            "hobbies": hobbies or [],
        }
    except Exception as e:
        print("[KaIA] Erro ao buscar perfil:", e)
        return JSONResponse({"status": "erro"}, status_code=500)

# ============ API: PAINEL DO RESPONSÁVEL (professor/coordenador/pai) ========
# Um endpoint só, que despacha pela `role` do perfil — o frontend faz uma
# chamada e renderiza conforme o que voltar.
#
# NOTA SOBRE O SCHEMA: `professores` tem escola_id + materia, mas NÃO tem
# turma_id. Então "a turma do professor" não existe no banco: o professor vê os
# alunos de TODAS as turmas da escola dele, filtrados pela matéria que leciona.
#
# A semana é o inteiro `semana` (1..8) de desempenho_semanal — não é uma data.
# "Semana mais recente" = max(semana).
def _turma_rotulo(ano, turno):
    return f"{ano}º ano · {turno}" if ano is not None else "—"


# Faixas de status por % de atenção. Cortes fixos, validados contra a
# distribuição real do dataset (mediana ~0.65): < 50% = em risco ·
# 50–70% = atenção · ≥ 70% = bem. Espalha ~30/25/45 (vs. 82% em "bem" com
# cortes de 20/30%, que escondiam quase todo mundo).
def _status_atencao(media):
    if media is None:
        return None
    if media < 0.50:
        return "risco"
    if media < 0.70:
        return "atencao"
    return "bem"


def _distribuicao_status(valores):
    d = {"bem": 0, "atencao": 0, "risco": 0}
    for v in valores:
        s = _status_atencao(v)
        if s:
            d[s] += 1
    return d


@app.get("/responsavel/painel", dependencies=[Depends(usuario_autenticado)])
async def painel_responsavel(request: Request, email: Optional[str] = None):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    if not email:
        return JSONResponse({"erro": "Informe o e-mail do usuário logado."}, status_code=400)

    async with pool.acquire() as conn:
        perfil = await conn.fetchrow(
            "select user_id, nome, role from perfis where lower(email) = lower($1)", email
        )
        if perfil is None:
            return JSONResponse({"erro": "Usuário não encontrado."}, status_code=404)

        role = (perfil["role"] or "").lower()
        semana = await conn.fetchval("select max(semana) from desempenho_semanal")

        # ---------- PROFESSOR: alunos da escola, na matéria dele ----------
        if role == "professor":
            prof = await conn.fetchrow(
                "select nome, materia, escola_id from professores where lower(email) = lower($1)", email
            )
            if prof is None:
                return JSONResponse(
                    {"erro": "Este e-mail tem role='professor' em `perfis`, mas não está "
                             "vinculado a nenhuma linha de `professores`."},
                    status_code=404,
                )

            escola = await conn.fetchval(
                "select nome from escolas where escola_id = $1", prof["escola_id"]
            )
            linhas = await conn.fetch(
                """
                select p.nome, t.ano, t.turno,
                       d.media_atencao, d.taxa_acerto, d.minutos_estudados
                from desempenho_semanal d
                join perfis p on p.user_id  = d.aluno_id
                join turmas t on t.turma_id = d.turma_id
                where d.escola_id = $1 and d.materia = $2 and d.semana = $3
                order by d.media_atencao asc          -- quem mais precisa de atenção primeiro
                """,
                prof["escola_id"], prof["materia"], semana,
            )
            # Gráficos: barras de atenção por turma (na matéria do professor) e
            # evolução semanal (média de atenção por semana, 1..8).
            turmas_rows = await conn.fetch(
                """
                select t.ano, t.turno, avg(r.media_atencao_turma) as atencao
                from resumo_turma_semanal r
                join turmas t on t.turma_id = r.turma_id
                where r.escola_id = $1 and r.materia = $2 and r.semana = $3
                group by t.turma_id, t.ano, t.turno
                order by t.ano, t.turno
                """,
                prof["escola_id"], prof["materia"], semana,
            )
            evo_rows = await conn.fetch(
                """
                select semana, avg(media_atencao) as atencao
                from desempenho_semanal
                where escola_id = $1 and materia = $2
                group by semana order by semana
                """,
                prof["escola_id"], prof["materia"],
            )
            atencoes = [float(r["media_atencao"]) for r in linhas]
            return {
                "role": "professor",
                "semana": semana,
                "professor": {"nome": prof["nome"], "materia": prof["materia"], "escola": escola},
                "alunos": [
                    {
                        "nome": r["nome"],
                        "turma": _turma_rotulo(r["ano"], r["turno"]),
                        "media_atencao": round(float(r["media_atencao"]), 3),
                        "taxa_acerto": round(float(r["taxa_acerto"]), 3),
                        "minutos": int(r["minutos_estudados"]),
                        "status": _status_atencao(float(r["media_atencao"])),
                    }
                    for r in linhas
                ],
                "graficos": {
                    "status": _distribuicao_status(atencoes),
                    "atencao_turma": [
                        {"turma": _turma_rotulo(r["ano"], r["turno"]), "atencao": round(float(r["atencao"]), 3)}
                        for r in turmas_rows
                    ],
                    "evolucao": [
                        {"semana": int(r["semana"]), "atencao": round(float(r["atencao"]), 3)}
                        for r in evo_rows
                    ],
                },
            }

        # ---------- COORDENADOR: resumo de todas as turmas da escola ----------
        if role == "coordenador":
            coord = await conn.fetchrow(
                "select nome, escola_id from coordenadores where lower(email) = lower($1)", email
            )
            if coord is None:
                return JSONResponse(
                    {"erro": "Este e-mail tem role='coordenador' em `perfis`, mas não está "
                             "vinculado a nenhuma linha de `coordenadores`."},
                    status_code=404,
                )

            escola = await conn.fetchval(
                "select nome from escolas where escola_id = $1", coord["escola_id"]
            )
            linhas = await conn.fetch(
                """
                select t.ano, t.turno,
                       avg(r.media_atencao_turma)     as media_atencao,
                       avg(r.media_taxa_acerto_turma) as taxa_acerto,
                       sum(r.alunos_em_risco)         as casos_risco,
                       count(*)                       as materias,
                       (select count(*) from perfis p where p.turma_id = t.turma_id) as alunos
                from resumo_turma_semanal r
                join turmas t on t.turma_id = r.turma_id
                where r.escola_id = $1 and r.semana = $2
                group by t.turma_id, t.ano, t.turno
                order by t.ano, t.turno
                """,
                coord["escola_id"], semana,
            )
            # Gráficos: status por ALUNO da escola (média entre matérias),
            # barras por turma (reaproveita `linhas`) e evolução semanal.
            status_rows = await conn.fetch(
                """
                select aluno_id, avg(media_atencao) as atencao
                from desempenho_semanal
                where escola_id = $1 and semana = $2
                group by aluno_id
                """,
                coord["escola_id"], semana,
            )
            evo_rows = await conn.fetch(
                """
                select semana, avg(media_atencao) as atencao
                from desempenho_semanal
                where escola_id = $1
                group by semana order by semana
                """,
                coord["escola_id"],
            )
            return {
                "role": "coordenador",
                "semana": semana,
                "coordenador": {"nome": coord["nome"], "escola": escola},
                "turmas": [
                    {
                        "turma": _turma_rotulo(r["ano"], r["turno"]),
                        "alunos": int(r["alunos"]),
                        "media_atencao": round(float(r["media_atencao"]), 3),
                        "taxa_acerto": round(float(r["taxa_acerto"]), 3),
                        # soma dos alertas nas N matérias — um mesmo aluno pode
                        # estar em risco em mais de uma, então isto são CASOS.
                        "casos_risco": int(r["casos_risco"]),
                        "materias": int(r["materias"]),
                    }
                    for r in linhas
                ],
                "graficos": {
                    "status": _distribuicao_status([float(r["atencao"]) for r in status_rows]),
                    "atencao_turma": [
                        {"turma": _turma_rotulo(r["ano"], r["turno"]), "atencao": round(float(r["media_atencao"]), 3)}
                        for r in linhas
                    ],
                    "evolucao": [
                        {"semana": int(r["semana"]), "atencao": round(float(r["atencao"]), 3)}
                        for r in evo_rows
                    ],
                },
            }

        # ---------- PAI: desempenho dos filhos vinculados ----------
        if role == "pai":
            linhas = await conn.fetch(
                """
                select p.nome, t.ano, t.turno,
                       avg(d.media_atencao)      as media_atencao,
                       avg(d.taxa_acerto)        as taxa_acerto,
                       sum(d.minutos_estudados)  as minutos
                from pai_aluno pa
                join perfis p       on p.user_id  = pa.aluno_id
                left join turmas t  on t.turma_id = p.turma_id
                left join desempenho_semanal d
                       on d.aluno_id = p.user_id and d.semana = $2
                where pa.pai_id = $1
                group by p.user_id, p.nome, t.ano, t.turno
                order by p.nome
                """,
                perfil["user_id"], semana,
            )
            return {
                "role": "pai",
                "semana": semana,
                "responsavel": {"nome": perfil["nome"]},
                "filhos": [
                    {
                        "nome": r["nome"],
                        "turma": _turma_rotulo(r["ano"], r["turno"]),
                        # left join: filho ainda sem desempenho na semana → None
                        "media_atencao": round(float(r["media_atencao"]), 3) if r["media_atencao"] is not None else None,
                        "taxa_acerto": round(float(r["taxa_acerto"]), 3) if r["taxa_acerto"] is not None else None,
                        "minutos": int(r["minutos"]) if r["minutos"] is not None else 0,
                    }
                    for r in linhas
                ],
            }

    return JSONResponse(
        {"erro": f"O painel do responsável não atende a role '{role}'."}, status_code=403
    )


# ================== HEALTHCHECK =============================================
@app.get("/")
def health():
    return {"status": "KaIA backend no ar"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
