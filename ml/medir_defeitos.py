# -*- coding: utf-8 -*-
"""
Mede a taxa REAL de questões defeituosas geradas pelo pipeline.

Motivo: a avaliação com 28 questões apontou ~14% de defeito, mas com amostra desse
tamanho o intervalo vai de 4% a 33% — não dá para decidir nada com isso. Este script
gera um lote grande e mede.

Três camadas, da mais barata à mais cara:

  1. DESCARTE ESTRUTURAL — quantas o próprio pipeline já rejeita (_questao_utilizavel
     e, nas de cálculo, o PoT quando a conta não bate com nenhuma alternativa). Sai de
     graça: é só contar o que o gerador jogou fora.

  2. VERIFICAÇÃO INDEPENDENTE — um modelo DIFERENTE do gerador resolve cada questão
     SEM ver o gabarito e diz qual alternativa é a correta, ou que NENHUMA é. Onde ele
     discorda, há candidato a defeito. Modelo diferente de propósito: verificador da
     mesma família compartilha os mesmos vieses e concorda com o próprio erro.

  3. REVISÃO HUMANA — as divergências saem num arquivo para você conferir. O verificador
     também erra; divergência é suspeita, não veredito.

Uso (na raiz do projeto):
    python ml/medir_defeitos.py                     # 10 por matéria, 6 matérias
    python ml/medir_defeitos.py --n 20
    python ml/medir_defeitos.py --materias MAT,FIS  # só as de cálculo
    python ml/medir_defeitos.py --verificador gemini-3.6-flash

Saída em ml/artifacts/defeitos/:
    medicao_<ts>.json  — números + toda divergência, com enunciado e as duas respostas
    revisar_<ts>.txt   — só as divergências, em texto, para leitura humana
"""
import os
import sys
import json
import asyncio
import argparse
import textwrap
import time
from pathlib import Path
from datetime import datetime, timezone

import asyncpg
import requests
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

SAIDA = BASE / "artifacts" / "defeitos"
VERIFICADOR_PADRAO = "gemini-3.6-flash"     # mais forte que o gerador e fora da familia lite

BLOCOS = [
    ("MAT",  "Matemática", True),
    ("FIS",  "Física",     True),
    ("QUI",  "Química",    True),
    ("BIO",  "Biologia",   False),
    ("HIS",  "História",   False),
    ("GEO",  "Geografia",  False),
]

TEMAS = {
    "MAT": ["Progressões", "Funções do 1º grau", "Geometria plana", "Geometria espacial",
            "Probabilidade", "Análise combinatória", "Porcentagem e juros", "Estatística",
            "Trigonometria", "Razão e proporção"],
    "FIS": ["Cinemática", "Leis de Newton", "Trabalho e energia", "Eletricidade",
            "Termologia", "Ondulatória", "Hidrostática", "Óptica"],
    "QUI": ["Estequiometria", "Soluções", "Termoquímica", "Eletroquímica", "Cinética química"],
    "BIO": ["Genética", "Ecologia", "Citologia", "Evolução", "Corpo humano", "Botânica"],
    "HIS": ["Era Vargas", "Revolução Industrial", "Brasil Colônia", "Guerra Fria",
            "República Velha", "Idade Média"],
    "GEO": ["Urbanização", "Climatologia", "Geopolítica", "Recursos hídricos",
            "Agricultura", "Globalização"],
}

_PROMPT_VERIF = """Resolva esta questão de múltipla escolha do ensino médio brasileiro.

{questao}

Responda APENAS com um objeto JSON, sem mais nada:
{{"resposta": "A"|"B"|"C"|"D"|"E"|"NENHUMA", "problema": ""}}

- "resposta": a alternativa correta. Use "NENHUMA" se a resposta certa NÃO estiver entre
  as alternativas, ou se o enunciado não permitir chegar a uma resposta.
- "problema": vazio se está tudo bem. Se houver defeito, descreva em até 15 palavras
  (ex.: "enunciado não faz pergunta", "dados inconsistentes", "duas alternativas corretas",
  "afirmação factualmente errada").
Confira a conta/o conteúdo antes de responder."""


def _verificar(modelo, chave, enunciado, opts):
    """Resolve a questão num modelo DIFERENTE do gerador. Devolve (letra, problema)."""
    texto = enunciado + "\n\n" + "\n".join(
        f"{chr(65 + i)}) {o}" for i, o in enumerate(opts))
    url = ("https://generativelanguage.googleapis.com/v1beta/"
           f"models/{modelo}:generateContent?key={chave}")
    body = {"contents": [{"parts": [{"text": _PROMPT_VERIF.format(questao=texto)}]}]}
    # 503 "high demand" e frequente no tier gratuito; sem retry a medicao vira ruido
    # do provedor em vez de defeito do gerador.
    bruto = None
    for tentativa in range(4):
        try:
            r = requests.post(url, json=body, timeout=90).json()
            bruto = r["candidates"][0]["content"]["parts"][0]["text"]
            break
        except Exception:
            time.sleep(3 * (tentativa + 1))
    if bruto is None:
        return None, "(verificador indisponivel apos 4 tentativas)"
    try:
        t = bruto.strip()
        if "```" in t:
            t = t.split("```")[1].removeprefix("json").strip()
        d = json.loads(t[t.index("{"):t.rindex("}") + 1])
        return str(d.get("resposta", "")).strip().upper(), str(d.get("problema", "")).strip()
    except Exception:
        return None, "(resposta do verificador ilegível)"


