"""
Benchmark de latência do GET /diagnose contra o Supabase real (Sprint 4, Tarefa 2).

Cria uma sessão de teste, injeta eventos sintéticos, espera o scheduler (35s),
mede 20 chamadas ao /diagnose e imprime min/média/mediana/p95/máx (ms). Ao fim,
encerra a sessão e LIMPA os dados de teste do banco (não deixa resíduo).

Requer o servidor no ar: cd Backend && uvicorn app:app --port 5000
Uso: python tests/benchmark_latencia.py
"""
import asyncio
import os
import statistics
import time
import uuid

import asyncpg
import numpy as np
import requests
from dotenv import load_dotenv

load_dotenv("Backend/.env")
BASE = "http://127.0.0.1:5000"
DB = os.getenv("DATABASE_URL")

# >= 10 eventos cobrindo os 5 tipos (+ session_start).
EVENTOS = [
    ("session_start", {"features": {"sessoes_no_dia": 2}}),
    ("tab_change", {"tempo_fora_foco_s": 12.0}),
    ("tab_change", {"tempo_fora_foco_s": 8.0}),
    ("click_outside", {"x": 10, "y": 20}),
    ("click_outside", {"x": 30, "y": 40}),
    ("scroll_burst", {"px_s": 800.0, "duracao_s": 0.5}),
    ("scroll_burst", {"px_s": 1200.0, "duracao_s": 0.3}),
    ("keystroke_pause", {"duracao_s": 5.0}),
    ("keystroke_pause", {"duracao_s": 4.0}),
    ("question_answer", {"acertou": False, "tempo_resposta_ms": 8000}),
    ("question_answer", {"acertou": True, "tempo_resposta_ms": 5000}),
]


async def limpar(sid):
    """Remove a sessão de teste e tudo que pende dela (ordem FK-safe)."""
    conn = await asyncpg.connect(DB, statement_cache_size=0, timeout=15)
    try:
        for t in ("interventions", "session_features", "session_events", "sessions"):
            await conn.execute(f"delete from {t} where session_id = $1::uuid", sid)
    finally:
        await conn.close()


def main():
    sid = requests.post(f"{BASE}/sessions", json={"user_id": str(uuid.uuid4())}).json()["session_id"]
    print("sessão de teste:", sid)

    for et, payload in EVENTOS:
        requests.post(f"{BASE}/events", json={"session_id": sid, "event_type": et, "payload": payload})
    print(f"{len(EVENTOS)} eventos inseridos; aguardando 35s o scheduler rodar...")
    time.sleep(35)

    tempos = []
    for _ in range(20):
        t0 = time.perf_counter()
        r = requests.get(f"{BASE}/diagnose", params={"session_id": sid})
        tempos.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200, r.text

    print("\n=== LATÊNCIA /diagnose (20 chamadas, ms) ===")
    print(f"  min     = {min(tempos):.1f}")
    print(f"  média   = {statistics.mean(tempos):.1f}")
    print(f"  mediana = {statistics.median(tempos):.1f}")
    print(f"  p95     = {float(np.percentile(tempos, 95)):.1f}")
    print(f"  máximo  = {max(tempos):.1f}")

    requests.post(f"{BASE}/sessions/{sid}/end")   # rota real é POST (não PATCH)
    asyncio.run(limpar(sid))
    print("\nsessão de teste encerrada e limpa do banco.")


if __name__ == "__main__":
    main()
