# -*- coding: utf-8 -*-
"""
Gera questões em lote direto no cache, pelo mesmo caminho da produção — para repor
aposentadas (regras antigas do prompt) ou encher o cache antes de um beta (sem geração ao vivo).

GENÉRICAS por padrão (hobbie NULL): questão com hobbie só serve a quem tem o hobbie e
fragmenta cache pequeno; o serving tenta com hobbie e cai para a genérica. Verifica em
lote logo após gerar (não deixa pro job), para o lote nascer com veredito e fora da quarentena.

Uso (na raiz do projeto):
    python -u ml/gerar_lote.py --repor-calculo        # repõe MAT/FIS/QUI aposentadas
    python -u ml/gerar_lote.py --materia BIO --n 10
    python -u ml/gerar_lote.py --materia MAT --temas "Progressões,Trigonometria" --n 5
    python -u ml/gerar_lote.py --repor-calculo --sem-verificar

Use SEMPRE `python -u`: sem isso a saída fica em buffer e uma interrupção perde tudo.
"""
import os
import sys
import json
import asyncio
import argparse
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

CALCULO = ("MAT", "FIS", "QUI")

# Reposição do que foi aposentado, cobrindo os mesmos temas com mais variedade.
REPOR_CALCULO = {
    "MAT": ["Álgebra", "Geometria", "Probabilidade", "Progressões", "Porcentagem e juros"],
    "FIS": ["Óptica Geométrica", "Cinemática", "Leis de Newton", "Trabalho e energia"],
    "QUI": ["Soluções", "Estequiometria", "Termoquímica"],
}
# A rodada serve niveis 1..5 (centro do aluno +/-2, ver sortearDistribuicao no front).
# Gerar so 1..3 deixava metade da regua sem cache: o aluno que sobe de nivel cai
# direto em geracao ao vivo.
NIVEIS_PADRAO = [1, 2, 3, 4, 5]

# Todos os temas por materia — permite `--materia BIO` sem listar tema a tema.
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
    "PORT": ["Interpretação de texto", "Figuras de linguagem", "Variação linguística",
             "Funções da linguagem", "Gêneros textuais"],
}


async def gerar_um(app, conn, materia, nome, tema, nivel, n):
    """Gera n questões genéricas de um tema/nível e devolve as que passaram."""
    calc = materia in CALCULO
    for tentativa in range(3):
        try:
            ex = await app._exemplos_similares(conn, materia, tema, nivel, calculo=calc)
            gen = app._gerar_calculo_pot if calc else app._gerar_no_gemini
            qs = await gen(n, materia, nome, tema, None, nivel, exemplos=ex)
            if qs:
                return qs
        except Exception as e:
            print(f"    . tentativa {tentativa + 1} falhou: {e}")
        await asyncio.sleep(5)
    return []


async def salvar(conn, app, materia, tema, nivel, questoes):
    """Grava com proveniência (modelo + versão do prompt) e devolve os ids."""
    ids = []
    for q in questoes:
        item = app._frontend_q(q)
        try:
            qid = await conn.fetchval(
                """insert into questoes_cache
                     (materia, tema, nivel, hobbie, enunciado, alternativas,
                      resposta_correta, explicacao, porque_erradas, modelo, versao_prompt)
                   values ($1, $2, $3, null, $4, $5::jsonb, $6, $7, $8::jsonb, $9, $10)
                   returning questao_id""",
                materia, tema, nivel, item["q"], json.dumps(item["opts"], ensure_ascii=False),
                item["ans"], item["explicacao"],
                json.dumps(item["porque_erradas"], ensure_ascii=False),
                app.GEMINI_MODEL, app.VERSAO_PROMPT)
            ids.append((qid, item["q"], item["opts"], item["ans"]))
        except Exception as e:
            print(f"    ! falha ao salvar: {e}")
    return ids


async def verificar(conn, app, gravadas):
    """Verifica em lote e grava o veredito. Devolve (ok, suspeitas, sem_resposta)."""
    ok = susp = sem = 0
    for ini in range(0, len(gravadas), app.VERIF_LOTE):
        bloco = gravadas[ini:ini + app.VERIF_LOTE]
        res = None
        for _ in range(4):
            res = await asyncio.to_thread(
                app.verificar_lote, [(g[1], g[2]) for g in bloco])
            if any(i is not None for i, _ in res):
                break
            await asyncio.sleep(6)
        for (qid, enun, opts, gab), (idx, nota) in zip(bloco, res or []):
            if idx is None:
                sem += 1
                continue
            veredito = "ok" if idx == gab else "suspeita"
            if veredito == "ok":
                ok += 1
            else:
                susp += 1
                alvo = "NENHUMA correta" if idx == -1 else f"apontou {chr(65 + idx)}"
                print(f"    SUSPEITA ({alvo}) gab={chr(65 + gab)} — {enun[:50]}")
            await conn.execute(
                "update questoes_cache set veredito = $2, verificada_em = now(), "
                "verificador_disse = $3, verificador_nota = $4 where questao_id = $1",
                qid, veredito, idx, nota or None)
    return ok, susp, sem


