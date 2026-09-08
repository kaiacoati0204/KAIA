# -*- coding: utf-8 -*-
"""
Teste do impostor — as questões geradas passam por questões de vestibular?

Mistura questões GERADAS pelo pipeline de produção com questões REAIS do banco
(questoes_reais) e produz uma página para um avaliador humano separar as duas.

Por que assim, e não "dê uma nota de 1 a 5":
  - julgamento binário é mais confiável entre avaliadores diferentes;
  - existe gabarito (sabemos quais são reais), então dá para medir acerto e não só
    colher opinião;
  - a régua é a certa: o alvo não é "questão boa em abstrato", é "passa por prova".

O avaliador ideal é um PROFESSOR da matéria — independente (não construiu o
sistema) e capaz de ver erro de conteúdo, não só de estilo.

Gera SEM explicação e SEM gabarito: a questão real do banco não tem esses campos, e
mostrá-los só nas geradas entregaria o jogo.

Uso (na raiz do projeto):
    python ml/teste_impostor.py                 # todos os blocos
    python ml/teste_impostor.py --materias MAT,PORT
    python ml/teste_impostor.py --n 8
    python ml/teste_impostor.py --modelo gemini-3.1-flash-lite

Saída em ml/artifacts/impostor/:
    teste_<materia>.txt    — um por professor. O gabarito vai no FIM do próprio arquivo,
                             atrás de uma linha de corte: apague antes de enviar.
"""
import os
import sys
import json
import random
import asyncio
import argparse
import textwrap
from pathlib import Path
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

SAIDA = BASE / "artifacts" / "impostor"

# Um bloco por professor: área do ENEM -> matéria fina que a geração aceita.
# Concentrado numa matéria só (e não espalhado pela área) para que UM professor
# avalie um conjunto coerente da própria disciplina.
BLOCOS = [
    ("MAT",      "MAT",  "Matemática"),
    ("NATUREZA", "BIO",  "Biologia"),
    ("NATUREZA", "FIS",  "Física"),
    ("HUMANAS",  "HIS",  "História"),
    ("HUMANAS",  "GEO",  "Geografia"),
    ("PORT",     "PORT", "Português"),
]

# Matemática pede mais itens: o comportamento do gerador muda MUITO entre tópicos
# (probabilidade não se parece com geometria), e 5 questões não cobrem essa variação.
N_POR_MATERIA = {"MAT": 10}

TEMAS = {
    "MAT": ["Progressões", "Funções do 1º grau", "Geometria plana", "Geometria espacial",
            "Probabilidade", "Análise combinatória", "Porcentagem e juros", "Estatística",
            "Trigonometria", "Razão e proporção"],
    "BIO": ["Genética", "Ecologia", "Citologia", "Evolução", "Corpo humano"],
    "FIS": ["Cinemática", "Leis de Newton", "Trabalho e energia", "Eletricidade", "Termologia"],
    "HIS": ["Era Vargas", "Revolução Industrial", "Brasil Colônia", "Guerra Fria", "República Velha"],
    "GEO": ["Urbanização", "Climatologia", "Geopolítica", "Recursos hídricos", "Agricultura"],
    "PORT": ["Interpretação de texto", "Figuras de linguagem", "Variação linguística",
             "Funções da linguagem", "Gêneros textuais"],
}


# ==== COLETA ====
async def gerar(conn, materia, nome, n, app):
    """Gera n questões pelo MESMO caminho da produção (few-shot dinâmico incluso)."""
    fora = []
    temas = TEMAS[materia]
    for i in range(n):
        tema = temas[i % len(temas)]
        nivel = 2 + (i % 3)                       # 2, 3, 4 — evita só o nível médio
        # O Gemini devolve 503 "high demand" com alguma frequência no tier gratuito;
        # sem retry o bloco sai incompleto por motivo que não é do gerador.
        qs = None
        for tentativa in range(3):
            try:
                calc = materia in ("MAT", "FIS", "QUI")
                ex = await app._exemplos_similares(conn, materia, tema, nivel, calculo=calc)
                gen = (app._gerar_calculo_pot if calc else app._gerar_no_gemini)
                qs = await gen(1, materia, nome, tema, None, nivel, exemplos=ex)
                if qs:
                    break
            except Exception as e:
                print(f"  . tentativa {tentativa + 1} falhou em {materia}/{tema}: {e}")
            await asyncio.sleep(4)
        if not qs:
            print(f"  ! desisti de {materia}/{tema}")
            continue
        for q in (qs or [])[:1]:
            fora.append({"enunciado": q.get("q", ""), "alternativas": q.get("opts", []),
                         "origem": "gerada", "materia": materia, "tema": tema, "nivel": nivel})
        print(f"  gerada {len(fora)}/{n} — {tema} (nível {nivel})")
    return fora


