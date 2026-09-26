# -*- coding: utf-8 -*-
"""Compara LLMs nas tarefas que a KaIA realmente faz, com gabarito objetivo.

Não é benchmark de internet: usa 131 questões do ENEM 2023 com o gabarito OFICIAL do
INEP e o parâmetro de dificuldade `b` da TRI, medido na resposta de milhões de alunos.

Três provas, porque o verificador precisa de duas competências que não são a mesma:

  1. RESOLVER      acerta questão de vestibular em português?
  2. AUDITAR       recebe questão + gabarito e diz se o gabarito está certo. Metade
                   vem com o gabarito ADULTERADO de propósito. É a tarefa real do
                   verificador, e o que importa aqui não é só pegar o erro: acusar
                   questão boa joga fora conteúdo que custou para gerar.
  3. DIFICULDADE   ordena questões da mais fácil para a mais difícil; compara com o
                   `b` real. Serve para calibrar o nível que o gerador recebe.

Uso (na raiz do projeto):
    python -u ml/comparar_llms.py --chaves .chaves.env --base ml/artifacts/base_b_2023.json
    python -u ml/comparar_llms.py --so-auditar          # a prova que mais importa
"""
import os
import re
import sys
import json
import time
import math
import random
import argparse
import requests
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
random.seed(17)

N_RESOLVER = 30
N_AUDITAR = 40          # metade com gabarito trocado
N_DIFICULDADE = 40      # em lotes de 8
LOTE = 10
# Groq free: 8.000 TOKENS/minuto (o teto de 1.000 requisicoes/dia nem chega perto).
# Um lote de 10 questoes do ENEM passa de 3.000 tokens, entao duas chamadas seguidas
# estouram -- foi assim que o gpt-oss-120b respondeu so 10 de 40 na primeira rodada.
LOTE_LENTO = 5
PAUSA_TPM = {"groq": 30, "mistral": 3, "gemini": 0}

# (rotulo, provedor, modelo). Gemini entra como linha de base: e o que roda hoje.
MODELOS = [
    ("gemini-3.5-flash-lite (gerador hoje)", "gemini", "gemini-3.5-flash-lite"),
    ("gemini-3.6-flash (verificador hoje)",  "gemini", "gemini-3.6-flash"),
    ("groq gpt-oss-120b",                    "groq",   "openai/gpt-oss-120b"),
    ("groq gpt-oss-20b",                     "groq",   "openai/gpt-oss-20b"),
    ("groq qwen3.8-27b",                     "groq",   "qwen/qwen3.8-27b"),
    ("mistral ministral-8b",                 "mistral", "ministral-8b-latest"),
    ("mistral nemo",                         "mistral", "open-mistral-nemo"),
]

URLS = {"groq": "https://api.groq.com/openai/v1/chat/completions",
        "mistral": "https://api.mistral.ai/v1/chat/completions"}
CHAVES = {"groq": "GROQ_API_KEY", "mistral": "MISTRAL_API_KEY"}


def chamar(provedor, modelo, prompt, tentativas=4):
    """Devolve (texto, segundos). Texto vazio = falhou."""
    ini = time.time()
    time.sleep(PAUSA_TPM.get(provedor, 0))   # respeita o teto por minuto
    for t in range(tentativas):
        try:
            if provedor == "gemini":
                r = requests.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{modelo}:generateContent",
                    params={"key": os.environ["API_KEY"]}, timeout=180,
                    json={"contents": [{"parts": [{"text": prompt}]}]})
                if r.status_code == 200:
                    c = r.json().get("candidates")
                    if c:
                        return c[0]["content"]["parts"][0]["text"], time.time() - ini
            else:
                r = requests.post(
                    URLS[provedor], timeout=180,
                    headers={"Authorization": f"Bearer {os.environ[CHAVES[provedor]]}"},
                    json={"model": modelo, "max_tokens": 2500, "temperature": 0,
                          "messages": [{"role": "user", "content": prompt}]})
                if r.status_code == 200:
                    return (r.json()["choices"][0]["message"].get("content") or "",
                            time.time() - ini)
            if r.status_code in (429, 503):
                espera = float(r.headers.get("retry-after") or 0) or 20 * (t + 1)
                time.sleep(min(espera, 70))
                continue
            return "", time.time() - ini
        except Exception:
            time.sleep(4 * (t + 1))
    return "", time.time() - ini


