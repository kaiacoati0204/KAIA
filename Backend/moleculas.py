"""
Validador de cadeia carbônica a partir do SMILES (Química Orgânica, ensino médio).

Calcula as cinco classificações da cadeia e confere contra o gabarito que o Gemini
escreveu. É o portão: questão cuja molécula não bate com o próprio gabarito não chega
ao aluno. Módulo puro — não importa o app.

Uso:
    from moleculas import classificar_cadeia, conferir_gabarito
    classificar_cadeia("Cc1ccccc1")
    # {"ok": True, "motivo": None, "cobraveis": (...), "nao_aplicavel": {"normal_ramificada": "..."},
    #  "classificacao": {"aberta_fechada": "mista", "normal_ramificada": "nao_aplicavel", ...}}
    conferir_gabarito("CN", {"homogenea_heterogenea": "heterogenea", ...})
    # {"aprovada": False, "divergencias": [...], "motivo": "...", "calculado": {...}}

LIMITE, POR DESENHO: só enxerga o SMILES. Enunciado que NOMEIA uma molécula com SMILES de
outra de mesma classificação ("etilmetiléter" com o SMILES do éter dietílico) passa. O
conserto decidido não é conferir nome: é a questão NÃO TER NOME (nem nas alternativas,
nem na explicacao, nem no porque_erradas) — a molécula aparece só pelo desenho.
"""
import logging

import networkx as nx
from pysmiles import read_smiles

# O pysmiles avisa por logging a cada SMILES estranho; o motivo da reprovação já vai
# no retorno, então o log só poluiria o console do servidor.
logging.getLogger("pysmiles").setLevel(logging.ERROR)

CHAVES = ("aberta_fechada", "normal_ramificada", "saturada_insaturada",
          "homogenea_heterogenea", "aromatica_aliciclica")

# Eixo que a molécula não tem: valor explícito, não None nem ausência. A montagem do
# enunciado LÊ isto para não perguntar o que não se cobra.
NAO_APLICAVEL = "nao_aplicavel"
MOTIVO_RAMIFICACAO = ("ramificação só se cobra em cadeia aberta; os livros divergem em "
                      "anel com substituinte")

# EIXOS COBRÁVEIS por tipo de cadeia: o que faz sentido perguntar ao aluno. É a fonte
# para montar o enunciado. normal/ramificada fica de fora em fechada e mista (regra 5);
# aromática/alicíclica fica de fora em aberta, porque não há anel.
EIXOS_COBRAVEIS = {
    "aberta":  ("aberta_fechada", "normal_ramificada", "saturada_insaturada",
                "homogenea_heterogenea"),
    "fechada": ("aberta_fechada", "saturada_insaturada", "homogenea_heterogenea",
                "aromatica_aliciclica"),
    "mista":   ("aberta_fechada", "saturada_insaturada", "homogenea_heterogenea",
                "aromatica_aliciclica"),
}

# Elementos de molécula orgânica de ensino médio. Fora disso é SMILES inventado ou
# molécula que a questão não deveria usar.
_ELEMENTOS = {"C", "H", "N", "O", "S", "P", "F", "Cl", "Br", "I"}


def _reprova(motivo):
    return {"ok": False, "motivo": motivo, "cobraveis": (), "nao_aplicavel": {},
            "classificacao": None}


