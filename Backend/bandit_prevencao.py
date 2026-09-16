"""
Modelo 2 — bandit de prevenção (Thompson Sampling Beta-Bernoulli, implementação nossa).

Escolhe, numa pausa natural, qual apoio preventivo oferecer. Não é treinado antes: aprende com o
uso. No beta aprende o que funciona EM MÉDIA; personalizar por aluno só com muito mais uso
(Schmucker 2025: com ~1 milhão de alunos, o contextual quase não ganhou do simples).

Três cuidados vindos das pesquisas (Rafferty 2019; Liao 2020; Klasnja 2019):
- probabilidades travadas em [PROB_MIN, PROB_MAX]: nenhum braço some, o efeito continua medível;
- cada escolha devolve a PROBABILIDADE usada, para estimar efeito sem o viés do próprio bandit;
- a média bruta por braço engana (o bandit escolhe mais quem vai bem) — comparar sempre com "nada".

controle = o braço "nada", não um grupo de alunos. A prevenção NÃO usa o A/B 50/50 por aluno:
num beta pequeno ele não tem poder (precisaria de centenas de alunos por meses), e deixar metade
de alunos TEA/TDAH sem apoio o beta inteiro é feio. Com "nada" como braço e piso de PROB_MIN, a
comparação é dentro do mesmo aluno e sorteada por PAUSA: ninguém fica sem apoio o tempo todo, e
o cansaço de fim de sessão cai igual nos dois lados (o que um pré/pós rodada N-1 vs N não dá,
porque N é sempre mais tarde — e a atenção cai com o tempo na tarefa, Farley 2013).
"""
import json
from pathlib import Path

import numpy as np

PARAMS_PREVENCAO_PATH = (Path(__file__).resolve().parent.parent
                         / "ml" / "artifacts" / "bandit_prevencao_params.json")

BRACOS = ["nada", "pacote_foco", "pausa_curta"]
PROB_MIN, PROB_MAX = 0.1, 0.8
# O "nada" e o grupo de comparacao: com piso de 10% sobrariam ~7 pausas de controle num beta
# pequeno, e nada seria comparavel. Piso maior troca velocidade de aprendizado por poder de
# medicao - no beta, medir vale mais que convergir.
PISO_CONTROLE = 0.30
BRACO_CONTROLE = "nada"
AMOSTRAS_PROB = 2000          # sorteios para estimar a chance de cada braço ser o escolhido
# Personalizacao hierarquica: cada aluno COMECA na media do grupo e so se afasta dela conforme
# acumula evidencia propria. FORCA_GRUPO e quantas "observacoes de mentira" do grupo valem como
# ponto de partida - o peso do aluno acaba sendo n/(n+FORCA_GRUPO). Aluno sem historico fica
# IDENTICO ao global, entao isto nunca pode ser pior; e o contextual completo pode (aprende
# ruido). Mesma tecnica que o modelo v2 ja usa para comparar aluno com populacao.
FORCA_GRUPO = 20.0
MIN_RESPONDIDAS = 3           # rodada com menos respostas que isso não diz nada
META_QUESTOES = 10            # rodada completa; acima disso a recompensa não sobe mais
PESO_EVENTO = 2               # cada perda de foco custa 2 questões


def _pisos(bracos):
    """Piso de probabilidade por braco - o controle tem piso maior que os demais."""
    return np.array([PISO_CONTROLE if b == BRACO_CONTROLE else PROB_MIN for b in bracos])


def _travar(p, lo=PROB_MIN, hi=PROB_MAX, rodadas=20):
    """Leva as probabilidades para [lo, hi] mantendo a soma 1. `lo` pode ser vetor (piso por braco).

    Renormalizar dividindo pela soma empurra os pisos para baixo de novo e converge devagar.
    Aqui o excesso sai SO de quem tem folga acima do proprio piso — os pisos ficam exatos.
    """
    p = np.asarray(p, dtype=float)
    lo = np.broadcast_to(np.asarray(lo, dtype=float), p.shape).astype(float)
    for _ in range(rodadas):
        p = np.minimum(np.maximum(p, lo), hi)
        excesso = p.sum() - 1.0
        if abs(excesso) < 1e-12:
            break
        folga = (p - lo) if excesso > 0 else (hi - p)   # quem pode ceder / receber
        total = folga.sum()
        if total <= 0:
            break
        p = p - excesso * folga / total
    return np.minimum(np.maximum(p, lo), hi)


