"""
Validação do JWT do Supabase Auth (Sprint — gestão de sessão segura).

Os tokens do Supabase são assinados com ES256 (chave assimétrica) e as chaves
públicas ficam no JWKS do projeto. Aqui verificamos assinatura + expiração +
audience + issuer usando o JWKS (sem precisar de segredo no servidor).

Uso como dependência FastAPI:
    @app.get("/rota")
    async def rota(user_id: str = Depends(usuario_autenticado)):
        ...
"""
import os
import re
from pathlib import Path

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request

# Carrega o Backend/.env pelo caminho do próprio arquivo (robusto ao CWD dos
# testes). Variáveis já presentes no ambiente (ex.: CI) continuam valendo.
load_dotenv(Path(__file__).with_name(".env"))


def _supabase_url():
    """SUPABASE_URL do .env, ou derivada do DATABASE_URL (project ref no pooler)."""
    url = os.getenv("SUPABASE_URL")
    if url:
        return url.rstrip("/")
    db = os.getenv("DATABASE_URL", "")
    m = re.search(r"postgres\.([a-z0-9]{16,})", db) or re.search(r"@([a-z0-9]{16,})\.supabase", db)
    return f"https://{m.group(1)}.supabase.co" if m else None


SUPABASE_URL = _supabase_url()
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else None
ISSUER = f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else None

# Busca e cacheia as chaves públicas (ES256) do projeto.
_jwks_client = jwt.PyJWKClient(JWKS_URL) if JWKS_URL else None


def verificar_token(token):
    """Valida o JWT (assinatura ES256 via JWKS + exp + aud + iss) e devolve os
    claims. Levanta HTTPException 401/503 se inválido."""
    if not token:
        raise HTTPException(status_code=401, detail="Token de acesso ausente.")
    if not _jwks_client:
        raise HTTPException(status_code=503, detail="Auth não configurada no servidor.")
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=ISSUER,
            leeway=60,  # tolera clock skew leve no exp
            # iat ("emitido em") não é controle de segurança e quebra com relógio
            # atrasado; o que protege é a assinatura + exp, que seguem validados.
            options={"verify_iat": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado. Faça login de novo.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido.")


def _bearer(request):
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


async def usuario_autenticado(request: Request):
    """Dependência FastAPI: exige um Bearer token válido; retorna o user_id (sub)."""
    return verificar_token(_bearer(request))["sub"]
