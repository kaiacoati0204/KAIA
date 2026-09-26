# -*- coding: utf-8 -*-
"""Monta a base de dificuldade REAL: junta o TEXTO das questões do ENEM (dataset maritaca-ai/enem) com a dificuldade
MEDIDA pelo INEP (NU_PARAM_B dos microdados).

A chave é a posição na prova, mas a ordem das questões muda por COR de caderno —
então a cor é descoberta pelo gabarito: a cor certa é a que bate em quase 100%.
"""
import csv
import json
import time
import collections
import subprocess

ANO = "2023"
ARTIFACTS = "ml/artifacts"


def questoes_maritaca(ano):
    """Puxa as questões via datasets-server, 100 por página."""
    saida, offset = [], 0
    while True:
        url = ("https://datasets-server.huggingface.co/rows?dataset=maritaca-ai%2Fenem"
               f"&config={ano}&split=train&offset={offset}&length=100")
        txt = subprocess.run(["curl", "-sL", "--max-time", "120", url],
                             capture_output=True, text=True, encoding="utf-8").stdout
        j = json.loads(txt)
        linhas = j.get("rows", [])
        if not linhas:
            break
        for r in linhas:
            saida.append(r["row"])
        offset += 100
        if offset >= j.get("num_rows_total", 0):
            break
        time.sleep(0.3)
    return saida


def itens_inep(caminho):
    with open(caminho, encoding="latin-1") as f:
        return list(csv.DictReader(f, delimiter=";"))


def main():
    qs = questoes_maritaca(ANO)
    print(f"maritaca {ANO}: {len(qs)} questões")
    print("  exemplo de id:", [q["id"] for q in qs[:3]], "...", [q["id"] for q in qs[-2:]])

    itens = itens_inep(f"{ARTIFACTS}/itens_{ANO}.csv")
    # gabarito do dataset por posição
    gab_ds = {}
    for q in qs:
        n = int("".join(c for c in q["id"] if c.isdigit()))
        gab_ds[n] = (q["label"] or "").strip().upper()

    # qual cor de caderno bate?
    print("\n  acerto de gabarito por cor de caderno:")
    melhor = None
    for cor in sorted({i["TX_COR"] for i in itens if i["TX_COR"]}):
        bate = tot = 0
        for i in itens:
            if i["TX_COR"] != cor:
                continue
            pos = int(i["CO_POSICAO"])
            if pos in gab_ds:
                tot += 1
                bate += (i["TX_GABARITO"].strip().upper() == gab_ds[pos])
        if tot:
            pct = 100 * bate / tot
            print(f"    {cor:<10} {bate:>4}/{tot:<4} ({pct:5.1f}%)")
            if melhor is None or pct > melhor[1]:
                melhor = (cor, pct)
    print(f"  -> caderno usado pelo dataset: {melhor[0]} ({melhor[1]:.1f}%)")

    cor = melhor[0]
    por_pos = {}
    for i in itens:
        if i["TX_COR"] != cor or i["IN_ITEM_ABAN"] == "1":
            continue
        b = (i["NU_PARAM_B"] or "").replace(",", ".").strip()
        if not b or b in ("NA", "NULL"):
            continue
        por_pos.setdefault(int(i["CO_POSICAO"]), []).append(
            {"b": float(b), "area": i["SG_AREA"], "hab": i["CO_HABILIDADE"],
             "gab": i["TX_GABARITO"].strip().upper()})

    base = []
    for q in qs:
        n = int("".join(c for c in q["id"] if c.isdigit()))
        cands = [c for c in por_pos.get(n, []) if c["gab"] == gab_ds.get(n)]
        if len(q.get("figures") or []) or not cands:
            continue                      # questão com imagem não dá p/ julgar por texto
        base.append({"pos": n, "b": cands[0]["b"], "area": cands[0]["area"],
                     "hab": cands[0]["hab"], "gabarito": gab_ds[n],
                     "enunciado": q["question"], "alternativas": q["alternatives"]})

    with open(f"{ARTIFACTS}/base_b_{ANO}.json", "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False)
    print(f"\n  base montada: {len(base)} questões com texto + b")
    print("  por área:", dict(collections.Counter(x["area"] for x in base)))
    bs = sorted(x["b"] for x in base)
    if bs:
        print(f"  b: min {bs[0]:.2f}  q1 {bs[len(bs)//4]:.2f}  mediana {bs[len(bs)//2]:.2f} "
              f" q3 {bs[3*len(bs)//4]:.2f}  max {bs[-1]:.2f}")


if __name__ == "__main__":
    # Rode antes: python ml/baixar_itens_enem.py 2023 ml/artifacts/itens_2023.csv
    main()
