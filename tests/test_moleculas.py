"""Validador de cadeia carbônica (Backend/moleculas.py).

Conjunto: as 40 questões de Química Orgânica pedidas ao Gemini (gemini-3.5-flash-lite,
20/10/2026). O ESPERADO NÃO É O GABARITO DO GEMINI: foi escrito à mão pela convenção do
módulo. Copiar o gabarito dele faria o teste exigir que o validador reproduzisse os erros.
Cada linha traz os dois; CORRECAO diz onde o esperado diverge do Gemini e por quê.
"""
import pytest
from moleculas import (CHAVES, EIXOS_COBRAVEIS, MOTIVO_RAMIFICACAO, NAO_APLICAVEL,
                       classificar_cadeia, conferir_gabarito)

_V = {"AB": "aberta", "FE": "fechada", "MI": "mista", "N": "normal", "R": "ramificada",
      "NA": NAO_APLICAVEL, "S": "saturada", "I": "insaturada", "HO": "homogenea",
      "HE": "heterogenea", "ARO": "aromatica", "ALI": "aliciclica", "-": None}


def _cls(abrev):
    return dict(zip(CHAVES, (_V[x] for x in abrev.split())))


# (nº, molécula do enunciado, SMILES, gabarito do GEMINI, ESPERADO à mão)
AMOSTRA = [
    (1, "Butano", "CCCC", "AB N S HO -", "AB N S HO -"),
    (2, "Metilpropano", "CC(C)C", "AB R S HO -", "AB R S HO -"),
    (3, "Propeno", "CC=C", "AB N I HO -", "AB N I HO -"),
    (4, "Etilmetiléter", "CCOCC", "AB N S HE -", "AB N S HE -"),
    (5, "Ciclopentano", "C1CCCC1", "FE N S HO ALI", "FE NA S HO ALI"),
    (6, "Benzeno", "c1ccccc1", "FE N I HO ARO", "FE NA I HO ARO"),
    (7, "Furano", "c1ccoc1", "FE N I HE ARO", "FE NA I HE ALI"),
    (8, "Tetrahidrofurano", "C1CCCO1", "FE N S HE ALI", "FE NA S HE ALI"),
    (9, "Tolueno", "Cc1ccccc1", "FE R I HO ARO", "MI NA I HO ARO"),
    (10, "Fenol", "Oc1ccccc1", "FE N I HO ARO", "FE NA I HO ARO"),
    (11, "Piridina", "c1ccncc1", "FE N I HE ARO", "FE NA I HE ALI"),
    (12, "Propanona", "CC(=O)C", "AB N S HO -", "AB N S HO -"),
    (13, "2-metilpentano", "CCCC(C)C", "AB R S HO -", "AB R S HO -"),
    (14, "Etino", "C#C", "AB N I HO -", "AB N I HO -"),
    (15, "Metilamina", "CN", "AB N S HE -", "AB N S HO -"),
    (16, "Ciclohexeno", "C1=CCC=CC1", "FE N I HO ALI", "FE NA I HO ALI"),
    (17, "Anisol", "COc1ccccc1", "FE N I HE ARO", "MI NA I HE ARO"),
    (18, "Ácido acético", "CC(=O)O", "AB N S HO -", "AB N S HO -"),
    (19, "1,3-butadieno", "C=CC=C", "AB N I HO -", "AB N I HO -"),
    (20, "Naftaleno", "c1ccc2ccccc2c1", "FE N I HO ARO", "FE NA I HO ARO"),
    (21, "Butano", "CCCC", "AB N S HO -", "AB N S HO -"),
    (22, "2-metilpropano", "CC(C)C", "AB R S HO -", "AB R S HO -"),
    (23, "Eteno", "C=C", "AB N I HO -", "AB N I HO -"),
    (24, "Éter dietílico", "CCOCC", "AB N S HE -", "AB N S HE -"),
    (25, "Ciclopentano", "C1CCCC1", "FE N S HO ALI", "FE NA S HO ALI"),
    (26, "Benzeno", "c1ccccc1", "FE N I HO ARO", "FE NA I HO ARO"),
    (27, "Furano", "c1ccoc1", "FE N I HE ARO", "FE NA I HE ALI"),
    (28, "Piridina", "c1ccncc1", "FE N I HE ARO", "FE NA I HE ALI"),
    (29, "Tetrahidrofurano", "C1COCC1", "FE N S HE ALI", "FE NA S HE ALI"),
    (30, "Propino", "CC#C", "AB N I HO -", "AB N I HO -"),
    (31, "Metilamina", "CN", "AB N S HO -", "AB N S HO -"),
    (32, "Ciclohexeno", "C1=CCCCC1", "FE N I HO ALI", "FE NA I HO ALI"),
    (33, "Tolueno", "Cc1ccccc1", "FE R I HO ARO", "MI NA I HO ARO"),
    (34, "Propiofenona", "CCC(=O)c1ccccc1", "FE R I HO ARO", "MI NA I HO ARO"),
    (35, "Anilina", "Nc1ccccc1", "FE N I HE ARO", "FE NA I HO ARO"),
    (36, "1,3-Butadieno", "C=CC=C", "AB N I HO -", "AB N I HO -"),
    (37, "Ácido acético", "CC(=O)O", "AB N S HO -", "AB N S HO -"),
    (38, "2-Pentanona", "CCCC(=O)C", "AB N S HO -", "AB N S HO -"),
    (39, "Etilenodiamina", "NCCCN", "AB N S HE -", "AB N S HO -"),
    (40, "Fenol", "Oc1ccccc1", "FE N I HE ARO", "FE NA I HO ARO"),
]