async def medir(materia, nome, calc, n, app, conn, modelo, chave):
    """Gera n questões e confronta cada uma com o verificador."""
    temas = TEMAS[materia]
    brutas = descartadas = 0
    linhas = []
    for i in range(0, n, 5):                      # lotes de 5: menos chamadas, menos 429
        tema = temas[(i // 5) % len(temas)]
        nivel = 2 + ((i // 5) % 3)
        qs = None
        for _ in range(3):
            try:
                ex = await app._exemplos_similares(conn, materia, tema, nivel, calculo=calc)
                gen = app._gerar_calculo_pot if calc else app._gerar_no_gemini
                qs = await gen(min(5, n - i), materia, nome, tema, None, nivel, exemplos=ex)
                if qs:
                    break
            except Exception as e:
                print(f"    . retry {materia}/{tema}: {e}")
            await asyncio.sleep(4)
        pedidas = min(5, n - i)
        brutas += pedidas
        entregues = qs or []
        descartadas += max(0, pedidas - len(entregues))

        for q in entregues:
            opts = q.get("opts") or []
            gab = q.get("ans")
            letra_gab = chr(65 + gab) if isinstance(gab, int) and 0 <= gab < len(opts) else "?"
            resp, problema = await asyncio.to_thread(
                _verificar, modelo, chave, q.get("q", ""), opts)
            concorda = (resp == letra_gab)
            linhas.append({
                "materia": materia, "tema": tema, "nivel": nivel,
                "enunciado": q.get("q", ""), "opts": opts,
                "gabarito": letra_gab, "verificador": resp,
                "problema": problema, "concorda": concorda,
                "formula": q.get("formula_pot"),
            })
            marca = "ok" if concorda else ("sem verif." if resp is None else "DIVERGE")
            print(f"    {materia} {tema[:18]:<18} gab={letra_gab} verif={resp or '-'} "
                  f"{marca}{(' — ' + problema) if problema and resp else ''}")
    return brutas, descartadas, linhas


async def main(n, materias, modelo):
    url, chave = os.getenv("DATABASE_URL"), os.getenv("API_KEY")
    if not url or not chave:
        print("DATABASE_URL/API_KEY ausentes no Backend/.env — abortando.")
        return
    import app
    SAIDA.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    print(f"gerador: {app.GEMINI_MODEL}   verificador: {modelo}\n")

    tot_brutas = tot_desc = 0
    todas = []
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        for materia, nome, calc in BLOCOS:
            if materias and materia not in materias:
                continue
            print(f"[{nome}]")
            b, d, linhas = await medir(materia, nome, calc, n, app, conn, modelo, chave)
            tot_brutas += b
            tot_desc += d
            todas += linhas
            print()
    finally:
        await conn.close()

    verificadas = [l for l in todas if l["verificador"] is not None]
    diverg = [l for l in verificadas if not l["concorda"]]
    nenhuma = [l for l in diverg if l["verificador"] == "NENHUMA"]

    def pct(a, b):
        return f"{100 * a / b:.1f}%" if b else "—"

    resumo = {
        "gerador": app.GEMINI_MODEL, "verificador": modelo, "quando": ts,
        "pedidas": tot_brutas,
        "descartadas_pelo_pipeline": tot_desc,
        "entregues": len(todas),
        "verificadas": len(verificadas),
        "divergencias": len(diverg),
        "sem_alternativa_correta": len(nenhuma),
    }
    print("=" * 70)
    print(f"pedidas ao gerador ............. {tot_brutas}")
    print(f"descartadas pelo pipeline ...... {tot_desc}  ({pct(tot_desc, tot_brutas)})")
    print(f"entregues ...................... {len(todas)}")
    print(f"verificadas .................... {len(verificadas)}")
    print(f"DIVERGENCIAS ................... {len(diverg)}  ({pct(len(diverg), len(verificadas))})")
    print(f"  das quais 'NENHUMA correta' .. {len(nenhuma)}")
    print("=" * 70)
    print("divergência é SUSPEITA, não veredito — o verificador também erra.")
    print("por matéria:")
    for materia, nome, _ in BLOCOS:
        v = [l for l in verificadas if l["materia"] == materia]
        if v:
            dv = [l for l in v if not l["concorda"]]
            print(f"  {nome:<12} {len(dv):>2}/{len(v):<3} divergiram  ({pct(len(dv), len(v))})")

    (SAIDA / f"medicao_{ts}.json").write_text(
        json.dumps({"resumo": resumo, "itens": todas}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    rev = [f"DIVERGENCIAS — gerador {app.GEMINI_MODEL} x verificador {modelo}", ""]
    for l in diverg:
        rev += [f"[{l['materia']}] {l['tema']} (nivel {l['nivel']})", ""]
        rev += textwrap.wrap(l["enunciado"], 78)
        rev += [""]
        rev += [f"  {chr(65 + i)}) {o}" for i, o in enumerate(l["opts"])]
        rev += ["", f"  gabarito do gerador: {l['gabarito']}",
                f"  verificador respondeu: {l['verificador']}"]
        if l["problema"]:
            rev.append(f"  problema apontado: {l['problema']}")
        if l["formula"]:
            rev.append(f"  formula do PoT: {l['formula']}")
        rev += ["", "-" * 78, ""]
    (SAIDA / f"revisar_{ts}.txt").write_text("\n".join(rev), encoding="utf-8")
    print(f"\nmedicao_{ts}.json e revisar_{ts}.txt salvos em ml/artifacts/defeitos/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="questões por matéria")
    ap.add_argument("--materias", default=None, help="só estas (ex.: MAT,FIS)")
    ap.add_argument("--verificador", default=VERIFICADOR_PADRAO)
    a = ap.parse_args()
    alvo = {m.strip().upper() for m in a.materias.split(",")} if a.materias else None
    asyncio.run(main(a.n, alvo, a.verificador))
