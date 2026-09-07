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
    python ml/teste_impostor.py                 # 5 por bloco (MAT, BIO, HIS)
    python ml/teste_impostor.py --n 8
    python ml/teste_impostor.py --modelo gemini-3.1-flash-lite

Saída em ml/artifacts/impostor/:
    teste_<materia>.txt    — o que circula: manda por mensagem, imprime, responde na hora
    teste_<materia>.html   — mesma coisa em página (soma as respostas sozinho)
    gabarito_<ts>.json     — quem é quem. NÃO abra antes de coletar as respostas.
"""
import os
import sys
import json
import random
import asyncio
import argparse
import html as _html
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
    ("MAT",      "MAT", "Matemática"),
    ("NATUREZA", "BIO", "Biologia"),
    ("HUMANAS",  "HIS", "História"),
]

TEMAS = {
    "MAT": ["Progressões", "Funções do 1º grau", "Geometria plana", "Porcentagem", "Estatística"],
    "BIO": ["Genética", "Ecologia", "Citologia", "Evolução", "Corpo humano"],
    "HIS": ["Era Vargas", "Revolução Industrial", "Brasil Colônia", "Guerra Fria", "República Velha"],
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
# Formato principal: e o que se manda por WhatsApp, imprime e o professor responde
# na hora. O HTML e conveniencia (soma as respostas sozinho); o .txt e o que circula.
def montar_texto(nome, itens):
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
    return "\n".join(fora)


# ==== PÁGINA ====
def montar_html(titulo, itens):
    """Página autoexplicativa: só enunciado e alternativas, com as duas perguntas."""
    linhas = []
    for i, q in enumerate(itens, 1):
        alts = "".join(
            f"<li>{_html.escape(str(a))}</li>" for a in (q["alternativas"] or []))
        linhas.append(f"""
  <article>
    <h2>Questão {i}</h2>
    <p class="enun">{_html.escape(q["enunciado"])}</p>
    <ol type="A">{alts}</ol>
    <div class="perg">
      <label><b>1. Esta questão é:</b>
        <select data-q="{i}" class="voto">
          <option value="">—</option>
          <option value="real">de prova/vestibular</option>
          <option value="gerada">gerada por IA</option>
        </select>
      </label>
      <label><b>2. O que te fez decidir?</b>
        <input type="text" data-q="{i}" class="motivo" placeholder="uma linha basta">
      </label>
    </div>
  </article>""")

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(titulo)}</title>
<style>
  :root {{ --marfim:#f4ecdd; --card:#fbf6ec; --tinta:#2b2a26; --profundo:#1a2b4c; --kinrou:#f3d009; }}
  body {{ background:var(--marfim); color:var(--tinta); font:16px/1.6 Georgia, serif;
          margin:0; padding:32px 20px; }}
  main {{ max-width:760px; margin:0 auto; }}
  h1 {{ color:var(--profundo); font-size:1.5rem; }}
  .intro {{ background:var(--card); border-left:3px solid var(--kinrou);
            padding:16px 20px; border-radius:6px; }}
  article {{ background:var(--card); border-radius:8px; padding:20px 24px; margin:22px 0; }}
  h2 {{ color:var(--profundo); font-size:1.05rem; margin:0 0 10px; }}
  .enun {{ margin:0 0 12px; white-space:pre-wrap; }}
  ol {{ margin:0 0 16px; padding-left:26px; }}
  li {{ margin:4px 0; }}
  .perg {{ border-top:1px solid #e4dcc9; padding-top:14px; display:grid; gap:10px; }}
  label {{ display:block; font-size:.92rem; }}
  select, input {{ font:inherit; padding:6px 8px; margin-top:4px;
                   border:1px solid #cfc6b2; border-radius:5px; background:#fff; }}
  input {{ width:100%; box-sizing:border-box; }}
  button {{ font:inherit; padding:10px 18px; border:0; border-radius:6px;
            background:var(--profundo); color:var(--card); cursor:pointer; }}
  #saida {{ width:100%; height:150px; margin-top:12px; font:13px monospace;
            display:none; box-sizing:border-box; }}
</style></head><body><main>
<h1>{_html.escape(titulo)}</h1>
<div class="intro">
  <p>Abaixo há questões de duas origens misturadas: algumas vieram de provas reais de
  vestibular/ENEM, outras foram escritas por um sistema automático. <b>Não dizemos
  quantas são de cada.</b></p>
  <p>Para cada uma, diga de onde você acha que ela veio — e, mais importante,
  <b>o que te fez decidir</b>. Não precisa resolver a questão; o que interessa é se ela
  parece uma questão de prova.</p>
  <p>Ao final, clique no botão e envie o texto que aparecer.</p>
</div>
{''.join(linhas)}
<button onclick="montar()">Gerar minhas respostas</button>
<textarea id="saida" readonly></textarea>
<script>
function montar() {{
  const linhas = [];
  document.querySelectorAll('.voto').forEach(s => {{
    const i = s.dataset.q;
    const m = document.querySelector('.motivo[data-q="' + i + '"]').value.trim();
    linhas.push(i + ';' + (s.value || 'sem resposta') + ';' + m.replace(/;/g, ','));
  }});
  const t = document.getElementById('saida');
  t.value = linhas.join('\\n');
  t.style.display = 'block';
  t.select();
}}
</script>
</main></body></html>"""


# ==== MAIN ====
async def main(n, modelo):
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
    gabarito = {"modelo": app.GEMINI_MODEL, "gerado_em": ts, "blocos": {}}

    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        for area, materia, nome in BLOCOS:
            print(f"[{nome}]")
            g = await gerar(conn, materia, nome, n, app)
            r = await reais(conn, materia, area, n)
            if not g or not r:
                print(f"  ! bloco {nome} incompleto (geradas={len(g)}, reais={len(r)}) — pulando\n")
                continue
            itens = g + r
            rng.shuffle(itens)

            arq = SAIDA / f"teste_{materia.lower()}.txt"
            arq.write_text(montar_texto(nome, itens), encoding="utf-8")
            (SAIDA / f"teste_{materia.lower()}.html").write_text(
                montar_html(f"Avaliação de questões — {nome}", itens), encoding="utf-8")
            gabarito["blocos"][materia] = [
                {"n": i, "origem": q["origem"], "tema": q["tema"], "nivel": q["nivel"]}
                for i, q in enumerate(itens, 1)]
            print(f"  -> {arq.name} ({len(g)} geradas + {len(r)} reais)\n")
    finally:
        await conn.close()

    if gabarito["blocos"]:
        gab = SAIDA / f"gabarito_{ts}.json"
        gab.write_text(json.dumps(gabarito, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"gabarito: {gab.name}  (não abra antes de coletar as respostas)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="geradas por bloco (e o mesmo tanto de reais)")
    ap.add_argument("--modelo", default=None, help="sobrescreve GEMINI_MODEL só nesta execução")
    a = ap.parse_args()
    asyncio.run(main(a.n, a.modelo))
