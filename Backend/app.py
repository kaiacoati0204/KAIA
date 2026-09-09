from contextlib import asynccontextmanager
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
import os
import re
import json
import random
import asyncio
import pickle
import uuid
import ast
import math

import asyncpg
import pandas as pd
import requests

from statistics import mean, pstdev

from thompson import ThompsonSampling, INTERVENCOES, PARAMS_PATH
from auth import usuario_autenticado, usuario_identidade
from mouse_features import features_mouse, blocos_parados
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Body, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

# --- Inicialização ------------------------------------------------------------
load_dotenv()
# Aceita os dois nomes: API_KEY (prod/CI) ou CHAVE_ACESSO (.env local).
API_KEY = os.getenv("API_KEY") or os.getenv("CHAVE_ACESSO")
DATABASE_URL = os.getenv("DATABASE_URL")
# Schema-alvo: 'public' (produção, padrão) ou 'teste' (sandbox isolado no MESMO banco).
# No modo teste o search_path aponta pro schema `teste` -> dados separados do público.
DB_SCHEMA = os.getenv("KAIA_DB_SCHEMA", "public")

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
    "FIL":  "Filosofia",
    "SOC":  "Sociologia",
}

# Área do ENEM p/ o banco de questões reais (o dataset rotula por ÁREA, não matéria fina).
# O filtro por área estreita o pool; o embedding faz o casamento fino do tema.
_AREA_ENEM = {
    "PORT": "PORT",
    "HIS": "HUMANAS", "GEO": "HUMANAS", "FIL": "HUMANAS", "SOC": "HUMANAS",
    "BIO": "NATUREZA", "FIS": "NATUREZA", "QUI": "NATUREZA",
    "MAT": "MAT",
}

# Temas FIXOS e curados por matéria (alto rendimento no ENEM/vestibulares — Matriz do
# INEP + análise das provas). Nomes curtos p/ caber no card. Substitui a geração por IA.
TEMAS_FIXOS = {
    "PORT": ["Interpretação de Texto", "Gêneros Textuais", "Funções da Linguagem",
             "Variação Linguística", "Figuras de Linguagem", "Coesão e Coerência"],
    "HIS":  ["Brasil Colônia", "Brasil Império", "Brasil República", "Ditadura Militar",
             "Era Vargas", "Movimentos Sociais"],
    "GEO":  ["Questões Ambientais", "Urbanização", "Industrialização", "Globalização",
             "Questão Agrária", "Geopolítica"],
    "BIO":  ["Ecologia", "Genética", "Evolução", "Citologia", "Fisiologia Humana",
             "Biotecnologia"],
    "FIL":  ["Filosofia Antiga", "Filosofia Moderna", "Filosofia Política", "Ética",
             "Teoria Crítica", "Existencialismo"],
    "SOC":  ["Cultura e Sociedade", "Movimentos Sociais", "Estado e Cidadania",
             "Trabalho e Sociedade", "Sociologia Brasileira", "Indústria Cultural"],
    "MAT":  ["Funções", "Progressões", "Análise Combinatória", "Geometria Plana",
             "Geometria Espacial", "Estatística", "Probabilidade", "Porcentagem"],
    "FIS":  ["Leis de Newton", "Trabalho e Energia", "Cinemática", "Eletricidade",
             "Termodinâmica", "Ondas"],
    "QUI":  ["Química Geral", "Físico-Química", "Química Orgânica", "Estequiometria",
             "Soluções", "Eletroquímica"],
}

# Tópicos de CÁLCULO -> geração via PoT (a IA dá a fórmula, o backend executa).
# Os demais seguem a geração normal. QUI é misto (Orgânica/Geral são conceituais).
TEMAS_CALCULO = {
    "MAT": set(TEMAS_FIXOS["MAT"]),
    "FIS": set(TEMAS_FIXOS["FIS"]),
    "QUI": {"Físico-Química", "Estequiometria", "Soluções", "Eletroquímica"},
}


def _eh_calculo(materia, tema):
    return tema in TEMAS_CALCULO.get(materia, ())


def _exatas_natureza(materia):
    # onde a estrutura da questão muda por tema -> few-shot prefere o MESMO tema
    return materia in ("MAT", "FIS", "QUI", "BIO")

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
            _pool_kwargs = dict(statement_cache_size=0, min_size=1, max_size=5,
                                timeout=8, command_timeout=15)
            if DB_SCHEMA != "public":     # sandbox: todo nome solto cai no schema de teste
                _pool_kwargs["server_settings"] = {"search_path": f"{DB_SCHEMA}, public, extensions"}
            app.state.pool = await asyncpg.create_pool(DATABASE_URL, **_pool_kwargs)
            print(f"[KaIA] Pool de conexão com o Supabase criado (schema={DB_SCHEMA}).")
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

    # Thompson Sampling (bandit das intervenções) — carrega params persistidos. No modo
    # sandbox usa um ARQUIVO separado (o params é local, não tabela; sem isso o teste
    # treinaria o mesmo bandit da produção na mesma máquina).
    try:
        _tp = (PARAMS_PATH if DB_SCHEMA == "public"
               else PARAMS_PATH.with_name(f"thompson_params_{DB_SCHEMA}.json"))
        app.state.thompson = ThompsonSampling(params_path=_tp)
        print(f"[KaIA] Thompson Sampling carregado (bandit={_tp.name}).")
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
        # Verificacao em background: tira a espera da frente do aluno e esvazia a
        # quarentena aos poucos, no ritmo que o limite de req/min permite.
        scheduler.add_job(job_verificar_cache, "interval", minutes=2, args=[app], id="verifica_cache")
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

