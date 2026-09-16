"""
Consentimento do responsável legal (LGPD art. 14) — regras puras.

O beta é com menores e coleta comportamento (tempo, saída de aba, ociosidade, mouse,
autorrelato). Sem o aceite de um responsável registrado, essa coleta não pode acontecer.

Fluxo sem depender de envio de e-mail (a KaIA ainda não tem servidor de e-mail): o cadastro
gera um LINK com token; o aluno/escola entrega ao responsável; o responsável abre, se
identifica e aceita. O registro guarda quem, quando, de onde e qual versão do documento.
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import date, timedelta

VERSAO_DOCUMENTO = "1.4"      # versão da Política de Privacidade aceita; sobe junto com ela
IDADE_MAIOR = 18
DIAS_PARA_EXPIRAR = 14        # 7 dias + 7 de lembrete, como no fluxo do documento
PARENTESCOS = ("mãe", "pai", "responsável legal")


def novo_token():
    """Token do link do responsável. É a credencial da página — precisa ser imprevisível."""
    return secrets.token_urlsafe(32)


def _digitos(cpf):
    return re.sub(r"\D", "", cpf or "")


def cpf_valido(cpf):
    """Dígitos verificadores. Evita erro de digitação num registro que vale como prova."""
    d = _digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for corte in (9, 10):
        soma = sum(int(d[i]) * (corte + 1 - i) for i in range(corte))
        dv = (soma * 10) % 11 % 10
        if dv != int(d[corte]):
            return False
    return True


def hash_cpf(cpf):
    """HMAC-SHA256 com segredo do ambiente.

    SHA256 puro de CPF não protege nada: são 10^11 combinações, quebra por força bruta em
    minutos. O segredo (KAIA_CPF_PEPPER) é o que torna o hash irreversível para quem só tem
    o banco. Sem o segredo no ambiente, a função falha de propósito em vez de gravar um hash
    fraco achando que está protegido.
    """
    segredo = os.getenv("KAIA_CPF_PEPPER")
    if not segredo:
        raise RuntimeError("KAIA_CPF_PEPPER não definida — sem ela o hash de CPF seria reversível.")
    return hmac.new(segredo.encode(), _digitos(cpf).encode(), hashlib.sha256).hexdigest()


def e_menor(data_nascimento, hoje=None):
    """None (data desconhecida) devolve None — 'não sei' é diferente de 'é maior'."""
    if not data_nascimento:
        return None
    hoje = hoje or date.today()
    anos = hoje.year - data_nascimento.year - (
        (hoje.month, hoje.day) < (data_nascimento.month, data_nascimento.day))
    return anos < IDADE_MAIOR


def coleta_permitida(data_nascimento, status, estrito=False, hoje=None):
    """Pode gravar dado de comportamento deste aluno?

    Maior de idade: sim (o aceite dos termos dele já cobre). Menor: só com 'aprovado'.
    Data desconhecida (contas antigas/de teste): passa, a menos que `estrito` — no beta com
    alunos reais, ligue KAIA_CONSENTIMENTO_ESTRITO=1 para não deixar brecha.
    """
    menor = e_menor(data_nascimento, hoje)
    if menor is None:
        return not estrito
    if not menor:
        return True
    return status == "aprovado"


def validar_aceite(nome, cpf, parentesco):
    """(ok, erro). O aceite é prova legal, então nome e parentesco são obrigatórios.

    CPF é OPCIONAL: a LGPD (art. 14) pede "esforços razoáveis" para verificar que quem
    consentiu é o responsável, e não exige CPF. Nome + parentesco + declaração sob as penas
    da lei + data, hora e IP já formam registro. Quem informa o CPF reforça a identificação;
    quem não informa coleta menos dado de terceiro — que é a direção mais segura em
    minimização. Se vier, tem que ser válido (erro de digitação num registro de prova é pior
    que campo vazio).
    """
    if not (nome or "").strip() or len((nome or "").strip()) < 5:
        return False, "Informe o nome completo do responsável."
    if parentesco not in PARENTESCOS:
        return False, "Informe o parentesco."
    if (cpf or "").strip() and not cpf_valido(cpf):
        return False, "CPF inválido."
    return True, None


def expira_em(criado_em):
    return criado_em + timedelta(days=DIAS_PARA_EXPIRAR)