async def reais(conn, materia, area, n):
    """Questões reais da mesma matéria (cai para a área se a matéria fina tiver pouca)."""
    rows = await conn.fetch(
        "select enunciado, alternativas, materia, nivel from questoes_reais "
        "where materia = any($1::text[]) order by random() limit $2",
        list({materia, area}), n)
    out = []
    for r in rows:
        alts = r["alternativas"]
        out.append({"enunciado": r["enunciado"],
                    "alternativas": json.loads(alts) if isinstance(alts, str) else alts,
                    "origem": "real", "materia": r["materia"], "tema": None, "nivel": r["nivel"]})
    return out


# ==== TEXTO ====
# Texto puro de proposito: e o que se manda por WhatsApp, imprime e o professor
# responde na hora, sem precisar baixar arquivo nem abrir navegador.
def montar_texto(nome, itens, modelo, ts):
    larg = 78
    fora = [f"AVALIACAO DE QUESTOES — {nome.upper()}", ""]
    fora += textwrap.wrap(
        "Abaixo ha questoes de duas origens misturadas: algumas vieram de provas reais "
        "de vestibular/ENEM, outras foram escritas por um sistema automatico. Nao "
        "dizemos quantas sao de cada.", larg)
    fora += ["", "Para cada uma, responda duas coisas:",
             "  1. E de PROVA ou GERADA?",
             "  2. O que te fez decidir? (uma linha basta)", ""]
    fora += textwrap.wrap(
        "Nao precisa resolver a questao — o que interessa e se ela parece questao de "
        "prova.", larg)
    fora += ["", "-" * larg, ""]
    for i, q in enumerate(itens, 1):
        fora += [f"QUESTAO {i}", ""]
        fora += textwrap.wrap(q["enunciado"], larg)
        fora += [""]
        for j, a in enumerate(q["alternativas"] or []):
            fora += textwrap.wrap(f"{chr(65 + j)}) {a}", larg, subsequent_indent="   ")
        fora += ["", "   ( ) de PROVA      ( ) GERADA",
                 "   Por que: _______________________________________________",
                 "", "-" * larg, ""]
    # Gabarito no proprio arquivo, atras de uma linha de corte: um arquivo so por
    # materia e mais facil de administrar do que dois. O risco e obvio — quem
    # recebe rola e ve. Apague daqui pra baixo antes de mandar.
    fora += ["", "=" * larg,
             "CORTE AQUI ANTES DE ENVIAR — daqui pra baixo e o gabarito",
             "=" * larg, "",
             f"modelo: {modelo}   gerado em: {ts}", ""]
    for i, q in enumerate(itens, 1):
        extra = (f"  ({q['tema']}, nivel {q['nivel']})" if q["tema"]
                 else f"  (nivel {q['nivel']})")
        fora.append(f"  {i:>2}. {q['origem'].upper():<7}{extra}")
    ger = sum(1 for q in itens if q["origem"] == "gerada")
    fora += ["", f"  total: {ger} geradas, {len(itens) - ger} reais", ""]
    return "\n".join(fora)


# ==== MAIN ====
async def main(n_padrao, modelo, materias):
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return
    if modelo:
        os.environ["GEMINI_MODEL"] = modelo
    import app                                    # importa DEPOIS de fixar o modelo
    print(f"modelo em uso: {app.GEMINI_MODEL}\n")

    SAIDA.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rng = random.Random(42)

    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        for area, materia, nome in BLOCOS:
            if materias and materia not in materias:
                continue
            n = N_POR_MATERIA.get(materia, n_padrao)
            print(f"[{nome}]")
            g = await gerar(conn, materia, nome, n, app)
            r = await reais(conn, materia, area, n)
            if not g or not r:
                print(f"  ! bloco {nome} incompleto (geradas={len(g)}, reais={len(r)}) — pulando\n")
                continue
            itens = g + r
            rng.shuffle(itens)

            arq = SAIDA / f"teste_{materia.lower()}.txt"
            arq.write_text(montar_texto(nome, itens, app.GEMINI_MODEL, ts), encoding="utf-8")
            print(f"  -> {arq.name} ({len(g)} geradas + {len(r)} reais)\n")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="geradas por bloco (e o mesmo tanto de reais)")
    ap.add_argument("--modelo", default=None, help="sobrescreve GEMINI_MODEL só nesta execução")
    ap.add_argument("--materias", default=None,
                    help="só estas (ex.: MAT,PORT). Sem isso, refaz todos os blocos — "
                         "cuidado se já distribuiu algum.")
    a = ap.parse_args()
    alvo = {m.strip().upper() for m in a.materias.split(",")} if a.materias else None
    asyncio.run(main(a.n, a.modelo, alvo))
