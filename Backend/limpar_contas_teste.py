"""
limpar_contas_teste.py — desfaz o seed_contas_teste.py.

- DELETA as contas net-new (aluno1, aluno2, aluno individual): auth + perfis.
- RESTAURA os 2 slots reaproveitados (professor/coordenador da Vale Verde) ao
  nome/email ORIGINAIS e remove o login deles. Esses slots são UNIQUE por
  escola/(escola,materia) — nunca podem ser deletados.
- MANTÉM o admin (kaia.coati0204@gmail.com): é a conta real, não uma de teste.

Toda a escrita roda numa transação (tudo-ou-nada).

Uso:
    python limpar_contas_teste.py            # dry-run
    python limpar_contas_teste.py --commit   # aplica
"""
import asyncio, os, re, sys
import asyncpg

ENV = os.path.join(os.path.dirname(__file__), ".env")

# Contas criadas do zero pelo seed — seguras para deletar por completo.
NET_NEW = ["aluno1@teste.kaia", "aluno2@teste.kaia", "aluno.individual@teste.kaia"]

# Slots únicos reaproveitados. Valores ORIGINAIS capturados antes do seed —
# ficam versionados aqui para a restauração não depender de nenhum backup.
ORIGINAIS = [
    {"tabela": "professores",   "id_col": "professor_id",
     "id": "b6c88b58-6613-4080-9872-2d7ea5f12f7b",
     "nome": "Ana Cecília Ferreira",      "email": "ana.cecilia.ferreira.b6c8@escola.kaia"},
    {"tabela": "coordenadores", "id_col": "coordenador_id",
     "id": "26b0114d-29dd-4ae7-b1fc-b5cd087026cd",
     "nome": "Pedro Henrique Cavalcanti", "email": "pedro.henrique.cavalcanti.26b0@escola.kaia"},
]


def load_db_url():
    with open(ENV, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\s*DATABASE_URL\s*=\s*"?([^"\n]+)"?', line)
            if m:
                return m.group(1).strip()
    raise SystemExit("DATABASE_URL não encontrado no .env")


async def remover_login(conn, uid):
    await conn.execute("delete from auth.identities where user_id=$1", uid)
    await conn.execute("delete from auth.users where id=$1", uid)


async def main(commit):
    conn = await asyncpg.connect(load_db_url(), statement_cache_size=0)
    try:
        print("Plano de limpeza:")
        for e in NET_NEW:
            print(f"  DELETAR   {e}")
        for o in ORIGINAIS:
            print(f"  RESTAURAR {o['tabela']:13} -> {o['nome']} / {o['email']} (remove login)")
        print("  MANTER    kaia.coati0204@gmail.com (admin real)")

        if not commit:
            print("\n[DRY-RUN] nada foi escrito. Rode com --commit para aplicar.")
            return

        async with conn.transaction():
            # net-new: apaga tudo
            for e in NET_NEW:
                uid = await conn.fetchval("select user_id from perfis where lower(email)=lower($1)", e)
                if uid:
                    await remover_login(conn, uid)
                    await conn.execute("delete from perfis where user_id=$1", uid)
            # slots reaproveitados: restaura nome/email e tira o login
            for o in ORIGINAIS:
                uid = o["id"]
                await conn.execute(
                    f"update {o['tabela']} set nome=$1, email=lower($2) where {o['id_col']}=$3",
                    o["nome"], o["email"], uid)
                await conn.execute(
                    "update perfis set nome=$1, email=lower($2), updated_at=now() where user_id=$3",
                    o["nome"], o["email"], uid)
                await remover_login(conn, uid)

        print("\n[COMMIT] limpeza aplicada.")
        restantes = await conn.fetch(
            "select email from auth.users order by email")
        print("auth.users restantes:", [r["email"] for r in restantes])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main(commit="--commit" in sys.argv))
