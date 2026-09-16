# -*- coding: utf-8 -*-
"""
Relatório do Fluxo 1 (prevenção nas pausas) — a leitura HONESTA do beta.

Existe para você nunca ler a média bruta por braço. Dois motivos:
- maldição do vencedor: o braço que parece melhor está superestimado, porque foi escolhido
  mais vezes JUSTAMENTE quando vinha indo bem (o megaestudo do PNAS corrige isso explicitamente);
- o bandit escolhe mais quem vai bem, então a média bruta mistura efeito com seleção.

A leitura certa é sempre CONTRA o braço `nada`, pesando cada rodada por 1/prob da escolha (IPW).
Também mostra a recompensa ao longo das rodadas: se cair, é habituação aparecendo — o Thompson
supõe valor fixo no tempo, e a habituação quebra essa suposição.

Offline. Precisa de DATABASE_URL (e KAIA_DB_SCHEMA=teste no sandbox). Rodar na raiz:
    python ml/relatorio_prevencao.py
"""
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv
import asyncpg

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

from bandit_prevencao import BRACOS, BRACO_CONTROLE  # noqa: E402

MIN_POR_BRACO = 20        # abaixo disso o número não é lido — nem para matar, nem para salvar


def _payload(p):
    return json.loads(p) if isinstance(p, str) else (p or {})


async def carregar():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return None
    schema = os.getenv("KAIA_DB_SCHEMA", "public")
    conn = await asyncpg.connect(url, statement_cache_size=0,
                                 server_settings={"search_path": f"{schema}, public, extensions"})
    try:
        return await conn.fetch(
            "select event_type, payload, ts from session_events "
            "where event_type in ('decisao_prevencao','recompensa_prevencao','meta_rodada') "
            "order by ts")
    finally:
        await conn.close()


def relatorio(linhas):
    decisoes = [_payload(r["payload"]) for r in linhas if r["event_type"] == "decisao_prevencao"]
    recompensas = [_payload(r["payload"]) for r in linhas if r["event_type"] == "recompensa_prevencao"]
    metas = [_payload(r["payload"]) for r in linhas if r["event_type"] == "meta_rodada"]

    # ---- alcance: de quantas pausas o sistema participou, e em quantas agiu
    acionadas = [d for d in decisoes if d.get("acionou")]
    print(f"pausas registradas: {len(decisoes)}   com oferta: {len(acionadas)} "
          f"({len(acionadas) / len(decisoes):.0%})" if decisoes else "nenhuma pausa registrada ainda.")
    if not decisoes:
        return
    if len(acionadas) < MIN_POR_BRACO:
        print(f"AVISO: menos de {MIN_POR_BRACO} ofertas — ainda não dá para ler nada abaixo.")

    # ---- aceitação da oferta (não precisa de efeito nenhum para ser informativa)
    if metas:
        aceitou = sum(1 for m in metas if m.get("meta") is not None)
        print(f"planos oferecidos e respondidos: {len(metas)}   aceitos: {aceitou} "
              f"({aceitou / len(metas):.0%})")

    # ---- por braço: bruta x IPW, sempre contra o controle
    por_braco = defaultdict(list)
    for r in recompensas:
        b, rec, prob = r.get("braco"), r.get("recompensa"), r.get("prob")
        if b in BRACOS and rec is not None:
            por_braco[b].append((float(rec), float(prob) if prob else None))

    n_total = sum(len(v) for v in por_braco.values())
    print(f"\nrodadas avaliadas: {n_total}")
    print(f"{'braço':<14}{'n':>5}{'média bruta':>14}{'IPW':>10}{'vs nada':>10}")
    ipw = {}
    for b in BRACOS:
        dados = por_braco.get(b, [])
        if not dados:
            print(f"{b:<14}{0:>5}{'—':>14}{'—':>10}{'—':>10}")
            continue
        bruta = mean(r for r, _ in dados)
        com_prob = [(r, p) for r, p in dados if p]
        ipw[b] = (sum(r / p for r, p in com_prob) / n_total) if com_prob and n_total else None
        print(f"{b:<14}{len(dados):>5}{bruta:>14.3f}"
              f"{(f'{ipw[b]:.3f}' if ipw.get(b) is not None else '—'):>10}"
              f"{'—' if b == BRACO_CONTROLE else '':>10}")

    base = ipw.get(BRACO_CONTROLE)
    if base:
        print()
        for b in BRACOS:
            if b != BRACO_CONTROLE and ipw.get(b) is not None:
                dif = ipw[b] - base
                marca = "" if len(por_braco.get(b, [])) >= MIN_POR_BRACO else "  (n baixo demais)"
                print(f"{b} menos {BRACO_CONTROLE}: {dif:+.3f}{marca}")
        print("\nDiferença POSITIVA = o apoio ajudou. Mas leia junto com o n: com poucas rodadas,"
              "\nqualquer diferença cabe dentro do acaso.")

    # ---- habituação: a recompensa cai conforme o aluno vê o mesmo apoio de novo?
    print("\nrecompensa por ordem de exposição (habituação aparece como queda):")
    ordem = defaultdict(list)
    vezes = defaultdict(int)
    for r in recompensas:
        b, rec = r.get("braco"), r.get("recompensa")
        if b in BRACOS and rec is not None:
            vezes[b] += 1
            ordem[b].append((vezes[b], float(rec)))
    for b in BRACOS:
        d = ordem.get(b, [])
        if len(d) < 6:
            print(f"  {b}: poucas exposições para olhar")
            continue
        meio = len(d) // 2
        prim, ult = mean(r for _, r in d[:meio]), mean(r for _, r in d[meio:])
        seta = "  <- caindo" if ult < prim - 0.05 else ""
        print(f"  {b}: primeiras {meio} = {prim:.3f}   últimas {len(d) - meio} = {ult:.3f}{seta}")

    print("\nDESCRITIVO. O braço que parecer melhor está superestimado — compare com `nada`,"
          "\nnunca a média bruta entre braços. Critérios de corte em ml/metodo_beta.md.")


async def main():
    linhas = await carregar()
    if linhas is None:
        return 1
    relatorio(linhas)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
