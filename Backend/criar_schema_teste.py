"""Cria um schema `teste` no MESMO banco Supabase, com CÓPIAS vazias das tabelas do
`public` — um sandbox isolado. O backend de teste aponta pra ele com KAIA_DB_SCHEMA=teste
(search_path), então grava tudo (sessões/eventos/probes/cache) em `teste.*` sem tocar
no `public`. Só copia os DADOS de referência (questoes_reais) pro few-shot funcionar.

NÃO modifica o schema public — apenas LÊ dele e cria coisas no schema `teste`.
Idempotente: pode rodar de novo (create ... if not exists).

    python Backend/criar_schema_teste.py            # cria/atualiza o schema teste
    python Backend/criar_schema_teste.py --refazer  # dropa e recria o schema teste
"""
import os
import sys
import asyncio
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
DATABASE_URL = os.getenv("DATABASE_URL")

# tabelas cujos DADOS a gente copia (referência do few-shot). O resto começa VAZIO.
COPIAR_DADOS = ["questoes_reais"]


async def main():
    if not DATABASE_URL:
        print("Defina DATABASE_URL no .env."); return
    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0,
                                 server_settings={"search_path": "public, extensions"})
    try:
        if "--refazer" in sys.argv:
            await conn.execute("drop schema if exists teste cascade")
            print("schema teste dropado.")
        await conn.execute("create schema if not exists teste")

        tabs = [r["tablename"] for r in await conn.fetch(
            "select tablename from pg_tables where schemaname='public' order by tablename")]
        print(f"{len(tabs)} tabelas no public:", tabs)

        criadas, falhas = [], []
        for t in tabs:
            try:
                await conn.execute(
                    f'create table if not exists teste."{t}" (like public."{t}" including all)')
                criadas.append(t)
            except Exception as e:
                falhas.append((t, str(e)[:120]))

        # copia SÓ os dados de referência (sem colunas identity/geradas p/ não conflitar)
        for t in COPIAR_DADOS:
            if t not in criadas:
                continue
            if await conn.fetchval(f'select count(*) from teste."{t}"'):
                print(f"  {t}: já tinha dados, pulando cópia")
                continue
            cols = [r["column_name"] for r in await conn.fetch(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name=$1 "
                "and is_generated <> 'ALWAYS' and coalesce(is_identity,'NO') <> 'YES' "
                "order by ordinal_position", t)]
            cl = ", ".join(f'"{c}"' for c in cols)
            await conn.execute(f'insert into teste."{t}" ({cl}) select {cl} from public."{t}"')
            n = await conn.fetchval(f'select count(*) from teste."{t}"')
            print(f"  {t}: {n} linhas de referência copiadas")

        print(f"\nOK: {len(criadas)} tabelas em teste.")
        if falhas:
            print("FALHAS (conferir):")
            for t, e in falhas:
                print(f"  {t}: {e}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
