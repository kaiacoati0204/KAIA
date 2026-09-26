# -*- coding: utf-8 -*-
"""Descobre quais assuntos REALMENTE caem, lendo as provas em vez de supor.

`TEMAS_FIXOS` tem 6 nomes por matéria, escritos a partir da Matriz do INEP e encurtados
para caber no card. O problema é que ninguém conferiu contra as provas: "Coesão e
Coerência" não apareceu nenhuma vez em 80 questões reais de português, e "Óptica",
que cai, nem está na lista.

Aqui a IA lê cada questão e diz LIVREMENTE que assunto ela cobra — sem receber lista
nenhuma. Assim o tema emerge da prova; dando a lista, tudo é encaixado à força no mais
próximo e não dá para distinguir "não cai" de "não tinha opção melhor".

As duas fontes ficam separadas no relatório, porque o que cai na Fuvest não é o que cai
no ENEM:
    ENEM (dataset maritaca)   guardado por ÁREA   -> PORT, HUMANAS, MAT, NATUREZA
    BLUEX (USP/UNICAMP/FUVEST) por matéria fina   -> HIS, GEO, FIL, SOC, BIO, FIS, QUI

Uso (na raiz do projeto):
    python -u ml/temas_que_caem.py --chaves caminho/para/.chaves.env
    python -u ml/temas_que_caem.py --limite 60        # amostra, p/ testar
"""
import os
import re
import sys
import json
import asyncio
import argparse
import unicodedata
import collections
from pathlib import Path

import asyncpg
import requests

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))

LOTE = 10
# Groq: catálogo atual é gpt-oss/qwen (os llama-3.x saíram). Free tier de 1.000/dia,
# contra ~20/dia do verificador Gemini -- por isso o trabalho em lote vem para cá.
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELO = os.getenv("KAIA_GROQ_MODELO", "openai/gpt-oss-120b")

FONTE = {"PORT": "ENEM", "HUMANAS": "ENEM", "MAT": "ENEM", "NATUREZA": "ENEM",
         "HIS": "BLUEX", "GEO": "BLUEX", "FIL": "BLUEX", "SOC": "BLUEX",
         "BIO": "BLUEX", "FIS": "BLUEX", "QUI": "BLUEX"}


def carregar_chaves(caminho):
    for ln in Path(caminho).read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def groq(prompt, tentativas=3):
    for t in range(tentativas):
        try:
            r = requests.post(
                GROQ_URL, timeout=180,
                headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
                json={"model": GROQ_MODELO, "max_tokens": 2000, "temperature": 0,
                      "messages": [{"role": "user", "content": prompt}]})
            if r.status_code == 200:
                return r.json()["choices"][0]["message"].get("content") or ""
            if r.status_code == 429:
                import time
                time.sleep(8 * (t + 1))
                continue
            print(f"    groq {r.status_code}: {str(r.json())[:90]}")
        except Exception as e:
            print(f"    groq erro: {str(e)[:80]}")
    return ""


def extrair_json(texto):
    m = re.search(r"\[.*\]", texto, re.S)
    return json.loads(m.group(0)) if m else []


def imprimivel(t):
    """O console do Windows é cp1252 e estoura em travessão/hífen não-quebrável."""
    return str(t).encode("cp1252", "replace").decode("cp1252")


def normalizar(t):
    """'cinemática ' e 'Cinemática' são o mesmo assunto; junta sem perder o acento."""
    t = " ".join(str(t).strip().split())
    if not t:
        return ""
    base = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in base if not unicodedata.combining(c))


async def main(limite, chaves):
    carregar_chaves(chaves)
    if not os.environ.get("GROQ_API_KEY"):
        print("GROQ_API_KEY não encontrada — passe --chaves"); return
    from dotenv import load_dotenv
    load_dotenv(BASE.parent / "Backend" / ".env")

    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    sql = "select id, materia, enunciado from public.questoes_reais order by materia, id"
    if limite:
        sql += f" limit {int(limite)}"
    linhas = [dict(r) for r in await conn.fetch(sql)]
    await conn.close()
    print(f"lendo {len(linhas)} questões reais com {GROQ_MODELO}\n")

    achados = []   # (fonte, materia, assunto)
    por_materia = collections.defaultdict(list)
    for r in linhas:
        por_materia[r["materia"]].append(r)

    for materia, qs in por_materia.items():
        fonte = FONTE.get(materia, "?")
        ok = 0
        for ini in range(0, len(qs), LOTE):
            bloco = qs[ini:ini + LOTE]
            itens = "\n\n".join(f"{i+1}. {q['enunciado'][:700]}"
                                for i, q in enumerate(bloco))
            resp = groq(
                "Abaixo estão questões reais de vestibular brasileiro (ensino médio).\n\n"
                "Para cada uma, diga em QUE UNIDADE do livro didático ela seria estudada.\n"
                "É o nome do CAPÍTULO, não a descrição da questão:\n"
                "  certo:  'Ecologia' · 'Cinemática' · 'Genética' · 'Termoquímica'\n"
                "  errado: 'Mutualismo entre formigas e acácias' · 'Toxina botulínica e\n"
                "          bloqueio neuromuscular' — isso descreve a questão, não o capítulo\n"
                "Uma disciplina inteira tem no máximo uns 10 a 12 capítulos: se o nome que\n"
                "você pensou serve para uma questão só, suba um nível.\n"
                "NÃO escolha de nenhuma lista: escreva o capítulo que a questão cobra.\n\n"
                f"{itens}\n\n"
                'Responda APENAS com um ARRAY JSON: [{"n": 1, "assunto": "..."}]')
            for o in extrair_json(resp) or []:
                try:
                    i = int(o.get("n", 0)) - 1
                except (TypeError, ValueError):
                    continue
                a = normalizar(o.get("assunto", ""))
                if 0 <= i < len(bloco) and a:
                    achados.append((fonte, materia, o["assunto"].strip(), a))
                    ok += 1
            print(f"  {materia} ({fonte}): {ok}/{len(qs)}", end="\r")
        print(f"  {materia} ({fonte}): {ok}/{len(qs)}   ")

    (BASE / "artifacts").mkdir(exist_ok=True)
    saida = BASE / "artifacts" / "temas_que_caem.json"
    saida.write_text(json.dumps(achados, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{'='*66}\nASSUNTOS QUE MAIS CAEM, POR FONTE\n{'='*66}")
    for fonte in ("ENEM", "BLUEX"):
        sub = [a for a in achados if a[0] == fonte]
        if not sub:
            continue
        print(f"\n### {fonte}  ({len(sub)} questões) ###")
        for materia in sorted({a[1] for a in sub}):
            cont = collections.Counter(a[3] for a in sub if a[1] == materia)
            rotulo = {}
            for f, m, bruto, norm in sub:
                if m == materia:
                    rotulo.setdefault(norm, bruto)
            tot = sum(cont.values())
            print(f"\n  {materia} ({tot})")
            for norm, n in cont.most_common(12):
                print(f"    {n:>3}x  {imprimivel(rotulo[norm])[:44]}")
    print(f"\ndetalhe em {saida}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--chaves", default=".chaves.env")
    a = ap.parse_args()
    asyncio.run(main(a.limite, a.chaves))
