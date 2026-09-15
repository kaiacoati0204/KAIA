# -*- coding: utf-8 -*-
"""
Item analysis — acha questão defeituosa pelas RESPOSTAS dos alunos, sem modelo nenhum.

Técnica padrão da psicometria; pega o que nenhum filtro automático pega: gabarito errado.
p-value = proporção de acertos (perto de 0 em nível fácil = algo errado). Ponto-bisserial =
correlação entre acertar ESTA questão e a nota do aluno na sessão; NEGATIVO (bons erram,
fracos acertam) quase sempre é gabarito trocado ou conteúdo incorreto. Não custa chamada
nem erra por "achismo" como o verificador por IA, mas precisa de VOLUME: abaixo de
MIN_RESPOSTAS o script diz que o número não significa nada.

Uso (na raiz do projeto):
    python ml/item_analysis.py                  # relatório
    python ml/item_analysis.py --min 20         # exige mais respostas por questão
    python ml/item_analysis.py --marcar         # marca as suspeitas no cache (não serve mais)

Precisa de DATABASE_URL. Lê só o que o front já grava: os eventos question_answer
com questao_id, acertou e opcao_escolhida.
"""
import os
import sys
import json
import asyncio
import argparse
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE.parent / "Backend" / ".env")

MIN_RESPOSTAS = 15        # abaixo disto o índice é ruído, não sinal
PB_SUSPEITO = 0.0         # ponto-bisserial <= 0: bons alunos errando
P_SUSPEITO = 0.20         # quase ninguém acerta


def _ponto_bisserial(acertos_item, notas):
    """Correlação de Pearson entre acertar o item (0/1) e a nota geral do aluno.
    Implementado à mão para não arrastar dependência só por isto."""
    n = len(acertos_item)
    if n < 3:
        return None
    m = sum(notas) / n
    dp = (sum((x - m) ** 2 for x in notas) / n) ** 0.5
    if dp == 0:
        return None                      # todos com a mesma nota: nada a correlacionar
    p = sum(acertos_item) / n
    if p in (0.0, 1.0):
        return None                      # todos acertaram ou todos erraram
    m1 = sum(no for a, no in zip(acertos_item, notas) if a) / sum(acertos_item)
    m0 = sum(no for a, no in zip(acertos_item, notas) if not a) / (n - sum(acertos_item))
    return (m1 - m0) / dp * (p * (1 - p)) ** 0.5


async def coletar(conn):
    """(por_questao, notas_por_sessao) a partir dos eventos de resposta."""
    rows = await conn.fetch(
        "select session_id, payload from session_events "
        "where event_type = 'question_answer' order by ts")
    respostas = []
    for r in rows:
        p = r["payload"]
        p = json.loads(p) if isinstance(p, str) else p
        qid = p.get("questao_id")
        if not qid:
            continue                     # evento anterior a passar o id: fica de fora
        respostas.append({
            "sessao": str(r["session_id"]), "questao_id": str(qid),
            "acertou": 1 if p.get("acertou") else 0,
            "escolhida": p.get("opcao_escolhida"),
            "correta": p.get("opcao_correta"),
            "nivel": p.get("nivel_dificuldade"),
        })
    # nota do aluno na sessão = fração de acertos; é o "desempenho geral" da correlação
    por_sessao = {}
    for x in respostas:
        por_sessao.setdefault(x["sessao"], []).append(x["acertou"])
    notas = {s: sum(v) / len(v) for s, v in por_sessao.items() if v}
    return respostas, notas


def analisar(respostas, notas, minimo):
    por_q = {}
    for x in respostas:
        por_q.setdefault(x["questao_id"], []).append(x)
    saida = []
    for qid, rs in por_q.items():
        if len(rs) < minimo:
            continue
        acertos = [r["acertou"] for r in rs]
        notas_al = [notas.get(r["sessao"], 0.0) for r in rs]
        p = sum(acertos) / len(acertos)
        pb = _ponto_bisserial(acertos, notas_al)
        escolhas = {}
        for r in rs:
            if r["escolhida"] is not None:
                escolhas[r["escolhida"]] = escolhas.get(r["escolhida"], 0) + 1
        favorita = max(escolhas, key=escolhas.get) if escolhas else None
        correta = rs[0]["correta"]
        motivos = []
        if pb is not None and pb <= PB_SUSPEITO:
            motivos.append(f"ponto-bisserial {pb:+.2f} (bons alunos errando)")
        if p <= P_SUSPEITO:
            motivos.append(f"só {p:.0%} acertam")
        if favorita is not None and correta is not None and favorita != correta:
            n_fav = escolhas[favorita]
            if n_fav / len(rs) >= 0.5:
                motivos.append(f"{n_fav / len(rs):.0%} escolhem a {chr(65 + favorita)}, "
                               f"gabarito é {chr(65 + correta)}")
        saida.append({"questao_id": qid, "n": len(rs), "p": p, "pb": pb,
                      "nivel": rs[0]["nivel"], "motivos": motivos})
    return sorted(saida, key=lambda x: (not x["motivos"], x["pb"] if x["pb"] is not None else 9))


async def main(minimo, marcar):
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        respostas, notas = await coletar(conn)
        print(f"respostas com questao_id: {len(respostas)}  |  sessões: {len(notas)}")
        if not respostas:
            print("\nNenhuma resposta traz questao_id ainda. O campo passou a ser enviado")
            print("agora; este relatório só terá conteúdo depois que alunos responderem.")
            return
        itens = analisar(respostas, notas, minimo)
        if not itens:
            print(f"\nNenhuma questão atingiu {minimo} respostas — sem volume, o índice é ruído.")
            print("Rode de novo quando houver mais uso, ou baixe o mínimo com --min.")
            return
        susp = [i for i in itens if i["motivos"]]
        print(f"questões com >= {minimo} respostas: {len(itens)}  |  SUSPEITAS: {len(susp)}\n")
        for i in itens:
            marca = "SUSPEITA" if i["motivos"] else "ok"
            pb = f"{i['pb']:+.2f}" if i["pb"] is not None else "  -  "
            print(f"  {marca:<8} n={i['n']:<3} p={i['p']:.2f} pb={pb} nivel={i['nivel']}  {i['questao_id'][:8]}")
            for m in i["motivos"]:
                print(f"           -> {m}")
        if marcar and susp:
            ids = [i["questao_id"] for i in susp]
            await conn.execute(
                "update questoes_cache set veredito = 'suspeita', "
                "verificador_nota = coalesce(verificador_nota, 'item analysis') "
                "where questao_id = any($1::uuid[])", ids)
            print(f"\n{len(ids)} questão(ões) marcadas como suspeitas — não serão mais servidas.")
        elif susp:
            print("\nUse --marcar para tirá-las de circulação.")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=MIN_RESPOSTAS, help="respostas mínimas por questão")
    ap.add_argument("--marcar", action="store_true", help="marca as suspeitas no cache")
    a = ap.parse_args()
    asyncio.run(main(a.min, a.marcar))
