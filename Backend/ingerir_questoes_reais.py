"""Ingere questões REAIS do ENEM (dataset maritaca-ai/enem, Apache 2.0) na tabela
`questoes_reais` do Supabase, COM embeddings (pgvector), para o few-shot DINÂMICO
(Passo 2). As reais NÃO são servidas ao aluno — entram só como exemplo recuperado
no prompt, chaveadas por ÁREA do ENEM (o embedding faz o casamento fino do tema).

Pré-requisitos:
  - Migration 20260815120000_questoes_reais_pgvector.sql aplicada (pgvector + tabela).
  - .env com DATABASE_URL (Supabase) e API_KEY (Gemini, p/ os embeddings).

Rodar (DEV, uma vez; DEMORA — são milhares de embeddings):
    python Backend/ingerir_questoes_reais.py
Opções:
    --limite N   só as N primeiras (p/ testar rápido / gastar pouca cota)
    --zerar      limpa a tabela antes (evita duplicar em re-execução)
"""
import os
import re
import sys
import json
import time
import asyncio
from pathlib import Path
from urllib.parse import urlencode

import requests
import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))   # carrega Backend/.env (mesma pasta do script)

ANOS = ["2022", "2023", "2024"]
API = "https://datasets-server.huggingface.co/rows"
API_KEY = os.getenv("API_KEY") or os.getenv("CHAVE_ACESSO")
DATABASE_URL = os.getenv("DATABASE_URL")
EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = 768   # TEM de bater com a coluna vector(768) e com EMBED_DIM no app.py


def _num(id_str):
    m = re.search(r"(\d+)", id_str or "")
    return int(m.group(1)) if m else None


def _area(n):
    """Posição da questão -> ÁREA do ENEM (mesmo mapeamento do few-shot fixo)."""
    if 1 <= n <= 5:     return "ING"
    if 6 <= n <= 45:    return "PORT"
    if 46 <= n <= 90:   return "HUMANAS"
    if 91 <= n <= 135:  return "NATUREZA"
    if 136 <= n <= 180: return "MAT"
    return None


def _limpar(t):
    if not isinstance(t, str):
        return t
    t = re.sub(r"(?m)^\s*#{1,6}\s*", "", t)
    return t.replace("**", "").replace("__", "").replace("`", "").strip()


def _baixar(ano):
    linhas, off = [], 0
    while True:
        q = urlencode({"dataset": "maritaca-ai/enem", "config": ano,
                       "split": "train", "offset": off, "length": 100})
        d = requests.get(f"{API}?{q}", timeout=30).json()
        rows = [x["row"] for x in d.get("rows", [])]
        linhas += rows
        if len(rows) < 100:
            break
        off += len(rows)
    return linhas


def _reg(row):
    """Questão de TEXTO PURO -> dict {materia(area), enunciado, alternativas, gabarito}."""
    if not row or row.get("IU") or row.get("figures"):
        return None
    n = _num(row.get("id"))
    area = _area(n) if n is not None else None
    if area is None:
        return None
    alts = [_limpar(a) for a in (row.get("alternatives") or [])]
    label = (row.get("label") or "").strip().upper()
    en = _limpar(row.get("question") or "")
    if len(alts) != 5 or label not in "ABCDE" or not en:
        return None
    return {"materia": area, "enunciado": en, "alternativas": alts,
            "gabarito": ord(label) - ord("A")}


def _embed(texto):
    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{EMBED_MODEL}:embedContent?key={API_KEY}")
    body = {"content": {"parts": [{"text": texto[:8000]}]}, "outputDimensionality": EMBED_DIM}
    for tent in range(4):
        try:
            r = requests.post(url, json=body, timeout=20).json()
            vals = r.get("embedding", {}).get("values")
            if isinstance(vals, list) and vals:
                return vals
            if isinstance(r.get("error"), dict) and r["error"].get("code") == 429:
                time.sleep(5 * (tent + 1))   # cota: espera e re-tenta
                continue
            print("  [embed] resposta inesperada:", str(r)[:200])
            return None
        except Exception as e:
            print("  [embed] erro:", e)
            time.sleep(2)
    return None


def _vec_literal(v):
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


async def main():
    if not DATABASE_URL or not API_KEY:
        print("Defina DATABASE_URL e API_KEY no .env."); return
    zerar = "--zerar" in sys.argv
    limite = int(sys.argv[sys.argv.index("--limite") + 1]) if "--limite" in sys.argv else None

    vistos, regs = set(), []
    for ano in ANOS:
        for row in _baixar(ano):
            r = _reg(row)
            if r and r["enunciado"] not in vistos:
                vistos.add(r["enunciado"]); regs.append(r)
    if limite:
        regs = regs[:limite]
    print(f"{len(regs)} questões reais (texto) coletadas. Gerando embeddings + inserindo...")

    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
    try:
        if zerar:
            await conn.execute("truncate questoes_reais")
        ok = 0
        for i, r in enumerate(regs, 1):
            vec = await asyncio.to_thread(_embed, r["enunciado"])
            if not vec:
                continue
            await conn.execute(
                "insert into questoes_reais (materia, enunciado, alternativas, gabarito, embedding) "
                "values ($1, $2, $3::jsonb, $4, $5::vector)",
                r["materia"], r["enunciado"], json.dumps(r["alternativas"]),
                r["gabarito"], _vec_literal(vec))
            ok += 1
            if i % 25 == 0:
                print(f"  {i}/{len(regs)} ({ok} inseridas)")
        print(f"Concluído: {ok} questões reais no banco (pgvector).")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