class BanditPrevencao:
    def __init__(self, bracos=BRACOS, semente=None, params_path=None):
        self.bracos = list(bracos)
        self.params = {b: [1.0, 1.0] for b in self.bracos}   # priori fraca e igual (Beta(1,1))
        self.params_aluno = {}                               # {aluno: {braço: [alpha, beta]}}
        self.rng = np.random.default_rng(semente)
        self.params_path = Path(params_path) if params_path else None
        self.carregar()

    # ------------------------------------------------------------------ persistência
    def carregar(self):
        """Sem isto o bandit esquece tudo a cada reinício do servidor e nunca sai do Beta(1,1).
        Arquivo ausente ou corrompido volta ao padrão em vez de derrubar o app."""
        if self.params_path and self.params_path.exists():
            try:
                dados = json.loads(self.params_path.read_text(encoding="utf-8"))
                grupo = dados.get("grupo", dados)     # formato antigo: os braços na raiz
                for b in self.bracos:
                    d = grupo.get(b)
                    if d and len(d) == 2:
                        self.params[b] = [float(d[0]), float(d[1])]
                self.params_aluno = {a: {b: [float(v[0]), float(v[1])] for b, v in m.items()
                                         if b in self.bracos}
                                     for a, m in (dados.get("alunos") or {}).items()}
            except Exception:
                pass
        return self

    def salvar(self):
        if not self.params_path:
            return
        self.params_path.parent.mkdir(parents=True, exist_ok=True)
        self.params_path.write_text(
            json.dumps({"grupo": self.params, "alunos": self.params_aluno}, indent=2),
            encoding="utf-8")

    def reconstruir(self, somas, por_aluno=None):
        """somas = {braço: (soma das recompensas, n)}; por_aluno = {aluno: {braço: (soma, n)}}.
        O JSON é só cache do processo: no plano grátis do Render o disco some a cada hibernação.
        A verdade são os eventos `recompensa_prevencao` gravados."""
        for b, (soma, n) in somas.items():
            if b in self.params and n > 0:
                self.params[b] = [1.0 + float(soma), 1.0 + max(0.0, n - float(soma))]
        for aluno, m in (por_aluno or {}).items():
            do_aluno = self.params_aluno.setdefault(aluno, {b: [1.0, 1.0] for b in self.bracos})
            for b, (soma, n) in m.items():
                if b in self.bracos and n > 0:
                    do_aluno[b] = [1.0 + float(soma), 1.0 + max(0.0, n - float(soma))]
        return self

    # ------------------------------------------------------------- personalização
    def _efetivo(self, braco, aluno):
        """(alpha, beta) do braço para ESTE aluno: a média do grupo entra como priori.

        Sem histórico do aluno, devolve exatamente a média do grupo — por isso personalizar
        aqui não pode ficar pior que o global. A força da priori é limitada pelo que o grupo
        de fato viu (min com n do grupo): no primeiro dia, quando ninguém viu nada, não se
        finge confiança que não existe.
        """
        a_g, b_g = self.params[braco]
        if not aluno:
            return a_g, b_g
        a_i, b_i = self.params_aluno.get(aluno, {}).get(braco, [1.0, 1.0])
        n_g = (a_g + b_g) - 2.0
        forca = min(FORCA_GRUPO, n_g)
        if forca <= 0:
            return a_i, b_i            # grupo ainda nao viu nada: so o que o aluno tem
        # a priori E a media do grupo, com peso `forca`. Somar 1+1 por cima puxaria tudo
        # para 0,5 e o aluno novo nao ficaria igual ao grupo - que e o ponto todo.
        media = a_g / (a_g + b_g)
        return (forca * media + (a_i - 1.0),
                forca * (1.0 - media) + (b_i - 1.0))

    def probabilidades(self, aluno=None):
        """Chance de cada braço sair no Thompson, já travada. Vetor na ordem de self.bracos."""
        amostras = np.column_stack([self.rng.beta(*self._efetivo(b, aluno), AMOSTRAS_PROB)
                                    for b in self.bracos])
        vencedores = np.bincount(amostras.argmax(axis=1), minlength=len(self.bracos))
        return _travar(vencedores / AMOSTRAS_PROB, _pisos(self.bracos))

    def escolher(self, aluno=None):
        """(braço, probabilidade com que foi escolhido) — a probabilidade vai para o registro."""
        p = self.probabilidades(aluno)
        i = int(self.rng.choice(len(self.bracos), p=p))
        return self.bracos[i], float(p[i])

    def atualizar(self, braco, recompensa, aluno=None):
        """Toda rodada conta DUAS vezes: para o grupo e para o aluno. O grupo é o que faz um
        aluno novo já começar em algum lugar razoável."""
        if recompensa is None:
            return
        r = min(max(float(recompensa), 0.0), 1.0)
        self.params[braco][0] += r
        self.params[braco][1] += 1.0 - r
        if aluno:
            do_aluno = self.params_aluno.setdefault(aluno, {b: [1.0, 1.0] for b in self.bracos})
            do_aluno.setdefault(braco, [1.0, 1.0])
            do_aluno[braco][0] += r
            do_aluno[braco][1] += 1.0 - r
        self.salvar()          # grava sempre: esquecer uma rodada é pior que o custo do write


def recompensa_rodada(eventos_objetivos, respondidas, abandonou):
    """Recompensa da rodada seguinte à escolha: questões feitas COM foco, com teto na rodada.

    `eventos_objetivos` conta SÓ risco.evento_objetivo (saída >= 30 s, abandono, regra DTS). Probe
    de autorrelato NUNCA entra aqui: premiar o bandit por uma medida que depende do aluno declarar
    o próprio estado traria de volta, por dentro da recompensa, a parte que não sabemos medir.

    Não é taxa de eventos por questão: pela taxa, o braço que encurta a rodada ganha só porque o
    aluno estudou menos (a simulação mostra o bandit convergindo em "sempre mandar parar"). Aqui a
    pausa só compensa se o aluno voltar e completar. O teto em META_QUESTOES evita o contrário,
    premiar maratona. Abandono vale 0; rodada curta demais não avalia (None).
    10 questões com 1 evento = 0,8; com 5 eventos = 0."""
    if abandonou:
        return 0.0
    if respondidas < MIN_RESPONDIDAS:
        return None
    focadas = max(0.0, respondidas - PESO_EVENTO * eventos_objetivos)
    return round(min(1.0, focadas / META_QUESTOES), 3)
