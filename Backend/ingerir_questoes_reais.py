"""Ingere questões REAIS de vestibulares na tabela `questoes_reais` do Supabase,
COM embeddings (pgvector), para o few-shot DINÂMICO (Passo 2). As reais NÃO são
servidas ao aluno — entram só como exemplo recuperado no prompt (o embedding faz
o casamento fino do tema).

Duas bases:
  - maritaca-ai/enem (Apache 2.0): ENEM, rotulado por ÁREA (posição da questão).
  - portuguese-benchmark-datasets/BLUEX: USP/UNICAMP/FUVEST, por DISCIPLINA (fina).
Guardamos o maritaca por ÁREA (HUMANAS, NATUREZA...) e o BLUEX por matéria FINA
(HIS, GEO, FIL...). O app (_exemplos_similares) busca em [matéria_fina, área],
unindo as duas.

Pré-requisitos:
  - Migration 20260815120000_questoes_reais_pgvector.sql aplicada (pgvector + tabela).
  - .env com DATABASE_URL (Supabase) e API_KEY (Gemini, p/ os embeddings).

Rodar (DEV; DEMORA — um embedding por questão, sujeito à cota do Gemini):
    python Backend/ingerir_questoes_reais.py                    # tudo, as duas bases
    python Backend/ingerir_questoes_reais.py --area HUMANAS     # só Humanas (His/Geo/Fil/Soc)
    python Backend/ingerir_questoes_reais.py --area NATUREZA --sem-calculo  # só conceituais (pula conta)
    python Backend/ingerir_questoes_reais.py --fonte bluex      # só uma base
    python Backend/ingerir_questoes_reais.py --limite 20        # teste rápido
    python Backend/ingerir_questoes_reais.py --zerar            # limpa a tabela antes
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
GEN_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")   # p/ classificar nível

# Rubrica cognitiva (igual à _NIVEIS_DIF do app.py) — usada p/ classificar o banco.
RUBRICA = (
    "1 = reconhecer/lembrar um conceito isolado (definição direta)\n"
    "2 = aplicar um conceito em situação direta, um único passo\n"
    "3 = interpretar um texto/gráfico/dado e relacionar a um conceito (padrão ENEM)\n"
    "4 = combinar 2+ conceitos/etapas; interpretar e inferir\n"
    "5 = integrar áreas/ideias, raciocínio contra-intuitivo, distrator forte"
)

# BLUEX rotula por DISCIPLINA (mais fino que o maritaca, que é por posição/área).
# Guardamos a matéria FINA (o app busca por [matéria_fina, área], unindo as duas bases).
DISCIPLINA_MATERIA = {
    "portuguese": "PORT", "portugues": "PORT", "literature": "PORT", "literatura": "PORT",
    "english": "ING", "ingles": "ING",
    "history": "HIS", "historia": "HIS",
    "geography": "GEO", "geografia": "GEO",
    "philosophy": "FIL", "filosofia": "FIL",
    "sociology": "SOC", "sociologia": "SOC",
    "biology": "BIO", "biologia": "BIO",
    "physics": "FIS", "fisica": "FIS",
    "chemistry": "QUI", "quimica": "QUI",
    "mathematics": "MAT", "matematica": "MAT", "math": "MAT",
}
_AREA_MATERIA = {  # matéria fina -> ÁREA do ENEM (p/ o filtro --area)
    "ING": "ING", "PORT": "PORT",
    "HIS": "HUMANAS", "GEO": "HUMANAS", "FIL": "HUMANAS", "SOC": "HUMANAS",
    "BIO": "NATUREZA", "FIS": "NATUREZA", "QUI": "NATUREZA", "MAT": "MAT",
}


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


def _get_json(params, tent=5):
    """GET no datasets-server com retry — a API às vezes devolve 5xx/corpo vazio."""
    url = f"{API}?{urlencode(params)}"
    for i in range(tent):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                return r.json()
            print(f"  [hf] status {r.status_code} em offset {params.get('offset')}, re-tentando...")
        except Exception as e:
            print(f"  [hf] erro ({e}) em offset {params.get('offset')}, re-tentando...")
        time.sleep(3 * (i + 1))
    print(f"  [hf] desisti do offset {params.get('offset')} após {tent} tentativas.")
    return {}


def _baixar(ano):
    linhas, off = [], 0
    while True:
        d = _get_json({"dataset": "maritaca-ai/enem", "config": ano,
                       "split": "train", "offset": off, "length": 100})
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


# ==== BLUEX (USP/UNICAMP/FUVEST) ====
def _baixar_bluex():
    linhas, off = [], 0
    while True:
        d = _get_json({"dataset": "portuguese-benchmark-datasets/BLUEX", "config": "default",
                       "split": "questions", "offset": off, "length": 100})
        rows = [x["row"] for x in d.get("rows", [])]
        linhas += rows
        if len(rows) < 100:
            break
        off += len(rows)
    return linhas


_PREFIXO_ALT = re.compile(r"^\s*[a-eA-E]\s*[\)\.\-:]\s*")   # tira "a) ", "B. ", etc.


def _norm_ws(t):
    return re.sub(r"\s+", " ", t).strip() if isinstance(t, str) else t


def _limpar_alt(a):
    return _norm_ws(_PREFIXO_ALT.sub("", _limpar(a or "")))


def _materia_bluex(subject, area_filtro):
    """subject (str|list de disciplinas) -> código de matéria fina. Com area_filtro,
    escolhe a disciplina cuja ÁREA bate; senão a primeira reconhecida."""
    subs = subject if isinstance(subject, list) else [subject]
    cods = [DISCIPLINA_MATERIA.get(str(s).strip().lower()) for s in subs]
    cods = [c for c in cods if c]
    if not cods:
        return None
    if area_filtro:
        for c in cods:
            if _AREA_MATERIA.get(c) == area_filtro:
                return c
        return None
    return cods[0]


def _reg_bluex(row, area_filtro=None):
    """Questão do BLUEX (texto puro) -> {materia(fina), enunciado, alternativas, gabarito}."""
    if not row or row.get("has_associated_images") or row.get("IU"):
        return None
    if row.get("alternatives_type") not in (None, "string"):
        return None
    materia = _materia_bluex(row.get("subject"), area_filtro)
    if not materia:
        return None
    alts = [_limpar_alt(a) for a in (row.get("alternatives") or [])]
    alts = [a for a in alts if a]
    label = (row.get("answer") or "").strip().upper()
    en = _norm_ws(_limpar(row.get("question") or ""))
    if len(alts) != 5 or label not in "ABCDE" or not en:
        return None
    return {"materia": materia, "enunciado": en, "alternativas": alts,
            "gabarito": ord(label) - ord("A")}


def _alt_numerica(a):
    """Alternativa que é um VALOR (número + unidade curta) -> sinal de questão de conta."""
    a = (a or "").strip()
    if not re.match(r'^[-+(]?\s*\d', a):        # começa com número (ou sinal/parêntese)
        return False
    letras = sum(c.isalpha() for c in a)
    return letras <= 6 and len(a) <= 25          # curta, poucas letras (só a unidade)


def _parece_calculo(reg):
    """Heurística p/ pular questões de CÁLCULO na ingestão (--sem-calculo): alternativas
    majoritariamente numéricas, ou verbo de conta no enunciado."""
    alts = reg.get("alternativas") or []
    if sum(1 for a in alts if _alt_numerica(a)) >= 3:
        return True
    en = (reg.get("enunciado") or "").lower()
    return bool(re.search(r'\bcalcul\w+|\bdetermine o valor\b|valor (aproximado|numérico)', en))


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


def _gerar_texto(prompt):
    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{GEN_MODEL}:generateContent?key={API_KEY}")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    for tent in range(4):
        try:
            r = requests.post(url, json=body, timeout=40).json()
            err = r.get("error")
            if isinstance(err, dict) and err.get("code") in (429, 500, 503):
                time.sleep(5 * (tent + 1)); continue   # cota/sobrecarga -> espera e re-tenta
            cands = r.get("candidates") or []
            if cands:
                partes = cands[0].get("content", {}).get("parts", [])
                txt = "".join(p.get("text", "") for p in partes)
                if txt.strip():
                    return txt
            print("  [gen] resposta inesperada:", str(r)[:200]); return None
        except Exception as e:
            print("  [gen] erro:", e); time.sleep(2)
    return None


def _extrair_niveis(txt, n):
    """Extrai N inteiros 1..5 da resposta (array JSON de preferência)."""
    if not txt:
        return None
    m = re.search(r"\[[^\]]*\]", txt)
    if m:
        try:
            arr = json.loads(m.group(0))
            vals = [int(x) for x in arr if 1 <= int(x) <= 5]
            if len(vals) >= n:
                return vals[:n]
        except Exception:
            pass
    nums = [int(x) for x in re.findall(r"[1-5]", txt)]
    return nums[:n] if len(nums) >= n else None


def _vec_literal(v):
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


async def main():
    if not DATABASE_URL or not API_KEY:
        print("Defina DATABASE_URL e API_KEY no .env."); return
    zerar = "--zerar" in sys.argv
    limite = int(sys.argv[sys.argv.index("--limite") + 1]) if "--limite" in sys.argv else None
    fonte = (sys.argv[sys.argv.index("--fonte") + 1].lower() if "--fonte" in sys.argv else "ambas")
    area_filtro = (sys.argv[sys.argv.index("--area") + 1].upper() if "--area" in sys.argv else None)
    sem_calculo = "--sem-calculo" in sys.argv

    vistos, regs, pulados_calc = set(), [], 0
    if fonte in ("ambas", "maritaca"):
        for ano in ANOS:
            for row in _baixar(ano):
                r = _reg(row)
                if not r or (area_filtro and r["materia"] != area_filtro):
                    continue
                if sem_calculo and _parece_calculo(r):
                    pulados_calc += 1; continue
                if r["enunciado"] not in vistos:
                    vistos.add(r["enunciado"]); regs.append(r)
    if fonte in ("ambas", "bluex"):
        for row in _baixar_bluex():
            r = _reg_bluex(row, area_filtro)
            if not r:
                continue
            if sem_calculo and _parece_calculo(r):
                pulados_calc += 1; continue
            if r["enunciado"] not in vistos:
                vistos.add(r["enunciado"]); regs.append(r)
    if limite:
        regs = regs[:limite]
    from collections import Counter
    print(f"{len(regs)} questões reais (texto) coletadas -> {dict(Counter(r['materia'] for r in regs))}"
          + (f" | {pulados_calc} de cálculo puladas" if sem_calculo else ""))
    print("Gerando embeddings + inserindo...")

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


# ==== Reforço 1: classifica o banco por NÍVEL (rubrica cognitiva) ====
async def classificar_niveis():
    """Rotula cada questão de `questoes_reais` com um nível 1..5 (rubrica), em lotes.
    Assim o few-shot pode escolher exemplos DO NÍVEL pedido (não só do tema)."""
    if not DATABASE_URL or not API_KEY:
        print("Defina DATABASE_URL e API_KEY no .env."); return
    refazer = "--refazer" in sys.argv
    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
    try:
        await conn.execute("alter table questoes_reais add column if not exists nivel int")
        cond = "" if refazer else " where nivel is null"
        rows = await conn.fetch(f"select id, enunciado, alternativas from questoes_reais{cond}")
        print(f"{len(rows)} questões p/ classificar por nível...")
        LOTE, feitas = 10, 0
        for i in range(0, len(rows), LOTE):
            bloco = rows[i:i + LOTE]
            linhas = []
            for j, r in enumerate(bloco, 1):
                alts = r["alternativas"]
                alts = json.loads(alts) if isinstance(alts, str) else alts
                linhas.append(f"{j}. {r['enunciado'][:500]} | Alternativas: {' / '.join(alts)[:300]}")
            prompt = (
                "Classifique a DIFICULDADE de cada questão de 1 a 5 por esta rubrica de "
                "DEMANDA COGNITIVA:\n" + RUBRICA + "\n\nResponda APENAS com um array JSON de "
                f"{len(bloco)} inteiros (1 a 5), na ordem das questões.\n\nQuestões:\n"
                + "\n".join(linhas)
            )
            niveis = _extrair_niveis(await asyncio.to_thread(_gerar_texto, prompt), len(bloco))
            if not niveis:
                print(f"  bloco {i // LOTE + 1}: resposta inválida, pulando"); continue
            for r, nv in zip(bloco, niveis):
                await conn.execute("update questoes_reais set nivel = $1 where id = $2", nv, r["id"])
            feitas += len(bloco)
            print(f"  {min(i + LOTE, len(rows))}/{len(rows)} classificadas")
        dist = await conn.fetch("select nivel, count(*) c from questoes_reais group by nivel order by nivel")
        print(f"Concluído: {feitas} classificadas. Distribuição:", {r['nivel']: r['c'] for r in dist})
    finally:
        await conn.close()


if __name__ == "__main__":
    if "--classificar-nivel" in sys.argv:
        asyncio.run(classificar_niveis())
    else:
        asyncio.run(main())
