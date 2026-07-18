"""
Thompson Sampling para seleção de intervenções do KaIA (Sprint 3, Tarefa 3).

Multi-armed bandit Beta-Bernoulli: cada uma das 9 intervenções é um "braço"
com uma distribuição Beta(alpha, beta). A cada decisão, amostramos uma vez de
cada braço ELEGÍVEL (filtrado pelo estado do aluno) e escolhemos o de maior
amostra — equilibra exploração e explotação. O reward do feedback do aluno
(0.0, 0.5 ou 1.0) atualiza alpha/beta.

Módulo isolado (não depende do app.py). Persistência em
ml/artifacts/thompson_params.json.
"""
import json
from pathlib import Path

import numpy as np

RANDOM_STATE = 42

# As 9 intervenções do documento.
INTERVENCOES = [
    "nudge_refoco", "pausa_pomodoro", "mensagem_motivacional",
    "troca_atividade", "pausa_ativa", "microlearning",
    "alerta_fadiga", "badge_foco", "comparacao_social",
]

# Elegibilidade por estado do aluno.
ELEGIVEIS_POR_ESTADO = {
    "engajado": ["badge_foco"],
    "distraido": ["nudge_refoco", "pausa_pomodoro", "mensagem_motivacional", "alerta_fadiga"],
    "muito_distraido": ["troca_atividade", "pausa_ativa", "microlearning", "alerta_fadiga"],
}

# alerta_fadiga só é elegível a partir deste nº de sessões no dia.
MIN_SESSOES_ALERTA_FADIGA = 3

# Caminho padrão dos parâmetros persistidos.
PARAMS_PATH = Path(__file__).resolve().parent.parent / "ml" / "artifacts" / "thompson_params.json"


class ThompsonSampling:
    """Bandit Beta-Bernoulli com persistência em JSON."""

    def __init__(self, params_path=PARAMS_PATH, seed=RANDOM_STATE):
        self.params_path = Path(params_path)
        self.rng = np.random.default_rng(seed)  # random_state=42 (reprodutível)
        # params[tipo] = {"alpha": float, "beta": float}, ambos iniciados em 1.0
        self.params = {t: {"alpha": 1.0, "beta": 1.0} for t in INTERVENCOES}
        self.carregar()

    # ------------------------------------------------------------------ persist
    def carregar(self):
        """Carrega alpha/beta do JSON, se existir. Arquivo ausente/corrompido
        mantém os defaults (1.0/1.0)."""
        if self.params_path.exists():
            try:
                dados = json.loads(self.params_path.read_text(encoding="utf-8"))
                for t in INTERVENCOES:
                    if t in dados:
                        self.params[t]["alpha"] = float(dados[t].get("alpha", 1.0))
                        self.params[t]["beta"] = float(dados[t].get("beta", 1.0))
            except Exception:
                pass
        return self

    def salvar(self):
        self.params_path.parent.mkdir(parents=True, exist_ok=True)
        self.params_path.write_text(
            json.dumps(self.params, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------------- seleção
    def elegiveis(self, estado, sessoes_no_dia):
        """Intervenções elegíveis para o estado, aplicando a regra do alerta_fadiga."""
        elig = list(ELEGIVEIS_POR_ESTADO.get(estado, []))
        if sessoes_no_dia < MIN_SESSOES_ALERTA_FADIGA and "alerta_fadiga" in elig:
            elig.remove("alerta_fadiga")
        return elig

    def select(self, estado, sessoes_no_dia):
        """Amostra Beta(alpha,beta) de cada elegível e devolve o de maior amostra.
        Retorna None se não houver intervenção elegível."""
        elig = self.elegiveis(estado, sessoes_no_dia)
        if not elig:
            return None
        melhor, melhor_amostra = None, -1.0
        for t in elig:
            amostra = float(self.rng.beta(self.params[t]["alpha"], self.params[t]["beta"]))
            if amostra > melhor_amostra:
                melhor, melhor_amostra = t, amostra
        return melhor

    # -------------------------------------------------------------------- update
    def update(self, tipo_intervencao, reward):
        """Atualiza o braço: alpha += reward, beta += (1 - reward). Persiste."""
        if tipo_intervencao not in self.params:
            raise ValueError(f"Intervenção desconhecida: {tipo_intervencao}")
        reward = min(max(float(reward), 0.0), 1.0)  # clamp defensivo
        self.params[tipo_intervencao]["alpha"] += reward
        self.params[tipo_intervencao]["beta"] += (1.0 - reward)
        self.salvar()
        return self.params[tipo_intervencao]
