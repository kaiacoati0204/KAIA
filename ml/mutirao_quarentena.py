# -*- coding: utf-8 -*-
"""Esvazia o estoque de questões sem veredito, em LOTES e por um provedor de cota própria.

Por que existe, se já há `ml/verificar_cache.py`: aquele verifica uma questão por
chamada, o que multiplica por 5 o número de requisições — e requisição é exatamente o
recurso escasso. Aqui vai em lote (VERIF_LOTE), que é como o backend já faz.

E aceita `KAIA_VERIF_PROVEDOR=groq`, que roda numa conta separada da do Gemini. O ponto
não é qualidade: medido em 131 questões do ENEM com gabarito oficial, o gemini-3.6-flash
foi melhor (19/20 erros pegos, 0 questões boas acusadas) que o gpt-oss-20b do Groq
(100% dos erros, mas 1 questão boa acusada). O ponto é não gastar no mutirão a cota que
gera questão para o aluno — foi assim que 600 questões ficaram paradas.

Uso (na raiz do projeto):
    export $(grep GROQ caminho/.chaves.env | xargs)
    KAIA_DB_SCHEMA=public KAIA_VERIF_PROVEDOR=groq python -u ml/mutirao_quarentena.py
    ... --limite 50        # amostra
    ... --so-medir         # não grava veredito, só conta
"""
import os
import sys
import json
import time
import asyncio
import argparse
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))

import asyncpg                                    # noqa: E402
from dotenv import load_dotenv                    # noqa: E402
load_dotenv(BASE.parent / "Backend" / ".env")
import app                                        # noqa: E402


async def main(limite, so_medir, schema):
    print(f"provedor: {app.VERIF_PROVEDOR}  "
          f"modelo: {app.VERIF_MODELO_GROQ if app.VERIF_PROVEDOR == 'groq' else app.MODELO_VERIFICADOR}  "
          f"lote: {app.VERIF_LOTE}  {'(só medindo)' if so_medir else ''}")
    if app.VERIF_PROVEDOR == "groq" and not os.getenv("GROQ_API_KEY"):
        print("GROQ_API_KEY ausente — exporte antes de rodar."); return

    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    sql = (f"select questao_id, materia, tema, enunciado, alternativas, resposta_correta "
           f"from {schema}.questoes_cache where veredito is null order by criada_em desc")
    if limite:
        sql += f" limit {int(limite)}"
    pend = await conn.fetch(sql)
    print(f"sem veredito: {len(pend)}\n")

    ok = susp = falhou = 0
    por_materia = {}
    t0 = time.time()
    for ini in range(0, len(pend), app.VERIF_LOTE):
        bloco = list(pend[ini:ini + app.VERIF_LOTE])
        entradas = []
        for q in bloco:
            a = q["alternativas"]
            entradas.append((q["enunciado"], json.loads(a) if isinstance(a, str) else a))
        try:
            res = await asyncio.to_thread(app.verificar_lote, entradas)
        except Exception as e:
            print(f"  lote {ini//app.VERIF_LOTE+1}: EXPLODIU {type(e).__name__}: {str(e)[:90]}")
            falhou += len(bloco)
            continue
        for q, (idx, nota) in zip(bloco, res):
            if idx is None:
                falhou += 1
                continue
            veredito = "ok" if idx == q["resposta_correta"] else "suspeita"
            m = por_materia.setdefault(q["materia"], [0, 0])
            m[1] += 1
            if veredito == "ok":
                ok += 1
            else:
                susp += 1
                m[0] += 1
            if not so_medir:
                await conn.execute(
                    f"update {schema}.questoes_cache set veredito = $2, verificada_em = now(), "
                    f"verificador_disse = $3, verificador_nota = $4 where questao_id = $1",
                    q["questao_id"], veredito, idx, nota or None)
        feitas = ok + susp + falhou
        print(f"  {feitas}/{len(pend)}  ok={ok} suspeitas={susp} sem_resposta={falhou}"
              f"  ({time.time()-t0:.0f}s)", end="\r")
    print()

    restam = await conn.fetchval(
        f"select count(*) from {schema}.questoes_cache where veredito is null")
    await conn.close()
    print(f"\n{'='*60}")
    print(f"  verificadas ....... {ok + susp}")
    print(f"    concordaram ..... {ok}")
    print(f"    SUSPEITAS ....... {susp}" +
          (f"  ({100*susp/(ok+susp):.1f}%)" if ok + susp else ""))
    print(f"  sem resposta ...... {falhou}  (voltam na próxima passada)")
    print(f"  ainda em quarentena {restam}")
    if por_materia:
        print("\n  defeito por matéria:")
        for m, (s, n) in sorted(por_materia.items(), key=lambda x: -x[1][0] / max(x[1][1], 1)):
            print(f"    {m:<6} {s:>3} de {n:>3}  ({100*s/n:.0f}%)" if n else "")
    print(f"{'='*60}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--so-medir", action="store_true")
    ap.add_argument("--schema", default=os.getenv("KAIA_DB_SCHEMA", "public"))
    a = ap.parse_args()
    asyncio.run(main(a.limite, a.so_medir, a.schema))
