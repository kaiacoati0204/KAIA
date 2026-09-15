"""
Thompson Sampling para seleção de intervenções do KaIA.

Bandit Beta-Bernoulli: cada uma das 7 intervenções é um braço Beta(alpha, beta);
amostra os elegíveis pelo estado e escolhe a maior. Reward do aluno (0.0, 0.5 ou
1.0) atualiza alpha/beta. Isolado do app.py; persiste em ml/artifacts/thompson_params.json.
"""
import json
from pathlib import Path

import numpy as np

RANDOM_STATE = 42

# 7 braços com respaldo em pesquisa. badge_foco e comparacao_social saíram por serem
# desaconselhados p/ TEA-TDAH; resolver_rewards tolera tipos antigos em voo.
INTERVENCOES = [
    "auto_monitoramento", "micro_refoco", "checkpoint", "reancoragem",
    "troca_atividade", "pausa_ativa", "alerta_fadiga",
]

# Elegibilidade por estado. engajado NÃO intervém (regra de acessibilidade —
# não interromper aluno focado).
ELEGIVEIS_POR_ESTADO = {
    "distraido": ["auto_monitoramento", "micro_refoco", "checkpoint", "reancoragem", "alerta_fadiga"],
    "muito_distraido": ["troca_atividade", "pausa_ativa", "alerta_fadiga"],
}

# alerta_fadiga só é elegível a partir de tanto tempo de estudo acumulado no dia (1h30).
MIN_ESTUDO_ALERTA_FADIGA_MIN = 90

# Braço recém-usado leva a amostra Beta multiplicada por isto na próxima escolha
# (não repetir o mesmo card seguido -> combate a habituação, à la Duolingo).
PENALIDADE_RECENCIA = 0.5

PARAMS_PATH = Path(__file__).resolve().parent.parent / "ml" / "artifacts" / "thompson_params.json"


class ThompsonSampling:
    """Bandit Beta-Bernoulli com persistência em JSON."""

    def __init__(self, params_path=PARAMS_PATH, seed=RANDOM_STATE):
        self.params_path = Path(params_path)
        self.rng = np.random.default_rng(seed)  # random_state=42 (reprodutível)
        # params[(estado, tipo)], nao params[tipo]: alerta_fadiga vale nos dois estados e a
        # taxa-base de reward muda muito entre eles, entao um posterior unico misturaria contextos.
        self.params = {(e, t): {"alpha": 1.0, "beta": 1.0}
                       for e, ts in ELEGIVEIS_POR_ESTADO.items() for t in ts}
        self.carregar()

    # ------------------------------------------------------------------ persist
    def carregar(self):
        """Carrega alpha/beta do JSON, se existir. Arquivo ausente/corrompido
        mantém os defaults (1.0/1.0)."""
        if self.params_path.exists():
            try:
                dados = json.loads(self.params_path.read_text(encoding="utf-8"))
                for chave in self.params:                    # "estado|tipo" no JSON
                    d = dados.get(f"{chave[0]}|{chave[1]}")
                    if d:
                        self.params[chave]["alpha"] = float(d.get("alpha", 1.0))
                        self.params[chave]["beta"] = float(d.get("beta", 1.0))
            except Exception:
                pass
        return self

    def salvar(self):
        self.params_path.parent.mkdir(parents=True, exist_ok=True)
        self.params_path.write_text(
            json.dumps({f"{e}|{t}": v for (e, t), v in self.params.items()},
                       indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------------- seleção
    def elegiveis(self, estado, tempo_estudo_min):
        """Intervenções elegíveis para o estado, aplicando a regra do alerta_fadiga."""
        elig = list(ELEGIVEIS_POR_ESTADO.get(estado, []))
        if tempo_estudo_min < MIN_ESTUDO_ALERTA_FADIGA_MIN and "alerta_fadiga" in elig:
            elig.remove("alerta_fadiga")
        return elig

    def select(self, estado, tempo_estudo_min, evitar=()):
        """Amostra Beta(alpha,beta) de cada elegível e devolve o de maior amostra.
        Braços em `evitar` (recém-usados) levam PENALIDADE_RECENCIA na amostra — não
        somem, só ficam menos prováveis (se todos estiverem em evitar, ainda escolhe
        o melhor). Retorna None se não houver intervenção elegível."""
        elig = self.elegiveis(estado, tempo_estudo_min)
        if not elig:
            return None
        melhor, melhor_amostra = None, -1.0
        for t in elig:
            p = self.params[(estado, t)]
            amostra = float(self.rng.beta(p["alpha"], p["beta"]))
            if t in evitar:
                amostra *= PENALIDADE_RECENCIA
            if amostra > melhor_amostra:
                melhor, melhor_amostra = t, amostra
        return melhor

    # ------------------------------------------------------------- reconstrucao
    def reconstruir(self, somas):
        """Recalcula alpha/beta a partir dos rewards ja gravados em `interventions`.

        O disco do Render gratuito some a cada hibernacao, e bandit zerado e Beta(1,1)
        (sorteio uniforme). `somas` = {(estado, tipo): (soma_rewards, n)}: alpha = 1 +
        soma, beta = 1 + (n - soma); reward 0.5 e sucesso parcial, como no update().
        NAO persiste: o banco e a fonte da verdade, o arquivo e so cache.
        """
        for chave, (soma, n) in (somas or {}).items():
            if chave not in self.params:
                continue                       # braco aposentado ou contexto invalido
            soma = max(0.0, float(soma))
            n = max(0, int(n))
            self.params[chave]["alpha"] = 1.0 + soma
            self.params[chave]["beta"] = 1.0 + max(0.0, n - soma)
        return self.params

    # -------------------------------------------------------------------- update
    def update(self, estado, tipo_intervencao, reward):
        """Atualiza o braço NAQUELE estado: alpha += reward, beta += (1 - reward)."""
        chave = (estado, tipo_intervencao)
        if chave not in self.params:
            raise ValueError(f"Braço desconhecido: {estado}/{tipo_intervencao}")
        reward = min(max(float(reward), 0.0), 1.0)  # clamp defensivo
        self.params[chave]["alpha"] += reward
        self.params[chave]["beta"] += (1.0 - reward)
        self.salvar()
        return self.params[chave]
