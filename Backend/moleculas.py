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
    eixos_nao_cobraveis(classificacao)   # {eixo: motivo}, a partir de REGRAS_NAO_COBRAVEL
    instrucao_eixos()                    # o mesmo, em texto para o prompt
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

# QUANDO UM EIXO NÃO SE COBRA. Dados, não ifs espalhados: cada regra diz o eixo, a
# condição (sobre a classificação JÁ CALCULADA da molécula), a condição em texto (vai
# para o prompt) e o motivo. Os eixos cobráveis saem daqui — da molécula, não do tipo.
# normal/ramificada sai em DOIS casos, e nos dois a ambiguidade é de LIVRO, não de
# química; a saída foi NÃO COBRAR em vez de escolher um lado. Não "complete" o eixo:
#  - anel: tolueno sai "ramificado" num livro e "normal" noutro;
#  - heteroátomo na cadeia: o livro diverge se ele conta como membro da cadeia
#    (COC(C)C, CCOC(C)C saem ramificados contando o O, normais sem contar).
REGRAS_NAO_COBRAVEL = (
    ("normal_ramificada", lambda c: c["aberta_fechada"] != "aberta",
     "cadeia fechada ou mista",
     "ramificação só se cobra em cadeia aberta; os livros divergem em anel com substituinte"),
    ("normal_ramificada", lambda c: c["homogenea_heterogenea"] == "heterogenea",
     "cadeia heterogênea",
     "ramificação não se cobra em cadeia heterogênea; os livros divergem se o heteroátomo "
     "conta como membro da cadeia"),
    ("aromatica_aliciclica", lambda c: c["aberta_fechada"] == "aberta",
     "cadeia aberta",
     "sem anel, não há aromática nem alicíclica"),
)


# A CONVENÇÃO EM TEXTO — fonte ÚNICA para o GERADOR e para o VERIFICADOR (app.py). Sem ela
# o verificador aplica química de faculdade (furano aromático), marca 'suspeita' o gabarito
# que o cálculo acima provou certo, e 'suspeita' nunca é servida: as duas barreiras se
# contradiriam e a segunda venceria. Mudou a regra no código acima? Mude aqui também.
CONVENCAO = """\
1. ABERTA / FECHADA / MISTA. Cadeia com anel E carbono fora do anel é MISTA, não fechada.
   Ex.: Cc1ccccc1 (anel com CH3) é mista; COc1ccccc1 (anel com O-CH3) é mista;
   CCC(=O)c1ccccc1 é mista. Só anel, sem carbono fora: fechada (C1CCCC1, c1ccccc1).
   Oc1ccccc1 é FECHADA: o OH não é carbono.
2. AROMÁTICA é SÓ quem tem anel BENZÊNICO (seis carbonos aromáticos). Furano (c1ccoc1) e
   piridina (c1ccncc1) NÃO são aromáticos nesta convenção: são alicíclicos (heterocíclicos).
3. HETEROGÊNEA exige heteroátomo (O, N, S...) ENTRE DOIS CARBONOS. Heteroátomo na PONTA
   (OH, NH2) não conta: a cadeia é HOMOGÊNEA. Ex.: CN é homogênea; Nc1ccccc1 é homogênea;
   CCO é homogênea; CCOCC é heterogênea; c1ccoc1 é heterogênea (O entre carbonos no anel).
4. INSATURADA é só ligação dupla ou tripla ENTRE CARBONOS (C=C, C#C). C=O NÃO conta:
   CC(=O)C é saturada. Anel benzênico conta como insaturado.
5. NORMAL / RAMIFICADA só se pergunta em cadeia ABERTA e HOMOGÊNEA (ramificada = carbono
   ligado a 3 ou mais carbonos). Em cadeia FECHADA, MISTA ou HETEROGÊNEA esse eixo NÃO se
   cobra: não afirme "normal" nem "ramificada" nem no gabarito nem nas alternativas."""


def eixos_nao_cobraveis(classificacao):
    """{eixo: motivo} dos eixos que NÃO se perguntam para esta molécula (1º motivo que vale)."""
    fora = {}
    for eixo, vale, _quando, motivo in REGRAS_NAO_COBRAVEL:
        if eixo not in fora and vale(classificacao):
            fora[eixo] = motivo
    return fora


def instrucao_eixos():
    """Texto para o prompt, gerado de REGRAS_NAO_COBRAVEL: mudou a regra, muda o prompt."""
    linhas = ['- O "classificacao" tem estas cinco chaves: ' + ", ".join(f'"{k}"' for k in CHAVES)
              + ", MENOS as que não se cobram para aquela molécula:"]
    for eixo, _vale, quando, _motivo in REGRAS_NAO_COBRAVEL:
        linhas.append(f'  - em {quando}, NÃO ponha "{eixo}" no gabarito nem pergunte isso '
                      f'nas alternativas;')
    return "\n".join(linhas)

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

    # 5. NORMAL / RAMIFICADA: ramificada = carbono com 3+ vizinhos carbono (=O e heteroátomo
    #    não são ramo). Só vale em cadeia aberta e homogênea — nas outras o eixo não se
    #    cobra (REGRAS_NAO_COBRAVEL, decisão da Bia).
    ramificacao = "ramificada" if any(len(viz_c[n]) >= 3 for n in carbonos - no_anel) else "normal"

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
    benzenico = any(len(c) == 6 and all(n in carbonos and n in escrito for n in c)
                    for c in nx.cycle_basis(g))
    tipo_anel = "aromatica" if benzenico else "aliciclica"

    cls = {
        "aberta_fechada": aberta,
        "normal_ramificada": ramificacao,
        "saturada_insaturada": "insaturada" if insaturada else "saturada",
        "homogenea_heterogenea": "heterogenea" if heterogenea else "homogenea",
        "aromatica_aliciclica": tipo_anel,
    }
    fora = eixos_nao_cobraveis(cls)
    for eixo in fora:
        cls[eixo] = NAO_APLICAVEL
    return {"ok": True, "motivo": None, "classificacao": cls, "nao_aplicavel": fora,
            "cobraveis": tuple(k for k in CHAVES if k not in fora)}


class IndiceMoleculas:
    """Conjunto de moléculas para o portão de REPETIÇÃO. Compara a MOLÉCULA, não o texto:
    C1CCOC1 e C1COCC1 são a mesma. O hash de Weisfeiler-Lehman separa em baldes; dentro
    do balde, isomorfismo de verdade decide (o hash sozinho colide em casos raros)."""

    def __init__(self, smiles=()):
        self._baldes = {}
        for s in smiles:
            self.adicionar(s)

    @staticmethod
    def _grafo(s):
        try:
            g = read_smiles(str(s or ""), reinterpret_aromatic=False)
        except Exception:
            return None
        for _, d in g.nodes(data=True):
            d["rotulo"] = f'{d.get("element")}{"a" if d.get("aromatic") else ""}'
        for _, _, d in g.edges(data=True):
            d["rotulo"] = str(d.get("order", 1))
        return g if g.number_of_nodes() else None

    def _chave(self, g):
        return nx.weisfeiler_lehman_graph_hash(g, node_attr="rotulo", edge_attr="rotulo")

    def contem(self, s):
        g = self._grafo(s)
        if g is None:
            return False
        igual = lambda a, b: a["rotulo"] == b["rotulo"]   # noqa: E731
        return any(nx.is_isomorphic(g, h, node_match=igual, edge_match=igual)
                   for h in self._baldes.get(self._chave(g), ()))

    def adicionar(self, s):
        g = self._grafo(s)
        if g is not None:
            self._baldes.setdefault(self._chave(g), []).append(g)


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
