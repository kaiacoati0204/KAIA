"""
seed_contas_teste.py — cria ~6 contas de teste COM senha real no Supabase Auth.

Todas passam pelo MESMO caminho de uma conta real (auth.users + login por senha),
sem flag de desvio. Idempotente por e-mail; toda a escrita roda numa transação
(tudo-ou-nada), então uma falha no meio não deixa meio-estado.

Uso:
    python seed_contas_teste.py            # dry-run: só mostra o plano
    python seed_contas_teste.py --commit   # aplica

Limpeza / rollback: limpar_contas_teste.py (restaura os 2 slots reaproveitados).

================================================================================
AVISO DE ROBUSTEZ (test-only)
--------------------------------------------------------------------------------
Insere DIRETO em auth.users / auth.identities — schema interno do GoTrue, que
NÃO é API pública. Aceitável só por serem poucas contas de teste, controladas e
recriáveis. Regras:
  - Cadastro de usuário REAL (Etapa 2) vai por supabase.auth.signUp, nunca aqui.
  - Colunas de token string entram como '' (não NULL): o GoTrue-Go quebra o login
    ao ler NULL num string ("converting NULL to string is unsupported").
  - Professor/coordenador NÃO são criados: `coordenadores` é UNIQUE(escola_id) e
    `professores` é UNIQUE(escola_id, materia). Reaproveitamos as linhas que já
    ocupam esses slots na Vale Verde (mesmo padrão do admin: dar login a quem já
    existe). A limpeza restaura nome/email originais desses dois.
  - Se algum login quebrar após um update do Supabase/GoTrue, ESTE script é o
    primeiro suspeito.
================================================================================
"""
import asyncio, os, re, json, sys
import asyncpg

ENV = os.path.join(os.path.dirname(__file__), ".env")
SENHA = "teste1234"
INSTANCE = "00000000-0000-0000-0000-000000000000"

# Colunas string de token que precisam ser '' e não NULL (armadilha do GoTrue).
TOKENS_VAZIOS = [
    "confirmation_token", "recovery_token", "email_change_token_new",
    "email_change", "email_change_token_current", "reauthentication_token",
]

# ---- as 6 contas ----
# escola/turma/materia resolvidos por nome no banco (sem uuid hardcoded).
# reaproveita: 'professor'/'coordenador' -> UPDATE do slot único existente.
CONTAS = [
    {"email": "kaia.coati0204@gmail.com", "nome": None,                "role": "admin"},
    {"email": "coordenador@teste.kaia",   "nome": "Coordenador Teste",  "role": "coordenador",
        "escola": "Escola Vale Verde", "reaproveita": "coordenador"},
    {"email": "professor@teste.kaia",     "nome": "Professor Teste",    "role": "professor",
        "escola": "Escola Vale Verde", "materia_like": "Matem%", "reaproveita": "professor"},
    {"email": "aluno1@teste.kaia",        "nome": "Aluno Teste 1",      "role": "aluno",
        "escola": "Escola Vale Verde", "turma": (2, "manh%")},
    {"email": "aluno2@teste.kaia",        "nome": "Aluno Teste 2",      "role": "aluno",
        "escola": "Escola Vale Verde", "turma": (2, "manh%")},
    {"email": "aluno.individual@teste.kaia", "nome": "Aluno Individual Teste", "role": "aluno"},
]


def load_db_url():
    with open(ENV, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\s*DATABASE_URL\s*=\s*"?([^"\n]+)"?', line)
            if m:
                return m.group(1).strip()
    raise SystemExit("DATABASE_URL não encontrado no .env")


async def resolver(conn, c):
    """Resolve escola_id / turma_id / materia / id-reaproveitado por nome."""
    v = {"escola_id": None, "turma_id": None, "materia": None, "reaproveita_id": None}
    if c.get("escola"):
        v["escola_id"] = await conn.fetchval("select escola_id from escolas where nome ilike $1", c["escola"])
        if v["escola_id"] is None:
            raise SystemExit(f"escola não encontrada: {c['escola']}")
    if c.get("turma"):
        ano, turno = c["turma"]
        v["turma_id"] = await conn.fetchval(
            "select turma_id from turmas where escola_id=$1 and ano=$2 and turno ilike $3",
            v["escola_id"], ano, turno)
        if v["turma_id"] is None:
            raise SystemExit(f"turma não encontrada: {c['escola']} {c['turma']}")
    if c.get("materia_like"):
        v["materia"] = await conn.fetchval(
            "select distinct materia from desempenho_semanal where escola_id=$1 and materia ilike $2 limit 1",
            v["escola_id"], c["materia_like"])
        if v["materia"] is None:
            raise SystemExit(f"matéria não encontrada em desempenho_semanal: {c['materia_like']}")
    if c.get("reaproveita") == "professor":
        v["reaproveita_id"] = await conn.fetchval(
            "select professor_id from professores where escola_id=$1 and materia=$2", v["escola_id"], v["materia"])
        if v["reaproveita_id"] is None:
            raise SystemExit(f"professor do slot {c['escola']}/{v['materia']} não encontrado")
    if c.get("reaproveita") == "coordenador":
        v["reaproveita_id"] = await conn.fetchval(
            "select coordenador_id from coordenadores where escola_id=$1", v["escola_id"])
        if v["reaproveita_id"] is None:
            raise SystemExit(f"coordenador do slot {c['escola']} não encontrado")
    return v