def classificar_cadeia(smiles):
    """SMILES -> as cinco classificações, pela convenção do ensino médio brasileiro.
    Nunca lança: SMILES ruim volta com ok=False e o motivo em texto."""
    s = str(smiles or "").strip()
    if not s:
        return _reprova("SMILES vazio.")
    try:
        # reinterpret_aromatic=False: respeita o que veio escrito (minúscula = aromático).
        g = read_smiles(s, reinterpret_aromatic=False)
        g_perc = read_smiles(s, reinterpret_aromatic=True)
    except Exception as e:
        return _reprova(f"SMILES inválido: {e}")

    elementos = {d.get("element") for _, d in g.nodes(data=True)}
    if not g.number_of_nodes() or "C" not in elementos:
        return _reprova("SMILES sem carbono (ou não reconhecido).")
    if not elementos <= _ELEMENTOS:
        return _reprova(f"Elemento fora do escopo: {sorted(elementos - _ELEMENTOS)}.")

    # KEKULÉ é reprovado, não adivinhado. Se a percepção de aromaticidade acha anel
    # aromático que não veio em minúscula, o SMILES está em Kekulé (C1=CC=CC=C1). O
    # pysmiles não é confiável nessa conversão, e um anel benzênico lido como alicíclico
    # vira gabarito errado. O prompt exige minúscula.
    escrito = {n for n, d in g.nodes(data=True) if d.get("aromatic")}
    percebido = {n for n, d in g_perc.nodes(data=True) if d.get("aromatic")}
    if percebido - escrito:
        return _reprova("Anel aromático em forma de Kekulé (C1=CC=CC=C1); "
                        "escreva aromático em minúscula (c1ccccc1).")

    carbonos = {n for n, d in g.nodes(data=True) if d["element"] == "C"}
    no_anel = set().union(*map(set, nx.cycle_basis(g))) if nx.cycle_basis(g) else set()
    viz_c = {n: [m for m in g.neighbors(n) if m in carbonos] for n in g.nodes}

    # 1. ABERTA / FECHADA / MISTA. Mista é anel com carbono FORA dele (tolueno, anisol,
    #    propiofenona). Decisão da Bia: segue o livro brasileiro, que tem a mista como
    #    categoria própria. Heteroátomo fora do anel (OH do fenol) não faz mista.
    if not no_anel:
        aberta = "aberta"
    elif carbonos - no_anel:
        aberta = "mista"
    else:
        aberta = "fechada"

    # 5. NORMAL / RAMIFICADA. Só em cadeia ABERTA: ramificada = carbono com 3+ vizinhos
    #    carbono (heteroátomo e =O não são ramo: só carbono é cadeia).
    #    Em FECHADA e MISTA o eixo é NÃO APLICÁVEL, por decisão da Bia. A ambiguidade é de
    #    LIVRO, não de química: tolueno sai "ramificado" num livro e "normal" noutro. A
    #    saída foi NÃO COBRAR, em vez de escolher um lado. Não "complete" este eixo.
    if aberta == "aberta":
        ramificacao = "ramificada" if any(len(viz_c[n]) >= 3 for n in carbonos) else "normal"
        nao_aplicavel = {}
    else:
        ramificacao = NAO_APLICAVEL
        nao_aplicavel = {"normal_ramificada": MOTIVO_RAMIFICACAO}

    # 4. SATURADA / INSATURADA. Só ligação múltipla ENTRE CARBONOS: C=C, C≡C e a ligação
    #    aromática (1,5) entre carbonos, porque anel benzênico conta como insaturado.
    #    C=O NÃO é insaturação nesta convenção (propanona e ácido acético são saturadas).
    insaturada = any(u in carbonos and v in carbonos and d.get("order", 1) > 1
                     for u, v, d in g.edges(data=True))

    # 3. HOMOGÊNEA / HETEROGÊNEA. Heteroátomo só conta ENTRE carbonos (2+ vizinhos C).
    #    Na ponta (OH, NH2) é homogênea. Foi o erro de 4 das 6 reprovações da amostra, e o
    #    Gemini se contradiz nisso (metilamina heterogênea numa questão, homogênea noutra).
    heterogenea = any(d["element"] not in ("C", "H") and len(viz_c[n]) >= 2
                      for n, d in g.nodes(data=True))

    # 2. AROMÁTICA / ALICÍCLICA (só cadeia com anel). Aromática = SÓ ANEL BENZÊNICO: seis
    #    carbonos aromáticos. Furano e piridina NÃO são aromáticos aqui, são heterocíclicos
    #    (saem alicíclicos e heterogêneos). Decisão da Bia: alinha com o livro do ensino
    #    médio brasileiro, não com a definição de faculdade. NÃO "conserte" para o outro lado.
    if not no_anel:
        tipo_anel = None
    else:
        benzenico = any(len(c) == 6 and all(n in carbonos and n in escrito for n in c)
                        for c in nx.cycle_basis(g))
        tipo_anel = "aromatica" if benzenico else "aliciclica"

    return {"ok": True, "motivo": None, "cobraveis": EIXOS_COBRAVEIS[aberta],
            "nao_aplicavel": nao_aplicavel, "classificacao": {
        "aberta_fechada": aberta,
        "normal_ramificada": ramificacao,
        "saturada_insaturada": "insaturada" if insaturada else "saturada",
        "homogenea_heterogenea": "heterogenea" if heterogenea else "homogenea",
        "aromatica_aliciclica": tipo_anel,
    }}


def conferir_gabarito(smiles, gabarito):
    """O portão: aprova só se as cinco classificações do gabarito batem com as calculadas.
    Devolve as divergências e o motivo em texto, não só o booleano.

    Eixo NÃO APLICÁVEL: o gabarito tem de deixá-lo vazio (None, ausente ou
    "nao_aplicavel"). AFIRMAR um valor ali (normal/ramificada em cadeia fechada) reprova:
    a questão perguntou o que não devia perguntar. Não é tolerância, é reprovação."""
    r = classificar_cadeia(smiles)
    if not r["ok"]:
        return {"aprovada": False, "divergencias": [], "motivo": r["motivo"], "calculado": None}
    calc = r["classificacao"]
    gab = gabarito or {}
    div, partes = [], []
    for k in CHAVES:
        g, c = gab.get(k), calc[k]
        if c == NAO_APLICAVEL:
            if g not in (None, NAO_APLICAVEL):
                div.append((k, g, c))
                partes.append(f"{k}: gabarito afirma {g!r}, mas o eixo não se cobra nesta "
                              f"cadeia ({r['nao_aplicavel'][k]})")
        elif g != c:
            div.append((k, g, c))
            partes.append(f"{k}: gabarito diz {g!r}, a molécula é {c!r}")
    return {"aprovada": not div, "divergencias": div, "motivo": "; ".join(partes) or None,
            "calculado": calc}
