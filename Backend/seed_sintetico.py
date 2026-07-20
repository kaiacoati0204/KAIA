# ============================================================
#  KaIA — seed de sessões SINTÉTICAS para o dashboard interno
# ============================================================
# Objetivo: dar volume/variedade para AVALIAR VISUALMENTE os gráficos (com 34
# sessões em 2 dias não dá). NÃO é dado real.
#
# Marcação: sessions.app_version = 'seed-sintetico'  (apagável via limpar_sintetico.sql).
# Vínculo:  apenas às contas @aluno.sintetico.kaia já existentes (não cria usuários).
#
# Uso:
#   python seed_sintetico.py            # DRY-RUN: só mostra o resumo, não grava
#   python seed_sintetico.py --commit   # grava de verdade
#
# Re-rodar com --commit INSERE de novo (soma). Para zerar, rode limpar_sintetico.sql.

import asyncio, re, sys, json, random
from datetime import datetime, timedelta, timezone

import asyncpg

N_SESSOES = 400
DIAS = 30
APP_TAG = "seed-sintetico"
SEED = 20260720  # reprodutível

random.seed(SEED)

# Peso por hora do dia (0..23): pouco de madrugada, pico à tarde/noite.
HORA_PESO = [1, 1, 1, 1, 1, 1, 2, 3, 4, 5, 6, 7, 7, 9, 10, 10, 9, 9, 10, 10, 8, 6, 4, 2]

# Distribuição de matérias (sigla -> peso). Temas por matéria só para o payload.
MATERIA_PESO = {"PORT": 20, "MAT": 18, "HIS": 12, "BIO": 10, "GEO": 8,
                "FIS": 8, "QUI": 8, "FIL": 6, "SOC": 6, "ING": 4}
TEMAS = {
    "PORT": ["Gramática Normativa", "Interpretação de Texto", "Análise Sintática"],
    "MAT": ["Funções", "Geometria Espacial", "Estatística"],
    "HIS": ["Era Vargas", "Guerra Fria", "Brasil Colônia"],
    "BIO": ["Ecologia", "Genética", "Citologia"],
    "GEO": ["Geopolítica", "Climatologia", "Urbanização"],
    "FIS": ["Mecânica", "Eletromagnetismo", "Termodinâmica"],
    "QUI": ["Estequiometria", "Química Orgânica", "Termoquímica"],
    "FIL": ["Filosofia Antiga", "Ética e Moral", "Existencialismo"],
    "SOC": ["Movimentos Sociais", "Cultura e Identidade", "Cidadania"],
    "ING": ["Interpretação de Texto", "Tempos Verbais", "Falsos Cognatos"],
}

# Perfis de dispersão: cada aluno recebe um, e as features saem coerentes com ele.
def features_por_perfil(perfil):
    if perfil == "focado":
        return dict(
            mudancas_aba=random.randint(0, 1),
            tempo_fora_foco_s=round(random.uniform(0, 30), 1),
            acertos_questoes=random.randint(6, 10),
            tempo_resposta_ms=round(random.uniform(2000, 6000), 1),
            cliques_fora_area_estudo=random.randint(0, 1),
            pausas_digitacao_s=round(random.uniform(0.5, 3), 1),
            velocidade_scroll_px_s=round(random.uniform(200, 600), 1),
            nivel_dificuldade_atividade=random.randint(2, 4),
        )
    if perfil == "disperso":
        return dict(
            mudancas_aba=random.randint(3, 8),
            tempo_fora_foco_s=round(random.uniform(60, 300), 1),
            acertos_questoes=random.randint(0, 4),
            tempo_resposta_ms=round(random.uniform(7000, 15000), 1),
            cliques_fora_area_estudo=random.randint(2, 6),
            pausas_digitacao_s=round(random.uniform(3, 15), 1),
            velocidade_scroll_px_s=round(random.uniform(500, 1500), 1),
            nivel_dificuldade_atividade=random.randint(1, 4),
        )
    return dict(  # medio
        mudancas_aba=random.randint(1, 3),
        tempo_fora_foco_s=round(random.uniform(20, 90), 1),
        acertos_questoes=random.randint(4, 7),
        tempo_resposta_ms=round(random.uniform(4000, 9000), 1),
        cliques_fora_area_estudo=random.randint(0, 3),
        pausas_digitacao_s=round(random.uniform(1, 6), 1),
        velocidade_scroll_px_s=round(random.uniform(300, 900), 1),
        nivel_dificuldade_atividade=random.randint(1, 5),
    )

def escolha_ponderada(dic):
    return random.choices(list(dic.keys()), weights=list(dic.values()), k=1)[0]

def load_db_url():
    with open("./.env", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\s*DATABASE_URL\s*=\s*"?([^"\n]+)"?', line)
            if m:
                return m.group(1).strip()
    raise SystemExit("DATABASE_URL não encontrado em ./.env")

