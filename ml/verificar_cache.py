# -*- coding: utf-8 -*-
"""
Verifica em lote as questões do cache que ainda não têm veredito.

Faz duas coisas de uma vez, e por isso substitui a medição em separado:

  PROTEGE  — questão com gabarito errado sai de circulação antes de chegar ao aluno.
  MEDE     — como são questões REAIS do cache (as que os alunos receberiam), a taxa
             de divergência é a taxa de defeito de produção, sobre uma amostra bem
             maior do que gerar algumas dezenas descartáveis.

O job do backend faz o mesmo, 12 a cada 2 min. Este script existe para o caso em que
há um estoque acumulado e você quer resolver de uma vez, sem depender do backend ligado.

Uso (na raiz do projeto):
    python -u ml/verificar_cache.py                 # tudo que está sem veredito
    python -u ml/verificar_cache.py --limite 50
    python -u ml/verificar_cache.py --so-medir      # não grava veredito, só conta
    python -u ml/verificar_cache.py --paralelo 2    # menos agressivo com a cota

Use SEMPRE `python -u`: sem isso a saída fica em buffer e uma interrupção perde tudo.
"""
import os
import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

SAIDA = BASE / "artifacts" / "defeitos"


async def main(limite, so_medir, paralelo):
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return
    import app
    print(f"verificador: {app.MODELO_VERIFICADOR}   (modo: "
          f"{'só medir' if so_medir else 'medir e marcar'})\n")

    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        pend = await conn.fetch(
            "select questao_id, materia, tema, nivel, enunciado, alternativas, "
            "resposta_correta from questoes_cache where veredito is null "
            "order by criada_em desc" + (f" limit {int(limite)}" if limite else ""))
        print(f"sem veredito: {len(pend)}\n")
        if not pend:
            return

        sem = asyncio.Semaphore(paralelo)
        ok = suspeitas = indisponivel = 0
        achados = []
        lock = asyncio.Lock()

        async def uma(i, q):
            nonlocal ok, suspeitas, indisponivel
            alts = q["alternativas"]
            opts = json.loads(alts) if isinstance(alts, str) else alts
            # O job do backend nao re-tenta de proposito (o proximo ciclo ja e a
            # re-tentativa). Aqui e execucao unica, entao insiste: no tier gratuito
            # o 503 "high demand" derruba mais da metade das chamadas sem isto.
            idx, nota = None, ""
            for tentativa in range(5):
                async with sem:
                    idx, nota = await asyncio.to_thread(
                        app.verificar_questao, q["enunciado"], opts)
                if idx is not None:
                    break
                await asyncio.sleep(4 * (tentativa + 1))
            # A escrita fica DENTRO do lock: uma conexao asyncpg nao aceita duas
            # operacoes ao mesmo tempo, e as verificacoes rodam em paralelo.
            async with lock:
                if idx is None:
                    indisponivel += 1
                    print(f"  {i:>4}/{len(pend)} {q['materia']:<5} sem resposta do verificador")
                    return
                bate = (idx == q["resposta_correta"])
                if bate:
                    ok += 1
                else:
                    suspeitas += 1
                    achados.append({
                        "questao_id": str(q["questao_id"]), "materia": q["materia"],
                        "tema": q["tema"], "nivel": q["nivel"],
                        "enunciado": q["enunciado"], "opts": opts,
                        "gabarito": q["resposta_correta"], "verificador": idx, "nota": nota,
                    })
                    alvo = "NENHUMA correta" if idx == -1 else f"apontou {chr(65 + idx)}"
                    print(f"  {i:>4}/{len(pend)} {q['materia']:<5} SUSPEITA ({alvo}) "
                          f"gab={chr(65 + q['resposta_correta'])} — {q['enunciado'][:52]}")
                if not so_medir:
                    await conn.execute(
                        "update questoes_cache set veredito = $2, verificada_em = now(), "
                        "verificador_disse = $3, verificador_nota = $4 where questao_id = $1",
                        q["questao_id"], "ok" if bate else "suspeita", idx, nota or None)

        # Em blocos: o semáforo limita a concorrência e o bloco dá pontos de progresso.
        for ini in range(0, len(pend), 20):
            bloco = pend[ini:ini + 20]
            await asyncio.gather(*(uma(ini + k + 1, q) for k, q in enumerate(bloco)))
            feitos = ok + suspeitas
            if feitos:
                print(f"    ... {feitos} verificadas, {suspeitas} suspeitas "
                      f"({100 * suspeitas / feitos:.1f}%)")

        feitos = ok + suspeitas
        print("\n" + "=" * 66)
        print(f"verificadas .......... {feitos}")
        print(f"  concordaram ........ {ok}")
        print(f"  SUSPEITAS .......... {suspeitas}"
              + (f"  ({100 * suspeitas / feitos:.1f}%)" if feitos else ""))
        print(f"verificador indisponível {indisponivel}  (ficam sem veredito, voltam depois)")
        print("=" * 66)
        if achados:
            por_mat = {}
            for a in achados:
                por_mat[a["materia"]] = por_mat.get(a["materia"], 0) + 1
            tot_mat = {}
            for q in pend:
                tot_mat[q["materia"]] = tot_mat.get(q["materia"], 0) + 1
            print("suspeitas por matéria:")
            for m in sorted(por_mat, key=lambda x: -por_mat[x]):
                print(f"  {m:<6} {por_mat[m]:>3}/{tot_mat.get(m, 0):<4}"
                      f" ({100 * por_mat[m] / max(1, tot_mat.get(m, 1)):.0f}%)")
            nenhuma = sum(1 for a in achados if a["verificador"] == -1)
            print(f"\ndas suspeitas, {nenhuma} são 'nenhuma alternativa correta'")
        print("\nSUSPEITA é divergência, não veredito final: o verificador também erra.")
        print("Revise o arquivo antes de tratar tudo como defeito.")

        SAIDA.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        alvo = SAIDA / f"cache_verificado_{ts}.json"
        alvo.write_text(json.dumps(
            {"verificador": app.MODELO_VERIFICADOR, "quando": ts, "verificadas": feitos,
             "ok": ok, "suspeitas": suspeitas, "indisponivel": indisponivel,
             "achados": achados}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\ndetalhe em ml/artifacts/defeitos/{alvo.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=None, help="quantas verificar (default: todas)")
    ap.add_argument("--so-medir", action="store_true", help="não grava veredito")
    ap.add_argument("--paralelo", type=int, default=2, help="chamadas simultâneas")
    a = ap.parse_args()
    asyncio.run(main(a.limite, a.so_medir, a.paralelo))