async def uid_de(conn, c, v):
    """Slot reaproveitado usa o id existente; senão auth.users -> perfis -> novo."""
    if v["reaproveita_id"]:
        return v["reaproveita_id"]
    return (await conn.fetchval("select id from auth.users where lower(email)=lower($1)", c["email"])
            or await conn.fetchval("select user_id from perfis where lower(email)=lower($1)", c["email"])
            or await conn.fetchval("select gen_random_uuid()"))


async def escrever(conn, c, v, uid):
    # --- auth.users + identity (delete+insert por id: idempotente) ---
    await conn.execute("delete from auth.identities where user_id=$1", uid)
    await conn.execute("delete from auth.users where id=$1", uid)
    await conn.execute(f"""
        insert into auth.users (
            instance_id, id, aud, role, email, encrypted_password,
            email_confirmed_at, created_at, updated_at,
            raw_app_meta_data, raw_user_meta_data,
            {", ".join(TOKENS_VAZIOS)},
            is_sso_user, is_anonymous
        ) values (
            $1, $2, 'authenticated', 'authenticated', lower($3), crypt($4, gen_salt('bf')),
            now(), now(), now(),
            '{{"provider":"email","providers":["email"]}}'::jsonb, '{{}}'::jsonb,
            {", ".join("''" for _ in TOKENS_VAZIOS)},
            false, false
        )""", INSTANCE, uid, c["email"], SENHA)
    await conn.execute("""
        insert into auth.identities (user_id, provider, provider_id, identity_data,
                                     last_sign_in_at, created_at, updated_at)
        values ($1,'email',$2,$3::jsonb, now(), now(), now())
    """, uid, str(uid), json.dumps({"sub": str(uid), "email": c["email"].lower(), "email_verified": True}))

    # --- perfis (upsert; nome=None preserva o do admin) ---
    await conn.execute("""
        insert into perfis (user_id, email, nome, role, escola_id, turma_id,
                            hobbies, sequencia_dias_estudo, sessoes_no_dia, created_at, updated_at)
        values ($1, lower($2), coalesce($3,'Usuário'), $4, $5, $6, '[]'::jsonb, 0, 0, now(), now())
        on conflict (user_id) do update set
            email=excluded.email, nome=coalesce($3, perfis.nome), role=excluded.role,
            escola_id=excluded.escola_id, turma_id=excluded.turma_id, updated_at=now()
    """, uid, c["email"], c["nome"], c["role"], v["escola_id"], v["turma_id"])

    # --- professor/coordenador: UPDATE do slot existente (nunca INSERT) ---
    if c.get("reaproveita") == "professor":
        await conn.execute(
            "update professores set email=lower($1), nome=$2 where professor_id=$3",
            c["email"], c["nome"], uid)
    if c.get("reaproveita") == "coordenador":
        await conn.execute(
            "update coordenadores set email=lower($1), nome=$2 where coordenador_id=$3",
            c["email"], c["nome"], uid)


async def main(commit):
    conn = await asyncpg.connect(load_db_url(), statement_cache_size=0)
    try:
        print(f"{'e-mail':32} {'role':12} vínculo")
        print("-" * 78)
        plano = []
        for c in CONTAS:
            v = await resolver(conn, c)
            uid = await uid_de(conn, c, v)
            det = []
            if v["reaproveita_id"]: det.append(f"reaproveita slot {c['reaproveita']}")
            if c.get("escola"):     det.append(c["escola"])
            if v["turma_id"]:       det.append(f"turma {c['turma'][0]}/{c['turma'][1].strip('%')}")
            if v["materia"]:        det.append(v["materia"])
            if not det:             det.append("(individual — sem escola/turma)")
            print(f"{c['email']:32} {c['role']:12} {' · '.join(det)}")
            plano.append((c, v, uid))

        if not commit:
            print("\n[DRY-RUN] nada foi escrito. Rode com --commit para aplicar.")
            return

        async with conn.transaction():   # tudo-ou-nada
            for c, v, uid in plano:
                await escrever(conn, c, v, uid)
        print(f"\n[COMMIT] {len(plano)} contas criadas/atualizadas (senha: {SENHA}).")

        print("\n=== conferência em perfis ===")
        rows = await conn.fetch("""
            select p.email, p.role, e.nome escola, t.ano, t.turno
            from perfis p
            left join escolas e on e.escola_id=p.escola_id
            left join turmas  t on t.turma_id=p.turma_id
            where p.email ilike '%@teste.kaia' or p.email='kaia.coati0204@gmail.com'
            order by p.role, p.email
        """)
        for r in rows:
            vinc = f"{r['escola']} · {r['ano']}/{r['turno']}" if r['escola'] else "—"
            print(f"  {r['email']:32} {r['role']:12} {vinc}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(commit="--commit" in sys.argv))