async def main(commit):
    conn = await asyncpg.connect(load_db_url(), statement_cache_size=0)
    try:
        alunos = [r["user_id"] for r in await conn.fetch(
            "select user_id from perfis where role='aluno' and email ilike '%@aluno.sintetico.kaia'")]
        if not alunos:
            raise SystemExit("Nenhuma conta @aluno.sintetico.kaia encontrada.")

        # Perfil de dispersão e "nível de atividade" por aluno (desigual).
        perfil_aluno, ativ_aluno = {}, {}
        for a in alunos:
            perfil_aluno[a] = random.choices(["focado", "medio", "disperso"], weights=[25, 50, 25])[0]
            ativ_aluno[a] = random.choices([3.0, 1.0, 0.2], weights=[25, 50, 25])[0]  # ativo/medio/pouco

        agora = datetime.now(timezone.utc)
        # Peso por dia: dias de semana > fim de semana.
        dias = [(agora - timedelta(days=d)) for d in range(DIAS)]
        peso_dia = [1.0 if dt.weekday() < 5 else 0.5 for dt in dias]

        sessions_rows, feat_rows, event_rows = [], [], []
        contador_dia = {}   # (aluno, data) -> nº da sessão no dia
        resumo = {"focado": 0, "medio": 0, "disperso": 0}
        mat_count, hora_count, dur_list = {}, {}, []

        for _ in range(N_SESSOES):
            aluno = random.choices(alunos, weights=[ativ_aluno[a] for a in alunos], k=1)[0]
            perfil = perfil_aluno[aluno]
            base = random.choices(dias, weights=peso_dia, k=1)[0]
            hora = random.choices(range(24), weights=HORA_PESO, k=1)[0]
            inicio = base.replace(hour=hora, minute=random.randint(0, 59),
                                  second=random.randint(0, 59), microsecond=0)
            dur_min = min(70, max(5, round(random.lognormvariate(3.1, 0.5))))
            fim = inicio + timedelta(minutes=dur_min)

            chave = (aluno, inicio.date())
            contador_dia[chave] = contador_dia.get(chave, 0) + 1
            n_dia = contador_dia[chave]

            sid = await conn.fetchval("select gen_random_uuid()")
            feats = features_por_perfil(perfil)
            materia = escolha_ponderada(MATERIA_PESO)
            tema = random.choice(TEMAS[materia])

            sessions_rows.append((sid, aluno, inicio, fim, "web", APP_TAG))
            feat_rows.append((
                sid, inicio.time().replace(microsecond=0), n_dia,
                feats["tempo_resposta_ms"], feats["velocidade_scroll_px_s"],
                feats["pausas_digitacao_s"], feats["cliques_fora_area_estudo"],
                feats["mudancas_aba"], feats["tempo_fora_foco_s"],
                feats["acertos_questoes"], feats["nivel_dificuldade_atividade"], inicio,
            ))
            event_rows.append((
                sid, "session_start",
                json.dumps({"materia": materia, "tema": tema, "origem": "seed-sintetico"}),
                inicio,
            ))

            resumo[perfil] += 1
            mat_count[materia] = mat_count.get(materia, 0) + 1
            hora_count[hora] = hora_count.get(hora, 0) + 1
            dur_list.append(dur_min)

        # ---- Resumo (sempre exibido) ----
        print(f"\n=== SEED SINTÉTICO — {N_SESSOES} sessões, {DIAS} dias, {len(alunos)} alunos ===")
        print("perfis de dispersão:", resumo)
        print("duração min/mediana/max:", min(dur_list),
              sorted(dur_list)[len(dur_list)//2], max(dur_list), "min")
        print("matérias:", dict(sorted(mat_count.items(), key=lambda x: -x[1])))
        print("top horas:", dict(sorted(hora_count.items(), key=lambda x: -x[1])[:6]))
        dias_distintos = len({r[2].date() for r in sessions_rows})
        print("dias distintos cobertos:", dias_distintos)
        print("amostra de 3 sessões:")
        for r, f in list(zip(sessions_rows, feat_rows))[:3]:
            print(f"  {r[2]:%d/%m %H:%M} dur até {r[3]:%H:%M} · aba={f[7]} fora={f[8]}s acertos={f[9]} dif={f[10]}")

        if not commit:
            print("\n[DRY-RUN] Nada gravado. Rode com --commit para inserir.")
            return

        # ---- Inserção real ----
        async with conn.transaction():
            await conn.executemany(
                "insert into sessions (session_id, user_id, session_start_ts, session_end_ts, platform, app_version)"
                " values ($1,$2,$3,$4,$5,$6)", sessions_rows)
            await conn.executemany(
                "insert into session_features (session_id, horario_inicio, sessoes_no_dia, tempo_resposta_ms,"
                " velocidade_scroll_px_s, pausas_digitacao_s, cliques_fora_area_estudo, mudancas_aba,"
                " tempo_fora_foco_s, acertos_questoes, nivel_dificuldade_atividade, window_ts)"
                " values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)", feat_rows)
            await conn.executemany(
                "insert into session_events (session_id, event_type, payload, ts)"
                " values ($1,$2,$3::jsonb,$4)", event_rows)
        print(f"\n[COMMIT] Inseridas {len(sessions_rows)} sessões sintéticas (app_version='{APP_TAG}').")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main("--commit" in sys.argv))