async def main(alvos, n, verificar_depois, pular_prontas=False):
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return
    import app
    print(f"gerador: {app.GEMINI_MODEL}  prompt: {app.VERSAO_PROMPT}  "
          f"verificador: {app.MODELO_VERIFICADOR}\n")

    conn = await asyncpg.connect(url, statement_cache_size=0)
    tot_ok = tot_susp = tot_sem = tot_ger = 0
    try:
        for materia, temas in alvos.items():
            nome = app.MATERIAS.get(materia, materia)
            print(f"[{nome}]")
            for tema in temas:
                for nivel in NIVEIS_PADRAO:
                    if pular_prontas:
                        # Retomada: uma execucao interrompida (cota, rede) nao deve
                        # regerar o que ja entrou. Conta pela versao do prompt em uso.
                        ja = await conn.fetchval(
                            "select count(*) from questoes_cache where materia = $1 "
                            "and tema = $2 and nivel = $3 and versao_prompt = $4",
                            materia, tema, nivel, app.VERSAO_PROMPT)
                        if ja >= n:
                            print(f"  {tema[:22]:<22} nível {nivel}: já tem {ja} — pulando")
                            continue
                    qs = await gerar_um(app, conn, materia, nome, tema, nivel, n)
                    if not qs:
                        print(f"  {tema[:22]:<22} nível {nivel}: nenhuma")
                        continue
                    gravadas = await salvar(conn, app, materia, tema, nivel, qs)
                    tot_ger += len(gravadas)
                    print(f"  {tema[:22]:<22} nível {nivel}: {len(gravadas)} gravadas")
                    if verificar_depois and gravadas:
                        o, s, x = await verificar(conn, app, gravadas)
                        tot_ok += o
                        tot_susp += s
                        tot_sem += x
            print()
        print("=" * 62)
        print(f"geradas e gravadas ..... {tot_ger}")
        if verificar_depois:
            print(f"  aprovadas ............ {tot_ok}")
            print(f"  suspeitas ............ {tot_susp}")
            print(f"  sem resposta ......... {tot_sem}  (o job verifica depois)")
        servivel = await conn.fetchval(
            "select count(*) from questoes_cache where veredito is distinct from 'suspeita'")
        print(f"cache servível ......... {servivel}")
        print("=" * 62)
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repor-calculo", action="store_true",
                    help="repõe MAT/FIS/QUI (as aposentadas por serem pré-v3)")
    ap.add_argument("--materia", default=None, help="uma matéria (ex.: BIO)")
    ap.add_argument("--temas", default=None, help="lista separada por vírgula")
    ap.add_argument("--n", type=int, default=5, help="questões por tema/nível")
    ap.add_argument("--sem-verificar", action="store_true",
                    help="não verifica agora (o job do backend verifica depois)")
    ap.add_argument("--niveis", default=None,
                    help="níveis a gerar (ex.: '1,2,3'). Padrão: 1..5")
    ap.add_argument("--pular-prontas", action="store_true",
                    help="pula tema/nível que já tem n questões na versão de prompt atual")
    a = ap.parse_args()

    if a.repor_calculo:
        alvos = REPOR_CALCULO
    elif a.materia:
        m = a.materia.upper()
        if a.temas:
            alvos = {m: [t.strip() for t in a.temas.split(",") if t.strip()]}
        elif m in TEMAS:
            alvos = {m: TEMAS[m]}                     # sem --temas: cobre a matéria inteira
        else:
            print(f"--materia {m} desconhecida; use --temas")
            sys.exit(1)
    else:
        print("use --repor-calculo ou --materia X --temas 'a,b'")
        sys.exit(1)
    if a.niveis:
        NIVEIS_PADRAO = [int(x) for x in a.niveis.split(",") if x.strip()]
    asyncio.run(main(alvos, a.n, not a.sem_verificar, a.pular_prontas))
