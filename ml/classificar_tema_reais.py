# -*- coding: utf-8 -*-
"""Preenche o `tema` das questões reais que estão sem ele (humanas e português).

Sem tema, o few-shot dinâmico não consegue preferir exemplos do MESMO tema — e aí ele
pesca por semelhança solta e traz terremoto quando o pedido é geopolítica. Medido: com
few-shot o tema da questão gerada sai certo em 4/6; sem few-shot, 6/6.

As matérias de NATUREZA e MAT já foram classificadas na ingestão; estas ficaram de fora
porque na época o tema só importava onde "a estrutura muda por tema".

Uso:
    python ml/classificar_tema_reais.py --simular
    python ml/classificar_tema_reais.py
"""
import os
import sys
import json
import asyncio
import argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
for _ln in (BASE.parent / "Backend" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _ln and not _ln.strip().startswith("#"):
        _k, _v = _ln.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import asyncpg      # noqa: E402
import app as A     # noqa: E402

LOTE = 10
# "HUMANAS" é ÁREA (dataset por posição da prova), não matéria: a questão pode ser de
# qualquer uma das quatro, então os candidatos são a união dos temas delas.
HUMANAS = ("HIS", "GEO", "FIL", "SOC")


def candidatos(materia):
    if materia == "HUMANAS":
        return [t for m in HUMANAS for t in A.TEMAS_FIXOS[m]]
    return list(A.TEMAS_FIXOS.get(materia, ()))


def classificar(bloco, temas):
    lista = "\n".join(f"- {t}" for t in temas)
    itens = "\n\n".join(f"{i+1}. {q['enunciado'][:700]}" for i, q in enumerate(bloco))
    prompt = f"""Abaixo estão questões reais de vestibular do ensino médio brasileiro.

Temas possíveis:
{lista}

Para cada questão, diga qual desses temas ela aborda. Escolha o MAIS PRÓXIMO mesmo que
não seja perfeito; use "" (vazio) só se nenhum tiver relação nenhuma.

{itens}

Responda APENAS com um ARRAY JSON, na mesma ordem:
[{{"n": 1, "tema": "nome exato do tema"}}]"""
    try:
        r = A.extrair_json(A.chamar_gemini(prompt))
        if isinstance(r, dict):
            r = r.get("questoes") or [r]
        canon = {t.casefold(): t for t in temas}
        saida = {}
        for obj in r or []:
            i = int(obj.get("n", 0)) - 1
            t = canon.get(str(obj.get("tema", "")).strip().casefold())
            if 0 <= i < len(bloco) and t:
                saida[i] = t
        return saida
    except Exception as e:
        print(f"    lote falhou: {str(e)[:70]}")
        return {}


async def main(simular, schema):
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    pend = await conn.fetch(
        f"select id, materia, enunciado from {schema}.questoes_reais "
        "where tema is null order by materia, id")
    print(f"sem tema: {len(pend)} questões\n")
    por_materia = {}
    for r in pend:
        por_materia.setdefault(r["materia"], []).append(dict(r))

    total = gravadas = 0
    for materia, linhas in por_materia.items():
        temas = candidatos(materia)
        if not temas:
            print(f"  {materia}: sem lista de temas — pulando")
            continue
        print(f"  {materia} ({len(linhas)} questões, {len(temas)} temas candidatos)")
        conta = {}
        for ini in range(0, len(linhas), LOTE):
            bloco = linhas[ini:ini + LOTE]
            res = classificar(bloco, temas)
            for i, tema in res.items():
                total += 1
                conta[tema] = conta.get(tema, 0) + 1
                if not simular:
                    await conn.execute(
                        f"update {schema}.questoes_reais set tema = $1 where id = $2",
                        tema, bloco[i]["id"])
                    gravadas += 1
            print(f"    {min(ini+LOTE, len(linhas))}/{len(linhas)}", end="\r")
        print(f"    -> {sum(conta.values())} classificadas: "
              + ", ".join(f"{t.split()[0]}={n}" for t, n in
                          sorted(conta.items(), key=lambda x: -x[1])[:6]))

    print(f"\n{'SIMULACAO — nada gravado' if simular else f'gravadas: {gravadas}'}"
          f"  (classificadas: {total} de {len(pend)})")
    await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--schema", default="public")
    a = ap.parse_args()
    asyncio.run(main(a.simular, a.schema))
