"""Química Orgânica com molécula (app.py): chave KAIA_ORGANICA_MOLECULA, portões e coluna.

Com a chave DESLIGADA nada pode mudar: nem o caminho de geração, nem o SQL, nem o payload.
Com ela LIGADA, cada questão passa por três portões (gabarito, nome, repetição) e o nome
interno da molécula nunca chega ao banco nem ao front.
"""
import json
import uuid

import pytest
import app as app_mod


class _Row(dict):
    def keys(self):
        return super().keys()


class FakeConn:
    """Registra todo SQL. `cache_smiles` simula o que já está em questoes_cache."""

    def __init__(self, cache_smiles=()):
        self.sql, self.valores, self.cache_smiles = [], [], list(cache_smiles)

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        if "select smiles from questoes_cache" in sql:
            return [_Row(smiles=s) for s in self.cache_smiles]
        return []

    async def fetchval(self, sql, *args):
        self.sql.append(sql)
        self.valores.append(args)
        return uuid.uuid4()

    async def execute(self, sql, *args):
        self.sql.append(sql)


def _q(smiles, cls, nome="x", **extra):
    base = {"q": "Qual é a classificação da cadeia carbônica representada na figura?",
            "opts": ["aberta, normal, saturada e homogênea", "aberta, ramificada, saturada e homogênea",
                     "aberta, normal, insaturada e homogênea", "fechada, saturada e homogênea",
                     "mista, saturada e homogênea"],
            "ans": 0, "explicacao": "Só ligações simples entre carbonos.",
            "porque_erradas": ["", "a", "b", "c", "d"], "smiles": smiles,
            "classificacao": cls, "molecula_interna": nome}
    base.update(extra)
    return base


ABERTA_N = {"aberta_fechada": "aberta", "normal_ramificada": "normal",
            "saturada_insaturada": "saturada", "homogenea_heterogenea": "homogenea"}
ABERTA_R = ABERTA_N | {"normal_ramificada": "ramificada"}


# ---------------- chave DESLIGADA: nada muda ----------------
def test_chave_desligada_por_padrao():
    assert app_mod.ORGANICA_MOLECULA is False
    assert app_mod._eh_molecula("QUI", "Química Orgânica") is False


async def test_desligada_organica_segue_no_conceitual_e_sql_sem_smiles(monkeypatch):
    monkeypatch.setattr(app_mod, "ORGANICA_MOLECULA", False)
    chamados = []

    async def conceitual(n, *a, **k):
        chamados.append("conceitual")
        return [app_mod._normalizar_questao({"q": "Enunciado de orgânica?", "opts": list("ABCDE"),
                                             "ans": 0, "explicacao": "e", "porque_erradas": [""] * 5})]

    async def molecula(*a, **k):
        chamados.append("molecula")
        return []

    monkeypatch.setattr(app_mod, "_gerar_no_gemini", conceitual)
    monkeypatch.setattr(app_mod, "_gerar_molecula", molecula)
    conn = FakeConn()
    out = await app_mod._montar_banda(conn, "u", "QUI", "Química", "Química Orgânica", None, 2, 1)
    assert chamados and set(chamados) == {"conceitual"}
    assert not any("smiles" in s for s in conn.sql)          # select e insert de sempre
    assert all("smiles" not in q for q in out)                # payload de sempre


def test_questao_antiga_sem_coluna_smiles_funciona():
    # linha do cache como o select de hoje devolve: SEM a coluna smiles
    row = _Row(questao_id=uuid.uuid4(), veredito="ok", enunciado="Q?", alternativas=json.dumps(list("ABCDE")),
               resposta_correta=1, explicacao="e", porque_erradas=json.dumps([""] * 5))
    q = app_mod._row_para_questao(row)
    assert q["smiles"] is None
    assert "smiles" not in app_mod._frontend_q(q)


def test_frontend_q_leva_smiles_e_nunca_o_nome():
    q = app_mod._frontend_q({"q": "Q?", "opts": list("ABCDE"), "ans": 0, "smiles": "CCCC",
                             "molecula_interna": "butano", "classificacao": ABERTA_N})
    assert q["smiles"] == "CCCC"
    assert "molecula_interna" not in q and "classificacao" not in q


# ---------------- chave LIGADA: os três portões ----------------
async def test_ligada_portoes_descartam_e_nome_nao_vaza(monkeypatch):
    monkeypatch.setattr(app_mod, "ORGANICA_MOLECULA", True)
    itens = [
        _q("CCCC", ABERTA_N, "butano"),                                  # boa
        _q("CC(C)C", ABERTA_N, "isobutano"),                             # gabarito errado
        _q("CCCCC", ABERTA_N, "pentano",
           porque_erradas=["", "o pentano não é ramificado", "b", "c", "d"]),   # nome vazou
        _q("CCCCCC", ABERTA_N, "hexano"),                                # já está no cache
        _q("C(C)CC", ABERTA_N, "butano de novo"),                        # repete a 1ª (outra escrita)
        _q("C1=CC=CC=C1", {"aberta_fechada": "fechada"}, "benzeno"),    # Kekulé
    ]
    monkeypatch.setattr(app_mod, "chamar_gemini", lambda p: json.dumps(itens))
    conn = FakeConn(cache_smiles=["C(CCCC)C"])                           # hexano, escrito diferente
    out = await app_mod._gerar_molecula(10, "QUI", "Química", "Química Orgânica", None, 2, conn=conn)
    assert [q["smiles"] for q in out] == ["CCCC"]
    assert all("molecula_interna" not in q and "classificacao" not in q for q in out)