def extrair(texto):
    m = re.search(r"\[.*\]", texto or "", re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return []


def fmt(q, i):
    return (f"{i}. {q['enunciado'][:900]}\n"
            + "\n".join(f"{chr(65+j)}) {a[:160]}" for j, a in enumerate(q["alternativas"])))


# ------------------------------------------------------------------ 1. resolver
def prova_resolver(prov, mod, questoes):
    acertos = certas = 0
    for ini in range(0, len(questoes), LOTE):
        bloco = questoes[ini:ini + LOTE]
        itens = "\n\n".join(fmt(q, i + 1) for i, q in enumerate(bloco))
        txt, _ = chamar(prov, mod,
            "Resolva cada questão de vestibular brasileiro abaixo.\n\n"
            f"{itens}\n\n"
            'Responda APENAS o ARRAY JSON: [{"n": 1, "resposta": "A"}]')
        for o in extrair(txt):
            try:
                i = int(o.get("n", 0)) - 1
            except (TypeError, ValueError):
                continue
            letra = str(o.get("resposta", "")).strip().upper()[:1]
            if 0 <= i < len(bloco) and letra:
                certas += 1
                acertos += letra == bloco[i]["gabarito"]
    return acertos, certas


# ------------------------------------------------------------------ 2. auditar
def prova_auditar(prov, mod, itens_audit):
    """itens_audit: [(questao, gabarito_mostrado, esta_certo)]"""
    vp = vn = fp = fn = respondidas = 0
    passo = LOTE_LENTO if prov != "gemini" else LOTE
    for ini in range(0, len(itens_audit), passo):
        bloco = itens_audit[ini:ini + passo]
        itens = "\n\n".join(
            fmt(q, i + 1) + f"\nGabarito informado: {g}"
            for i, (q, g, _) in enumerate(bloco))
        txt, _ = chamar(prov, mod,
            "Abaixo há questões de vestibular com o gabarito que alguém informou.\n"
            "Resolva cada uma por conta própria e diga se o gabarito informado está\n"
            "CERTO ou ERRADO. Alguns estão errados de propósito.\n\n"
            f"{itens}\n\n"
            'Responda APENAS o ARRAY JSON: [{"n": 1, "gabarito_correto": true}]')
        for o in extrair(txt):
            try:
                i = int(o.get("n", 0)) - 1
            except (TypeError, ValueError):
                continue
            v = o.get("gabarito_correto")
            if not (0 <= i < len(bloco)) or not isinstance(v, bool):
                continue
            respondidas += 1
            era_certo = bloco[i][2]
            if era_certo and v:
                vn += 1                      # gabarito bom, aprovado: certo
            elif era_certo and not v:
                fp += 1                      # ACUSOU questao boa -> perda de conteudo
            elif not era_certo and not v:
                vp += 1                      # pegou o gabarito trocado
            else:
                fn += 1                      # deixou passar o erro
    return {"vp": vp, "vn": vn, "fp": fp, "fn": fn, "n": respondidas}


# ------------------------------------------------------------------ 3. dificuldade
def postos(xs):
    ordem = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(ordem):
        j = i
        while j + 1 < len(ordem) and xs[ordem[j + 1]] == xs[ordem[i]]:
            j += 1
        for k in range(i, j + 1):
            r[ordem[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = postos(a), postos(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return num / (da * db) if da and db else 0.0


def prova_dificuldade(prov, mod, questoes, tam=8):
    rhos = []
    for ini in range(0, len(questoes) - tam + 1, tam):
        bloco = questoes[ini:ini + tam]
        itens = "\n\n".join(fmt(q, i + 1) for i, q in enumerate(bloco))
        txt, _ = chamar(prov, mod,
            f"ORDENE as {len(bloco)} questões da MAIS FÁCIL para a MAIS DIFÍCIL, pensando\n"
            "em que porcentagem dos alunos de ensino médio acertaria cada uma.\n\n"
            f"{itens}\n\n"
            "Responda APENAS o ARRAY JSON com os números na ordem, ex: [3,1,5,2,4,8,6,7]")
        ordem = [int(x) for x in extrair(txt)
                 if isinstance(x, (int, float)) or str(x).strip().isdigit()]
        ordem = [x for x in ordem if 1 <= x <= len(bloco)]
        if len(set(ordem)) != len(bloco):
            continue
        pos = {n - 1: p for p, n in enumerate(ordem)}
        rhos.append(spearman([pos[i] for i in range(len(bloco))],
                             [q["b"] for q in bloco]))
    return sum(rhos) / len(rhos) if rhos else None


def main(a):
    for ln in Path(a.chaves).read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    for ln in (BASE.parent / "Backend" / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    random.shuffle(base)
    resolver = base[:N_RESOLVER]
    dificil = base[:N_DIFICULDADE]

    # metade com gabarito trocado, embaralhado para nao ficar tudo junto
    audit = []
    for k, q in enumerate(base[:N_AUDITAR]):
        if k % 2 == 0:
            audit.append((q, q["gabarito"], True))
        else:
            outras = [chr(65 + j) for j in range(len(q["alternativas"]))
                      if chr(65 + j) != q["gabarito"]]
            audit.append((q, random.choice(outras), False))
    random.shuffle(audit)

    print(f"base: ENEM 2023, gabarito oficial do INEP")
    print(f"  resolver {len(resolver)} · auditar {len(audit)} "
          f"({sum(1 for x in audit if not x[2])} adulteradas) · "
          f"dificuldade {len(dificil)}\n")

    linhas = []
    for rotulo, prov, mod in MODELOS:
        print(f"  {rotulo} ...", end="", flush=True)
        t0 = time.time()
        r = {"rotulo": rotulo}
        if not a.so_auditar:
            ac, n = prova_resolver(prov, mod, resolver)
            r["resolver"] = (ac, n)
        au = prova_auditar(prov, mod, audit)
        r["auditar"] = au
        if not a.so_auditar:
            r["dificuldade"] = prova_dificuldade(prov, mod, dificil)
        r["segundos"] = time.time() - t0
        linhas.append(r)
        print(f" {r['segundos']:.0f}s")

    print(f"\n{'='*78}")
    print(f"{'modelo':<38}{'resolve':>9}{'pega erro':>11}{'poupa boa':>11}{'dific.':>9}")
    print("=" * 78)
    for r in linhas:
        au = r["auditar"]
        res = "—"
        if r.get("resolver") and r["resolver"][1]:
            res = f"{100*r['resolver'][0]/r['resolver'][1]:.0f}%"
        # recall: dos gabaritos trocados, quantos pegou
        rec = f"{100*au['vp']/(au['vp']+au['fn']):.0f}%" if (au["vp"] + au["fn"]) else "—"
        # especificidade: das questoes BOAS, quantas NAO acusou
        esp = f"{100*au['vn']/(au['vn']+au['fp']):.0f}%" if (au["vn"] + au["fp"]) else "—"
        dif = (f"{r['dificuldade']:+.2f}" if r.get("dificuldade") is not None else "—")
        print(f"{r['rotulo']:<38}{res:>9}{rec:>11}{esp:>11}{dif:>9}")
    print("=" * 78)
    print("  resolve   = acertou a questão (gabarito oficial)")
    print("  pega erro = dos gabaritos ADULTERADOS, quantos identificou  (recall)")
    print("  poupa boa = das questões BOAS, quantas NÃO acusou à toa     (especificidade)")
    print("  dific.    = correlação da ordem prevista com o b real da TRI")
    saida = BASE / "artifacts" / "comparar_llms.json"
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(linhas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\ndetalhe em {saida}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chaves", default=".chaves.env")
    ap.add_argument("--base", default="ml/artifacts/base_b_2023.json")
    ap.add_argument("--so-auditar", action="store_true")
    main(ap.parse_args())