# CORS: só os domínios da app — nunca "*". Local (Live Server) por padrão;
# produção via env KAIA_CORS_ORIGINS (lista separada por vírgula).
_CORS_PADRAO = "http://127.0.0.1:5500,http://localhost:5500"
CORS_ORIGINS = [o.strip() for o in os.getenv("KAIA_CORS_ORIGINS", _CORS_PADRAO).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================= HELPERS GEMINI =============================================
# Modelo do Gemini. 3.5-flash-lite: geração nova + cota grátis maior (~500/dia no
# projeto) que o 2.5-flash (~20/dia). Configurável por env GEMINI_MODEL (limites em
# https://ai.google.dev/gemini-api/docs/rate-limits).
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


def chamar_gemini(prompt):
    """Faz uma chamada ao Gemini e devolve o texto da resposta (ou levanta erro)."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent?key={API_KEY}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(url, json=body, timeout=30)
    data = response.json()
    candidatos = data.get("candidates")
    if not candidatos:
        raise ValueError(f"Resposta inesperada do Gemini: {data}")
    return candidatos[0]["content"]["parts"][0]["text"]


# ================= EMBEDDINGS (few-shot dinâmico via pgvector) ================
# Mesma chave do Gemini. Modelo multilíngue (bom p/ PT). Degradação graciosa: se
# falhar, o caller cai nos exemplos few-shot fixos.
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = 768   # TEM de bater com a coluna vector(768) da tabela questoes_reais
# Few-shot dinâmico (pgvector) DESLIGADO por padrão: só ligue (=1) depois de aplicar a
# migration e rodar Backend/ingerir_questoes_reais.py — senão gasta embedding à toa.
FEWSHOT_DINAMICO = os.getenv("KAIA_FEWSHOT_DINAMICO") == "1"


# O texto embeddado no serving e sempre "Materia: tema" — conjunto pequeno e fixo, e a
# conversao texto->vetor e deterministica. Sem cache, a MESMA frase ia pra API a cada
# geracao: era o que estourava o limite do embedding (126/100 RPM) enquanto a geracao
# em si ficava em 15. Cacheia o VETOR, nao o resultado da busca — assim os filtros
# (nivel, calculo) e as questoes recem-ingeridas continuam valendo.
_EMBED_CACHE = {}
_EMBED_CACHE_MAX = 500        # teto de seguranca; materia x tema nao chega perto disso


def _embed(texto):
    """Vetor de embedding (EMBED_DIM floats) do texto, ou None em falha."""
    if texto in _EMBED_CACHE:
        return _EMBED_CACHE[texto]
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_EMBED_MODEL}:embedContent?key={API_KEY}"
    )
    body = {"content": {"parts": [{"text": texto}]}, "outputDimensionality": EMBED_DIM}
    try:
        vals = requests.post(url, json=body, timeout=15).json().get("embedding", {}).get("values")
        if not (isinstance(vals, list) and vals):
            return None                       # falha NAO entra no cache: retenta na proxima
        if len(_EMBED_CACHE) < _EMBED_CACHE_MAX:
            _EMBED_CACHE[texto] = vals
        return vals
    except Exception as e:
        print("[KaIA] erro embedding:", e)
        return None


# ==== FALHA DE GERAÇÃO (proxy de cota estourada) ====
# Cota estourada NÃO quebra o app: o cache-first serve questão antiga e o front entra
# em cooldown. Ótimo pro aluno, péssimo pra você — passa despercebido até alguém notar
# que as questões pararam de variar. O contador põe isso no log, com total do dia.
_FALHAS_GERACAO = {}          # 'AAAA-MM-DD' -> n
FALHAS_GERACAO_ALERTA = 10    # a partir daqui o log sobe de tom


def _registrar_falha_geracao(onde):
    """Conta e loga uma falha de geração. Devolve o total de hoje."""
    dia = datetime.now(timezone.utc).date().isoformat()
    for d in [d for d in _FALHAS_GERACAO if d < dia]:      # ISO ordena por data
        _FALHAS_GERACAO.pop(d, None)
    n = _FALHAS_GERACAO[dia] = _FALHAS_GERACAO.get(dia, 0) + 1
    marca = "AVISO (cota?)" if n >= FALHAS_GERACAO_ALERTA else "info"
    print(f"[KaIA] {marca}: falha de geração em {onde} — {n}ª hoje ({dia})")
    return n


def _vec_literal(v):
    """Vetor como literal pgvector ('[a,b,...]') p/ passar via asyncpg + cast ::vector."""
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def extrair_json(texto):
    """Extrai JSON mesmo quando vem dentro de cercas markdown ```json ... ```."""
    m = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
    if m:
        texto = m.group(1)
    return json.loads(texto.strip())


# ================== API: TEMAS de uma matéria ===============================
# Temas FIXOS e curados (TEMAS_FIXOS) — sem geração/IA e sem cache. Instantâneo,
# ZERO chamada ao Gemini, e alinhado ao que mais cai no ENEM (Matriz INEP + análise).
@app.post("/temas", dependencies=[Depends(usuario_autenticado)])
async def temas(dados: dict = Body(default={})):
    materia = (dados.get("materia") or "").strip()
    lista = TEMAS_FIXOS.get(materia, [])
    if not lista:
        return JSONResponse({"temas": [], "erro": "Matéria sem temas cadastrados."},
                            status_code=404)
    return {"temas": lista, "fonte": "fixo"}


@app.post("/intervencao/reancoragem", dependencies=[Depends(usuario_autenticado)])
async def intervencao_reancoragem(dados: dict = Body(default={})):
    """Reancoragem (refeita): dado o ENUNCIADO da questão atual, gera 3 frases curtas —
    o que a questão REALMENTE pede + 2 leituras erradas plausíveis (presa à moldura /
    foca num detalhe). Micro-check de compreensão do PRESENTE (vs checkpoint = passado).
    Escopo: trabalha no enunciado da questão (o produto foca em questões, não em textos)."""
    enunciado = (dados.get("enunciado") or "").strip()
    if not enunciado:
        return JSONResponse({"erro": "sem enunciado"}, status_code=400)
    prompt = f"""Um aluno se distraiu lendo esta questão. Antes de voltar às alternativas,
ele vai reancorar identificando O QUE A QUESTÃO REALMENTE PEDE (o comando central).
ENUNCIADO: {enunciado[:1500]}

Responda APENAS com um objeto JSON EXATO:
{{"pede": "frase curta (no máximo 12 palavras) do comando central da questão",
  "erros": ["leitura errada 1: presa à MOLDURA/contexto do enunciado, não ao comando",
            "leitura errada 2: foca num DETALHE secundário em vez do comando central"]}}
As 3 frases devem ser curtas, do MESMO tamanho/estilo (não entregue qual é a certa),
em texto corrido sem markdown."""
    for _ in range(3):     # re-tenta: o Gemini às vezes dá soluço (429/timeout/JSON torto)
        try:
            d = extrair_json(await asyncio.to_thread(chamar_gemini, prompt))
            pede = _sem_markdown((d or {}).get("pede", "") or "").strip()
            erros = [_sem_markdown(e or "").strip() for e in ((d or {}).get("erros") or [])]
            erros = [e for e in erros if e]
            if pede and len(erros) >= 2:
                return {"pede": pede, "erros": erros[:2]}
        except Exception as e:
            print("[KaIA] erro reancoragem (re-tentando):", e)
    _registrar_falha_geracao("intervencao_reancoragem")
    return JSONResponse({"erro": "falha na geração"}, status_code=502)


# ================== API: ANOTAÇÕES (caderno do aluno por tema) ================
# Canvas de anotações da tela de estudo (Etapa 9a — só texto). Uma linha por
# (aluno_id, tema); os elementos ficam num array jsonb. Só o backend acessa a
# tabela `anotacoes` (RLS ligado, SEM policy para a anon key) — o isolamento por
# aluno é o `where aluno_id = $1` daqui. Sem Supabase Auth, é o mesmo modelo de
# confiança do resto do app: convém, não é segurança forte (ver Etapa 10).
@app.get("/anotacoes")
async def obter_anotacoes(request: Request, tema: str = "",
                          ident: dict = Depends(usuario_identidade)):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    aluno_id, tema = (ident.get("sub") or "").strip(), tema.strip()   # dono = token, não cliente
    if not aluno_id or not tema:
        return JSONResponse({"erro": "tema é obrigatório."}, status_code=400)
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


@app.put("/anotacoes")
async def salvar_anotacoes(body: AnotacoesIn, request: Request,
                          ident: dict = Depends(usuario_identidade)):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    aluno_id, tema = (ident.get("sub") or "").strip(), body.tema.strip()   # dono = token, não body.aluno_id
    if not aluno_id or not tema:
        return JSONResponse({"erro": "tema é obrigatório."}, status_code=400)
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


@app.get("/perfil/estatisticas")
async def perfil_estatisticas(request: Request, ident: dict = Depends(usuario_identidade)):
    # Auto-consulta: o aluno só vê as PRÓPRIAS estatísticas. aluno_id vem do token
    # (sub), nunca de query param — desempenho_semanal e sessions são chaveados por
    # user_id == sub.
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    aluno_id = (ident.get("sub") or "").strip()
    if not aluno_id:
        return JSONResponse({"erro": "identidade ausente no token."}, status_code=400)

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

@app.get("/questoes/hoje")
async def questoes_hoje(request: Request, uid: str = Depends(usuario_autenticado)):
    """Conta as questões respondidas HOJE pelo aluno (eventos question_answer),
    para a barra de meta diária. Identidade vem do token, não do cliente."""
    pool = request.app.state.pool
    if pool is None:
        return {"respondidas_hoje": 0, "meta": META_QUESTOES_DIA}
    user_id = (uid or "").strip()
    if not user_id:
        return JSONResponse({"erro": "identidade ausente no token."}, status_code=400)
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
def _sem_markdown(t):
    """Tira markdown do texto (cabeçalhos ##, negrito **, crase) — os exemplos reais
    do ENEM têm isso e a IA às vezes copia."""
    if not isinstance(t, str):
        return t
    t = re.sub(r'(?m)^\s*#{1,6}\s*', '', t)        # "## Título" -> "Título"
    return t.replace('**', '').replace('__', '').replace('`', '').strip()


def _enunciado_incompleto(q, opts):
    """True quando o enunciado fecha em frase completa mas as alternativas sao
    FRAGMENTOS que precisariam completa-la — a questao acaba sem pergunta nenhuma.
    Foi assim que passou uma do DIP: texto correto, alternativas soltas, nada ligando.
    Medido contra as 715 reais do banco: marca 0,7% delas, e nao marca o estilo ENEM de
    completar (que termina SEM ponto final)."""
    e = (q or "").strip()
    if not e or not e.endswith("."):
        return False                       # pergunta direta ou trecho a completar: ok
    ini = [str(o).strip()[:1] for o in opts if str(o).strip()]
    if not ini:
        return False
    return sum(1 for c in ini if c.islower()) >= max(1, len(ini) - 1)


def _questao_utilizavel(questao):
    """Barreira antes de a questao chegar ao aluno. Pega defeito ESTRUTURAL — nao pega
    erro de conteudo, que exige um verificador entendendo a materia."""
    opts = [str(o).strip() for o in (questao.get("opts") or [])]
    if len(opts) < 4 or any(not o for o in opts):
        return False                                    # alternativa faltando ou vazia
    if len({o.lower() for o in opts}) != len(opts):
        return False                                    # alternativas repetidas
    if not str(questao.get("q") or "").strip():
        return False
    return not _enunciado_incompleto(questao.get("q"), opts)


def _normalizar_questao(questao):
    questao["q"] = _sem_markdown(questao.get("q", ""))
    opts = [_sem_markdown(o) for o in (questao.get("opts") or [])]
    questao["opts"] = opts
    pe = questao.get("porque_erradas")
    if not isinstance(pe, list) or len(pe) != len(opts):
        questao["porque_erradas"] = [
            (pe[i] if isinstance(pe, list) and i < len(pe) else "")
            for i in range(len(opts))
        ]
    # Embaralha as alternativas -> posição da correta fica UNIFORME. O LLM tende a pôr
    # a certa na 2ª e quase nunca na última; aqui remapeamos ans e mantemos o
    # porque_erradas alinhado por índice.
    ans = questao.get("ans")
    n = len(opts)
    if isinstance(ans, int) and 0 <= ans < n and n > 1:
        ordem = list(range(n))
        random.shuffle(ordem)
        questao["opts"] = [opts[i] for i in ordem]
        pe2 = questao.get("porque_erradas") or []
        if len(pe2) == n:
            questao["porque_erradas"] = [pe2[i] for i in ordem]
        questao["ans"] = ordem.index(ans)
    questao.setdefault("explicacao", "")
    return questao


# ==== PoT (cálculo): a IA dá a FÓRMULA, o backend EXECUTA -> gabarito correto ====
_POT_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
            ast.Pow: lambda a, b: a ** b, ast.Mod: lambda a, b: a % b}
_POT_UN = {ast.USub: lambda a: -a, ast.UAdd: lambda a: +a}
_POT_FUN = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "log": math.log, "log10": math.log10, "ln": math.log, "exp": math.exp, "abs": abs}
_POT_CONST = {"pi": math.pi, "e": math.e}


def _pot_eval(expr):
    """Avalia SÓ aritmética + funções básicas (sem nomes/atributos livres) — seguro."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _POT_OPS:
            return _POT_OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _POT_UN:
            return _POT_UN[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _POT_FUN:
            return _POT_FUN[n.func.id](*[ev(a) for a in n.args])
        if isinstance(n, ast.Name) and n.id in _POT_CONST:
            return _POT_CONST[n.id]
        raise ValueError("expressão não permitida")
    return ev(ast.parse(expr, mode="eval"))


def _pot_limpar_formula(f):
    f = str(f).split("=")[-1]
    f = f.replace("^", "**").replace("×", "*").replace("·", "*").replace("÷", "/").replace(",", ".")
    return re.sub(r"[^\d+\-*/().\sa-zA-Z_]", "", f).strip()


def _pot_num(s):
    m = re.search(r"[-+]?\d[\d.,\s]*", str(s))
    if not m:
        return None
    t = m.group(0).replace(" ", "")
    if "." in t and "," in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif t.count(".") > 1:
        p = t.split("."); t = "".join(p[:-1]) + "." + p[-1]
    try:
        return float(t)
    except ValueError:
        return None


def _pot_acha_opcao(calc, opts, tol=0.005, folga=2.0):
    """Índice da opção que É o valor calculado. None = descarta a questão.

    Duas regras, as duas vindas de defeito achado à mão:

    tol — a opção tem de SER o resultado, não ficar perto dele. Com os 3% de antes,
    uma média ponderada que dá 7,3 casava com 7,2 e com 7,4 (ambas a 1,4%) e virava
    gabarito, sem que 7,3 estivesse entre as alternativas. Meio por cento cobre
    arredondamento de exibição (7,333 escrito "7,33") e não cobre distrator.

    folga — se a segunda mais próxima também está perto, o número não identifica
    uma opção só. Aí a questão é ambígua e não se serve, mesmo com uma vencedora."""
    limite = max(tol * abs(calc), 1e-6)
    dists = []
    for i, o in enumerate(opts):
        v = _pot_num(o)
        if v is not None:
            dists.append((abs(v - calc), i))
    if not dists:
        return None
    dists.sort()
    d1, i1 = dists[0]
    if d1 > limite:
        return None
    if len(dists) > 1 and dists[1][0] < folga * max(d1, limite):
        return None                                    # duas opções servem -> ambígua
    return i1


# Formato EXATO de cada questão (string literal — as chaves NÃO são interpoladas).
_FORMATO_QUESTAO = (
    '{"q": "enunciado da questão", "opts": ["a", "b", "c", "d", "e"], "ans": 0,\n'
    '  "explicacao": "por que a alternativa correta é a correta (1 a 2 frases)",\n'
    '  "porque_erradas": ["por que a opção 0 está errada", "...opção 1...", "...", "...", "..."]}'
)

# Descrição da dificuldade por nível (1..5) para o prompt do Gemini (Parte 6).
_NIVEIS_DIF = {
    1: "reconhecer/lembrar um conceito isolado (definição direta)",
    2: "aplicar um conceito em situação direta, um único passo",
    3: "interpretar um texto/gráfico/dado e relacionar a um conceito (padrão ENEM)",
    4: "combinar 2 ou mais conceitos/etapas; interpretar e inferir",
    5: "integrar áreas/ideias, com raciocínio contra-intuitivo e distrator forte que exige eliminação",
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
        "veredito": row["veredito"] if "veredito" in row.keys() else None,
        "q": row["enunciado"],
        "opts": json.loads(row["alternativas"]),
        "ans": row["resposta_correta"],
        "explicacao": row["explicacao"],
        "porque_erradas": json.loads(row["porque_erradas"]),
    }

# Só os campos que o frontend precisa (tira usa_hobbie e afins).
def _frontend_q(q):
    return {
        # Sem o id, a resposta do aluno nao volta amarrada a QUAL questao — e sem isso
        # nao existe item analysis (ninguem consegue agrupar respostas por questao).
        "questao_id": q.get("questao_id"),
        # Em quarentena = ainda nao verificada. O front nao a esconde (o aluno responde
        # normalmente), mas ela NAO entra na nota que decide subir/descer de nivel: um
        # gabarito errado nao pode rebaixar o aluno.
        "em_quarentena": q.get("veredito") is None,
        "q": q.get("q", ""),
        "opts": q.get("opts", []),
        "ans": q.get("ans", 0),
        "explicacao": q.get("explicacao", ""),
        "porque_erradas": q.get("porque_erradas", []),
    }

# Exemplos reais (few-shot) carregados do JSON no repo (curados do ENEM, Apache 2.0).
# Chaveado por matéria KaIA; matérias de conta (MAT/FIS/QUI) não têm entrada -> [].
_EXEMPLOS_PATH = Path(__file__).with_name("exemplos_few_shot.json")
try:
    _EXEMPLOS_FEW_SHOT = json.loads(_EXEMPLOS_PATH.read_text(encoding="utf-8"))
except Exception:
    _EXEMPLOS_FEW_SHOT = {}


def _exemplos_few_shot(materia):
    """TODOS os exemplos reais da matéria (curados p/ variedade de formato), em ordem
    embaralhada — [] se não houver (matéria de conta ou JSON ausente). Sem banco."""
    pool = list(_EXEMPLOS_FEW_SHOT.get(materia) or [])
    random.shuffle(pool)
    return pool


# Gera `n` questões no Gemini (roda em thread p/ não travar o loop). Com hobbie,
# instrui ~60% a usá-lo e a marcar "usa_hobbie" (Parte 5). `exemplos`: questões
# reais injetadas como few-shot (estilo/dificuldade), quando houver.
async def _gerar_no_gemini(n, materia, nome, tema, hobbie, nivel, exemplos=None, evitar=None):
    n_pedir = max(n, math.ceil(n * FATOR_SOBRA_GERACAO))   # sobra p/ cobrir os descartes
    dificuldade = _NIVEIS_DIF[max(1, min(nivel, 5))]
    if hobbie:
        proporcao = max(1, round(n_pedir * 0.6))
        formato = _FORMATO_QUESTAO_HOBBIE
        regra_hobbie = (
            f'- Em aproximadamente {proporcao} das {n_pedir} questões, use o hobbie "{hobbie}" como '
            f'CONTEXTO CENTRAL do enunciado — a situação/cenário gira em torno dele, não é só '
            f'uma menção de passagem; o conceito avaliado continua EXATAMENTE o mesmo. Nas '
            f'outras, enunciados genéricos (sem citar o hobbie).\n'
            f'- Em CADA questão inclua o booleano "usa_hobbie" indicando se usou o hobbie.\n'
        )
    else:
        formato = _FORMATO_QUESTAO
        regra_hobbie = ''
    # Few-shot: questões reais como referência de ESTILO/dificuldade (não copiar conteúdo).
    bloco_exemplos = ''
    if exemplos:
        refs = []
        for ex in exemplos:
            alts = ' / '.join(ex.get('alternativas') or [])
            refs.append(f'Enunciado: {ex["enunciado"][:400]}\nAlternativas: {alts}')
        bloco_exemplos = (
            '\nExemplos de questões REAIS de vestibular desta matéria — copie o ESTILO, '
            'registro, comprimento e nível, e VARIE o tipo/formato de enunciado entre as '
            'questões como estes exemplos variam (interpretação de texto, análise de fonte, '
            'aplicação de conceito). Crie questões NOVAS — NÃO reaproveite o conteúdo, NEM '
            'repita a mesma estrutura em todas:\n'
            + '\n---\n'.join(refs) + '\n'
        )
    # Anti-repetição: mostra o que JÁ existe dessa combinação pra o modelo divergir.
    bloco_evitar = ''
    if evitar:
        lista = '\n'.join(f'- {e[:180]}' for e in evitar[:10] if e)
        if lista:
            bloco_evitar = (
                '\nEstas questões JÁ EXISTEM sobre este tema — NÃO repita o enunciado nem o '
                'mesmo foco; aborde aspectos/subtemas DIFERENTES:\n' + lista + '\n'
            )
    prompt = f"""
Crie {n_pedir} questões objetivas DIFERENTES de múltipla escolha sobre "{tema}" ({nome})
para o ensino médio.
Responda APENAS com um ARRAY JSON de {n_pedir} objetos, cada um no formato EXATO:
{formato}
Regras:
- "ans" é o índice (0 a 4) da alternativa correta.
- "porque_erradas" tem EXATAMENTE o tamanho e a ordem de "opts"; no índice da correta use "".
- As {n_pedir} questões devem ser distintas entre si (enunciados e focos diferentes).
- Alternativas (corretas E erradas) devem ser termos/conceitos REAIS e plausíveis; NUNCA invente palavras ou termos que não existam.
- Enunciados em TEXTO CORRIDO — sem markdown (nada de ##, **, títulos ou listas).
- O enunciado TEM de terminar em PERGUNTA ("?") ou em trecho que as alternativas completam
  (sem ponto final). NUNCA termine em frase fechada seguida de alternativas soltas.
- As 5 alternativas devem ser DIFERENTES entre si (nem repetição, nem paráfrase da mesma coisa).
- Dificuldade: nível {nivel}/5 ({dificuldade}) — calibre a esse nível.
{regra_hobbie}- Linguagem simples e acolhedora — o erro não é punição, é aprendizado.
{bloco_evitar}{bloco_exemplos}"""
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
        prontas = [_normalizar_questao(q) for q in itens
                   if isinstance(q, dict) and q.get("opts")]
        boas = [q for q in prontas if _questao_utilizavel(q)]
        if len(boas) < len(prontas):
            print(f"[KaIA] descartadas {len(prontas) - len(boas)} questao(oes) malformada(s) "
                  f"p/ {materia}/{tema}")
        return boas[:n]                                    # a sobra fica de fora
    except Exception as e:
        print("[KaIA] erro Gemini /gerar-questao:", e)
        return []


_FORMATO_POT = (
    '{"q": "enunciado", "opts": ["v1","v2","v3","v4","v5"], '
    '"formula": "expressão aritmética SÓ com números e + - * / ** e funções '
    'sqrt/sin/cos/log/pi, com os valores JÁ substituídos (sem variáveis, sem unidades, '
    'sem =), que calcula a resposta correta", '
    '"porque_erradas": ["por que v1 erra", "...", "...", "...", "..."]}'
)


async def _gerar_calculo_pot(n, materia, nome, tema, hobbie, nivel, exemplos=None, evitar=None):
    n_pedir = max(n, math.ceil(n * FATOR_SOBRA_GERACAO))   # o PoT descarta bastante
    """PoT: a IA gera a questão de cálculo COM a fórmula; o backend EXECUTA a fórmula e
    usa a opção que bate como gabarito (a CONTA, não o 'achismo'), DESCARTANDO as que não
    fecham. Devolve no formato normal (q/opts/ans/porque_erradas)."""
    dificuldade = _NIVEIS_DIF[max(1, min(nivel, 5))]
    regra_hobbie = ""
    if hobbie:
        regra_hobbie = (f'- Em ~{max(1, round(n_pedir * 0.6))} das {n_pedir}, use "{hobbie}" como contexto '
                        f'central do enunciado (a conta continua a mesma).\n')
    bloco_ex = ""
    if exemplos:
        refs = "\n---\n".join(
            f"Enunciado: {e['enunciado'][:400]}\nAlternativas: {' / '.join(e.get('alternativas') or [])}"
            for e in exemplos)
        bloco_ex = ("\nExemplos de questões REAIS de cálculo desta matéria — copie o ESTILO e o "
                    "tipo de conta (NÃO copie os números):\n" + refs + "\n")
    bloco_evitar = ""
    if evitar:
        lst = "\n".join(f"- {e[:150]}" for e in evitar[:8] if e)
        if lst:
            bloco_evitar = "\nEstas JÁ EXISTEM — mude os números e o contexto:\n" + lst + "\n"
    prompt = f"""Crie {n_pedir} questões objetivas de CÁLCULO sobre "{tema}" ({nome}) para o ensino médio.
Responda APENAS com um ARRAY JSON de {n_pedir} objetos no formato EXATO:
{_FORMATO_POT}
Regras:
- A "formula" tem de resolver EXATAMENTE o que o enunciado pergunta: confira que os números
  dela vêm do enunciado e que ela responde à pergunta feita, não a outra parecida.
- Os dados do enunciado têm de ser CONSISTENTES entre si (se há duas condições, ambas
  precisam valer para a mesma resposta) e levar a um resultado limpo.
- A resposta CORRETA tem de ser EXATAMENTE o valor que a "formula" calcula, e estar entre as 5 "opts".
- As outras 4 "opts" são distratores plausíveis (erros comuns), com a MESMA unidade/formato.
- "opts" com número + unidade (ex.: "12 m/s"); use ponto decimal.
- Dificuldade: nível {nivel}/5 ({dificuldade}). Termos/unidades REAIS, nunca invente.
- Enunciado em texto corrido, sem markdown, terminando em pergunta ou trecho a completar.
{regra_hobbie}{bloco_evitar}{bloco_ex}"""
    try:
        dados = extrair_json(await asyncio.to_thread(chamar_gemini, prompt))
    except Exception as e:
        print("[KaIA] erro Gemini PoT:", e)
        return []
    itens = dados if isinstance(dados, list) else (
        dados.get("questoes") if isinstance(dados, dict) and "questoes" in dados else [dados])
    saida = []
    for q in itens or []:
        if not isinstance(q, dict) or not q.get("opts") or not q.get("formula"):
            continue
        try:
            calc = _pot_eval(_pot_limpar_formula(q["formula"]))
        except Exception:
            continue                                   # fórmula inválida -> descarta
        opts = [_sem_markdown(o) for o in q["opts"]]
        idx = _pot_acha_opcao(calc, opts)
        if idx is None:
            continue                                   # a conta não bate com opção -> furada, descarta
        q["opts"] = opts
        q["ans"] = idx                                 # gabarito = a CONTA (não o que a IA disse)
        q["formula_pot"] = q.pop("formula", None)      # guardada: e o que permite auditar depois
        pronta = _normalizar_questao(q)
        if _questao_utilizavel(pronta):
            saida.append(pronta)
    print(f"[KaIA] PoT: {len(saida)}/{len(itens or [])} de cálculo válidas p/ {materia}/{tema} (nível {nivel})")
    return saida[:n]


# ==== VERIFICACAO INDEPENDENTE (2a barreira) =================================
# O filtro estrutural pega enunciado malformado; o PoT pega a conta que nao fecha com
# nenhuma alternativa. Nenhum dos dois pega GABARITO ERRADO, que foi o defeito mais
# grave achado na avaliacao com professores. Aqui um modelo DIFERENTE do gerador
# resolve a questao sem ver o gabarito. Diferente de proposito: verificador da mesma
# familia compartilha os mesmos vieses e concorda com o proprio erro.
#
# Roda em BACKGROUND, nao na geracao: verificar na hora somaria ~5s de espera ao aluno.
# Ate ser verificada, a questao fica em QUARENTENA — servida a poucos alunos, para que
# um defeito atinja um punhado e nao a base inteira.
# Versao das REGRAS do prompt. Suba quando mudar qualquer regra de geracao: e o que
# permite responder depois "a regra nova reduziu o erro?". Sem isso, questao velha e
# questao nova ficam indistinguiveis no banco.
VERSAO_PROMPT = "v3-2026-09"

# Pede mais questoes do que precisa e fica com as que passam nas barreiras — e o que o
# Duolingo faz (gera variantes, seleciona). A saida e a parte cara, entao isto encarece
# ~50% a geracao (fracao de centavo) e evita entregar lote curto quando alguma e
# descartada. So a geracao aumenta: o que o aluno ve continua sendo n.
FATOR_SOBRA_GERACAO = 1.5
# Familia Flash (nao Flash-Lite, que e a do gerador): a independencia vem justamente
# de nao compartilhar treinamento. O 3.6 tem cota diaria pequena demais no tier
# gratuito (~20 chamadas); o 3.8 e mais novo e tem cota.
MODELO_VERIFICADOR = os.getenv("KAIA_MODELO_VERIFICADOR", "gemini-3.8-flash")
VERIF_LOTE = int(os.getenv("KAIA_VERIF_LOTE", "5"))   # questoes por chamada de verificacao
QUARENTENA_MAX_ALUNOS = int(os.getenv("KAIA_QUARENTENA_ALUNOS", "3"))
VERIFICA_POR_RODADA = 20          # quantas por ciclo do job (em lotes de VERIF_LOTE)

# Verifica em LOTE: uma chamada para VERIF_LOTE questoes, nao uma por questao. Foi o
# que destravou o volume — a cota do tier gratuito nao aguenta uma chamada por questao.
# Pede o raciocinio de cada uma antes da resposta para o modelo nao ficar preguicoso
# despachando o lote inteiro sem conferir.
_PROMPT_VERIFICACAO = """Resolva cada questão de múltipla escolha do ensino médio brasileiro
abaixo. Trate cada uma de forma independente e confira a conta/o conteúdo antes de responder.

{questoes}

Responda APENAS com um ARRAY JSON, um objeto por questão, na mesma ordem:
[{{"n": 1, "raciocinio": "como chegou à resposta, 1 frase", "resposta": "A"|"B"|"C"|"D"|"E"|"NENHUMA", "problema": ""}}]

- "resposta": a alternativa correta. Use "NENHUMA" se a resposta certa NÃO estiver entre
  as alternativas, ou se o enunciado não permitir chegar a uma resposta.
- "problema": vazio se está tudo bem; senão descreva o defeito em até 15 palavras."""


def _letra_para_indice(letra):
    letra = str(letra).strip().upper()
    if letra == "NENHUMA":
        return -1
    return ord(letra) - 65 if len(letra) == 1 and "A" <= letra <= "E" else None


def verificar_lote(questoes):
    """[(indice, nota)] para uma lista de (enunciado, opts), UMA chamada só.
    -1 = "nenhuma alternativa correta"; None = sem resposta do verificador para aquela
    questao (fica SEM veredito: falha de infra nao e defeito da questao)."""
    if not questoes:
        return []
    blocos = []
    for i, (enun, opts) in enumerate(questoes, 1):
        alts = "\n".join(f"{chr(65 + j)}) {o}" for j, o in enumerate(opts))
        blocos.append(f"### Questão {i}\n{enun}\n{alts}")
    url = ("https://generativelanguage.googleapis.com/v1beta/"
           f"models/{MODELO_VERIFICADOR}:generateContent?key={API_KEY}")
    body = {"contents": [{"parts": [{"text": _PROMPT_VERIFICACAO.format(
        questoes=("\n\n").join(blocos))}]}]}
    vazio = [(None, "")] * len(questoes)
    try:
        r = requests.post(url, json=body, timeout=180).json()
        bruto = r["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return vazio
    try:
        if "```" in bruto:
            bruto = bruto.split("```")[1].removeprefix("json").strip()
        dados = json.loads(bruto[bruto.index("["):bruto.rindex("]") + 1])
    except Exception:
        return vazio
    saida = list(vazio)
    for d in dados if isinstance(dados, list) else []:
        if not isinstance(d, dict):
            continue
        try:
            pos = int(d.get("n", 0)) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= pos < len(saida):
            saida[pos] = (_letra_para_indice(d.get("resposta", "")),
                          str(d.get("problema", "")).strip()[:200])
    return saida


def verificar_questao(enunciado, opts):
    """Uma questao só — atalho sobre verificar_lote (usado por scripts offline)."""
    return verificar_lote([(enunciado, opts)])[0]


async def job_verificar_cache(app):
    """Verifica questoes do cache ainda sem veredito, em lotes pequenos."""
    if app.state.pool is None or not API_KEY:
        return
    async with app.state.pool.acquire() as conn:
        try:
            pend = await conn.fetch(
                "select questao_id, enunciado, alternativas, resposta_correta "
                "from questoes_cache where veredito is null "
                "order by criada_em desc limit $1", VERIFICA_POR_RODADA)
        except Exception as e:
            print("[KaIA] verificacao indisponivel (banco atras do schema?):", e)
            return
        for ini in range(0, len(pend), VERIF_LOTE):
            bloco = list(pend[ini:ini + VERIF_LOTE])
            entradas = []
            for q in bloco:
                alts = q["alternativas"]
                entradas.append((q["enunciado"],
                                 json.loads(alts) if isinstance(alts, str) else alts))
            resultados = await asyncio.to_thread(verificar_lote, entradas)
            for q, (idx, nota) in zip(bloco, resultados):
                if idx is None:
                    continue                   # sem veredito: volta no proximo ciclo
                veredito = "ok" if idx == q["resposta_correta"] else "suspeita"
                await conn.execute(
                    "update questoes_cache set veredito = $2, verificada_em = now(), "
                    "verificador_disse = $3, verificador_nota = $4 where questao_id = $1",
                    q["questao_id"], veredito, idx, nota or None)
                if veredito == "suspeita":
                    motivo = ("nenhuma alternativa correta" if idx == -1
                              else f"apontou {chr(65 + idx)}")
                    print(f"[KaIA] questao SUSPEITA ({motivo}) — {q['enunciado'][:60]}")


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
    # 'suspeita' nunca e servida. Sem veredito ainda -> QUARENTENA: so enquanto poucos
    # alunos a viram, para um defeito atingir um punhado e nao a base inteira. E o
    # `order by veredito is null` poe as ja verificadas na frente.
    params.append(QUARENTENA_MAX_ALUNOS)
    gate_veredito = f"""and (c.veredito = 'ok' or (c.veredito is null and
              (select count(*) from questoes_vistas q2 where q2.questao_id = c.questao_id)
              < ${len(params)}))"""
    params.append(limite)
    lim = len(params)
    rows = await conn.fetch(f"""
        select c.questao_id, c.enunciado, c.alternativas, c.resposta_correta,
               c.explicacao, c.porque_erradas, c.veredito
        from questoes_cache c
        where c.materia = $1 and c.tema = $2 and c.nivel = $3 and {cond_hobbie}
          and not exists (select 1 from questoes_vistas v
                          where v.aluno_id = ${uid}::uuid and v.questao_id = c.questao_id)
          {gate_veredito}
          {excl_sql}
        order by c.veredito is null, random() limit ${lim}
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
                      resposta_correta, explicacao, porque_erradas, modelo, versao_prompt)
                   values ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9::jsonb, $10, $11)
                   returning questao_id""",
                materia, tema, nivel, hob, item["q"], json.dumps(item["opts"]),
                item["ans"], item["explicacao"], json.dumps(item["porque_erradas"]),
                GEMINI_MODEL, VERSAO_PROMPT)
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


# Few-shot DINÂMICO: recupera do banco de questões reais (pgvector) as k mais parecidas
# com o tema pedido. Devolve no formato de _exemplos_few_shot, ou None em qualquer falha
# (sem pgvector, sem embedding, tabela vazia) — aí o caller usa os exemplos FIXOS.
async def _exemplos_similares(conn, materia, tema, nivel=None, calculo=None, por_tema=False, k=5):
    vetor = await asyncio.to_thread(_embed, f"{MATERIAS.get(materia, materia)}: {tema}")
    if not vetor:
        return None
    area = _AREA_ENEM.get(materia, materia)
    alvos = list(dict.fromkeys([materia, area]))   # matéria fina (BLUEX) + área (maritaca)
    vec = _vec_literal(vetor)
    sel = ("select enunciado, alternativas, gabarito from questoes_reais "
           "where materia = any($1::text[]) and embedding is not null ")
    fcalc = ("and calculo is true " if calculo is True
             else "and (calculo is not true) " if calculo is False else "")
    fniv = "and (nivel is null or abs(nivel - $2) <= 1) "
    # candidatos (sql, params) do mais específico ao mais amplo. Em Exatas/Natureza,
    # `por_tema` põe as do MESMO tema PRIMEIRO (backfill pelo pool da matéria). Degrada
    # gracioso se a coluna (tema/nivel) faltar.
    cand = []
    if por_tema and nivel is not None:
        cand.append((sel + fcalc + fniv + "order by (tema is distinct from $3), embedding <=> $4::vector limit $5",
                     [alvos, nivel, tema, vec, k]))
    if por_tema:
        cand.append((sel + fcalc + "order by (tema is distinct from $2), embedding <=> $3::vector limit $4",
                     [alvos, tema, vec, k]))
    if nivel is not None:
        cand.append((sel + fcalc + fniv + "order by embedding <=> $3::vector limit $4",
                     [alvos, nivel, vec, k]))
    if fcalc:
        cand.append((sel + fcalc + "order by embedding <=> $2::vector limit $3", [alvos, vec, k]))
    cand.append((sel + "order by embedding <=> $2::vector limit $3", [alvos, vec, k]))
    rows = None
    for sql, params in cand:
        try:
            rows = await conn.fetch(sql, *params)
            if rows:
                break
        except Exception:
            rows = None
    if not rows:
        return None
    exemplos = []
    for r in rows:
        alts = r["alternativas"]
        exemplos.append({"enunciado": r["enunciado"],
                         "alternativas": json.loads(alts) if isinstance(alts, str) else alts,
                         "gabarito": r["gabarito"]})
    print(f"[KaIA] few-shot dinâmico: {len(exemplos)} exemplos reais p/ {materia}/{tema} (nível {nivel})")
    return exemplos


# Enunciados JÁ existentes dessa combinação (p/ o prompt anti-repetição divergir).
async def _enunciados_existentes(conn, materia, tema, nivel, limite=10):
    try:
        rows = await conn.fetch(
            "select enunciado from questoes_cache "
            "where materia = $1 and tema = $2 and nivel = $3 order by random() limit $4",
            materia, tema, nivel, limite)
        return [r["enunciado"] for r in rows]
    except Exception as e:
        print("[KaIA] erro ao buscar enunciados existentes:", e)
        return []


async def _montar_banda(conn, user_id, materia, nome, tema, hobbie, nivel, n):
    """Monta até `n` questões de UMA faixa (materia+tema+nivel): cache-first (hobbie ->
    genérica -> reset de vistas antigas) e gera o que faltar no Gemini (few-shot),
    salvando no cache. Marca as entregues como vistas e etiqueta o nível em cada uma
    (o front escolhe pela faixa no buffer)."""
    entregues = []
    # 1) cache com o hobbie da vez
    if hobbie:
        entregues += await _buscar_cache(conn, user_id, materia, tema, nivel, hobbie, n)
    # 2) completa com genéricas (hobbie NULL)
    if len(entregues) < n:
        entregues += await _buscar_cache(conn, user_id, materia, tema, nivel, None, n - len(entregues))
    # 3) esgotou? libera as vistas antigas (>30d) e tenta o cache de novo.
    if len(entregues) < n:
        await _resetar_vistas_antigas(conn, user_id, materia, tema, nivel)
        if hobbie:
            ja = [q["questao_id"] for q in entregues if q.get("questao_id")]
            entregues += await _buscar_cache(conn, user_id, materia, tema, nivel, hobbie, n - len(entregues), ja)
        if len(entregues) < n:
            ja = [q["questao_id"] for q in entregues if q.get("questao_id")]
            entregues += await _buscar_cache(conn, user_id, materia, tema, nivel, None, n - len(entregues), ja)
    # 4) ainda falta -> Gemini (few-shot) + salva no cache. O Gemini às vezes devolve
    #    MENOS que o pedido (faixa concentrada, tema estreito) -> re-tenta até completar
    #    (com anti-repetição a cada volta) pra não devolver o buffer curto.
    if n - len(entregues) > 0:
        calc = _eh_calculo(materia, tema)               # cálculo -> PoT (fórmula executada)
        gerar = _gerar_calculo_pot if calc else _gerar_no_gemini
        # few-shot dinâmico (pgvector) SE ligado; conceitual cai nos exemplos fixos, cálculo não
        exemplos = None
        if FEWSHOT_DINAMICO:
            exemplos = await _exemplos_similares(conn, materia, tema, nivel, calculo=calc,
                                                 por_tema=_exatas_natureza(materia))
        exemplos = exemplos or (None if calc else _exemplos_few_shot(materia))
        for _ in range(3):
            if n - len(entregues) <= 0:
                break
            evitar = await _enunciados_existentes(conn, materia, tema, nivel)
            novas = await gerar(n - len(entregues), materia, nome, tema, hobbie, nivel,
                                exemplos=exemplos, evitar=evitar)
            if not novas:
                break   # vazio/erro -> não insiste (evita loop e gasto de cota)
            entregues += await _salvar_no_cache(conn, materia, tema, nivel, hobbie, novas)
    # 5) marca vistas + etiqueta o nível
    await _marcar_vistas(conn, user_id, entregues)
    for q in entregues:
        q["nivel"] = nivel
    return entregues


@app.post("/gerar-questao")
async def gerar_questao(request: Request, dados: dict = Body(default={}),
                        uid: str = Depends(usuario_autenticado)):
    materia = dados.get("materia", "")
    nome = MATERIAS.get(materia, materia)
    tema = dados.get("tema", "")
    hobbie = dados.get("hobbie") or None                 # singular; None = genérica
    user_id = (uid or "").strip() or None                # dono = token, não body.user_id
    # compat com o formato antigo (lista "hobbies"): usa o 1º como hobbie.
    if hobbie is None and isinstance(dados.get("hobbies"), list) and dados["hobbies"]:
        hobbie = dados["hobbies"][0]
    # Lista completa de hobbies (buffer varia o hobby POR FAIXA -> não domina um só).
    hobbies_lista = [h for h in (dados.get("hobbies") or []) if h] if isinstance(dados.get("hobbies"), list) else []

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

    # Buffer da sessão: {"nivel": qtd, ...} — o front pede o leque de níveis de uma
    # vez (carregar tudo no início). O backend gera por FAIXA (chamadas pequenas).
    distribuicao = dados.get("distribuicao") if isinstance(dados.get("distribuicao"), dict) else None
    if distribuicao:
        try:
            n = min(sum(int(v) for v in distribuicao.values()), 40)   # teto de segurança
            lote = True
        except (TypeError, ValueError):
            distribuicao = None

    pool = getattr(request.app.state, "pool", None)

    # Sem banco ou sem user_id: sem cache — gera tudo no Gemini (comportamento antigo).
    if pool is None or not user_id:
        entregues = [_frontend_q(q) for q in await _gerar_no_gemini(
            n, materia, nome, tema, hobbie, nivel, exemplos=_exemplos_few_shot(materia))]
        if not entregues:
            _registrar_falha_geracao("gerar-questao (sem cache)")
            return JSONResponse({"erro": "Não foi possível gerar a questão."}, status_code=502)
        return {"questoes": entregues} if lote else entregues[0]

    entregues = []
    try:
        async with pool.acquire() as conn:
            if distribuicao:
                # buffer: gera por FAIXA de nível (chamadas pequenas, calibração limpa).
                # Hobbies em RODÍZIO entre as faixas (ordem embaralhada) -> os hobbies da
                # sessão se alternam, sem um só dominar o buffer.
                if hobbies_lista:
                    random.shuffle(hobbies_lista)
                for i, (niv_str, cnt) in enumerate(distribuicao.items()):
                    try:
                        niv = max(1, min(int(niv_str), 5))
                        cnt = max(0, min(int(cnt), 10))
                    except (TypeError, ValueError):
                        continue
                    if cnt:
                        hob = hobbies_lista[i % len(hobbies_lista)] if hobbies_lista else hobbie
                        entregues += await _montar_banda(conn, user_id, materia, nome, tema, hob, niv, cnt)
            else:
                entregues = await _montar_banda(conn, user_id, materia, nome, tema, hobbie, nivel, n)
    except Exception as e:
        print("[KaIA] erro no cache /gerar-questao:", e)

    if not entregues:
        _registrar_falha_geracao("gerar-questao")
        return JSONResponse({"erro": "Não foi possível gerar a questão."}, status_code=502)
    return {"questoes": entregues} if (lote or distribuicao) else entregues[0]


# Devolve ao pool as questões que o aluno recebeu mas NÃO usou (mudou de nível,
# trocou de tema ou encerrou) — remove de questoes_vistas (Parte 6). Ignora ids
# ausentes (questões de fallback/pré-cache).
@app.post("/questoes/devolver")
async def devolver_questoes(request: Request, dados: dict = Body(default={}),
                           uid: str = Depends(usuario_autenticado)):
    pool = request.app.state.pool
    if pool is None:
        return {"devolvidas": 0}
    user_id = (uid or "").strip()   # dono = token, não body.user_id
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
    Freios (evitam excesso): só distraido/muito_distraido; estado SUSTENTADO por
    >= INTERV_MIN_JANELAS janelas (debounce); confiança >= INTERV_SCORE_MIN;
    warm-up (>=1 questão respondida e sessão >= INTERV_WARMUP_MIN); cooldown por
    estado (INTERV_COOLDOWN_MIN) e teto INTERV_MAX_POR_SESSAO por sessão.
    Silencioso se a tabela interventions ainda não existir (Tarefa 4)."""
    thompson = app.state.thompson
    modelo, scaler = app.state.modelo, app.state.scaler
    if thompson is None or modelo is None or scaler is None:
        return

    async with app.state.pool.acquire() as conn:
        res = await predizer_estado(modelo, scaler, conn, session_id)
        if res is None:
            return
        # Sem baseline não há leitura: nem intervir, nem fechar reward (o bandit
        # aprenderia com uma transição inventada). Zera a streak: o que veio antes
        # não se compara com o que vier depois.
        if not res["confiavel"]:
            _ESTADO_STREAK.pop(str(session_id), None)
            return
        # Reward implícito: fecha intervenções passadas cuja janela já expirou,
        # comparando o estado de então com o atual. Roda mesmo se agora está engajado
        # (o sucesso é justamente ter virado engajado).
        await resolver_rewards(conn, thompson, session_id, res["estado"])

        # Freio 1 (debounce): conta janelas consecutivas no mesmo estado. Atualiza
        # SEMPRE (inclusive engajado) pra resetar quando o aluno reancora.
        sid = str(session_id)
        st = _ESTADO_STREAK.get(sid)
        if st and st["estado"] == res["estado"]:
            st["n"] += 1
        else:
            _ESTADO_STREAK[sid] = {"estado": res["estado"], "n": 1}
        janelas = _ESTADO_STREAK[sid]["n"]

        if res["estado"] not in ESTADOS_QUE_INTERVEM:
            return
        if res["score"] < INTERV_SCORE_MIN:          # freio 3: confiança mínima
            return
        if janelas < INTERV_MIN_JANELAS:             # freio 1: estado sustentado (~60s)
            return

        # Freio 4 (warm-up): só depois da 1ª questão respondida E de um tempo mínimo.
        # Questões de vestibular são longas — a leitura inicial não pode virar "distração";
        # o timer segura caso a 1ª seja respondida rápido demais.
        respondidas = await conn.fetchval(
            "select count(*) from session_events where session_id = $1::uuid "
            "and event_type = 'question_answer'", session_id) or 0
        duracao_min = float(res["feats"].get("duracao_sessao_min") or 0)
        if respondidas < 1 or duracao_min < INTERV_WARMUP_MIN:
            return

        try:
            stats = await conn.fetchrow(
                """
                select count(*) as n, max(triggered_at) as ultima,
                       (select intervention_type from interventions
                         where session_id = $1::uuid order by triggered_at desc limit 1) as ultimo_tipo
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
            if desde_min < INTERV_COOLDOWN_MIN[res["estado"]]:   # freio 2: cooldown por estado
                return

        tempo_estudo_min = float(res["feats"].get("tempo_estudo_acumulado_dia_min") or 0)
        evitar = [stats.get("ultimo_tipo")] if stats.get("ultimo_tipo") else []   # penalidade de recência
        tipo = thompson.select(res["estado"], tempo_estudo_min, evitar=evitar)
        if not tipo:
            return

        # A/B test (DESLIGADO por padrão): metade dos alunos é grupo CONTROLE — NÃO recebe
        # intervenção; loga 'controle_ab' pra medir a recuperação SEM ajuda e comparar com
        # o bandit. Ligar AB_TESTE_ATIVO por um tempo, coletar a prova, e desligar.
        if AB_TESTE_ATIVO:
            uid = await conn.fetchval(
                "select user_id from sessions where session_id = $1::uuid", session_id)
            if _grupo_ab(str(uid)) == "controle":
                tipo = "controle_ab"

        await conn.execute(
            """
            insert into interventions (session_id, intervention_type, triggered_at, estado_antes)
            values ($1::uuid, $2, now(), $3)
            """,
            session_id, tipo, res["estado"],
        )
        if tipo != "controle_ab":
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
        print("[KaIA] colunas de reward ausentes — o banco está atrás do schema "
              "versionado (supabase/migrations/*_remote_schema.sql):", e)
        return

    for p in pendentes:
        reward = reward_por_transicao(p["estado_antes"], estado_atual)
        if reward is None:
            continue
        try:
            if p["intervention_type"] in INTERVENCOES:   # 'controle_ab' mede o reward mas NÃO treina o bandit
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
    "mudancas_aba", "tempo_fora_foco_s", "maior_ausencia_unica_s",
    "cliques_fora_area_estudo", "taxa_abandono_sessao",
    # ritmo (absolutas) — FORMA da imobilidade, nao o total: separa leitura densa
    # (muitos blocos medios) de mente vagando/ausencia (um bloco longo).
    "maior_bloco_parado_s", "n_blocos_parados",
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
DURACAO_MAX_MIN = 240         # teto: acima disso é sessão que nunca fechou, não estudo

# Mapeamento do rótulo (int) -> estado, conforme encoding do treino.
ESTADOS = ["engajado", "distraido", "muito_distraido"]  # 0, 1, 2

# Regras de disparo de intervenção (no scheduler de 30s).
# Cooldown por estado (min). Por ora 3 nos dois: a distração interna é quase
# constante, então ~3 min já é responsivo sem naguear (10 min seria lento demais).
# Estrutura por-estado pronta caso queira diferenciar depois.
INTERV_COOLDOWN_MIN = {"distraido": 3, "muito_distraido": 3}
INTERV_MAX_POR_SESSAO = 5      # teto de intervenções por sessão
ESTADOS_QUE_INTERVEM = ("distraido", "muito_distraido")
INTERV_MIN_JANELAS = 2         # freio: estado sustentado por N janelas (~60s) antes de intervir
INTERV_SCORE_MIN = 0.6         # freio: só intervir com confiança do modelo >= isto
INTERV_WARMUP_MIN = 3          # freio: sessão >= isto (min) antes da 1ª intervenção (+ >=1 questão)
_ESTADO_STREAK = {}            # session_id -> {"estado", "n"}: janelas consecutivas no mesmo estado
# A/B: grupo CONTROLE (detecta e mede, mas NÃO intervém) para provar que a leitura
# serve — sem depender de autorrelato. Ligar com KAIA_AB_TESTE=1 desde o 1º teste
# real: sessão que passa sem controle é evidência causal que não volta.
AB_TESTE_ATIVO = os.getenv("KAIA_AB_TESTE") == "1"


def _grupo_ab(user_id):
    """Grupo A/B determinístico e estável por aluno (50/50): controle vs bandit."""
    try:
        h = int(str(user_id).replace("-", "")[:8], 16)
    except (ValueError, TypeError):
        h = 0
    return "controle" if h % 2 == 0 else "bandit"
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

    # Duração ANTES das externas: ela é o teto físico do tempo fora de foco. Sessão
    # que nunca fechou (o sendBeacon do /end não manda header) inflaria sem limite,
    # e o modelo nunca viu nada acima de ~44 min no treino.
    duracao_min = min(
        max((datetime.now(timezone.utc) - sess["session_start_ts"]).total_seconds() / 60.0, 1e-6),
        DURACAO_MAX_MIN)

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
    # Aba suspensa pelo navegador reporta tempo fora maior que a própria sessão —
    # impossível, e fora da distribuição de treino. Teto na duração.
    teto_fora_s = duracao_min * 60.0
    ausencias = [min(float(p.get("tempo_fora_foco_s") or 0), teto_fora_s) for p in tab]
    f["mudancas_aba"] = len(tab)
    f["tempo_fora_foco_s"] = round(min(sum(ausencias), teto_fora_s), 1)
    # max, nao soma: uma saida de 5 min e outra coisa que quinze de 20s
    f["maior_ausencia_unica_s"] = round(max(ausencias), 1) if ausencias else 0.0
    f["cliques_fora_area_estudo"] = len(cliques)

    # ritmo da imobilidade (absoluto: segue valendo no cold-start, quando as
    # internas ficam mudas em 0 sigma)
    maior_bloco, n_blocos = 0.0, 0
    for p in (p for et, p in evs if et == "question_answer"):
        mb, nb = blocos_parados(p.get("mouse_track") or [], p.get("tempo_resposta_ms"))
        maior_bloco = max(maior_bloco, mb)
        n_blocos += nb
    f["maior_bloco_parado_s"] = round(maior_bloco, 1)
    f["n_blocos_parados"] = n_blocos
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
    f["duracao_sessao_min"] = round(duracao_min, 2)
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


def leitura_confiavel(feats, estado=None):
    """As 10 internas TODAS zeradas é a assinatura de cold-start (< MIN_SESSOES_BASELINE)
    ou sessão sem resposta: zero ali não é "o aluno está na média", é "não há com o que
    comparar". Como o vetor todo em 0σ é o retrato do aluno concentrado, o modelo
    responde engajado com confiança alta sobre informação nenhuma.

    Mas a confiança depende de QUAL estado foi afirmado. `muito_distraido` se apoia nas
    11 features ABSOLUTAS (trocar de aba, sumir da tela), que valem sem referência
    pessoal nenhuma — medido: 0,894 de acerto com ou sem baseline. Já engajado e
    distraído dependem das internas (o distraído cai para 0,379 sem elas). Sem `estado`
    responde só se há baseline — é o que o probe quer saber sobre as features."""
    if any(float(feats.get(k) or 0.0) != 0.0 for k in INTERNAS_RELATIVAS):
        return True
    return estado == "muito_distraido"


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
    return {"estado": estado, "score": score, "feats": feats,
            "confiavel": leitura_confiavel(feats, estado)}


async def _dono_sessao(conn, session_id):
    """user_id dono da sessão (ownership). None se a sessão não existe OU o id é
    malformado — o chamador trata None como 'sem dono conhecido'."""
    try:
        return await conn.fetchval(
            "select user_id from sessions where session_id = $1::uuid", session_id)
    except Exception:
        return None


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
        dono = await _dono_sessao(conn, session_id)
        if dono is not None and str(dono) != str(_uid):
            return JSONResponse({"erro": "Sessão não pertence ao usuário."}, status_code=403)
        res = await predizer_estado(modelo, scaler, conn, session_id)
    if res is None:
        return JSONResponse({"erro": "Sessão não encontrada."}, status_code=404)

    return {
        "session_id": session_id,
        "estado": res["estado"],
        "score": round(res["score"], 4),
        # false = sem baseline do aluno: leia como "ainda calibrando", não como estado
        "confiavel": res["confiavel"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ================== API: INTERVENÇÃO (pendente + feedback) ===================
class FeedbackIn(BaseModel):
    session_id: str
    intervention_type: str
    reward: float                              # 0.0, 0.5 ou 1.0
    tempo_ate_aceitar_s: Optional[float] = None
    feedback_usuario: Optional[str] = None


@app.get("/intervencao/pendente")
async def intervencao_pendente(request: Request, session_id: str,
                               uid: str = Depends(usuario_autenticado)):
    """Frontend consulta a intervenção recém-disparada (sem reward ainda) nos
    últimos 5 min. É a 'flag' que substitui o WebSocket: o front faz polling."""
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    async with pool.acquire() as conn:
        dono = await _dono_sessao(conn, session_id)
        if dono is not None and str(dono) != str(uid):
            return JSONResponse({"erro": "Sessão não pertence ao usuário."}, status_code=403)
        try:
            row = await conn.fetchrow(
                """
                select intervention_id, intervention_type, triggered_at
                from interventions
                where session_id = $1::uuid and reward is null
                  and intervention_type <> 'controle_ab'   -- grupo controle do A/B não vê card
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


@app.post("/intervencao/feedback")
async def intervencao_feedback(body: FeedbackIn, request: Request,
                               uid: str = Depends(usuario_autenticado)):
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
        dono = await _dono_sessao(conn, body.session_id)
        if dono is not None and str(dono) != str(uid):
            return JSONResponse({"erro": "Sessão não pertence ao usuário."}, status_code=403)
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
    # Sem versao real, TODA sessao dizia "mvp-0.1" e nao dava para separar "antes" de
    # "depois" de nenhuma correcao feita durante o beta.
    app_version: str = "desconhecida"


@app.post("/sessions")
async def criar_sessao(body: SessionIn, request: Request, ident: dict = Depends(usuario_identidade)):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    user_id = ident.get("sub") or str(uuid.uuid4())   # dono da sessão = usuário do token, não body.user_id
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


class ReporteIn(BaseModel):
    session_id: Optional[str] = None
    enunciado: str
    motivo: Optional[str] = None


@app.post("/questoes/reportar")
async def reportar_questao(body: ReporteIn, request: Request,
                           uid: str = Depends(usuario_autenticado)):
    """O aluno marca a questão como errada. Tira do cache NA HORA (não volta para mais
    ninguém) e registra o evento.

    Existe porque nenhum filtro automático chega a zero: os estruturais pegam alternativa
    repetida e enunciado sem pergunta, o PoT pega a conta que não fecha com a alternativa —
    mas erro de CONTEÚDO passa por todos. Sem isto, uma questão errada fica no cache
    servindo indefinidamente. Com isto, sai no primeiro aluno que a encontra, e a contagem
    de reportes é a única medida real da taxa de defeito no volume real."""
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    enun = (body.enunciado or "").strip()
    if len(enun) < 20:
        return JSONResponse({"erro": "Enunciado inválido."}, status_code=400)
    async with pool.acquire() as conn:
        removidas = await conn.execute(
            "delete from questoes_cache where enunciado = $1", enun)
        try:
            await conn.execute(
                "insert into session_events (session_id, event_type, payload, ts) "
                "values ($1::uuid, $2, $3::jsonb, now())",
                body.session_id, "questao_reportada",
                json.dumps({"enunciado": enun[:500], "motivo": (body.motivo or "")[:200],
                            "removidas_do_cache": removidas}, ensure_ascii=False),
            )
        except Exception as e:
            print("[KaIA] reporte sem sessão válida:", e)   # o reporte vale mesmo assim
    print(f"[KaIA] questão reportada ({removidas}) — {enun[:70]}")
    return {"ok": True}


@app.post("/events")
async def receber_evento(body: EventIn, request: Request, ident: dict = Depends(usuario_identidade)):
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    payload_json = json.dumps(body.payload, ensure_ascii=False)
    sub = ident.get("sub")

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Garante perfil + sessão pai do usuário AUTENTICADO (não mais anônimo).
            # No fluxo normal o /sessions já criou a sessão; este é o fallback se o
            # evento chegar antes.
            await conn.execute(
                "insert into perfis (user_id) values ($1::uuid) on conflict (user_id) do nothing", sub)
            await conn.execute(
                """
                insert into sessions (session_id, user_id, session_start_ts, platform, app_version)
                values ($1::uuid, $2::uuid, now(), 'web', 'mvp-0.1')
                on conflict (session_id) do nothing
                """,
                body.session_id, sub,
            )
            # OWNERSHIP: o evento só entra na PRÓPRIA sessão — impede injeção na de
            # outro aluno. Sessão anônima legada ainda é tolerada.
            dono = await conn.fetchval(
                "select user_id from sessions where session_id = $1::uuid", body.session_id)
            if str(dono) != str(sub) and str(dono) != str(ANON_USER):
                return JSONResponse({"erro": "Sessão não pertence ao usuário."}, status_code=403)
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
        # O rótulo vale sempre (é autorrelato); as FEATURES é que podem estar mudas.
        # Marca fora do FEATURE_ORDER — treinar_com_probe lê só as chaves do modelo.
        registro = dict(feats, _leitura_confiavel=leitura_confiavel(feats))
        await conn.execute(
            "insert into probe_labels (session_id, user_id, estado, features) "
            "values ($1::uuid, $2, $3, $4::jsonb)",
            session_id, uid, estado, json.dumps(registro),
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


@app.post("/perfil")
async def perfil(request: Request, dados: dict = Body(default={}),
                 uid: str = Depends(usuario_autenticado)):
    user_id = uid   # dono do perfil = usuário do token, não body.user_id

    p = dados.get("perfil") or {}
    email = p.get("email") or dados.get("email") or None
    hobbies = p.get("hobbies") or dados.get("hobbies") or []
    ambiente = p.get("ambiente_dispositivo")
    seq = int(p.get("sequencia_dias_estudo") or 0)
    sess_dia = int(p.get("sessoes_no_dia") or 0)
    # Aceite dos termos: ate agora existia so como checkbox no navegador, entao nao
    # havia como responder depois QUEM aceitou, QUANDO e QUAL versao. Publico menor de
    # idade e coleta de comportamento (mouse, ocioso, autorrelato) — nao da pra
    # reconstruir isso retroativamente. Grava na PRIMEIRA vez e nao sobrescreve.
    versao_termos = (p.get("versao_termos") or dados.get("versao_termos") or None)

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
                    sequencia_dias_estudo, sessoes_no_dia, ultimo_dia_estudo, ultima_sessao_ts,
                    versao_termos, aceite_termos_em, updated_at)
                values ($1::uuid, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, $10,
                        case when $10::text is not null then now() end, now())
                on conflict (user_id) do update set
                    email                 = coalesce(excluded.email, perfis.email),
                    hobbies               = excluded.hobbies,
                    data_prova            = coalesce(excluded.data_prova, perfis.data_prova),
                    ambiente_dispositivo  = coalesce(excluded.ambiente_dispositivo, perfis.ambiente_dispositivo),
                    sequencia_dias_estudo = excluded.sequencia_dias_estudo,
                    sessoes_no_dia        = excluded.sessoes_no_dia,
                    ultimo_dia_estudo     = coalesce(excluded.ultimo_dia_estudo, perfis.ultimo_dia_estudo),
                    ultima_sessao_ts      = coalesce(excluded.ultima_sessao_ts, perfis.ultima_sessao_ts),
                    -- aceite: grava o PRIMEIRO e nunca sobrescreve (a data original e a
                    -- que vale; um novo aceite so entra se ainda nao houver nenhum)
                    versao_termos         = coalesce(perfis.versao_termos, excluded.versao_termos),
                    aceite_termos_em      = coalesce(perfis.aceite_termos_em, excluded.aceite_termos_em),
                    updated_at            = now()
                """,
                user_id, email, json.dumps(hobbies, ensure_ascii=False),
                _to_date(p.get("data_prova")), ambiente, seq, sess_dia,
                _to_date(p.get("ultimo_dia_estudo")), ult_ts, versao_termos,
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


# Roles que podem consultar dados de ALUNOS. Um aluno comum não vê outro aluno.
RESPONSAVEL_ROLES = {"professor", "coordenador", "pai", "admin"}


@app.get("/responsavel/aluno")
async def stats_aluno(request: Request, ident: dict = Depends(usuario_identidade),
                      email: Optional[str] = None, user_id: Optional[str] = None):
    """Painel do responsável: resolve o aluno por e-mail (ou user_id) e devolve a
    evolução diária das features de atenção/desempenho + uma leitura de tendência
    (o filho está melhorando?)."""
    if not email and not user_id:
        return JSONResponse({"erro": "Informe o e-mail (ou user_id) do aluno."}, status_code=400)

    pool = request.app.state.pool
    if pool is None:
        return _demo_aluno(email or "demo@kaia.com")

    # GATE: só um responsável (role) pode ver dados de um aluno — não outro aluno.
    # Escopo fino ("este aluno é da turma deste professor") ainda é dívida.
    papel = await _role_do_usuario(pool, ident.get("sub"), ident.get("email"))
    if (papel or "").lower() not in RESPONSAVEL_ROLES:
        return JSONResponse({"erro": "Acesso restrito a responsáveis."}, status_code=403)

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
    # Rota de DEV: desligada por padrão. Só roda com KAIA_SEED_ATIVO=1 no ambiente.
    if os.getenv("KAIA_SEED_ATIVO") != "1":
        return JSONResponse(
            {"erro": "Rota de seed desativada. Defina KAIA_SEED_ATIVO=1 para usar em dev."},
            status_code=403,
        )
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
@app.get("/api/dados-grafico", dependencies=[Depends(usuario_autenticado)])
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
# FONTE ÚNICA: o Supabase, via _agregar_supabase(). Sem banco, a rota responde
# 503 como todas as outras rotas de dados.
#
# Havia um fallback offline em cascata (base sintética em xlsx → planilha manual
# → demo do front), de quando o projeto ainda não tinha banco externo. Saiu: a
# base sintética não era mais usada, a planilha manual nunca existiu no repo, e
# manter a cascata custava ~120 linhas que ninguém exercitava.
#
# Os blocos financeiros (`mrr_mensal`, `metas_fase`, `saude_financeira`) nunca
# foram emitidos por aqui — o frontend preenche com dados de demonstração e
# sinaliza isso na UI. Segue valendo.

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


async def _role_do_usuario(pool, user_id, email=None):
    """Papel do usuário (perfis.role) pela identidade VERIFICADA do token: tenta o
    user_id (sub) e cai para o email. None se não achar (→ tratado como não-admin)."""
    try:
        async with pool.acquire() as conn:
            role = None
            if user_id:
                role = await conn.fetchval("select role from perfis where user_id = $1::uuid", user_id)
            if role is None and email:
                role = await conn.fetchval("select role from perfis where lower(email) = lower($1)", email)
            return role
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
            if res and res["confiavel"]:      # sem base a sessão não entra na estatística
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


@app.get("/dashboard/dados")
async def dashboard_dados(request: Request, ident: dict = Depends(usuario_identidade)):
    # --- Porteiro de acesso -------------------------------------------------
    # SEGURANÇA: a identidade vem do JWT VERIFICADO (sub/email), não mais do header
    # X-Kaia-User (que o front apenas afirmava e era spoofável). A decisão de acesso
    # continua vindo do BANCO (perfis.role), nunca de e-mail hardcoded no código.
    pool = request.app.state.pool
    # Sem banco não há dashboard: 503, igual às demais rotas de dados. Antes daqui
    # saía o fallback offline — e, de quebra, ele saía SEM passar pelo porteiro:
    # qualquer usuário autenticado recebia os dados agregados sem ser admin.
    if pool is None:
        return _SEM_BANCO
    if await _role_do_usuario(pool, ident.get("sub"), ident.get("email")) != "admin":
        return JSONResponse({"erro": "Acesso restrito ao dashboard interno."}, status_code=403)

    modelo, scaler = request.app.state.modelo, request.app.state.scaler
    try:
        async with pool.acquire() as conn:
            return await _agregar_supabase(conn, modelo, scaler)
    except Exception as e:
        # Sem cascata para onde cair: o erro vira 500 explícito em vez de uma
        # página montada com dados de outra fonte, que escondia a falha.
        print("[KaIA] erro ao agregar dados do Supabase:", e)
        return JSONResponse({"erro": "Não foi possível montar o dashboard."}, status_code=500)

# ========================================= PERFIL =============================================
# AUTH: a validação de JWT do Supabase existe em auth.py (dependência
# usuario_autenticado) e já protege o /diagnose. DÍVIDA: estender o Depends às
# demais rotas de dados — depende do frontend passar a enviar Authorization:
# Bearer <token> em todas as páginas (hoje várias não carregam o supabase-js).
@app.get("/perfil")
async def get_perfil(request: Request, ident: dict = Depends(usuario_identidade)):
    # Identidade vem do TOKEN (sub + email verificados), NUNCA de query param: o
    # aluno só lê o próprio perfil. sub primeiro; email como fallback (cobre perfil
    # cujo user_id ainda não foi unificado com o id do Supabase Auth).
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    sub, email = ident.get("sub"), ident.get("email")
    try:
        async with pool.acquire() as conn:
            row = None
            if sub:
                row = await conn.fetchrow(
                    """
                    SELECT user_id, email, hobbies, nome, role, escola_id, turma_id
                    FROM perfis WHERE user_id = $1::uuid
                    """,
                    sub
                )
            if not row and email:
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


@app.get("/responsavel/painel")
async def painel_responsavel(request: Request, ident: dict = Depends(usuario_identidade)):
    # O painel é do PRÓPRIO responsável logado: o e-mail vem do token, não do
    # cliente (senão qualquer um pediria o painel de qualquer e-mail).
    pool = request.app.state.pool
    if pool is None:
        return _SEM_BANCO
    email = ident.get("email")
    if not email:
        return JSONResponse({"erro": "identidade ausente no token."}, status_code=400)

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