async def test_ligada_insert_grava_smiles_e_nao_o_nome(monkeypatch):
    monkeypatch.setattr(app_mod, "ORGANICA_MOLECULA", True)
    conn = FakeConn()
    q = app_mod._normalizar_questao(_q("CCCC", ABERTA_N, "butano"))
    await app_mod._salvar_no_cache(conn, "QUI", "Química Orgânica", 2, None, [q])
    sql = conn.sql[-1]
    assert "smiles" in sql
    assert "CCCC" in conn.valores[-1]
    assert not any("butano" in str(v) for v in conn.valores[-1])     # nome não vai ao banco


async def test_ligada_select_le_smiles(monkeypatch):
    monkeypatch.setattr(app_mod, "ORGANICA_MOLECULA", True)
    conn = FakeConn()
    await app_mod._buscar_cache(conn, "u", "QUI", "Química Orgânica", 2, None, 3)
    assert "c.smiles" in conn.sql[-1]


async def test_ligada_organica_vai_para_a_molecula(monkeypatch):
    monkeypatch.setattr(app_mod, "ORGANICA_MOLECULA", True)
    chamados = []

    async def molecula(n, *a, conn=None, **k):
        chamados.append(("molecula", conn is not None))
        return []

    async def conceitual(*a, **k):
        chamados.append(("conceitual", False))
        return []

    monkeypatch.setattr(app_mod, "_gerar_molecula", molecula)
    monkeypatch.setattr(app_mod, "_gerar_no_gemini", conceitual)
    await app_mod._montar_banda(FakeConn(), "u", "QUI", "Química", "Química Orgânica", None, 2, 1)
    assert chamados == [("molecula", True)]
    # outro tema de QUI continua no caminho de sempre, mesmo com a chave ligada
    chamados.clear()
    await app_mod._montar_banda(FakeConn(), "u", "QUI", "Química", "Química Geral", None, 2, 1)
    assert chamados == [("conceitual", False)]


def test_prompt_monta_eixos_das_regras_do_modulo():
    p = app_mod._prompt_molecula(5)
    assert app_mod.instrucao_eixos() in p
    assert "cadeia heterogênea" in p and "JÁ FORAM USADAS" not in p


# ---------------- verificador ----------------
def _prompt_do_verificador(monkeypatch, itens):
    visto = {}

    def fake(prompt):
        visto["p"] = prompt
        return json.dumps([{"n": i + 1, "resposta": "A", "problema": ""} for i in range(len(itens))])

    monkeypatch.setattr(app_mod, "_chamar_verificador", fake)
    app_mod.verificar_lote(itens)
    return visto["p"]


def test_verificador_sem_smiles_igual_ao_de_sempre(monkeypatch):
    p2 = _prompt_do_verificador(monkeypatch, [("Quanto é 2+2?", list("ABCDE"))])
    p3 = _prompt_do_verificador(monkeypatch, [("Quanto é 2+2?", list("ABCDE"), None)])
    assert p2 == p3                                          # 3º campo vazio não muda nada
    assert app_mod.CONVENCAO not in p2 and "SMILES" not in p2
    assert p2.startswith("Resolva cada questão")             # o prompt de sempre, desde a 1ª linha


def test_verificador_com_smiles_recebe_a_mesma_convencao(monkeypatch):
    from moleculas import CONVENCAO
    p = _prompt_do_verificador(monkeypatch, [("Qual a classificação da cadeia da figura?",
                                              list("ABCDE"), "c1ccoc1")])
    assert CONVENCAO in p                                    # o MESMO texto, não uma cópia
    assert "SMILES c1ccoc1" in p


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_):
                return pool.conn

            async def __aexit__(self_, *a):
                return False
        return _Ctx()


@pytest.mark.parametrize("ligada", [False, True])
async def test_job_de_verificacao_so_pede_smiles_com_a_chave(monkeypatch, ligada):
    monkeypatch.setattr(app_mod, "ORGANICA_MOLECULA", ligada)
    monkeypatch.setattr(app_mod, "API_KEY", "x")
    conn = FakeConn()

    class _App:
        class state:
            pool = _Pool(conn)

    await app_mod.job_verificar_cache(_App)
    assert ("smiles" in conn.sql[0]) is ligada


# ---------------- rodada C: portão de texto e texto alternativo ----------------
async def test_ligada_portao_de_texto_descarta(monkeypatch):
    monkeypatch.setattr(app_mod, "ORGANICA_MOLECULA", True)
    het = {"aberta_fechada": "aberta", "saturada_insaturada": "saturada", "homogenea_heterogenea": "heterogenea"}
    citam = _q("COC(C)C", het, "metoxipropano",
               opts=["aberta, ramificada, saturada e heterogênea", "aberta, saturada e heterogênea",
                     "fechada, saturada e heterogênea", "mista, saturada e homogênea", "aberta, insaturada e homogênea"])
    limpa = _q("CCOC", het, "metoxietano",
               opts=["aberta, saturada e heterogênea", "aberta, insaturada e heterogênea",
                     "fechada, saturada e heterogênea", "mista, saturada e homogênea", "aberta, saturada e homogênea"])
    monkeypatch.setattr(app_mod, "chamar_gemini", lambda p: json.dumps([citam, limpa]))
    out = await app_mod._gerar_molecula(5, "QUI", "Química", "Química Orgânica", None, 2, conn=FakeConn())
    assert [q["smiles"] for q in out] == ["CCOC"]


def test_frontend_q_leva_texto_alternativo_so_com_smiles():
    com = app_mod._frontend_q({"q": "Q?", "opts": list("ABCDE"), "ans": 0, "smiles": "Cc1ccccc1"})
    sem = app_mod._frontend_q({"q": "Q?", "opts": list("ABCDE"), "ans": 0})
    assert "círculo dentro" in com["figura_descricao"]
    assert "figura_descricao" not in sem and "smiles" not in sem