# Onde o ESPERADO diverge do Gemini, e por quê. Toda cadeia fechada/mista diverge ao menos
# no eixo normal/ramificada, que é não aplicável (regra 5); o resto vem anotado.
_NA = "normal/ramificada não aplicável em cadeia fechada/mista"
CORRECAO = {
    5: _NA, 6: _NA, 8: _NA, 10: _NA, 16: _NA, 20: _NA, 25: _NA, 26: _NA, 29: _NA, 32: _NA,
    7: _NA + "; furano não é aromático nesta convenção (só anel benzênico)",
    11: _NA + "; piridina não é aromática nesta convenção (só anel benzênico)",
    27: _NA + "; furano não é aromático nesta convenção",
    28: _NA + "; piridina não é aromática nesta convenção",
    9: _NA + "; anel + CH3 fora dele = mista",
    33: _NA + "; anel + CH3 fora dele = mista",
    17: _NA + "; anel + CH3 (via O) fora dele = mista",
    34: _NA + "; anel + etila/C=O fora dele = mista",
    15: "N na ponta, não entre carbonos = homogênea",
    35: _NA + "; N fora do anel, não entre carbonos = homogênea",
    39: "N nas pontas = homogênea",
    40: _NA + "; OH fora do anel, não entre carbonos = homogênea",
}

# As 6 que a conferência à mão reprovou. 4 e 16: o NOME do enunciado não é a molécula do
# SMILES, mas a classificação coincide.
REPROVADAS_A_MAO = {15, 35, 40, 39, 4, 16}
SO_NOME_ERRADO = {4, 16}


def test_amostra_bem_formada():
    assert len(AMOSTRA) == 40
    for n, _, _, gemini, esperado in AMOSTRA:
        divergem = gemini != esperado
        assert divergem == (n in CORRECAO), f"nº {n}: marque (ou desmarque) em CORRECAO"


# ---- a) POSITIVO: as cinco classificações corretas, para cada molécula ----
@pytest.mark.parametrize("n,nome,smiles,gemini,esperado", AMOSTRA, ids=[f"{a[0]}-{a[1]}" for a in AMOSTRA])
def test_classificacao_correta(n, nome, smiles, gemini, esperado):
    r = classificar_cadeia(smiles)
    assert r["ok"], r["motivo"]
    assert r["classificacao"] == _cls(esperado)


# ---- b) NEGATIVO: o portão tem de pegar o gabarito errado do Gemini ----
_NEG = [a for a in AMOSTRA if a[0] in REPROVADAS_A_MAO - SO_NOME_ERRADO]


@pytest.mark.parametrize("n,nome,smiles,gemini,esperado", _NEG, ids=[f"{a[0]}-{a[1]}" for a in _NEG])
def test_portao_reprova_gabarito_errado(n, nome, smiles, gemini, esperado):
    r = conferir_gabarito(smiles, _cls(gemini))
    assert not r["aprovada"]
    assert ("homogenea_heterogenea", "heterogenea", "homogenea") in r["divergencias"]
    assert "homogenea_heterogenea" in r["motivo"]


# LIMITE POR DESENHO, registrado e não escondido: 4 e 16 erram NOME contra SMILES, com a
# mesma classificação. O portão não cobre isso e não vai cobrir: o conserto decidido é a
# questão NÃO TER NOME (nem nas alternativas, nem na explicacao, nem no porque_erradas),
# na montagem do prompt. strict=True: se um dia passarem a reprovar, o teste avisa.
# O gabarito usado é o ESPERADO (correto pela convenção), não o do Gemini: assim o nome é o
# ÚNICO erro da questão. Com o do Gemini, a 16 reprova pelo eixo normal/ramificada afirmado
# em cadeia fechada, o que esconderia o limite em vez de medi-lo.
_NOME = [a for a in AMOSTRA if a[0] in SO_NOME_ERRADO]


