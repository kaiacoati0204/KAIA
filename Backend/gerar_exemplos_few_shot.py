"""Gera Backend/exemplos_few_shot.json a partir do dataset ENEM (maritaca-ai/enem,
licença Apache 2.0). São exemplos REAIS usados como FEW-SHOT no /gerar-questao —
NÃO servidos ao aluno, entram só no prompt como referência de estilo/dificuldade.

Só TEXTO PURO, matérias NÃO-DE-CONTA, ~5 por matéria com tipos de enunciado
variados. Humanas/BIO foram classificadas à mão (o dataset não etiqueta matéria
fina); PORT/ING saem por espaçamento no pool.

Atribuição: questões do ENEM (INEP), via dataset maritaca-ai/enem (Apache 2.0).

Ferramenta de DEV — rodar p/ (re)gerar o JSON:
    python Backend/gerar_exemplos_few_shot.py
"""
import re
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ANOS = ["2022", "2023", "2024"]
API = "https://datasets-server.huggingface.co/rows"
SAIDA = Path(__file__).with_name("exemplos_few_shot.json")

# Curadas à mão (ano, nº da questão) — escolhidas LENDO, priorizando tipos variados
# (interpretação, análise de fonte, aplicação de conceito). PORT/ING por espaçamento.
CURADAS = {
    "FIL": [(2022, 46), (2022, 48), (2022, 88), (2023, 58), (2023, 65)],
    "HIS": [(2022, 49), (2022, 58), (2022, 66), (2022, 73), (2023, 71)],
    "GEO": [(2022, 47), (2022, 74), (2022, 81), (2023, 47), (2023, 64)],
    "SOC": [(2022, 52), (2022, 80), (2022, 79), (2022, 89), (2023, 49)],
    "BIO": [(2022, 97), (2022, 116), (2022, 124), (2023, 99), (2023, 118)],
}


def _num(id_str):
    m = re.search(r"(\d+)", id_str or "")
    return int(m.group(1)) if m else None


def _baixar(ano):
    linhas, off = [], 0
    while True:
        q = urlencode({"dataset": "maritaca-ai/enem", "config": ano,
                       "split": "train", "offset": off, "length": 100})
        with urlopen(f"{API}?{q}") as r:
            d = json.loads(r.read())
        rows = [x["row"] for x in d.get("rows", [])]
        linhas += rows
        if len(rows) < 100:
            break
        off += len(rows)
    return linhas


def _limpar(t):
    """Tira markdown (## títulos, ** negrito, crase) — o dataset traz isso e a IA copia."""
    if not isinstance(t, str):
        return t
    t = re.sub(r"(?m)^\s*#{1,6}\s*", "", t)
    return t.replace("**", "").replace("__", "").replace("`", "").strip()


def _reg(row):
    """dict do exemplo (enunciado/alternativas/gabarito) ou None se não for texto puro."""
    if not row or row.get("IU") or row.get("figures"):
        return None
    alts = [_limpar(a) for a in (row.get("alternatives") or [])]
    if len(alts) != 5:
        return None
    label = (row.get("label") or "").strip().upper()
    if label not in "ABCDE":
        return None
    en = _limpar(row.get("question") or "")
    if not en:
        return None
    return {"enunciado": en, "alternativas": alts, "gabarito": ord(label) - ord("A")}


def _espacar(pool, k):
    if len(pool) <= k:
        return pool
    step = (len(pool) - 1) / (k - 1)
    return [pool[round(i * step)] for i in range(k)]


def main():
    por_chave, port_pool, ing_pool = {}, [], []
    for ano in ANOS:
        for row in _baixar(ano):
            n = _num(row.get("id"))
            if n is None:
                continue
            por_chave[(int(ano), n)] = row
            reg = _reg(row)
            if reg is None:
                continue
            if 6 <= n <= 45:
                port_pool.append(reg)
            elif 1 <= n <= 5:
                ing_pool.append(reg)

    saida = {}
    for materia, ids in CURADAS.items():
        regs = []
        for (ano, num) in ids:
            reg = _reg(por_chave.get((ano, num)))
            if reg:
                regs.append(reg)
            else:
                print(f"[aviso] {materia} ({ano} q{num}) não encontrada/com figura — pulou")
        saida[materia] = regs
    saida["PORT"] = _espacar(port_pool, 5)
    saida["ING"] = _espacar(ing_pool, 5)

    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    print("gerado", SAIDA.name, "->", {k: len(v) for k, v in saida.items()})


if __name__ == "__main__":
    main()
