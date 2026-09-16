# -*- coding: utf-8 -*-
"""
O probe faz mal? Mede o custo de perguntar "onde estava sua atenção?".

O probe é ele mesmo uma intervenção: perguntar muda o foco, e com TEA/TDAH pode quebrar o fio de
quem já tem dificuldade de retomar. Isso contamina recompensa e rótulo — e pode ser dano ao aluno.
Nenhum outro critério de abandono media isso.

Compara a questão respondida LOGO DEPOIS de um probe com as outras questões DA MESMA SESSÃO
(pareado por sessão, senão a diferença viraria diferença entre alunos). Mede acerto e tempo
relativo à leitura. Também mostra quanto o probe é pulado — se for muito, ele morre como fonte de
rótulo antes de qualquer discussão de dano. Critérios em ml/metodo_beta.md.

Offline/manual. Precisa de DATABASE_URL (e KAIA_DB_SCHEMA=teste no sandbox). Rode na raiz:
    python ml/medir_dano_probe.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from statistics import mean

import asyncpg
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

from risco import _tempo_relativo  # noqa: E402  mesma régua log(rt / tempo de leitura) do Modelo 1

TIPOS = ("question_answer", "probe_atencao", "probe_pulado")


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
            "select session_id, ts, event_type, payload from session_events "
            "where event_type = any($1::text[]) order by session_id, ts", list(TIPOS))
    finally:
        await conn.close()


def _payload(p):
    return json.loads(p) if isinstance(p, str) else (p or {})


def separar(rows):
    """Por sessão: (respostas logo após um probe, as outras respostas). Só sessões com as duas."""
    por_sessao = {}
    for r in rows:
        por_sessao.setdefault(str(r["session_id"]), []).append((r["event_type"], _payload(r["payload"])))

    pares, pulados, respondidos = [], 0, 0
    for eventos in por_sessao.values():
        depois, outras, marcado = [], [], False
        for tipo, p in eventos:
            if tipo == "probe_atencao":
                respondidos += 1
                marcado = True
            elif tipo == "probe_pulado":
                pulados += 1
                marcado = True
            elif tipo == "question_answer":
                (depois if marcado else outras).append(p)
                marcado = False
        if depois and outras:
            pares.append((depois, outras))
    return pares, respondidos, pulados


def _medias(respostas):
    acertos = [1.0 if p.get("acertou") else 0.0 for p in respostas]
    rel = [r for r in map(_tempo_relativo, respostas) if r is not None]
    return (mean(acertos) if acertos else None, mean(rel) if rel else None)


def relatorio(pares, respondidos, pulados):
    total = respondidos + pulados
    if total:
        taxa_pulo = pulados / total
        print(f"probes mostrados: {total}  respondidos: {respondidos}  pulados: {pulados} "
              f"({taxa_pulo:.0%})")
        if taxa_pulo > 0.5:
            print("  ACIMA DO CRITÉRIO (50%): probe morre como fonte de rótulo/recompensa.")
    else:
        print("nenhum probe registrado ainda.")

    if not pares:
        print("sem sessões com probe E questões de comparação — nada a medir por enquanto.")
        return
    difs_acerto, difs_tempo = [], []
    for depois, outras in pares:
        a_d, t_d = _medias(depois)
        a_o, t_o = _medias(outras)
        if a_d is not None and a_o is not None:
            difs_acerto.append(a_d - a_o)
        if t_d is not None and t_o is not None:
            difs_tempo.append(t_d - t_o)

    print(f"\nsessões comparáveis: {len(pares)}  (pareado dentro da sessão)")
    if difs_acerto:
        d = mean(difs_acerto)
        print(f"acerto depois do probe menos o resto: {d:+.3f}"
              + ("   <- pior depois do probe" if d < -0.10 else ""))
    if difs_tempo:
        d = mean(difs_tempo)
        print(f"tempo relativo (log) depois do probe menos o resto: {d:+.3f}"
              + ("   <- mais lento depois do probe" if d > 0.20 else ""))
    print("\nDESCRITIVO, não causal: quando o probe aparece não é sorteado. Serve para ACENDER "
          "alerta — piora consistente pede baixar a frequência do probe, não 'provar dano'.")
    if len(pares) < 20:
        print(f"AVISO: {len(pares)} sessões é pouco para ler esses números com confiança.")


async def main():
    rows = await carregar()
    if rows is None:
        return 1
    relatorio(*separar(rows))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