@pytest.mark.xfail(strict=True, reason="nome contra SMILES: fora do portão por desenho; o "
                                       "conserto é tirar o nome da questão (enunciado, "
                                       "alternativas, explicacao, porque_erradas)")
@pytest.mark.parametrize("n,nome,smiles,gemini,esperado", _NOME, ids=[f"{a[0]}-{a[1]}" for a in _NOME])
def test_portao_reprova_nome_errado(n, nome, smiles, gemini, esperado):
    assert not conferir_gabarito(smiles, _cls(esperado))["aprovada"]


# ---- regra 5: ramificação só em cadeia aberta ----
@pytest.mark.parametrize("smiles", ["Cc1ccccc1", "COc1ccccc1", "CCC(=O)c1ccccc1",
                                    "c1ccccc1", "c1ccoc1", "C1CCCC1"])
def test_ramificacao_nao_aplicavel_em_fechada_e_mista(smiles):
    r = classificar_cadeia(smiles)
    assert r["classificacao"]["normal_ramificada"] == NAO_APLICAVEL
    assert r["nao_aplicavel"] == {"normal_ramificada": MOTIVO_RAMIFICACAO}
    assert "normal_ramificada" not in r["cobraveis"]


@pytest.mark.parametrize("smiles,esperado", [("CC(C)C", "ramificada"), ("CCCC(C)C", "ramificada"),
                                             ("CCCC", "normal"), ("CC=C", "normal")])
def test_cadeia_aberta_nao_mudou(smiles, esperado):
    r = classificar_cadeia(smiles)
    assert r["classificacao"]["normal_ramificada"] == esperado
    assert r["nao_aplicavel"] == {}
    assert "normal_ramificada" in r["cobraveis"]


@pytest.mark.parametrize("afirmado", ["normal", "ramificada"])
def test_portao_reprova_quem_afirma_ramificacao_em_fechada(afirmado):
    gab = _cls("FE NA S HO ALI") | {"normal_ramificada": afirmado}
    r = conferir_gabarito("C1CCCC1", gab)
    assert not r["aprovada"]
    assert "não se cobra" in r["motivo"]


@pytest.mark.parametrize("vazio", [None, NAO_APLICAVEL])
def test_portao_aceita_eixo_vazio_em_fechada(vazio):
    gab = _cls("FE NA S HO ALI") | {"normal_ramificada": vazio}
    assert conferir_gabarito("C1CCCC1", gab)["aprovada"]


def test_eixos_cobraveis_por_tipo():
    assert set(EIXOS_COBRAVEIS) == {"aberta", "fechada", "mista"}
    assert "aromatica_aliciclica" not in EIXOS_COBRAVEIS["aberta"]
    for tipo in ("fechada", "mista"):
        assert "normal_ramificada" not in EIXOS_COBRAVEIS[tipo]


# ---- demais convenções ----
def test_kekule_e_reprovado_com_motivo():
    r = classificar_cadeia("C1=CC=CC=C1")
    assert not r["ok"] and "Kekulé" in r["motivo"]


def test_furano_em_kekule_nao_e_aromatico_e_passa():
    # O furano não é aromático nesta convenção, então em Kekulé ele não tem o que adivinhar.
    assert classificar_cadeia("C1=COC=C1")["classificacao"] == _cls("FE NA I HE ALI")


def test_c_o_nao_e_insaturacao():
    assert classificar_cadeia("CC(=O)C")["classificacao"]["saturada_insaturada"] == "saturada"


def test_heteroatomo_entre_carbonos_e_heterogenea_na_ponta_nao():
    assert classificar_cadeia("CCOCC")["classificacao"]["homogenea_heterogenea"] == "heterogenea"
    assert classificar_cadeia("CCO")["classificacao"]["homogenea_heterogenea"] == "homogenea"


@pytest.mark.parametrize("ruim", ["", "   ", "xyz", "C1CC", "[Fe]", "O", None])
def test_smiles_ruim_reprova_sem_lancar(ruim):
    r = classificar_cadeia(ruim)
    assert not r["ok"] and r["motivo"]
    assert not conferir_gabarito(ruim, _cls("AB N S HO -"))["aprovada"]
