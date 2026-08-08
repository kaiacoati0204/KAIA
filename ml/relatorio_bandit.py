# -*- coding: utf-8 -*-
"""
Relatório do bandit (Thompson) — análogo da avaliar.py, mas pro lado das
INTERVENÇÕES. Lê o que já disparou (tabela `interventions`) e mostra, por braço:
quantas dispararam, quantas têm reward, o reward médio, e a estimativa do bandit
(α/β de thompson_params.json → taxa de sucesso que ele acredita).

Fica PRONTO pra quando as intervenções reais começarem — hoje mostra vazio/zero.
Offline. Precisa de DATABASE_URL (Backend/.env). Rodar na raiz:
    python ml/relatorio_bandit.py
"""
import os
import sys
import json
import asyncio
from pathlib import Path

from dotenv import load_dotenv
import asyncpg

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "Backend"))
load_dotenv(BASE.parent / "Backend" / ".env")

from thompson import INTERVENCOES, PARAMS_PATH  # noqa: E402


async def _carregar_disparos():
    """Agrega a tabela interventions por tipo (n, n com reward, reward médio)."""
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL não definida no Backend/.env — abortando.")
        return None
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        rows = await conn.fetch(
            """
            select intervention_type,
                   count(*)      as n,
                   count(reward) as n_reward,
                   avg(reward)   as reward_medio
              from interventions
             group by intervention_type
            """
        )
    except Exception as e:
        print("tabela interventions indisponível:", e)
        return None
    finally:
        await conn.close()
    return {r["intervention_type"]: dict(r) for r in rows}


def _params_bandit():
    """α/β persistidos do Thompson (thompson_params.json)."""
    try:
        return json.loads(Path(PARAMS_PATH).read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    dados = asyncio.run(_carregar_disparos())
    if dados is None:
        return
    params = _params_bandit()
    total = sum((d.get("n") or 0) for d in dados.values())

    print(f"\n== Relatório do bandit — {total} intervenções disparadas ==")
    if not total:
        print("Nenhuma intervenção ainda. Fica pronto — rode depois de coletar.")

    print(f"\n{'braço':<22}{'disparos':>9}{'c/ reward':>10}{'reward méd':>12}{'α/β':>12}{'estim.':>8}")
    for arm in INTERVENCOES:
        d = dados.get(arm, {})
        n = d.get("n") or 0
        nr = d.get("n_reward") or 0
        rm = d.get("reward_medio")
        p = params.get(arm, {})
        a, b = float(p.get("alpha", 1.0)), float(p.get("beta", 1.0))
        estim = a / (a + b)
        rm_s = f"{rm:.2f}" if rm is not None else "—"
        print(f"{arm:<22}{n:>9}{nr:>10}{rm_s:>12}{f'{a:.1f}/{b:.1f}':>12}{estim:>8.2f}")

    # Proxy de "o bandit bate o aleatório?": reward médio ponderado pelas ESCOLHAS
    # dele vs. média simples dos braços (o que o uniforme renderia). Bandit > uniforme
    # = ele está escolhendo os braços bons mais vezes. (Proxy honesto, não regret exato.)
    real = {arm: d for arm, d in dados.items() if arm in INTERVENCOES}   # exclui controle_ab
    com_reward = [(d["reward_medio"], d.get("n_reward") or 0)
                  for d in real.values() if d.get("reward_medio") is not None]
    bandit_med = None
    if com_reward:
        somaw = sum(rm * nr for rm, nr in com_reward)
        totnr = sum(nr for _, nr in com_reward)
        bandit_med = somaw / totnr if totnr else 0.0
        uniforme_med = sum(rm for rm, _ in com_reward) / len(com_reward)
        print(f"\nreward médio do bandit (pelas escolhas): {bandit_med:.3f}")
        print(f"reward médio se escolhesse UNIFORME:      {uniforme_med:.3f}")
        print(f"ganho sobre o aleatório: {bandit_med - uniforme_med:+.3f}  "
              f"({'bandit à frente' if bandit_med >= uniforme_med else 'atrás — revisar'})")

    # A/B test: se houve grupo CONTROLE (controle_ab), compara intervir vs. não intervir.
    ctrl = dados.get("controle_ab")
    if ctrl and ctrl.get("reward_medio") is not None and bandit_med is not None:
        cm = ctrl["reward_medio"]
        print(f"\n[A/B] reward COM intervenção (bandit):  {bandit_med:.3f}")
        print(f"[A/B] reward SEM intervenção (controle): {cm:.3f}  (n={ctrl.get('n_reward') or 0})")
        print(f"[A/B] efeito das intervenções: {bandit_med - cm:+.3f}  "
              f"({'ajudam' if bandit_med > cm else 'não provaram valor ainda'})")

    print("\nestim. = taxa de sucesso que o bandit acredita, α/(α+β) — começa em 0.50.")
    print("reward: 1.0 re-focou · 0.5 melhorou · 0.2 ficou igual · 0.0 piorou.")


if __name__ == "__main__":
    main()
