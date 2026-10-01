"""
Pagamento (Mercado Pago) — regras puras, sem banco e sem rede.

Separado do app.py de propósito: aqui mora o que dá para testar sem chave e sem
Postgres — validação de assinatura do webhook, janela do trial, decisão de acesso.
As rotas ficam no app.py; o que chama o Mercado Pago de verdade está marcado com o
banner PENDENTE (Bia) lá.

Uso:
    from pagamento import assinatura_valida, validar_webhook, PLANOS
"""
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

# ______________________ PENDENTE (Bia) ______________________
# Os preços abaixo são os que já existiam nas telas de plano. Confira antes de cobrar
# de verdade — daqui para a frente eles viram dinheiro real.
# ____________________________________________________________
PLANOS = {
    "essencial": {"nome": "Essencial", "preco": 19.90},
    "foco":      {"nome": "Foco",      "preco": 29.90},
    "turbo":     {"nome": "Turbo",     "preco": 39.90},
    "familia":   {"nome": "Família",   "preco": 59.90},
    "escola":    {"nome": "Escola",    "preco": 0.00},   # sob consulta
}

DIAS_TRIAL = 7

# Estados que dão acesso ao estudo. 'suspensa' e 'cancelada' ficam de fora — mas os
# DADOS continuam: suspender bloqueia a porta, não apaga o caderno.
STATUS_COM_ACESSO = ("trial", "ativa")


# ============================================================
#  CHAVES (sempre do ambiente, nunca do código)
# ============================================================
def _chave(nome):
    v = (os.getenv(nome) or "").strip()
    return v or None


def credenciais():
    """(access_token, public_key, secret_do_webhook). None em qualquer uma = não configurado."""
    return (_chave("MP_ACCESS_TOKEN"), _chave("MP_PUBLIC_KEY"), _chave("MP_WEBHOOK_SECRET"))


def pagamento_configurado():
    """Sem access token não dá para cobrar. O site NÃO cai por isso — as rotas respondem
    'pagamento indisponível' e o resto da plataforma segue de pé."""
    return _chave("MP_ACCESS_TOKEN") is not None


def modo_sandbox():
    """Chave de teste do MP começa com TEST-. Serve para a tela avisar que não é cobrança
    real — e para nunca confundir um ambiente com o outro."""
    tok = _chave("MP_ACCESS_TOKEN") or ""
    return tok.startswith("TEST-")


# ============================================================
#  WEBHOOK — validação de assinatura
# ============================================================
# O MP assina cada notificação no header `x-signature`, no formato:
#     ts=1700000000,v1=<hex sha256>
# O que é assinado é um template fixo (manifest):
#     id:<data.id>;request-id:<x-request-id>;ts:<ts>;
# e a chave é o "segredo" do webhook, que sai do painel do MP.
#
# Sem isto, QUALQUER um que descubra a URL pode postar "pagou" e liberar acesso de graça.
# É por isso que a ausência de assinatura é rejeição, não aviso.
_RE_TS = re.compile(r"ts=([^,]+)")
_RE_V1 = re.compile(r"v1=([0-9a-fA-F]+)")

TOLERANCIA_S = 300   # 5 min: barra replay de notificação antiga capturada


def validar_webhook(x_signature, x_request_id, data_id, segredo, agora=None):
    """(ok, motivo). Falha FECHADA: sem segredo configurado, recusa.

    O contrário — aceitar quando não há segredo — deixaria a porta aberta justo no
    ambiente mal configurado, que é onde o ataque acontece.
    """
    if not segredo:
        return False, "webhook sem segredo configurado"
    if not x_signature:
        return False, "sem x-signature"
    if not data_id:
        return False, "sem data.id"

    m_ts, m_v1 = _RE_TS.search(x_signature), _RE_V1.search(x_signature)
    if not m_ts or not m_v1:
        return False, "x-signature malformado"
    ts, recebida = m_ts.group(1).strip(), m_v1.group(1).strip().lower()

    # Janela de tempo: assinatura válida capturada ontem não pode ser reenviada hoje.
    try:
        agora = agora if agora is not None else datetime.now(timezone.utc).timestamp()
        if abs(agora - int(ts) / (1000 if len(ts) > 11 else 1)) > TOLERANCIA_S:
            return False, "timestamp fora da janela"
    except (TypeError, ValueError):
        return False, "timestamp inválido"

    manifest = f"id:{data_id};request-id:{x_request_id or ''};ts:{ts};"
    esperada = hmac.new(segredo.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    # compare_digest: comparação com "==" vaza o tamanho do prefixo correto pelo tempo
    # de resposta, e isso é suficiente para adivinhar a assinatura byte a byte.
    if not hmac.compare_digest(esperada, recebida):
        return False, "assinatura não confere"
    return True, None


# ============================================================
#  TRIAL E ACESSO
# ============================================================
def fim_do_trial(inicio):
    return inicio + timedelta(days=DIAS_TRIAL)


def trial_expirou(fim, agora=None):
    if fim is None:
        return False
    return (agora or datetime.now(timezone.utc)) >= fim


def assinatura_valida(status, fim, agora=None):
    """Acesso ao estudo. Trial vencido NÃO dá acesso mesmo com status='trial': o MP pode
    demorar a avisar a cobrança, e até lá a data manda."""
    if status not in STATUS_COM_ACESSO:
        return False
    if status == "trial" and trial_expirou(fim, agora):
        return False
    return True


def plano_valido(plano):
    return plano in PLANOS
