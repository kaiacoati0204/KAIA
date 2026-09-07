"""Cria contas de TESTE no Supabase (uma por role + 2 alunos) — auth.users + identities
+ perfis (nos schemas public E teste). Idempotente: pula o que já existe.

Precisa só de DATABASE_URL no .env. Senha igual pra todas: `teste1234`.
Login verificado via GoTrue (as colunas de token vão como '' — NULL quebra o login).

    python Backend/criar_contas_teste.py
"""
import os
import json
import asyncio
from datetime import date, timedelta
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
SENHA = "teste1234"

# email, role, nome, hobbies, dias_ate_prova
CONTAS = [
    ("admin@teste.kaia",       "admin",       "Ana (Admin)",  [],                                None),
    ("professor@teste.kaia",   "professor",   "Prof. Bruno",  [],                                None),
    ("coordenador@teste.kaia", "coordenador", "Coord. Carla", [],                                None),
    ("pai@teste.kaia",         "pai",         "Pai Daniel",   [],                                None),
    ("aluno1@teste.kaia",      "aluno",       "Lucas",        ["futebol", "videogames"],         60),
    ("aluno2@teste.kaia",      "aluno",       "Marina",       ["música", "leitura", "desenho"], 200),
]


async def main():
    if not os.getenv("DATABASE_URL"):
        print("Defina DATABASE_URL no .env."); return
    c = await asyncpg.connect(os.getenv("DATABASE_URL"), statement_cache_size=0,
                              server_settings={"search_path": "auth, extensions, public"})
    try:
        for email, role, nome, hobbies, dias in CONTAS:
            uid = await c.fetchval("select id from auth.users where email=$1", email)
            if not uid:
                uid = await c.fetchval("""
                    insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
                        email_confirmed_at, created_at, updated_at, raw_app_meta_data, raw_user_meta_data)
                    values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), 'authenticated',
                        'authenticated', $1, crypt($2, gen_salt('bf')), now(), now(), now(),
                        '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb)
                    returning id""", email, SENHA)
                print(f"  {email}: CRIADO")
            else:
                print(f"  {email}: já existe")
            # identity (email.email é coluna GERADA -> não inserir); idempotente
            await c.execute("""
                insert into auth.identities (provider_id, user_id, identity_data, provider,
                    last_sign_in_at, created_at, updated_at)
                select $1::text, $1::uuid,
                    jsonb_build_object('sub',$1::text,'email',$2,'email_verified',true),
                    'email', now(), now(), now()
                where not exists (select 1 from auth.identities
                                  where user_id=$1::uuid and provider='email')""", str(uid), email)
            # perfis nos DOIS schemas (role/hobbies/nome)
            prova = (date.today() + timedelta(days=dias)) if dias else None
            for sch in ("public", "teste"):
                await c.execute(f"""
                    insert into {sch}.perfis (user_id, email, role, nome, hobbies, data_prova)
                    values ($1::uuid, $2, $3, $4, $5::jsonb, $6)
                    on conflict (user_id) do update set role=excluded.role, nome=excluded.nome,
                        hobbies=excluded.hobbies, email=excluded.email, data_prova=excluded.data_prova
                """, str(uid), email, role, nome, json.dumps(hobbies), prova)

        # GoTrue quebra com colunas de token NULL -> '' (todas as text, menos phone)
        cols = [r["column_name"] for r in await c.fetch(
            "select column_name from information_schema.columns "
            "where table_schema='auth' and table_name='users' "
            "and data_type in ('text','character varying') and column_name <> 'phone'")]
        sets = ", ".join(f"{n} = coalesce({n}, '')" for n in cols)
        await c.execute(f"update auth.users set {sets} where email like '%@teste.kaia'")

        print("\nContas (@teste.kaia), senha 'teste1234':")
        for r in await c.fetch("select role, email, nome from public.perfis "
                               "where email like '%@teste.kaia' order by role, email"):
            print(f"  {r['role']:12} {r['email']:24} {r['nome']}")
    finally:
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
