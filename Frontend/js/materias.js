// ============================================================
//  KaIA — materias.js: página de estudo (sessão, sensores, missão/quiz,
//  pomodoro, caderno, intervenções)
// ============================================================
// Depende de comum.js (API_URL, $, $$, apiFetch, postJSON, userId, lerHobbies),
// carregado ANTES deste arquivo. Só materias.html usa.

// --- Estado da sessão -------------------------------------------------------
// session_id: criado via POST /sessions, vive no sessionStorage (1 por aba).
// user_id: identidade estável do aluno, vive no localStorage (até o Supabase Auth).
let sessionId       = sessionStorage.getItem('kaia_session_id') || null;
let isMissionActive = false;
// Cobre a sessão de estudo INTEIRA (tema → questão → explicação), inclusive
// depois de responder (quando isMissionActive já é false). Só zera em ABANDONAR
// / Sair. É o gate do exit-intent — não confundir com isMissionActive (sensores).
let sessaoDeEstudoAberta = false;
let idleInterval    = null;

// --- Estado dos sensores ----------------------------------------------------
let idleTime        = 0;
let dynamicLimit    = 10;
let focusLostAt     = null;
let mudancasAba     = 0;
let questionShownAt = 0;
let firstInteractionAt = 0;   // 1ª interação com a questão → tempo_iniciacao_resposta_ms
let mouseSamples = [];        // trajeto do mouse na questão: [dt_ms, x, y] (features de mouse no Incr. B)
let lastMouseSampleAt = 0;    // throttle da amostragem do mouse
let tempoOciosoMs = 0;  // tempo ocioso COM a aba focada, na questão (proxy do estado interno)
let mexeuDesdeUltimoTick = false;  // houve mousemove desde o último tick do idle?
let tempoDwellMs = 0;   // tempo com o cursor sobre as alternativas SEM responder (hesitação)
let dwellEntrouEm = 0;  // performance.now() de quando o cursor entrou nas alternativas (0 = fora)
let currentQuestion = null;
let currentSubject  = null;   // matéria/tema da questão atual — para "Próxima questão"
let currentTema     = null;
let temasAtuais     = [];     // temas da matéria atual (p/ "troca de tema" reengajar por novidade)
let historicoQuestoes = [];   // questões já respondidas na sessão (fonte do checkpoint de recuperação)

// ============================================================
//                        SESSÃO
// ============================================================
// Cria uma NOVA sessão (1 por missão): não envia session_id, o backend gera.
async function criarSessao() {
    try {
        const data = await postJSON('/sessions', { user_id: userId });
        sessionId = data.session_id;
        console.log('[KaIA] Nova sessão:', sessionId, '| user:', userId);
    } catch (e) {
        // Fallback offline: o backend auto-cria a sessão no /events.
        sessionId = crypto.randomUUID();
        console.warn('[KaIA] /sessions indisponível, usando id local:', sessionId, e);
    }
    sessionStorage.setItem('kaia_session_id', sessionId);
    return sessionId;
}

// Grava session_end_ts. sendBeacon sobrevive ao fechamento da aba.
function encerrarSessao() {
    if (!sessionId) return;
    const url = `${API_URL}/sessions/${sessionId}/end`;
    if (navigator.sendBeacon) navigator.sendBeacon(url);
    else fetch(url, { method: 'POST', keepalive: true }).catch(() => {});
}

function logEvent(type, payload) {
    // (gatilho de teste) — REMOVER junto com o bloco do gatilho. Marca o que
    // acontece durante uma intervenção de teste, para dar para filtrar depois.
    if (typeof _intervencaoDeTeste !== 'undefined' && _intervencaoDeTeste) {
        payload = { ...(payload || {}), origem: 'gatilho_teste' };
    }
    const event = { session_id: sessionId, ts: new Date().toISOString(), event_type: type, payload };
    console.log('[KaIA Event]', event);
    postJSON('/events', event, true).catch(() => {});
}

// ============================================================
//        INTERVENÇÕES (polling /intervencao/pendente + feedback)
// ============================================================
let intervencaoInterval   = null;
let intervencaoAtual      = null;   // tipo em exibição (evita duplicar)
let intervencaoMostradaEm = 0;      // p/ calcular tempo_ate_aceitar_s

// Sorteia uma variação (usado nas frases das intervenções — evita repetir sempre
// a mesma, combatendo a habituação).
const _variar = (a) => a[Math.floor(Math.random() * a.length)];

// ============================================================
//   TODO: ajustar tempo pra produção — TEMPOS DE TESTE
// ============================================================
// Enquanto o visual das 7 está sendo calibrado, TODOS os tempos das
// intervenções estão encurtados: com os valores reais, ver uma pausa ativa
// inteira custa 90 segundos por rodada de ajuste.
//
// COMO RESTAURAR: troque TEMPOS_DE_TESTE para false. Só isso. Cada chamada de
// T() carrega os DOIS valores — T(teste, produção) — então o valor real nunca
// se perdeu, está ali do lado. Todos os pontos afetados carregam o comentário
// "TODO: ajustar tempo pra produção", então um grep por esse texto lista a
// lista inteira.
//
// Os tempos de PRODUÇÃO abaixo são os que estavam valendo antes desta fase e
// ainda NÃO foram calibrados de verdade — isso é etapa própria, com dados de
// uso. Não trate a segunda coluna como número final.
const TEMPOS_DE_TESTE = true;
const T = (teste, producao) => (TEMPOS_DE_TESTE ? teste : producao);

// ============================================================
//   ÍCONES DAS 7 — trocar aqui pelos ícones da marca
// ============================================================
// Substituem os emojis dos títulos. Emoji renderiza diferente em cada sistema
// operacional e nenhum deles é da marca; estes são SVG de traço, no mesmo
// vocabulário dos ícones da rail (comum.js), herdando cor via currentColor.
//
// PARA TROCAR: substitua o SVG da entrada correspondente. Só isso — o CSS
// (.kaia-ic no style.css) cuida de tamanho, cor e alinhamento, e nenhuma outra
// parte do código conhece os desenhos.
//
// NOTA: os emojis que aparecem DENTRO do texto dos passos (🙆 👀 💧 🌬️ em
// PAUSA_ATIVA_PASSOS) continuam como estão — são conteúdo da instrução, não
// identidade da intervenção. Dá para trocar também, é só pedir.
const ICONES_INTERVENCAO = {
    // bússola — "onde está sua atenção agora?"
    auto_monitoramento: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/></svg>',
    // lua — cansaço
    alerta_fadiga:      '<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>',
    // onda de respiração
    micro_refoco:       '<svg viewBox="0 0 24 24"><path d="M3 12h3l2-4 3 8 2.5-6 1.5 2h6"/></svg>',
    // figura em movimento
    pausa_ativa:        '<svg viewBox="0 0 24 24"><circle cx="12" cy="4.5" r="2"/><path d="M12 8v6"/><path d="m7 10 5-2 5 2"/><path d="m9 21 3-7 3 7"/></svg>',
    // duas setas em ciclo
    troca_atividade:    '<svg viewBox="0 0 24 24"><path d="M3 11a8 8 0 0 1 13.5-5.5L21 9"/><polyline points="21 4 21 9 16 9"/><path d="M21 13a8 8 0 0 1-13.5 5.5L3 15"/><polyline points="3 20 3 15 8 15"/></svg>',
    // alvo — recuperar o que já viu
    checkpoint:         '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/></svg>',
    // âncora
    reancoragem:        '<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="2"/><path d="M12 7v14"/><path d="M6 11h12"/><path d="M4 15a8 8 0 0 0 16 0"/></svg>',
};

// Devolve o <span> do ícone pronto. `chip` põe o ícone num quadrado de bege
// (usado nos dois overlays, onde ele é o único elemento gráfico do card).
function _iconeHTML(tipo, chip = false) {
    const svg = ICONES_INTERVENCAO[tipo];
    if (!svg) return '';
    return `<span class="kaia-ic${chip ? ' kaia-ic-chip' : ''}" aria-hidden="true">${svg}</span>`;
}

// Copy dos braços que renderizam como CARD de texto. Os demais do alvo
// (micro_refoco, pausa_ativa, troca_atividade, checkpoint, reancoragem) são AÇÃO —
// mostrarIntervencao desvia antes deste lookup. `texto` é uma LISTA: sorteia uma
// frase a cada disparo. Adicionar/editar frases aqui.
// `titulo` e `texto` são LISTAS: cada disparo sorteia um de cada, então o card
// muda de cabeçalho E de corpo. Combinado com a rotação de POSIÇÃO (POSICOES_CARD,
// abaixo), duas aparições seguidas nunca são iguais nem no lugar nem no que dizem
// — que é o que impede o card de virar banner ignorado.
// Tom das listas: nomear o que está acontecendo sem cobrar, sem urgência e sem
// prometer resultado. Nada de "você precisa", "foque!" ou exclamação dupla.
// Para editar: acrescenta ou troca linhas aqui, nada mais depende disso.
const INTERVENCOES_MSG = {
    auto_monitoramento: {
        titulo: [
            'Como está seu foco?',
            'Só um instante',
            'Pausa de um segundo',
            'E aí, ainda por aqui?',
            'Um respiro rápido',
        ],
        texto: [
            'Se a mente vagou, tudo bem — perceber já ajuda. Bora focar nas próximas 3?',
            'Deu uma dispersada? Acontece. Reancora nas próximas 3 questões.',
            'Notou que saiu do foco? Só de perceber você já voltou.',
            'Tudo bem divagar. Respira e escolhe voltar pra questão.',
            'A atenção vai e volta o dia inteiro. Agora ela pode voltar.',
            'Sem cobrança: só um lembrete de que a questão continua aí.',
            'Reparar que se distraiu é metade do caminho de volta.',
            'Onde estava sua cabeça? Não precisa responder — só voltar.',
            'A próxima questão é um recomeço. Não precisa de impulso nenhum.',
            'Perder o fio é normal. Pegar de novo também.',
            'Você não precisa de foco perfeito. Só do próximo passo.',
            'Se travou nesta questão, tudo bem pular e voltar depois.',
        ],
    },
    alerta_fadiga: {
        titulo: [
            'Sinais de cansaço',
            'Seu ritmo caiu',
            'Já foi bastante',
            'Hora de desacelerar?',
            'O corpo está avisando',
        ],
        texto: [
            'Talvez seja hora de um descanso de verdade.',
            'Você já estudou bastante hoje — que tal uma pausa maior?',
            'Cansaço é sinal de que rendeu. Vale descansar um pouco.',
            'Seu foco pede uma pausa de verdade. Sem culpa.',
            'Insistir cansado costuma render menos que voltar depois.',
            'Parar agora não apaga o que você já fez hoje.',
            'Descansar faz parte de estudar. Não é o contrário.',
            'O que você aprendeu hoje continua aí amanhã.',
            'Uma pausa longa agora pode valer mais que dez questões.',
            'Seu corpo pediu primeiro. Vale escutar.',
            'Estudar cansado vira releitura. Melhor voltar inteiro.',
            'Sem meta a bater agora. Pode ir descansar.',
        ],
    },
};

// Pilha de notificações no canto inferior direito (card de intervenção + avisos):
// novas entram embaixo e empurram as antigas pra cima (não se sobrepõem).
function _pilhaNotif() {
    let c = $('kaia-notificacoes');
    if (!c) {
        c = document.createElement('div');
        c.id = 'kaia-notificacoes';
        document.body.appendChild(c);
    }
    return c;
}

// ---- Strip de feedback ("isso ajudou?") — reutilizável em TODA intervenção ----
// Fase 2. O tipo e o instante de exibição ficam FECHADOS no closure, não lidos do
// global: as intervenções de AÇÃO já liberaram o polling (intervencaoAtual = null)
// quando o strip aparece, e ler o global ali perderia o feedback em silêncio.
//
// O CSS de TODAS as intervenções (este strip, os cards, os overlays) mora no
// style.css, seção "INTERVENÇÕES". Antes era injetado daqui em template string;
// mudou de lugar para poder ser editado como CSS de verdade. Este arquivo só
// monta os elementos e aplica as classes.

// Bloco pronto: rótulo opcional + os 3 botões. `agradecer` troca o strip por um
// "valeu" ao responder — nos cards do polling isso não faz sentido (o card some na
// hora), então lá fica false + onResposta: esconderIntervencao.
function _stripFeedback(tipo, { compacto = false, rotulo = '', mostradaEm = 0,
                               agradecer = false, onResposta = null } = {}) {
    const wrap = document.createElement('div');
    wrap.className = 'kaia-fb-wrap';
    if (rotulo) {
        const l = document.createElement('p');
        l.className = 'kaia-fb-rotulo';
        l.textContent = rotulo;
        wrap.appendChild(l);
    }
    const strip = document.createElement('div');
    strip.className = compacto ? 'kaia-fb kaia-fb-compacto' : 'kaia-fb';
    [['k1', 1.0, 'Ajudou 👍'], ['k2', 0.5, 'Mais ou menos'], ['k3', 0.0, 'Não 👎']]
        .forEach(([cls, reward, texto]) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = cls;
            b.textContent = texto;
            b.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                enviarFeedbackIntervencao(tipo, reward, mostradaEm);
                if (agradecer) {
                    wrap.textContent = '';
                    const ok = document.createElement('p');
                    ok.className = 'kaia-fb-obrigado';
                    ok.textContent = 'Valeu! 💛';
                    wrap.appendChild(ok);
                }
                if (onResposta) onResposta(reward);
            });
            strip.appendChild(b);
        });
    wrap.appendChild(strip);
    return wrap;
}

// ---- Onde o card aparece, e por que não é sempre no mesmo canto ------------
// Dispensar o card aqui é RESPONDER o feedback (não há X): um clique no
// automático não desperdiça só a intervenção, ele injeta recompensa falsa no
// Thompson — e como os 3 botões saem sempre na mesma ordem, o reflexo acerta
// sempre a mesma resposta, o que é viés e não ruído.
// O reflexo se prende a um PONTO da tela. Então o REPERTÓRIO de zonas é fixo e
// pequeno (achar continua barato: são sempre os mesmos 6 lugares, todos na
// metade de baixo) e o ponto dentro dele roda. Em ORDEM, e não por sorteio:
// sorteio repetiria o mesmo canto ~1/6 das vezes, e é na repetição que o
// reflexo se forma.
// São 3 colunas x 2 linhas. A ordem abaixo é escolhida a dedo para que zonas
// CONSECUTIVAS mudem de coluna E de linha — o salto entre uma aparição e a
// seguinte é sempre o maior possível. As classes moram no style.css, junto com
// as medidas que provam que nenhuma zona toca a questão nem a barra lateral.
const POSICOES_CARD = [
    ['pos-esq'],                  // inferior esquerda
    ['pos-centro', 'pos-alta'],   // meio-alta, centro
    ['pos-dir'],                  // inferior direita
    ['pos-esq', 'pos-alta'],      // meio-alta, esquerda
    ['pos-centro'],               // inferior centro
    ['pos-dir', 'pos-alta'],      // meio-alta, direita
];
const _TODAS_POSICOES = POSICOES_CARD.flat();

// O índice VIVE ENTRE SESSÕES. Com teto de 5 intervenções por sessão e só 2 dos
// 7 braços sendo card, o aluno vê ~1 card por sessão: se o índice zerasse a cada
// carregamento, ele cairia SEMPRE na primeira zona — a rotação existiria no
// código e não na experiência, que é exatamente o reflexo que ela veio evitar.
const POS_CARD_CHAVE = 'kaia_pos_card_idx';
let _posicaoCardIdx = parseInt(localStorage.getItem(POS_CARD_CHAVE), 10);
if (!Number.isInteger(_posicaoCardIdx)) _posicaoCardIdx = -1;

const _probeNaTela = () => {
    const p = $('kaia-probe');
    return !!p && getComputedStyle(p).display !== 'none';
};

function _posicionarPilhaNotif() {
    const pilha = _pilhaNotif();
    // O toast da meta diária divide este contêiner. Se ele estiver na tela,
    // mover a pilha arrastaria o aviso junto — fica onde está (e a rotação não
    // avança, para o próximo card ainda cair num lugar diferente deste).
    if ([...pilha.children].some(el => el.id !== 'kaia-intervencao')) return;
    for (let i = 0; i < POSICOES_CARD.length; i++) {
        _posicaoCardIdx = (_posicaoCardIdx + 1) % POSICOES_CARD.length;
        const zona = POSICOES_CARD[_posicaoCardIdx];
        // O probe de autorrelato mora embaixo no centro e gera o rótulo do
        // modelo: o card (z-index 9999) o taparia. Só a zona centro-BAIXA
        // conflita — a centro-alta passa bem acima dele.
        if (zona.includes('pos-centro') && !zona.includes('pos-alta') && _probeNaTela()) continue;
        break;
    }
    localStorage.setItem(POS_CARD_CHAVE, String(_posicaoCardIdx));
    pilha.classList.remove(..._TODAS_POSICOES);
    pilha.classList.add(...POSICOES_CARD[_posicaoCardIdx]);
}

// Portão antes de o feedback aceitar clique. Vale para TODO card, não só o
// primeiro da sessão: com teto de 5 intervenções por sessão (app.py) e só 2 dos
// 7 arms sendo card, o aluno vê ~1 card por sessão — o reflexo não se forma
// DENTRO da sessão, vem das anteriores. Gatear "só o primeiro" seria quase o
// mesmo na prática e deixaria o card com dois comportamentos para o mesmo
// visual, que é a inconsistência que atrapalha TEA/TDAH.
const CARD_GATE_MS = T(350, 900);   // TODO: ajustar tempo pra produção

function _travarFeedbackDoCard(alvo) {
    const strip = alvo.querySelector('.kaia-fb');
    if (!strip) return;
    const botoes = [...strip.querySelectorAll('button')];
    strip.classList.add('kaia-fb-travado');
    // `disabled` e não só pointer-events: trava o teclado também e o leitor de
    // tela anuncia que ainda não dá para responder.
    botoes.forEach(b => b.disabled = true);
    setTimeout(() => {
        strip.classList.remove('kaia-fb-travado');
        botoes.forEach(b => b.disabled = false);
    }, CARD_GATE_MS);
}

// Card do polling: casca fixa (o strip é remontado a cada disparo em
// mostrarIntervencao, porque o tipo muda e o elemento é reaproveitado).
function _garantirCardIntervencao() {
    if ($('kaia-intervencao')) return;
    const card = document.createElement('div');
    card.id = 'kaia-intervencao';
    card.className = 'kaia-card-notif';
    card.innerHTML = `<h4 id="kaia-int-titulo"></h4><p id="kaia-int-texto"></p>
      <div id="kaia-int-fb"></div>`;
    _pilhaNotif().appendChild(card);
}

function mostrarIntervencao(intv) {
    intervencaoAtual = intv.intervention_type;   // trava o polling até resolver
    intervencaoMostradaEm = performance.now();
    if (intv.intervention_type === 'pausa_ativa')     { iniciarPausaAtiva();      return; }   // ação, não card
    if (intv.intervention_type === 'micro_refoco')    { iniciarMicroRefoco();     return; }
    if (intv.intervention_type === 'troca_atividade') { mostrarTrocaTema();       return; }
    if (intv.intervention_type === 'checkpoint')      { checkpointRecuperacao();  return; }
    if (intv.intervention_type === 'reancoragem')     { reancorarDestaque();      return; }
    _garantirCardIntervencao();
    const info = INTERVENCOES_MSG[intv.intervention_type]
              || { titulo: 'Dica', texto: 'Continue focado!' };
    // titulo e texto aceitam string OU lista — o fallback acima ainda é string.
    const _um = (v) => (Array.isArray(v) ? _variar(v) : v);
    // innerHTML só para o ÍCONE (SVG nosso, constante); o título entra por
    // append, que cria nó de texto e não interpreta marcação.
    const tit = $('kaia-int-titulo');
    tit.innerHTML = _iconeHTML(intv.intervention_type);
    tit.append(' ' + _um(info.titulo));
    $('kaia-int-texto').innerText  = _um(info.texto);
    const fb = $('kaia-int-fb');
    fb.textContent = '';
    fb.appendChild(_stripFeedback(intv.intervention_type, {
        mostradaEm: intervencaoMostradaEm, onResposta: esconderIntervencao,
    }));
    _posicionarPilhaNotif();
    _travarFeedbackDoCard(fb);
    $('kaia-intervencao').style.display = 'block';
}

// Esconder o card e liberar o polling eram a MESMA coisa; separá-los é o que
// permite pedir feedback depois que a intervenção de ação já acabou, sem deixar
// o polling travado enquanto o strip espera (aluno pode simplesmente ignorar).
function liberarPolling() { intervencaoAtual = null; }

function esconderIntervencao() {
    const c = $('kaia-intervencao');
    if (c) c.style.display = 'none';
    liberarPolling();
}

async function enviarFeedbackIntervencao(tipo, reward, mostradaEm = intervencaoMostradaEm) {
    if (!tipo) return;
    // (gatilho de teste) — REMOVER junto com o bloco do gatilho.
    // Intervenção que a Bia disparou para ver o design não pode virar recompensa
    // no Thompson: seria dado inventado alimentando o modelo.
    if (_intervencaoDeTeste) {
        console.log('[KaIA] (teste) feedback NÃO enviado:', tipo, reward);
        return;
    }
    const tempo = mostradaEm ? (performance.now() - mostradaEm) / 1000 : null;
    try {
        await postJSON('/intervencao/feedback', {
            session_id: sessionId, intervention_type: tipo,
            reward, tempo_ate_aceitar_s: tempo
        });
        console.log('[KaIA] feedback enviado:', tipo, reward);
    } catch (e) { console.warn('[KaIA] falha no feedback:', e); }
}

// Feedback ATRASADO: pergunta "ajudou?" um tempo DEPOIS, quando o aluno já pôde
// sentir o efeito (caso da troca de tema). Card próprio — o #kaia-intervencao é do
// polling e pode já estar ocupado por outra intervenção quando este disparar.
let _fbTardioTimer = null;

function _feedbackTardio(tipo, { titulo, pergunta, atrasoMs, mostradaEm, vidaMs = 45000,
                                 icone = null }) {
    clearTimeout(_fbTardioTimer);
    _fbTardioTimer = setTimeout(() => {
        // sessaoDeEstudoAberta (não isMissionActive): o aluno pode estar lendo a
        // explicação da questão, o que já zerou isMissionActive — e ainda vale perguntar.
        if (!sessaoDeEstudoAberta || !sessionId) return;
        const card = document.createElement('div');
        card.className = 'kaia-card-notif';
        const h = document.createElement('h4');
        h.innerHTML = icone ? _iconeHTML(icone) : '';   // SVG constante nosso
        h.append(icone ? ' ' + titulo : titulo);        // nó de texto, sem marcação
        const p = document.createElement('p');
        p.textContent = pergunta;
        const sumir = () => card.remove();
        card.append(h, p, _stripFeedback(tipo, {
            mostradaEm, agradecer: true, onResposta: () => setTimeout(sumir, 1200),
        }));
        _pilhaNotif().appendChild(card);
        setTimeout(sumir, vidaMs);      // ignorado: some sozinho, sem cobrar resposta
    }, atrasoMs);
}

function iniciarPollIntervencao() {
    clearInterval(intervencaoInterval);
    esconderIntervencao();
    intervencaoInterval = setInterval(async () => {
        if (!isMissionActive) { clearInterval(intervencaoInterval); return; }
        if (intervencaoAtual || !sessionId) return;   // já há uma aguardando feedback
        try {
            const r = await apiFetch(`/intervencao/pendente?session_id=${sessionId}`);
            const data = await r.json();
            if (data && data.pendente) {
                _intervencaoDeTeste = false;   // (gatilho de teste) veio do motor real
                mostrarIntervencao(data.pendente);
            }
        } catch (_) { /* silencioso */ }
        // TODO: ajustar tempo pra produção — 4s no teste (a intervenção aparece
        // quase na hora, dá pra iterar no visual), 15s de verdade.
    }, T(4000, 15000));
}

// =============================================================================
// ===== GATILHO DE TESTE (PROVISÓRIO) — REMOVER, o Vitor faz o motor real =====
// =============================================================================
// POR QUE EXISTE: as 7 intervenções não disparam sozinhas porque o motor de
// decisão ainda não existe. Este bloco é uma muleta para a Bia CONSEGUIR VER as
// intervenções acontecendo no fluxo real e validar o design. Não é heurística,
// não é modelo, não pretende ser: é "ficou parado N segundos, mostra a próxima
// da fila".
//
// COMO REMOVER (3 passos, nada mais depende disto):
//   1. apague este bloco inteiro;
//   2. apague a linha `iniciarGatilhoTeste();` (junto de iniciarPollIntervencao);
//   3. apague o guarda marcado "(gatilho de teste)" em enviarFeedbackIntervencao
//      e a linha `_intervencaoDeTeste = false;` em iniciarPollIntervencao.
//
// COMO DESLIGAR SEM APAGAR: GATILHO_TESTE = false. Ou, no console do navegador,
// kaiaGatilhoTeste(false).
//
// NÃO CONTAMINA O DADO: toda intervenção nascida daqui é marcada em
// _intervencaoDeTeste, e enviarFeedbackIntervencao NÃO envia o feedback nesse
// caso — o Thompson do backend não recebe recompensa de intervenção falsa. Os
// eventos que passarem por logEvent durante uma delas vão marcados com
// origem: 'gatilho_teste' no payload, para dar para filtrar depois.
const GATILHO_TESTE = true;

// TODO: ajustar tempo pra produção — não se aplica: isto sai antes da produção.
const GATILHO_TESTE_IDLE_S   = 9;      // segundos de inatividade até disparar
const GATILHO_TESTE_ESPERA_MS = 12000; // intervalo mínimo entre dois disparos

// A fila roda em ordem para a Bia ver as 7 sem depender de sorte.
const GATILHO_TESTE_ORDEM = [
    'auto_monitoramento', 'micro_refoco', 'alerta_fadiga', 'reancoragem',
    'checkpoint', 'pausa_ativa', 'troca_atividade',
];

let _gtIdx           = -1;
let _gtInterval      = null;
let _gtUltimoEm      = 0;
let _intervencaoDeTeste = false;   // lido por enviarFeedbackIntervencao e logEvent

// ---- Dock de botões: uma bolinha por intervenção --------------------------
// Só existe com GATILHO_TESTE ligado; no modo normal nem é criado.
// O CSS mora AQUI, injetado, e não no style.css — de propósito. A convenção do
// projeto é o contrário (CSS das intervenções foi todo para o style.css), mas
// isto é ferramenta de teste descartável: mantendo estilo e marcação no mesmo
// bloco, remover é apagar UM trecho, sem deixar regra órfã na folha de estilo.
//
// Fica no topo, encostado depois da rail: a faixa y 0→63 é a única área grande
// que não é usada nem pela questão (começa em 136) nem pelas 6 zonas dos cards
// (metade de baixo) nem pelos botões Caderno/ABANDONAR (x 984→1220).
function _montarDockTeste() {
    if (!GATILHO_TESTE || $('kaia-dock-teste')) return;

    const st = document.createElement('style');
    st.id = 'kaia-dock-teste-css';
    st.textContent = `
      #kaia-dock-teste {
        position: fixed; top: 10px; left: calc(var(--rail-col) + 12px);
        z-index: 10000;                      /* acima de tudo, inclusive dos cards (9999) */
        display: flex; align-items: center; gap: 6px;
        padding: 5px 8px; border-radius: 999px;
        background: var(--card); border: 1px dashed var(--bege-forte);
        box-shadow: 0 4px 14px rgba(var(--profundo-rgb), 0.12);
        transition: left 0.25s ease, opacity 0.2s ease;
        opacity: 0.55;
      }
      #kaia-dock-teste:hover { opacity: 1; }
      body.rail-aberta #kaia-dock-teste { left: calc(var(--rail-col-aberta) + 12px); }
      #kaia-dock-teste .dk-rot {
        color: var(--bege-tinta); font-size: 9px; font-weight: 800;
        letter-spacing: 0.12em; padding-right: 2px;
      }
      #kaia-dock-teste button {
        display: inline-flex; align-items: center; justify-content: center;
        width: 26px; height: 26px; padding: 0;
        border: 1px solid var(--bege-linha); border-radius: 50%;
        background: var(--bege-veu); color: var(--bege-tinta); cursor: pointer;
        transition: background-color 0.15s ease, color 0.15s ease;
      }
      #kaia-dock-teste button:hover { background: var(--bege-forte); color: var(--card); }
      #kaia-dock-teste button:focus-visible { outline: 2px solid var(--profundo); outline-offset: 2px; }
      #kaia-dock-teste button svg { width: 15px; height: 15px; fill: none;
        stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    `;
    document.head.appendChild(st);

    const dock = document.createElement('div');
    dock.id = 'kaia-dock-teste';
    dock.innerHTML = '<span class="dk-rot">TESTE</span>';
    GATILHO_TESTE_ORDEM.forEach(tipo => {
        const b = document.createElement('button');
        b.type = 'button';
        b.title = tipo.replace(/_/g, ' ');       // tooltip com o nome
        b.setAttribute('aria-label', `Disparar ${tipo}`);
        b.innerHTML = ICONES_INTERVENCAO[tipo] || '';
        b.addEventListener('click', () => {
            // fecha o que estiver aberto antes, senão o clique não faz nada
            esconderIntervencao();
            dispararIntervencaoTeste(tipo);
        });
        dock.appendChild(b);
    });
    document.body.appendChild(dock);
}

function iniciarGatilhoTeste() {
    if (!GATILHO_TESTE) return;
    _montarDockTeste();
    clearInterval(_gtInterval);
    console.log('[KaIA] GATILHO DE TESTE ligado — %ds parado dispara a próxima das 7. '
              + 'No console: kaiaTestar() lista, kaiaTestar("checkpoint") dispara uma, '
              + 'kaiaGatilhoTeste(false) desliga.', GATILHO_TESTE_IDLE_S);
    _gtInterval = setInterval(() => {
        if (!GATILHO_TESTE) return;
        if (!isMissionActive || pausaAtiva) return;   // não invade pausa/descanso
        if (intervencaoAtual) return;                 // já tem uma na tela
        if (idleTime < GATILHO_TESTE_IDLE_S) return;
        if (performance.now() - _gtUltimoEm < GATILHO_TESTE_ESPERA_MS) return;
        _gtIdx = (_gtIdx + 1) % GATILHO_TESTE_ORDEM.length;
        dispararIntervencaoTeste(GATILHO_TESTE_ORDEM[_gtIdx]);
    }, 1000);
}

function pararGatilhoTeste() { clearInterval(_gtInterval); _gtInterval = null; }

// Dispara UMA intervenção pelo caminho normal (mostrarIntervencao), só que
// marcada como teste. Reancoragem e checkpoint precisam da questão na tela.
function dispararIntervencaoTeste(tipo) {
    if (!GATILHO_TESTE_ORDEM.includes(tipo)) {
        console.warn('[KaIA] tipo desconhecido:', tipo, '— use um destes:', GATILHO_TESTE_ORDEM);
        return;
    }
    // Encerra de verdade o que estiver rodando antes de abrir a próxima.
    // Em produção duas intervenções nunca se sobrepõem (o polling é travado por
    // intervencaoAtual), mas o dock deixa clicar uma em cima da outra — e um
    // temporizador pendente do micro_refoco (o MR_DELAY_MS) voltava a abrir a
    // barra POR CIMA da intervenção seguinte, zerando pausaAtiva junto.
    _fecharMicroRefoco();
    _fecharSeq();
    _esconderTroca();

    // O checkpoint precisa de pelo menos uma questão RESPONDIDA para ter o que
    // recuperar — num teste avulso o histórico está vazio e ele não abriria.
    // Só no modo de teste: empresta uma questão de exemplo para o design poder
    // ser visto. Em produção o histórico vem das questões de verdade.
    if (tipo === 'checkpoint' && historicoQuestoes.length === 0) {
        console.log('[KaIA] (teste) histórico vazio — usando questão de exemplo no checkpoint.');
        historicoQuestoes.push({
            q: 'Qual gás é o principal responsável pelo efeito estufa de origem humana?',
            opts: ['Metano', 'Dióxido de carbono', 'Ozônio', 'Argônio'],
            ans: 1,
        });
    }

    _gtUltimoEm = performance.now();
    _intervencaoDeTeste = true;
    console.log('[KaIA] (teste) disparando:', tipo);
    mostrarIntervencao({ intervention_type: tipo });
}

// Atalhos de console para a Bia escolher o que ver, sem esperar a fila.
window.kaiaTestar = (tipo) => {
    if (!tipo) { console.log('[KaIA] tipos:', GATILHO_TESTE_ORDEM.join(', ')); return; }
    dispararIntervencaoTeste(tipo);
};
window.kaiaGatilhoTeste = (ligado) => {
    if (ligado === false) { pararGatilhoTeste(); console.log('[KaIA] gatilho de teste PARADO.'); }
    else { iniciarGatilhoTeste(); }
};
// =============================================================================
// ===== FIM DO GATILHO DE TESTE (PROVISÓRIO) ==================================
// =============================================================================

// ============================================================
//   SEQUÊNCIA GUIADA — base das intervenções com AÇÃO (Passos 3 e 4)
// ============================================================
// Overlay curto: timer + passos rotativos + retomada. Reusa o flag pausaAtiva
// (suspende idle/aba/exit). Base da pausa ativa (movimento) e do micro-refoco
// (respiração). idx cicla os passos (modulo) — cobre roteiro e respiração.
let _seqTimer = null;
let _seqFeedbackTipo   = null;   // tipo a perguntar ao fim (null = sem feedback)
let _seqMostradaEm     = 0;      // instante em que a intervenção apareceu
let _seqFeedbackAberto = false;  // card já trocou para "como foi?"

// ---- Troca suave da frase do roteiro (pausa_ativa) -------------------------
// O tick roda 4x por segundo e reescrevia a frase toda vez; agora ele só age
// quando o ÍNDICE do passo muda de verdade, e a troca é animada.
// Estes dois valores CASAM com as animações kaiaPassoSai/kaiaPassoEntra no
// style.css — mexeu num, mexe no outro.
const SEQ_PASSO_SAIDA_MS   = 220;
const SEQ_PASSO_ENTRADA_MS = 450;
let _seqPassoIdx   = -1;
let _seqPassoTimer = null;

// Quem pediu menos movimento recebe a troca direta, sem espera nenhuma: manter
// o atraso da saída só para depois trocar o texto seria um travamento sem
// motivo, já que a animação nem vai rodar.
const _menosMovimento = () =>
    !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function _trocarPassoSeq(texto) {
    const el = $('kaia-seq-passo');
    if (!el) return;
    clearTimeout(_seqPassoTimer);
    if (_menosMovimento()) { el.textContent = texto; return; }
    // Primeira frase da sequência: não há o que fazer sair, ela só entra.
    if (!el.textContent) {
        el.textContent = texto;
        el.classList.add('kaia-passo-entra');
        return;
    }
    el.classList.remove('kaia-passo-entra');
    el.classList.add('kaia-passo-sai');
    _seqPassoTimer = setTimeout(() => {
        el.textContent = texto;
        el.classList.remove('kaia-passo-sai');
        void el.offsetWidth;              // reflow: reinicia a animação de entrada
        el.classList.add('kaia-passo-entra');
    }, SEQ_PASSO_SAIDA_MS);
}

function _garantirOverlaySeq() {
    if ($('kaia-seq')) return;
    const el = document.createElement('div');
    el.id = 'kaia-seq';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.innerHTML = `<div class="kaia-seq-card">
        <div id="kaia-seq-ic"></div>
        <h2 id="kaia-seq-titulo"></h2>
        <p class="kaia-seq-passo" id="kaia-seq-passo"></p>
        <div class="kaia-seq-seg"><span id="kaia-seq-seg">0</span>s</div>
        <div id="kaia-seq-fb"></div>
        <button type="button" id="kaia-seq-voltar">Voltar agora</button>
      </div>`;
    document.body.appendChild(el);
    void el.offsetWidth;                     // ver a nota em _garantirBarraMicroRefoco
    // Em modo feedback o mesmo botão só FECHA — senão re-entraria em encerrar e
    // remontaria o strip por cima de si mesmo.
    $('kaia-seq-voltar').addEventListener('click', () => {
        if (_seqFeedbackAberto) _fecharSeq(); else encerrarSequenciaGuiada();
    });
}

function iniciarSequenciaGuiada({ titulo, passos, duracaoMs, passoMs, feedbackTipo = null,
                                  icone = null }) {
    _garantirOverlaySeq();
    pausaAtiva = true;                       // suspende idle/aba/exit durante a sequência
    _seqFeedbackTipo    = feedbackTipo;
    _seqMostradaEm      = intervencaoMostradaEm;
    _seqFeedbackAberto  = false;
    $('kaia-seq-fb').textContent = '';       // limpa o strip de uma sequência anterior
    // Zera a troca de frases: sem isto, um novo disparo começaria com o texto e
    // a classe de animação do disparo anterior, e a 1ª frase entraria sem o fade.
    clearTimeout(_seqPassoTimer);
    _seqPassoIdx = -1;
    $('kaia-seq-passo').classList.remove('kaia-passo-sai', 'kaia-passo-entra');
    $('kaia-seq-passo').textContent = '';
    $('kaia-seq-passo').style.display = '';
    $('kaia-seq').querySelector('.kaia-seq-seg').style.display = '';
    $('kaia-seq-voltar').textContent = 'Voltar agora';
    $('kaia-seq-ic').innerHTML = icone ? _iconeHTML(icone, true) : '';
    $('kaia-seq-titulo').innerText = titulo;
    $('kaia-seq').classList.add('aberto');
    const fim = performance.now() + duracaoMs;
    const tick = () => {
        const restante = Math.max(0, fim - performance.now());
        $('kaia-seq-seg').innerText = Math.ceil(restante / 1000);
        // Só troca quando o passo REALMENTE muda: reescrever a cada 250ms
        // reiniciaria a animação quatro vezes por segundo.
        const idx = Math.floor((duracaoMs - restante) / passoMs) % passos.length;
        if (idx !== _seqPassoIdx) {
            _seqPassoIdx = idx;
            _trocarPassoSeq(passos[idx]);
        }
        if (restante <= 0) return encerrarSequenciaGuiada();
        _seqTimer = setTimeout(tick, 250);
    };
    tick();
}

function _fecharSeq() {
    const el = $('kaia-seq');
    if (el) el.classList.remove('aberto');
    clearTimeout(_seqPassoTimer);   // troca de frase pendente não escreve num card fechado
    _seqFeedbackAberto = false;
    _seqFeedbackTipo   = null;
}

// Sensores e polling voltam SEMPRE aqui — o feedback (Fase 2) não pode segurar a
// sessão. O overlay só continua aberto mais alguns segundos para a pergunta, com
// o botão virando saída imediata.
function encerrarSequenciaGuiada() {
    clearTimeout(_seqTimer);
    pausaAtiva = false;
    idleTime = 0;                            // retoma os sensores sem contar o descanso
    if (isMissionActive) setEstado('ESTUDANDO');
    liberarPolling();
    if (_seqFeedbackTipo) _pedirFeedbackSeq(); else _fecharSeq();
}

// quanto o card fica perguntando antes de sair sozinho
const SEQ_FEEDBACK_MS = T(5000, 8000);   // TODO: ajustar tempo pra produção

function _pedirFeedbackSeq() {
    clearTimeout(_seqPassoTimer);   // o card vira "como foi?": nada mais de frase
    _seqFeedbackAberto = true;
    $('kaia-seq-titulo').innerText = 'Como foi a pausa?';
    $('kaia-seq-passo').style.display = 'none';
    $('kaia-seq').querySelector('.kaia-seq-seg').style.display = 'none';
    $('kaia-seq-voltar').textContent = 'Voltar à questão';
    const alvo = $('kaia-seq-fb');
    alvo.textContent = '';
    alvo.appendChild(_stripFeedback(_seqFeedbackTipo, {
        mostradaEm: _seqMostradaEm, agradecer: true,
        onResposta: () => setTimeout(_fecharSeq, 1200),
    }));
    setTimeout(() => { if (_seqFeedbackAberto) _fecharSeq(); }, SEQ_FEEDBACK_MS);
}

// Pausa ativa (movimento) — Passo 3.
// Bancos da pausa ativa. Os passos são um ROTEIRO (rodam em ordem durante a
// pausa), não um sorteio — sortear passo a passo mandaria o aluno alongar depois
// de já ter voltado a sentar. Quem varia entre disparos é o título.
const PAUSA_ATIVA_TITULOS = [
    'Pausa ativa',
    'Hora de mexer o corpo',
    'Levanta e respira',
    'Dois minutos de corpo',
    'Sai da cadeira um pouco',
];
const PAUSA_ATIVA_PASSOS = [
    'Levanta e alonga os ombros 🙆',
    'Olha pra longe — janela, parede 👀',
    'Bebe uma água 💧',
    'Respira fundo, 3 vezes 🌬️',
];

function iniciarPausaAtiva() {
    iniciarSequenciaGuiada({
        titulo: _variar(PAUSA_ATIVA_TITULOS),
        passos: PAUSA_ATIVA_PASSOS,
        // TODO: ajustar tempo pra produção — 9s no teste, 90s de verdade.
        // passoMs é sempre duracao/4 (são 4 passos): mexeu num, mexe no outro.
        duracaoMs: T(9 * 1000, 90 * 1000),
        passoMs:   T(2.25 * 1000, 22.5 * 1000),
        feedbackTipo: 'pausa_ativa',
        icone: 'pausa_ativa',
    });
}

// Micro-refoco (respiração) — Passo 4 · barra fixa NO RODAPÉ, deslizando de
// baixo: mensagem + barra que cai linearmente com o tempo restante (sem
// números). Não usa o overlay central. (Dizia "no TOPO" — a barra desceu para o
// rodapé e o comentário tinha ficado para trás.)
let _mrInterval = null;
let _mrDelayTimer     = null;
let _mrMostradaEm     = 0;
let _mrFeedbackAberto = false;

// Respiro ANTES de a barra começar a descer: ela aparece cheia e fica parada,
// dando tempo de LER a frase de acolhimento antes de qualquer movimento
// começar. Sem isso a barra já entrava descendo, e uma contagem correndo em
// cima do texto é justamente o tipo de pressa que a intervenção veio tirar.
// O tempo total na tela é MR_DELAY_MS + a duração da respiração.
// TODO: ajustar tempo pra produção — 1,5s no teste, 4s de verdade.
const MR_DELAY_MS = T(1500, 4000);

// Banco de frases de acolhimento da barra. Uma é sorteada na ABERTURA e fica
// PARADA do começo ao fim: variar entre aparições dá variedade, variar durante a
// respiração viraria movimento numa intervenção que existe para acalmar.
// Tom: sem cobrança, sem urgência, sem prometer resultado. Lista pensada para
// ser editada — é só acrescentar/trocar linhas aqui.
const FRASES_MICRO_REFOCO = [
    'Sem pressa. A questão continua aí quando você voltar.',
    'Estes trinta segundos são seus. Nada some enquanto isso.',
    'Não precisa fazer certo. É só respirar.',
    'Se a cabeça vagar, tudo bem — ela volta sozinha.',
    'Ninguém está cronometrando você.',
    'Solta os ombros. Eles costumam ficar tensos sem avisar.',
    'Você já está fazendo o suficiente por agora.',
    'Repara no ar entrando. Só isso, nada além.',
    'Cansaço não é preguiça. Descansar é parte de estudar.',
    'Um respiro de cada vez. Não precisa ser todos.',
    'Dá pra ir devagar e ainda assim chegar.',
    'Se distraiu? Acontece com todo mundo, o dia inteiro.',
    'Desencosta os dentes e afrouxa a mandíbula.',
    'Nada aqui depende de você acertar isso.',
    'Seu corpo agradece essa pausa mais do que parece.',
    'Está tudo bem se hoje render menos.',
    'Você voltou até aqui. Isso já conta.',
    'Deixa o ar sair devagar, sem empurrar.',
    'O foco não sumiu. Ele só foi tomar um ar.',
    'Estudar cansa mesmo. Não é você que está errado.',
];

function _garantirBarraMicroRefoco() {
    if ($('kaia-mr')) return;
    const el = document.createElement('div');
    el.id = 'kaia-mr';
    el.setAttribute('role', 'status');
    el.innerHTML = `<button type="button" class="kaia-mr-pular" id="kaia-mr-pular">Pular</button>
      <div class="kaia-mr-msg"><span class="kaia-ic">${ICONES_INTERVENCAO.micro_refoco}</span>
        <span id="kaia-mr-msg"></span></div>
      <div class="kaia-mr-frase" id="kaia-mr-frase"></div>
      <div class="kaia-mr-track"><div class="kaia-mr-fill" id="kaia-mr-fill"></div></div>
      <div id="kaia-mr-fb"></div>`;
    document.body.appendChild(el);
    // Reflow logo após inserir: sem ele o navegador nunca chega a calcular o
    // estado FECHADO, e a primeira abertura (criação + .aberto no mesmo tick)
    // pula a transição — justo a que o aluno mais nota. Mesmo truque que a
    // barra de progresso já usa abaixo.
    void el.offsetWidth;
    $('kaia-mr-pular').addEventListener('click', () => {
        if (_mrFeedbackAberto) _fecharMicroRefoco(); else encerrarMicroRefoco();
    });

    // (O X de teste que existia aqui saiu: com MR_DELAY_MS a barra fica parada
    // tempo suficiente para ser vista, e o "Pular" já é a saída. A barra volta a
    // se fechar sozinha em todos os modos, que é o conceito dela — faixa passiva
    // de "respire", sem exigir ação.)
}

function iniciarMicroRefoco() {
    _garantirBarraMicroRefoco();
    _mrMostradaEm     = intervencaoMostradaEm;
    _mrFeedbackAberto = false;
    $('kaia-mr-fb').textContent = '';          // limpa o strip do disparo anterior
    $('kaia-mr').querySelector('.kaia-mr-track').style.display = '';
    $('kaia-mr-pular').textContent = 'Pular';
    // Sorteia AQUI, uma vez só: nada de trocar a frase durante a respiração.
    const frase = $('kaia-mr-frase');
    frase.style.display = '';
    frase.textContent = _variar(FRASES_MICRO_REFOCO);
    pausaAtiva = true;                         // suspende idle/aba/exit durante a respiração
    const passos = ['Inspira… 🌬️', 'Segura…', 'Expira devagar…'];
    // TODO: ajustar tempo pra produção — 6s no teste, 30s de verdade. passoMs é
    // o tempo de cada fase da respiração (inspira/segura/expira).
    const dur = T(6 * 1000, 30 * 1000), passoMs = T(1.2 * 1000, 4 * 1000);
    $('kaia-mr').classList.add('aberto');
    document.body.classList.add('kaia-mr-aberta');
    $('kaia-mr-msg').innerText = passos[0];
    _medirBarraMicroRefoco();
    // A barra entra CHEIA e fica parada por MR_DELAY_MS — tempo de ler a frase.
    // Só depois ela começa a cair linearmente até 0 (via transition CSS, sem
    // números). A contagem que encerra a intervenção também só começa aí: o
    // delay é respiro, não desconto do tempo de respiração.
    const fill = $('kaia-mr-fill');
    clearInterval(_mrInterval);
    clearTimeout(_mrDelayTimer);
    fill.style.transition = 'none';
    fill.style.width = '100%';
    void fill.offsetWidth;                     // reflow p/ reiniciar a queda a cada disparo

    _mrDelayTimer = setTimeout(() => {
        fill.style.transition = `width ${dur}ms linear`;
        fill.style.width = '0%';
        // a mensagem troca por fase da respiração
        const inicio = performance.now();
        _mrInterval = setInterval(() => {
            const passado = performance.now() - inicio;
            if (passado >= dur) return encerrarMicroRefoco();
            $('kaia-mr-msg').innerText = passos[Math.floor(passado / passoMs) % passos.length];
        }, 200);
    }, MR_DELAY_MS);
}

// A barra vive no rodapé, onde o probe de autorrelato e a pilha de cards também
// moram. Publica a altura REAL dela para o CSS subir os dois enquanto ela está
// aberta — medida em vez de fixa porque a barra encolhe no modo feedback e
// cresce se a frase quebrar em duas linhas.
function _medirBarraMicroRefoco() {
    const el = $('kaia-mr');
    if (el) document.body.style.setProperty('--mr-altura', `${el.offsetHeight}px`);
}

function _fecharMicroRefoco() {
    clearInterval(_mrInterval);
    clearTimeout(_mrDelayTimer);
    const el = $('kaia-mr');
    if (el) el.classList.remove('aberto');
    document.body.classList.remove('kaia-mr-aberta');
    document.body.style.removeProperty('--mr-altura');
    _mrFeedbackAberto = false;
}

// A barra sobrevive alguns segundos só para perguntar (Fase 2) — em versão
// compacta, para não ficar mais intrusiva que a própria intervenção. Sensores e
// polling voltam antes disso.
const MR_FEEDBACK_MS = T(4000, 6000);   // TODO: ajustar tempo pra produção

function encerrarMicroRefoco() {
    clearInterval(_mrInterval);
    clearTimeout(_mrDelayTimer);   // "Pular" durante o delay não deixa a queda começar depois
    pausaAtiva = false;
    idleTime = 0;                              // retoma sensores sem contar a respiração
    if (isMissionActive) setEstado('ESTUDANDO');
    liberarPolling();
    _mrFeedbackAberto = true;
    $('kaia-mr-msg').innerText = 'Ajudou a reancorar?';
    $('kaia-mr-frase').style.display = 'none';   // a frase acalma a respiração, não a pergunta
    $('kaia-mr').querySelector('.kaia-mr-track').style.display = 'none';
    $('kaia-mr-pular').textContent = 'Fechar';
    const alvo = $('kaia-mr-fb');
    alvo.textContent = '';
    alvo.appendChild(_stripFeedback('micro_refoco', {
        compacto: true, mostradaEm: _mrMostradaEm, agradecer: true,
        onResposta: () => setTimeout(_fecharMicroRefoco, 1200),
    }));
    _medirBarraMicroRefoco();                   // encolheu: sem a frase e sem a barra
    setTimeout(() => { if (_mrFeedbackAberto) _fecharMicroRefoco(); }, MR_FEEDBACK_MS);
}

// Troca de tema (intervenção com AÇÃO — Passo 5): modal CENTRAL (como a pausa
// ativa, maior). Escolhe o tema-alvo ao aparecer e MOSTRA qual será; oferece a
// ESCOLHA "Trocar" / "Continuar" (dá agência ao aluno).
let _trocaTemaAlvo   = null;
let _trocaMostradaEm = 0;

function _garantirCardTroca() {
    if ($('kaia-troca')) return;
    const el = document.createElement('div');
    el.id = 'kaia-troca';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.innerHTML = `<div class="kaia-troca-card">
        ${_iconeHTML('troca_atividade', true)}
        <h2>Que tal trocar de tema?</h2>
        <p id="kaia-troca-sub"></p>
        <p class="kaia-troca-alvo">Ir para: <strong id="kaia-troca-tema"></strong></p>
        <div class="kaia-troca-btns">
          <button type="button" class="sim" id="kaia-troca-sim">Trocar de tema</button>
          <button type="button" class="nao" id="kaia-troca-nao">Continuar aqui</button>
        </div>
      </div>`;
    document.body.appendChild(el);
    // Feedback só DEPOIS (Fase 2): somar 3 botões aos 2 daqui daria 5 escolhas de
    // uma vez, e no instante da escolha o aluno ainda não sentiu o efeito da troca.
    $('kaia-troca-sim').addEventListener('click', () => { _esconderTroca(); liberarPolling(); _trocarTema(); _perguntarDepoisDaTroca(); });
    $('kaia-troca-nao').addEventListener('click', () => { _esconderTroca(); liberarPolling(); _perguntarDepoisDaTroca(); });
}

// tempo até perguntar (aluno já sentiu o efeito)
const TROCA_FEEDBACK_MS = T(8000, 45000);   // TODO: ajustar tempo pra produção

function _perguntarDepoisDaTroca() {
    _feedbackTardio('troca_atividade', {
        titulo: 'Sobre a troca de tema',
        icone: 'troca_atividade',
        pergunta: 'A sugestão de trocar de tema ajudou seu foco?',
        atrasoMs: TROCA_FEEDBACK_MS, mostradaEm: _trocaMostradaEm,
    });
}

// Zera a ociosidade ao fechar: o aluno acabou de CLICAR num botão, não está
// parado. Sem isto o overlay de inatividade, que estava segurado enquanto o
// modal existia, subiria no instante seguinte ao fechamento.
function _esconderTroca() {
    const c = $('kaia-troca');
    if (c) c.classList.remove('aberto');
    idleTime = 0;
}

function mostrarTrocaTema() {
    _garantirCardTroca();
    _trocaMostradaEm = intervencaoMostradaEm;   // capturado aqui: o card tardio dispara
                                                // 45s depois, quando o global já mudou
    const outros = temasAtuais.filter(t => t && t !== currentTema);
    _trocaTemaAlvo = outros.length ? outros[Math.floor(Math.random() * outros.length)] : currentTema;
    $('kaia-troca-sub').innerText = _variar([
        'Um assunto novo às vezes ajuda a reengajar.',
        'Que tal um tema diferente pra dar aquele gás?',
        'Mudar de assunto pode renovar o foco.',
        'Às vezes trocar de tema é o empurrãozinho que falta.',
    ]);
    $('kaia-troca-tema').innerText = (_trocaTemaAlvo !== currentTema)
        ? _trocaTemaAlvo
        : `outra questão de ${currentTema}`;
    $('kaia-troca').classList.add('aberto');
}

// A troca em si — usa o tema-alvo já mostrado. Reusa carregarQuestao (atualiza
// tema/cabeçalho/fila). Sem outro tema, cai na próxima do mesmo.
function _trocarTema() {
    carregarQuestao(currentSubject, _trocaTemaAlvo || currentTema);
}

// ============================================================
//   CHECKPOINT DE RECUPERAÇÃO (intervenção com AÇÃO — Passo 6)
// ============================================================
// INLINE (não é modal escuro): um card CURTO aparece no topo da área de estudo,
// com UMA pergunta do conteúdo RECENTE (últimas respondidas) — retrieval practice.
// A questão atual fica atenuada; ao fechar, um REALCE de re-entrada volta o olho
// pra ela (reduz o custo de retomada, alto no TEA/TDAH). Base: teste interpolado
// (Szpunar 2013) + resumption lag. Reusa pausaAtiva; warm-up garante histórico.
let _cpQuestao    = null;
let _cpMostradaEm = 0;

// ---- Bancos de texto do checkpoint ---------------------------------------
// Três momentos, três listas. O checkpoint é a intervenção que mais se repete
// dentro de uma mesma semana de estudo, então é a que mais sofre com texto
// fixo: o aluno decora a frase de abertura e para de ler o que vem depois.
// Em CHECKPOINT_ERRO, {r} é substituído pela resposta certa.
// Para editar: acrescenta linhas. Nada além destas listas precisa mudar.
const CHECKPOINT_ABERTURAS = [
    'Pausa relâmpago — recupere isto:',
    'Rapidinho: você lembra desta?',
    'Só pra fixar — responde essa:',
    'Mini-check do que você já viu:',
    'Uma de trás, pra assentar:',
    'Volta rápida no que já passou:',
    'Sem valer nota — só pra lembrar:',
    'Trinta segundos numa que você já viu:',
    'Puxa da memória essa aqui:',
    'Revisão relâmpago, sem pressa:',
    'Uma pergunta de aquecimento:',
    'Do que você já respondeu hoje:',
];
const CHECKPOINT_ACERTO = [
    'Isso! De volta pro foco.',
    'Certo — está fixado mesmo.',
    'Acertou. Isso é sinal de que ficou.',
    'Essa você já tem.',
    'Certinho. Bora seguir.',
    'Boa — memória em dia.',
];
const CHECKPOINT_ERRO = [
    'Sem problema — era: {r}.',
    'Passa nada. A resposta era: {r}.',
    'Essa escapou. Era: {r}. Agora fixou.',
    'Ainda não. Era: {r} — errar aqui ajuda a lembrar depois.',
    'Quase. A certa era: {r}.',
    'Era: {r}. Sem peso nenhum, isso aqui não conta nota.',
];
const CHECKPOINT_ROTULO_FB = [
    'Esse mini-check ajudou?',
    'Voltar numa questão antiga ajudou?',
    'Valeu a pena essa pausa rápida?',
    'Isso te ajudou a reancorar?',
];

function _questaoCheckpoint() {
    const recentes = historicoQuestoes.slice(-3);   // conteúdo RECENTE (últimas ~3 respondidas)
    return recentes.length ? recentes[Math.floor(Math.random() * recentes.length)] : null;
}

function checkpointRecuperacao() {
    const q = _questaoCheckpoint();
    const lado = document.querySelector('.quiz-lado-questao');
    if (!q || !Array.isArray(q.opts) || !lado) {
        // Falhava em SILÊNCIO: sem nenhuma questão respondida ainda,
        // historicoQuestoes está vazio, não há o que recuperar e a intervenção
        // simplesmente não acontecia — sem nada no console, o que faz parecer
        // que ela "quebrou". O aviso não muda o comportamento, só o torna
        // visível para quem está testando ou depurando.
        console.warn('[KaIA] checkpoint não disparou: '
            + (!lado ? 'a área de estudo não está na tela.'
                     : `é preciso ter respondido ao menos 1 questão (histórico: ${historicoQuestoes.length}).`));
        liberarPolling();
        return;
    }
    const antigo = $('kaia-cp');
    if (antigo) antigo.remove();             // evita duplicar se re-disparar
    pausaAtiva = true;                        // suspende sensores durante o checkpoint
    _cpQuestao = q;
    _cpMostradaEm = intervencaoMostradaEm;

    const wrap = document.querySelector('.question-wrapper');
    if (wrap) wrap.classList.add('kaia-cp-dim');   // atenua a questão atual (foco no checkpoint)

    const card = document.createElement('div');
    card.id = 'kaia-cp';
    card.setAttribute('role', 'group');
    const topo = document.createElement('div');
    topo.className = 'kaia-cp-topo';
    topo.innerHTML = _iconeHTML('checkpoint');      // SVG constante nosso
    topo.append(' ' + _variar(CHECKPOINT_ABERTURAS));   // nó de texto, sem marcação
    const pq = document.createElement('p');
    pq.className = 'kaia-cp-q';
    pq.textContent = q.q;                     // textContent: sem injeção de HTML
    const opts = document.createElement('div');
    opts.className = 'kaia-cp-opts';
    q.opts.forEach((opt, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'kaia-cp-opt';
        b.textContent = opt;
        b.addEventListener('click', () => _responderCheckpoint(i === q.ans));
        opts.appendChild(b);
    });
    const fb = document.createElement('p');
    fb.className = 'kaia-cp-fb';
    fb.id = 'kaia-cp-fb';
    const voltar = document.createElement('button');
    voltar.type = 'button';
    voltar.className = 'kaia-cp-voltar';
    voltar.id = 'kaia-cp-voltar';
    voltar.textContent = 'Voltar à questão';
    voltar.addEventListener('click', encerrarCheckpoint);
    card.append(topo, pq, opts, fb, voltar);
    lado.prepend(card);                        // INLINE no topo da área de estudo
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function _responderCheckpoint(acertou) {
    const certa = _cpQuestao ? _cpQuestao.opts[_cpQuestao.ans] : '';
    $('kaia-cp-fb').textContent = acertou
        ? _variar(CHECKPOINT_ACERTO)
        : _variar(CHECKPOINT_ERRO).replace('{r}', certa);
    $$('#kaia-cp .kaia-cp-opt').forEach(b => b.disabled = true);   // trava após responder
    // Feedback só depois de responder (Fase 2): antes disso competiria com a questão.
    const card = $('kaia-cp');
    if (card && !card.querySelector('.kaia-fb-wrap')) {
        card.insertBefore(_stripFeedback('checkpoint', {
            rotulo: _variar(CHECKPOINT_ROTULO_FB), mostradaEm: _cpMostradaEm, agradecer: true,
        }), $('kaia-cp-voltar'));
    }
    $('kaia-cp-voltar').style.display = 'inline-block';
}

function encerrarCheckpoint() {
    const card = $('kaia-cp');
    if (card) card.remove();
    const wrap = document.querySelector('.question-wrapper');
    if (wrap) {
        wrap.classList.remove('kaia-cp-dim');
        wrap.classList.add('kaia-cp-realce');          // cue de re-entrada: realça a questão atual
        setTimeout(() => wrap.classList.remove('kaia-cp-realce'), 1500);
    }
    pausaAtiva = false;
    idleTime = 0;                            // retoma os sensores sem contar o checkpoint
    if (isMissionActive) setEstado('ESTUDANDO');
    liberarPolling();
}

// ============================================================
//   REANCORAGEM POR DESTAQUE (intervenção com AÇÃO — Passo 7)
// ============================================================
// NÃO mostra card: um backdrop suave escurece o entorno (nav/rail) e a área da
// questão é ELEVADA acima dele (fica clara). Reduz a competição visual → reancora
// na tarefa (segmenting effect). NÃO pausa sensores (é refoco, não descanso).
// Reverte sozinho em REANCORA_MS. Sutil de propósito (regra TEA/TDAH: tirar
// estímulo, não adicionar — nada pisca).
const REANCORA_MS = T(2500, 4000);   // TODO: ajustar tempo pra produção
// O véu é um ::before condicional: sumir a classe = sumir o elemento, e o que
// não existe não transiciona. Então a saída é em dois tempos — liga a classe do
// fade, espera ele terminar, só aí limpa. Este valor CASA com a animação
// kaiaVeuSai no style.css; mexer num, mexer no outro.
const REANCORA_SAIDA_MS = 800;
let _reancoraTimer = null;

function reancorarDestaque() {
    liberarPolling();                        // não é card; o cooldown já segura novo disparo
    // Sem botão de feedback por decisão de produto (Fase 2): são 4s de escurecimento
    // sutil, sem UI — perguntar "ajudou?" seria mais intrusivo que a intervenção.
    // O reward continua vindo do sinal implícito (transição de estado).
    if (!document.querySelector('.question-wrapper')) return;
    document.body.classList.remove('kaia-reancorar-saindo');   // disparo novo cancela saída em curso
    document.body.classList.add('kaia-reancorar');
    clearTimeout(_reancoraTimer);
    _reancoraTimer = setTimeout(() => {
        document.body.classList.add('kaia-reancorar-saindo');
        _reancoraTimer = setTimeout(
            () => document.body.classList.remove('kaia-reancorar', 'kaia-reancorar-saindo'),
            REANCORA_SAIDA_MS);
    }, REANCORA_MS);
}

// ============================================================
//        CAMADA DE DADOS — PERFIL + FEATURES
// ============================================================
// lerPerfil/gravarPerfil/snapshotFeatures/registrarInicioSessao/enviarPerfil
// vivem SO no comum.js (carregado antes) — a copia daqui duplicava e quebrava
// o materias.js. So os hooks de onboarding abaixo continuam locais.
const definirAmbiente  = (valor) => gravarPerfil({ ...lerPerfil(), ambiente_dispositivo: valor });
const definirDataProva = (iso)   => gravarPerfil({ ...lerPerfil(), data_prova: iso });

// Login/cadastro (finalizarLogin, salvarLogin, criarConta, ROTA_POR_ROLE,
// TERMOS_VERSAO), hobbies (HOBBIES, registrarHobbies, salvarHobbies) e a luz
// do login (registrarLuz): removidos daqui — vivem so em login.js e
// hobbies.js (materias.html nao os carrega). Eram copias mortas do split antigo.

// ============================================================
//                  SENSORES DE COMPORTAMENTO
// ============================================================
// Escreve o estado da missão na sidebar + no overlay de inatividade.
function setEstado(texto, alertar = false) {
    const overlay = $('overlay');
    const status  = $('system-status');
    if (overlay) overlay.style.opacity = alertar ? '0.95' : '0';
    if (status)  status.innerText = texto;
}

// calculateReadingTime foi movida para puros.js (testável); carregada antes.

// Há intervenção ocupando a tela?
// Três checagens, e as três são necessárias:
//   1. `intervencaoAtual` — o registro de quem está segurando o polling. Só
//      vale quando a intervenção entrou por mostrarIntervencao().
//   2. a classe no body — a reancoragem libera o polling na hora, de propósito
//      (é refoco, não descanso), então some da checagem 1 imediatamente.
//   3. o DOM — a rede de segurança. Se algo abrir uma intervenção por fora do
//      mostrarIntervencao (o gatilho de teste chamando a função direto, ou o
//      motor do Vitor amanhã), 1 e 2 não veem, mas o elemento aberto está lá.
//      Sem esta, a troca_atividade voltava a ficar sob a tela de inatividade.
const _intervencaoNaTela = () =>
    !!intervencaoAtual
    || document.body.classList.contains('kaia-reancorar')
    || !!document.querySelector('#kaia-troca.aberto, #kaia-seq.aberto, #kaia-mr.aberto, #kaia-cp');

function iniciarIdleMonitor() {
    clearInterval(idleInterval);
    idleInterval = setInterval(() => {
        if (!isMissionActive || pausaAtiva) return;   // descanso não conta como inatividade
        idleTime++;
        // ocioso COM a aba focada (sem movimento no último segundo) → proxy do estado interno.
        // A tela escurecida ainda conta (segue parado); dispensá-la com o mouse só interrompe a
        // contagem daqui pra frente, não apaga o acumulado.
        if (!document.hidden && !mexeuDesdeUltimoTick) tempoOciosoMs += 1000;
        mexeuDesdeUltimoTick = false;
        const timer = $('timer');
        if (timer) timer.innerText = idleTime;
        // O overlay de inatividade NÃO sobe enquanto há intervenção na tela.
        // Subir o z-index resolveu para as que têm camada própria, mas não para
        // o checkpoint (inline, sem camada) nem para a reancoragem (o véu dela
        // mora em 40, dentro do #quiz-view). E, mesmo onde resolveu, mostrar
        // "Ainda está Conosco?" por cima de uma intervenção é dizer duas coisas
        // ao mesmo tempo para quem já está com a atenção comprometida: a
        // intervenção JÁ é o chamado de volta.
        if (idleTime >= dynamicLimit && !_intervencaoNaTela()) setEstado('FALTA DE INTERAÇÃO', true);
    }, 1000);
}

function registrarSensores() {
    const quizView = $('quiz-view');

    // --- mouse: zera ociosidade + captura 1ª interação e o trajeto (features de mouse) ---
    quizView?.addEventListener('mousemove', (e) => {
        if (!isMissionActive) return;
        idleTime = 0;
        mexeuDesdeUltimoTick = true;
        setEstado('ESTUDANDO');
        const agora = performance.now();
        if (firstInteractionAt === 0 && questionShownAt > 0) firstInteractionAt = agora;   // initiation time
        if (agora - lastMouseSampleAt >= 100) {   // amostra o trajeto ~10x/s (throttle p/ não inundar)
            lastMouseSampleAt = agora;
            mouseSamples.push([Math.round(agora - questionShownAt), e.clientX, e.clientY]);
        }
    });

    // --- teclado no caderno: escrever é foco, não ociosidade (Fase 5) ---
    // Espelha o mousemove acima, mas para a digitação. Listener DELEGADO no #caderno
    // (o container persiste; o evento `input` borbulha dos blocos .cad-texto criados
    // sob demanda). Só a escrita ATIVA reseta — caderno aberto e parado segue
    // contando como ocioso.
    $('caderno')?.addEventListener('input', () => {
        if (!isMissionActive) return;      // o idle-monitor só corre nesse estado
        idleTime = 0;                      // não escurece por causa da escrita
        mexeuDesdeUltimoTick = true;       // e a escrita não vira tempo ocioso (dado limpo)
        setEstado('ESTUDANDO');            // baixa o overlay se já tinha subido
    });

    // --- dwell: tempo sobre as ALTERNATIVAS sem ainda responder (hesitação → estado interno) ---
    // O container #options-display persiste (só o innerHTML troca), então basta 1 listener.
    const opcoesArea = $('options-display');
    opcoesArea?.addEventListener('mouseenter', () => {
        if (isMissionActive) dwellEntrouEm = performance.now();
    });
    opcoesArea?.addEventListener('mouseleave', () => {
        if (dwellEntrouEm) { tempoDwellMs += performance.now() - dwellEntrouEm; dwellEntrouEm = 0; }
    });

    // --- trocas de aba ---
    document.addEventListener('visibilitychange', () => {
        if (!isMissionActive || pausaAtiva) return;   // trocar de aba na pausa não é distração
        if (document.hidden) {
            focusLostAt = performance.now();
            mudancasAba++;
        } else if (focusLostAt !== null) {
            logEvent('tab_change', {
                mudancas_aba: mudancasAba,
                tempo_fora_foco_s: parseFloat(((performance.now() - focusLostAt) / 1000).toFixed(2))
            });
            focusLostAt = null;
        }
    });

    // --- exit-intent: cursor cruzando a borda superior (rumo à barra de abas) ---
    // Camada VISÍVEL da distração; o registro real continua no visibilitychange acima.
    // relatedTarget nulo = o mouse saiu do documento; clientY numa faixa fina do
    // topo (não exatamente 0) para pegar saídas RÁPIDAS, cujo último evento
    // costuma reportar alguns px dentro da tela.
    document.addEventListener('mouseout', (e) => {
        if (!sessaoDeEstudoAberta || pausaAtiva) return;   // não avisa durante o descanso
        if (e.relatedTarget || e.clientY > EXIT_TOPO_PX) return;
        mostrarAvisoSaida();
    });

    // (v2: scroll removido — múltipla escolha não rola, feature velocidade_scroll saiu)
    // (v2: keystroke_pause removido — quase não há digitação, feature pausas_digitacao saiu)

    // --- cliques fora da área da questão ---
    // Overlays da própria KaIA (intervenção, probe, avisos — id^="kaia-") contam
    // como área de estudo: responder um feedback NÃO é "sair", é interagir com ela.
    document.addEventListener('click', (e) => {
        if (!isMissionActive || !quizView) return;
        if (quizView.contains(e.target) || e.target.closest('[id^="kaia-"]')) return;
        logEvent('click_outside', { x: e.clientX, y: e.clientY });
    });

    // --- copiar / colar ---
    ['copy', 'paste'].forEach(tipo => {
        document.addEventListener(tipo, () => {
            if (isMissionActive) logEvent('copy_paste', { action: tipo });
        });
    });
}

// ============================================================
//                      MISSÃO (QUIZ)
// ============================================================
// Fallback local usado quando o Gemini está indisponível (ex.: cota estourada):
// a missão inicia mesmo assim e o pipeline continua testável.
const TEMAS_FALLBACK = {
    MAT:  ['Álgebra', 'Geometria', 'Trigonometria', 'Funções', 'Probabilidade', 'Estatística'],
    PORT: ['Morfologia', 'Sintaxe', 'Interpretação de Texto', 'Figuras de Linguagem', 'Variação Linguística', 'Gêneros Textuais'],
    HIS:  ['Brasil Colônia', 'Era Vargas', 'Guerras Mundiais', 'Idade Média', 'Revolução Industrial', 'Guerra Fria'],
    GEO:  ['Geopolítica', 'Climatologia', 'Cartografia', 'Urbanização', 'Regiões do Brasil', 'Globalização'],
    BIO:  ['Genética', 'Botânica', 'Ecologia', 'Citologia', 'Evolução', 'Corpo Humano'],
    FIS:  ['Mecânica', 'Eletromagnetismo', 'Óptica', 'Termodinâmica', 'Ondas', 'Cinemática'],
    QUI:  ['Estequiometria', 'Química Orgânica', 'Termoquímica', 'Eletroquímica', 'Soluções', 'Ligações Químicas'],
    ING:  ['Interpretação de Texto', 'Vocabulário em Contexto', 'Tempos Verbais', 'Falsos Cognatos', 'Conectivos', 'Ideia Central'],
    FIL:  ['Filosofia Antiga', 'Ética e Moral', 'Filosofia Política', 'Teoria do Conhecimento', 'Filosofia Moderna', 'Existencialismo'],
    SOC:  ['Trabalho e Sociedade', 'Movimentos Sociais', 'Cultura e Identidade', 'Cidadania e Direitos', 'Globalização', 'Desigualdade Social'],
};

const questaoFallback = (subject, tema) => ({
    q: `[OFFLINE] Questão de teste sobre "${tema}" (${subject}). Escolha uma opção:`,
    opts: ['Opção A', 'Opção B', 'Opção C', 'Opção D', 'Opção E'],
    ans: 0,
    explicacao: 'Modo offline: a explicação detalhada aparece quando a IA está disponível.',
    porque_erradas: ['', 'Não é a alternativa correta.', 'Não é a alternativa correta.',
                     'Não é a alternativa correta.', 'Não é a alternativa correta.'],
});

// ============================================================
//        LOTE DE QUESTÕES (economiza cota do Gemini)
// ============================================================
// Uma chamada ao /gerar-questao traz LOTE_QTD questões; consumimos uma por vez e
// só pedimos outro lote quando a fila esvazia. Trocar de tema descarta o lote.
let filaQuestoes     = [];
let filaChave        = null;   // `${materia}::${tema}` do lote em memória
let loteBloqueadoAte = 0;      // enquanto performance.now() < isto, não re-chama o backend
const LOTE_QTD          = 5;
const LOTE_COOLDOWN_MS  = 120000;   // após uma falha (ex.: cota estourada), 2 min sem re-tentar

async function obterProximaQuestao(subject, tema) {
    const chave = `${subject}::${tema}`;
    if (filaChave !== chave) { devolverFila(); filaChave = chave; }   // tema novo → devolve o lote antigo
    if (!filaQuestoes.length) {
        // Em cooldown após falha: serve fallback SEM re-chamar (não spamar endpoint que já falhou).
        if (performance.now() < loteBloqueadoAte) return questaoFallback(subject, tema);
        try {
            // Um hobbie aleatório por LOTE (não fixo na sessão): sorteia da lista do aluno.
            const hobbiesAluno = lerHobbies();
            const hobbie = hobbiesAluno.length ? hobbiesAluno[Math.floor(Math.random() * hobbiesAluno.length)] : null;
            const data = await postJSON('/gerar-questao', {
                materia: subject, tema, hobbie, user_id: userId, quantidade: LOTE_QTD, nivel: nivelDificuldade
            });
            const lote = Array.isArray(data?.questoes) ? data.questoes : [];
            filaQuestoes = lote.filter(q => q && Array.isArray(q.opts));
            if (!filaQuestoes.length) throw new Error(data?.erro || 'lote vazio');
            loteBloqueadoAte = 0;   // sucesso limpa o cooldown
        } catch (e) {
            console.warn('[KaIA] /gerar-questao (lote) indisponível, usando questão local:', e);
            loteBloqueadoAte = performance.now() + LOTE_COOLDOWN_MS;
            return questaoFallback(subject, tema);
        }
    }
    return filaQuestoes.shift();
}

// Devolve ao pool as questões do lote que NÃO foram usadas (mudou de nível/tema
// ou encerrou). Limpa a fila na hora; envia com keepalive p/ sobreviver a reload.
function devolverFila() {
    const ids = filaQuestoes.map(q => q && q.questao_id).filter(Boolean);
    filaQuestoes = [];
    if (ids.length) {
        postJSON('/questoes/devolver', { user_id: userId, questao_ids: ids }, true)
            .catch(e => console.warn('[KaIA] /questoes/devolver falhou:', e));
    }
}

// Troca qual das três telas de materias.html está visível.
function mostrarTela(id) {
    ['menu-view', 'temas-view', 'quiz-view'].forEach(tela => {
        const el = $(tela);
        if (el) el.style.display = (tela === id) ? 'block' : 'none';
    });
}

// Liga/desliga o AI Loader (ilha React em js/ai-loader.js). `alvo` é o container
// ESTÁVEL onde a ilha monta (.question-wrapper no quiz, #temas-view nos temas) —
// nunca um que a lógica limpe. Devolve true se montou de fato: só nesse caso quem
// chama apaga o texto de espera, então sem a ilha a tela fica com a mensagem de
// sempre. Blindado: falha da ilha vira aviso no console e a geração segue normal,
// inclusive o fallback. Ver CLAUDE.md.
const areaQuestao = () => document.querySelector('.question-wrapper');

function esperaIA(palavra, rotulo, alvo) {
    try {
        return !!(window.KaiaAILoader && window.KaiaAILoader.mostrar(palavra, rotulo, alvo));
    } catch (e) {
        console.warn('[KaIA] AI Loader indisponível:', e);
        return false;
    }
}
function esperaIAFim() {
    try {
        if (window.KaiaAILoader) window.KaiaAILoader.esconder();
    } catch (e) {
        console.warn('[KaIA] AI Loader não escondeu:', e);
    }
}

// renderBotoes foi movida para puros.js (testável); carregada antes.

// 1) A IA sugere os subtemas da matéria.
async function abrirMateria(subject) {
    const temasBox = $('temas-display');
    mostrarTela('temas-view');
    temasBox.innerHTML = 'KaIA montando os temas...';
    // Montou a ilha? então ela substitui o texto; senão o texto fica.
    if (esperaIA('Montando', 'Montando os temas da matéria', $('temas-view'))) temasBox.innerHTML = '';

    let temas = [];
    try {
        const data = await postJSON('/temas', { materia: subject });
        temas = data.temas || [];
    } catch (e) {
        console.warn('[KaIA] /temas indisponível:', e);
    } finally {
        esperaIAFim();   // sai sempre: o overlay é de tela cheia
    }
    if (!temas.length) {
        temas = TEMAS_FALLBACK[subject] || ['Tema 1', 'Tema 2', 'Tema 3'];
        console.warn('[KaIA] usando temas locais (fallback).');
    }
    temasAtuais = temas;   // guarda p/ a intervenção "troca de tema"
    renderBotoes(temasBox, temas, (tema) => startMission(subject, tema));
}

// ==== SESSÃO CONTÍNUA + META POR RODADA + META DIÁRIA ====
let questoesRespondidas = 0;    // respondidas NESTA sessão (para o resumo)
let acertosSessao       = 0;    // acertos NESTA sessão (resumo/XP)
let questoesNaRodada    = 0;    // respondidas na RODADA atual (0..META); zera a cada rodada
let respondidasHojeBase = 0;    // respondidas HOJE antes desta sessão (backend)
let metaDiariaContada   = false;// já contou a meta diária na streak nesta sessão?
const META_QUESTOES = 10;       // meta = 10 (por rodada e por dia)

// Probe de self-report (rótulo real de atenção p/ o ML): 1 por rodada, numa questão
// sorteada da 5ª à 9ª — baseline de RT já aquecido e antes do fim da rodada.
let probeAlvoRodada = 0;
function sortearAlvoProbe() { probeAlvoRodada = 5 + Math.floor(Math.random() * 5); }  // 5..9

// Revisão de erros (Parte 7): guarda as questões erradas da sessão + estado da revisão.
let errosSessao = [];
let emRevisao   = false;
let revisaoFila = [];
let revisaoTotal = 0;
let revisaoRespondidas = 0;

// Dificuldade adaptativa (Parte 6): começa em 2; +1 a cada 2 acertos seguidos
// (máx 5), -1 a cada 2 erros seguidos (mín 1). Passa no /gerar-questao.
let nivelDificuldade = 2;
let acertosSeguidos  = 0;
let errosSeguidos    = 0;
const NIVEL_MIN = 1, NIVEL_MAX = 5;

function ajustarNivel(acertou) {
    const antes = nivelDificuldade;
    if (acertou) {
        acertosSeguidos++; errosSeguidos = 0;
        if (acertosSeguidos >= 2 && nivelDificuldade < NIVEL_MAX) { nivelDificuldade++; acertosSeguidos = 0; }
    } else {
        errosSeguidos++; acertosSeguidos = 0;
        if (errosSeguidos >= 2 && nivelDificuldade > NIVEL_MIN) { nivelDificuldade--; errosSeguidos = 0; }
    }
    if (nivelDificuldade !== antes) devolverFila();   // nível mudou → devolve o lote (novo nível na próxima)
    atualizarNivel();
}

// Indicador discreto do nível (●●○○○) no quiz-nav.
function atualizarNivel() {
    const el = $('nivel-dif');
    if (!el) return;
    el.textContent = 'Nível ' + '●'.repeat(nivelDificuldade) + '○'.repeat(NIVEL_MAX - nivelDificuldade);
    el.title = `Dificuldade ${nivelDificuldade} de ${NIVEL_MAX}`;
}

// Total do DIA = base do backend + as respondidas nesta sessão.
const totalHoje = () => respondidasHojeBase + questoesRespondidas;

// Baseline diário: quantas o aluno já respondeu hoje (antes desta sessão).
async function carregarMetaHoje() {
    respondidasHojeBase = 0;
    try {
        const r = await apiFetch(`/questoes/hoje?user_id=${encodeURIComponent(userId)}`);
        if (r.ok) { const d = await r.json(); respondidasHojeBase = d.respondidas_hoje || 0; }
    } catch (e) { console.warn('[KaIA] /questoes/hoje indisponível:', e); }
}

// Abre a sessão de estudo UMA vez — não por questão. Cria o session_id, atualiza
// streak/contadores e liga o pomodoro; a sequência inteira usa ESTA sessão.
async function iniciarSessaoEstudo(subject, tema) {
    sessaoDeEstudoAberta = true;
    questoesRespondidas = 0;
    acertosSessao = 0;
    questoesNaRodada = 0;
    metaDiariaContada = false;
    sortearAlvoProbe();
    errosSessao = [];
    emRevisao = false;
    nivelDificuldade = 2;
    acertosSeguidos = 0;
    errosSeguidos = 0;
    iniciarPomodoro();                          // ciclo foco/pausa da sessão inteira
    await criarSessao();                        // 1 session_id para toda a série
    await carregarMetaHoje();                   // baseline do dia (contador diário)
    const features = registrarInicioSessao();
    logEvent('session_start', { materia: subject, tema, features });
    enviarPerfil({ tipo: 'session_start', materia: subject, tema });
}

// Carrega e renderiza UMA questão da fila. NÃO cria sessão (a sessão é contínua).
async function carregarQuestao(subject, tema) {
    currentSubject = subject;
    currentTema = tema;
    const fb = $('feedback');
    if (fb) { fb.className = 'feedback-msg'; fb.innerHTML = ''; }
    $('question-display').innerText = 'KaIA criando sua questão...';
    $('options-display').innerHTML  = '';
    if (esperaIA('Gerando', 'Preparando sua questão', areaQuestao())) $('question-display').innerText = '';

    try {
        currentQuestion = await obterProximaQuestao(subject, tema);   // vem da fila (lote); fallback interno
    } finally {
        esperaIAFim();   // sai sempre: o overlay é de tela cheia
    }

    // zera os sensores para esta questão
    isMissionActive = true;
    idleTime = 0;
    mudancasAba = 0;
    focusLostAt = null;

    const subjectEl = $('current-subject');
    if (subjectEl) subjectEl.innerText = `${subject} · ${tema}`;
    atualizarContador();

    dynamicLimit = calculateReadingTime(currentQuestion.q, currentQuestion.opts);
    $('question-display').innerText = currentQuestion.q;
    renderBotoes($('options-display'), currentQuestion.opts, (_opt, idx, btn) => checkAnswer(idx, btn));

    questionShownAt = performance.now();
    firstInteractionAt = 0;   // zera timing/trajeto para a nova questão
    mouseSamples = [];
    tempoOciosoMs = 0;
    tempoDwellMs = 0;
    dwellEntrouEm = 0;
    iniciarIdleMonitor();
    iniciarPollIntervencao();
    iniciarGatilhoTeste();   // (gatilho de teste) PROVISÓRIO — REMOVER esta linha

    // Se o caderno está aberto, troca o canvas para o tema desta questão.
    if (typeof cadAberto === 'function' && cadAberto() && cadTema !== tema) {
        carregarCaderno(tema);
    }
}

// Entrada ao escolher um tema: abre a sessão (se ainda não aberta) e carrega a 1ª
// questão. Trocar de matéria/tema no meio NÃO encerra — só muda as próximas questões.
async function startMission(subject, tema) {
    currentSubject = subject;
    currentTema = tema;
    mostrarTela('quiz-view');
    $('question-display').innerText = 'KaIA criando sua questão...';
    $('options-display').innerHTML  = '';
    if (esperaIA('Gerando', 'Preparando sua questão', areaQuestao())) $('question-display').innerText = '';
    try {
        if (!sessaoDeEstudoAberta) await iniciarSessaoEstudo(subject, tema);
        await carregarQuestao(subject, tema);
    } finally {
        esperaIAFim();   // sai sempre, inclusive se iniciarSessaoEstudo falhar
    }
}

// Só a barra da rodada (preenche conforme as respostas). Chamada ao responder.
function atualizarBarraRodada() {
    const fill = $('meta-fill');
    if (fill) fill.style.width = `${Math.min(questoesNaRodada / META_QUESTOES, 1) * 100}%`;
}

// Meta diária na TELA DE MATÉRIAS: "Faltam X questões para a meta de hoje".
async function mostrarMetaDiariaMenu() {
    const el = $('meta-diaria-menu');
    if (!el) return;
    let hoje = 0;
    try {
        const r = await apiFetch(`/questoes/hoje?user_id=${encodeURIComponent(userId)}`);
        if (r.ok) { const d = await r.json(); hoje = d.respondidas_hoje || 0; }
    } catch (e) { console.warn('[KaIA] /questoes/hoje indisponível:', e); }
    const faltam = Math.max(META_QUESTOES - hoje, 0);
    el.textContent = faltam > 0
        ? `Faltam ${faltam} ${faltam === 1 ? 'questão' : 'questões'} para a meta de hoje.`
        : '✓ Meta de hoje concluída — mandou bem!';
}

// Aviso gentil (na pilha do canto) quando a meta diária é alcançada.
function notificarMetaDiaria() {
    const el = document.createElement('div');
    el.className = 'meta-toast';
    el.setAttribute('role', 'status');
    el.textContent = 'Meta de hoje alcançada — 10 questões!';
    _pilhaNotif().appendChild(el);
    requestAnimationFrame(() => el.classList.add('visivel'));
    setTimeout(() => {
        el.classList.remove('visivel');
        setTimeout(() => el.remove(), 400);   // remove da pilha após o fade
    }, 5000);
}

// Contador da RODADA ("Questão X de 10") + barra + streak. Chamado ao carregar a questão.
function atualizarContador() {
    const n = Math.min(questoesNaRodada + 1, META_QUESTOES);
    const el = $('contador-questoes');
    if (el) el.textContent = `Questão ${n} de ${META_QUESTOES}`;
    atualizarBarraRodada();
    atualizarStreak();
    atualizarNivel();
}

// Streak "🔥 X dias" — lida do perfil (avança só na meta, via registrarMetaDiaria).
function atualizarStreak() {
    const el = $('streak-dias');
    if (!el) return;
    const dias = lerPerfil().sequencia_dias_estudo || 0;
    el.textContent = dias > 0 ? `🔥 ${dias} ${dias === 1 ? 'dia' : 'dias'}` : '';
}

// 3) Resposta: registra o tempo e mostra o feedback. A SESSÃO CONTINUA (Parte 1) —
// só encerra na meta ou no "Encerrar sessão".
function checkAnswer(idx, btn) {
    if (!isMissionActive) return;
    const acertou = (idx === currentQuestion.ans);

    // Modo REVISÃO: só mostra a explicação — não conta nada nem chama o backend.
    if (emRevisao) {
        isMissionActive = false;
        clearInterval(idleInterval);
        revisaoRespondidas++;
        if (acertou) currentQuestion.pendenteRevisao = false;   // acertou na revisão → sai da fila de pendências (Fase 1.1). Mesmo objeto de errosSessao (fila é cópia rasa), então o registro é atualizado.
        atualizarBarraRevisao();     // a barra enche ao longo da revisão
        mostrarExplicacao(idx, acertou);
        return;
    }

    if (dwellEntrouEm) {   // respondeu com o cursor ainda sobre as alternativas → fecha o dwell
        tempoDwellMs += performance.now() - dwellEntrouEm;
        dwellEntrouEm = 0;
    }
    if (questionShownAt > 0) {
        logEvent('question_answer', {
            tempo_resposta_ms: Math.round(performance.now() - questionShownAt),
            tempo_iniciacao_resposta_ms: firstInteractionAt ? Math.round(firstInteractionAt - questionShownAt) : null,
            nivel_dificuldade: nivelDificuldade,   // dificuldade REAL (adaptativa), não mais constante
            mouse_track: mouseSamples,             // trajeto [dt_ms, x, y] → features de mouse no Incr. B
            tempo_ocioso_s: Math.round(tempoOciosoMs / 1000),   // ocioso c/ aba focada
            tempo_dwell_sem_responder_s: Math.round(tempoDwellMs / 100) / 10,   // hesitação sobre as alternativas
            acertou,
            opcao_escolhida: idx,
            opcao_correta: currentQuestion.ans,
            tipo_questao: 'objetiva'
        });
    }
    questoesRespondidas++;
    historicoQuestoes.push(currentQuestion);   // fonte do checkpoint de recuperação
    if (acertou) acertosSessao++;
    else errosSessao.push({ ...currentQuestion, escolhaAluno: idx, pendenteRevisao: true });   // revisão (Parte 7): resposta do aluno (accordion) + ainda pendente de revisão (Fase 1.1)
    questoesNaRodada++;
    ajustarNivel(acertou);        // dificuldade adaptativa (Parte 6)
    atualizarBarraRodada();       // a barra da rodada sobe já na resposta
    if (questoesNaRodada === probeAlvoRodada) dispararProbe();   // probe de self-report (1/rodada, 5ª–9ª)
    // Ao atingir a META DIÁRIA (10 no dia, 1ª vez na sessão): conta a streak + avisa no canto.
    if (!metaDiariaContada && totalHoje() >= META_QUESTOES) {
        registrarMetaDiaria();
        atualizarStreak();
        notificarMetaDiaria();
        metaDiariaContada = true;
    }

    // Pausa os sensores enquanto o aluno lê a explicação — mas NÃO encerra a sessão.
    isMissionActive = false;
    clearInterval(idleInterval);
    setEstado('RESPONDIDA');   // também baixa o overlay de inatividade, se estava visível

    mostrarExplicacao(idx, acertou);
}

// Destaca correta/errada e mostra a explicação do erro, sem trocar de tela (Etapa 7).
// Usa textContent nos trechos vindos da IA (evita injeção de HTML no enunciado).
function mostrarExplicacao(escolha, acertou) {
    $$('#options-display .option-btn').forEach((b, i) => {
        b.disabled = true;
        b.classList.add('respondido');
        if (i === currentQuestion.ans) b.classList.add('correta');
        else if (i === escolha)        b.classList.add('errada');
    });

    const porque = currentQuestion.porque_erradas || [];
    const fb = $('feedback');
    fb.className = 'feedback-msg exp-aberta';
    fb.innerHTML = '';

    const bloco = document.createElement('div');
    bloco.className = 'exp-bloco';

    const h = document.createElement('h3');
    h.textContent = acertou ? 'Isso mesmo!' : 'Vamos entender';
    bloco.appendChild(h);

    const pExp = document.createElement('p');
    pExp.innerHTML = '<strong>Por que esta é a resposta: </strong>';
    pExp.appendChild(document.createTextNode(currentQuestion.explicacao || ''));
    bloco.appendChild(pExp);

    if (!acertou && porque[escolha]) {
        const pErr = document.createElement('p');
        pErr.className = 'exp-erro';
        const forte = document.createElement('strong');
        forte.textContent = `Sua escolha (${currentQuestion.opts[escolha]}): `;
        pErr.appendChild(forte);
        pErr.appendChild(document.createTextNode(porque[escolha]));
        bloco.appendChild(pErr);
    }

    fb.appendChild(bloco);

    // Rodada completa (10 respondidas) → o botão abre o modal de parabéns; senão, próxima.
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'botao-proxima';
    if (emRevisao) {
        btn.textContent = revisaoFila.length > 0 ? 'Próxima (revisão) →' : 'Voltar ao resumo →';
        btn.addEventListener('click', carregarQuestaoRevisao);
    } else if (questoesNaRodada >= META_QUESTOES) {
        btn.textContent = 'Ver resultado da rodada →';
        btn.addEventListener('click', abrirModalRodada);
    } else {
        btn.textContent = 'Próxima questão →';
        btn.addEventListener('click', proximaQuestao);
    }
    fb.appendChild(btn);
    fb.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// "Próxima questão": carrega a próxima da fila SEM criar sessão.
function proximaQuestao() {
    esconderProbe();   // o probe é sobre a questão que acabou — não deixa vazar pra próxima
    carregarQuestao(currentSubject, currentTema);
}

// ============================================================
//        PROBE DE ATENÇÃO (self-report — rótulo real p/ o ML)
// ============================================================
// Pergunta discreta ("sua mente estava na questão?") pareada com o momento.
// 3 opções = as 3 classes do modelo. Vira evento 'probe_atencao' no /events.
//
// ============================================================
//   COMO EDITAR AS PERGUNTAS (é só mexer no PERGUNTAS_PROBE abaixo)
// ============================================================
// Adicionar uma pergunta = colar mais um objeto na lista. Nada de lógica muda.
// Só duas regras, e as duas existem porque isto aqui NÃO é texto de tela — é o
// rótulo que treina o modelo de atenção:
//
//   1. SEMPRE três opções, SEMPRE nesta ordem:
//         [engajado, distraido, muito_distraido]
//      A 2ª é "a mente vagou mas eu continuei aqui"; a 3ª é "eu saí para outra
//      coisa". Inverter a ordem não muda a tela, corrompe o dataset em silêncio.
//      (Há uma checagem em _validarPergunta que descarta entrada malformada.)
//
//   2. O `id` é ESTÁVEL e nunca se reaproveita. É ele que vai no evento, não a
//      posição na lista — se a análise dependesse do índice, inserir uma
//      pergunta no meio reescreveria o significado de todo o dado já coletado.
//
// Ao escrever: nenhuma opção pode soar como "a resposta certa". Autorrelato que
// premia o foco devolve dado enviesado, e é esse dado que vira modelo. Daí o
// "sem certo nem errado" e o "sem julgamento" em algumas frases.
const ESTADOS_PROBE = ['engajado', 'distraido', 'muito_distraido'];

// PENDENTE (Bia + Vitor) — decisão de CONTEÚDO, não de código:
//   - Quais destas oito ficam. As sete últimas são proposta; a 1ª é a original.
//   - Variar a frase resolve o clique automático, mas introduz variância de
//     medida: formulações diferentes deslocam um pouco a distribuição das
//     respostas. É para isso que o `pergunta_id` vai no evento — dá para checar
//     depois se alguma frase puxa demais para um lado e aposentá-la.
const PERGUNTAS_PROBE = [
    { id: 'mente-na-questao',
      pergunta: 'Rapidinho: sua mente estava na questão agora?',
      opcoes: ['Sim, estava focado', 'Minha mente estava viajando', 'Fui ver outra coisa'] },

    { id: 'onde-estava-cabeca',
      pergunta: 'Só pra saber: onde estava sua cabeça nos últimos segundos?',
      opcoes: ['Na questão', 'Vagando por aí', 'Em outra coisa, fora daqui'] },

    { id: 'como-estava-atencao',
      pergunta: 'Sem certo nem errado: como estava sua atenção agora?',
      opcoes: ['Inteira na questão', 'Meio dispersa', 'Longe daqui'] },

    { id: 'lendo-ou-passando-olho',
      pergunta: 'Você estava lendo de verdade ou passando o olho?',
      opcoes: ['Lendo de verdade', 'Passando o olho, pensando noutra coisa', 'Nem estava aqui'] },

    { id: 'percebeu-mente-sair',
      pergunta: 'Um segundo: você percebeu sua mente sair da questão?',
      opcoes: ['Não, fiquei nela', 'Saiu e voltou', 'Saiu de vez'] },

    { id: 'questao-teve-atencao',
      pergunta: 'E aí, essa questão teve sua atenção?',
      opcoes: ['Teve', 'Mais ou menos, a cabeça fugiu', 'Não, fui fazer outra coisa'] },

    { id: 'o-que-rolava',
      pergunta: 'Checagem rápida: o que rolava na sua cabeça?',
      opcoes: ['Estava resolvendo', 'Estava pensando noutra coisa', 'Estava em outra tela'] },

    { id: 'estava-aqui',
      pergunta: 'Sem julgamento: você estava aqui agora?',
      opcoes: ['Estava', 'Meio aqui, meio não', 'Não, estava fora'] },
];

// ---- JANELAS DE TAMANHOS VARIADOS ---------------------------------------
// A CAPACIDADE está pronta; a LÓGICA de quando usar cada uma, não — é decisão
// de ML (Bia + Vitor). Enquanto _escolherTamanhoProbe devolver 'medio', a
// janelinha fica idêntica à de sempre: 'medio' É o tamanho atual, 340px.
// As classes CSS correspondentes estão no style.css, no bloco do #kaia-probe.
const TAMANHOS_PROBE = {
    pequeno: 'probe-pequeno',   // 260px
    medio:   'probe-medio',     // 340px — o de hoje, e o padrão
    grande:  'probe-grande',    // 460px
};

// PENDENTE (Bia + Vitor): QUANDO cada tamanho aparece e POR QUÊ.
// Para ligar a variação, troque SÓ o corpo desta função — devolva a chave de
// TAMANHOS_PROBE que quiser ('pequeno' | 'medio' | 'grande'). O tamanho
// escolhido já viaja no evento (campo `tamanho`), então o experimento nasce
// analisável: sem esse registro dá para ver os rótulos, mas não com qual
// janela cada um foi colhido.
// Ideias que ficaram na mesa, nenhuma decidida: sortear por sessão (mantém o
// tamanho estável para o aluno e compara ENTRE alunos), alternar por rodada
// (compara DENTRO do mesmo aluno), ou amarrar ao estado previsto pelo modelo.
function _escolherTamanhoProbe() {
    return 'medio';
}

let probeTimeout = null;
let probeAtual   = null;   // { id, tamanho } do que está na tela — vai no evento
let _probeUltimoId = null; // evita repetir a mesma frase em dois disparos seguidos

// Descarta entrada malformada em vez de gravar rótulo errado: com menos (ou
// mais) de três opções, o pareamento opção→estado sairia deslocado e o erro só
// apareceria meses depois, no dataset.
const _validarPergunta = (p) =>
    !!p && typeof p.id === 'string' && typeof p.pergunta === 'string'
    && Array.isArray(p.opcoes) && p.opcoes.length === ESTADOS_PROBE.length;

// PENDENTE (Bia + Vitor): sorteio ou rotação fixa? Por ora sorteia evitando
// repetir a frase anterior — variedade sem virar previsível.
function _sortearPergunta() {
    const validas = PERGUNTAS_PROBE.filter(_validarPergunta);
    if (!validas.length) return null;
    const candidatas = validas.length > 1
        ? validas.filter(p => p.id !== _probeUltimoId)
        : validas;
    return candidatas[Math.floor(Math.random() * candidatas.length)];
}

// Remonta o conteúdo a CADA disparo — o card é o mesmo nó (o CSS e o
// _probeNaTela contam com isso), mas a pergunta e o tamanho mudam. Montado com
// textContent, não com innerHTML: o texto vem de uma lista que humanos editam,
// e um `&` ou um apóstrofo não podem virar marcação.
function _montarCardProbe(pergunta, tamanho) {
    let card = $('kaia-probe');
    if (!card) {
        card = document.createElement('div');
        card.id = 'kaia-probe';
        document.body.appendChild(card);
    }
    card.classList.remove(...Object.values(TAMANHOS_PROBE));
    card.classList.add(TAMANHOS_PROBE[tamanho] || TAMANHOS_PROBE.medio);
    card.replaceChildren();

    const q = document.createElement('p');
    q.className = 'probe-q';
    q.textContent = pergunta.pergunta;
    card.appendChild(q);

    const caixa = document.createElement('div');
    caixa.className = 'probe-btns';
    pergunta.opcoes.forEach((rotulo, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.dataset.estado = ESTADOS_PROBE[i];   // a ORDEM é o contrato (ver acima)
        b.textContent = rotulo;
        b.addEventListener('click', () => responderProbe(b.dataset.estado));
        caixa.appendChild(b);
    });
    card.appendChild(caixa);
    return card;
}

function dispararProbe() {
    const pergunta = _sortearPergunta();
    if (!pergunta) return;            // banco vazio ou todo malformado: não pergunta nada
    const tamanho = _escolherTamanhoProbe();
    const card = _montarCardProbe(pergunta, tamanho);
    probeAtual = { id: pergunta.id, tamanho };
    _probeUltimoId = pergunta.id;
    card.style.display = 'block';
    clearTimeout(probeTimeout);
    probeTimeout = setTimeout(esconderProbe, 25000);   // o momento passa se for ignorado
}

function esconderProbe() {
    clearTimeout(probeTimeout);
    const c = $('kaia-probe');
    if (c) c.style.display = 'none';
    probeAtual = null;
}

function responderProbe(estado) {
    logEvent('probe_atencao', {
        estado,
        // QUAL frase e QUAL janela geraram este rótulo. Vai no payload do evento
        // (session_events.payload é jsonb — não precisa de migration). A tabela
        // probe_labels segue só com estado + as 20 features.
        // PENDENTE (Bia + Vitor): se o treinar_com_probe.py precisar destes dois
        // campos direto em probe_labels, aí sim é uma migration.
        pergunta_id: probeAtual?.id ?? null,
        tamanho: probeAtual?.tamanho ?? null,
        questao_na_rodada: questoesNaRodada,
        questoes_respondidas: questoesRespondidas,
    });
    esconderProbe();
}

// ==== MODAL DE RODADA / RESUMO (meta = limite sugerido) ====
const FRASES_RESUMO = [
    'Cada questão te deixa mais perto do seu objetivo. Continue no seu ritmo!',
    'O que importa é a constância — você apareceu e se dedicou hoje.',
    'Errar faz parte de aprender. Seu esforço é o que conta.',
    'Mais um passo dado. Pode se orgulhar de ter estudado hoje!',
    'Foco e paciência: você está construindo seu progresso aos poucos.',
    'Boa sessão! Descansar também faz parte de aprender bem.',
];

// Preenche os stats do resumo (acerto com o total embutido, streak, XP).
function preencherResumo() {
    const total   = questoesRespondidas;
    const acertos = acertosSessao;
    const xp      = acertos * 10 + (total - acertos) * 5;   // 10 por acerto, 5 por erro (só exibe)
    const streak  = lerPerfil().sequencia_dias_estudo || 0;
    const set = (id, txt) => { const el = $(id); if (el) el.textContent = txt; };
    set('resumo-acerto', `${acertos} de ${total}`);
    set('resumo-streak', `🔥 ${streak}`);
    set('resumo-xp',     `${xp} XP`);
}

// Ao completar a rodada de 10: modal SEM título — só o resumo rápido + escolha.
function abrirModalRodada() {
    preencherResumo();
    $('resumo-titulo').hidden = true;
    $('resumo-frase').hidden  = true;
    $('resumo-erros').hidden  = true;
    $('btn-continuar').hidden = false;
    $('btn-encerrar').hidden  = false;
    $('btn-revisar').hidden   = true;
    $('btn-voltar').hidden    = true;
    $('resumo-overlay').hidden = false;
}

// "Continuar estudando": nova rodada — zera contador/barra, mantém sessão e sensores.
function continuarRodada() {
    $('resumo-overlay').hidden = true;
    questoesNaRodada = 0;
    sortearAlvoProbe();
    atualizarContador();       // "Questão 1 de 10", barra zerada
    carregarQuestao(currentSubject, currentTema);
}

// "Encerrar sessão": encerra de fato e vira a tela de resumo COMPLETO (com frase).
function encerrarSessaoComResumo() {
    sessaoDeEstudoAberta = false;
    isMissionActive = false;
    pararPomodoro();
    _limparPomodoro();
    encerrarSessao();          // POST /sessions/{id}/end
    devolverFila();            // devolve o que sobrou na fila
    clearInterval(idleInterval);
    clearTimeout(_fbTardioTimer);   // nada de card de feedback caindo sobre o resumo

    preencherResumo();
    $('resumo-titulo').textContent = 'Sessão concluída!';
    $('resumo-titulo').hidden = false;
    $('resumo-frase').textContent = FRASES_RESUMO[Math.floor(Math.random() * FRASES_RESUMO.length)];
    $('resumo-frase').hidden  = false;
    preencherErros();          // lista de erradas + botão "Revisar erros" (Parte 7)
    $('btn-continuar').hidden = true;
    $('btn-encerrar').hidden  = true;
    $('btn-voltar').hidden    = false;
    $('resumo-overlay').hidden = false;
}

// "Voltar às matérias": recarrega mostrando o menu de matérias.
function voltarDoResumo() {
    location.reload();
}

// ==== REVISÃO DE ERROS (Parte 7) ====
// Popula a lista de questões erradas (accordion) + o botão "Revisar erros".
// Fechado por padrão: cada item mostra só "Questão N" + indicador; abre com
// Pergunta / Sua resposta / Correta / Por quê. Reduz carga cognitiva (Fase 1).
function preencherErros() {
    const sec = $('resumo-erros'), lista = $('resumo-erros-lista'), btn = $('btn-revisar');
    if (!sec || !lista || !btn) return;
    if (!errosSessao.length) { sec.hidden = true; btn.hidden = true; return; }
    lista.innerHTML = '';
    // Accordion = registro COMPLETO da sessão (todas as erradas), com selo nas já revisadas.
    errosSessao.forEach((q, i) => lista.appendChild(montarErroAccordion(q, i)));
    sec.hidden = false;
    // Botão/fila de revisão contam só as PENDENTES (Fase 1.1); o botão some quando zera.
    const pendentes = errosSessao.filter(q => q.pendenteRevisao).length;
    btn.textContent = `Revisar erros (${pendentes})`;
    btn.hidden = pendentes === 0;
}

// Um item do accordion. Todo texto vindo da IA (enunciado, alternativas,
// explicação) entra via textContent — nunca innerHTML — para não abrir injeção.
function montarErroAccordion(q, i) {
    const n = i + 1;
    const painelId = `acc-erro-${i}`;

    const li = document.createElement('li');
    li.className = 'acc-item';

    // Cabeçalho clicável — fechado por padrão. O ✗ e a tag "Rever" dão o
    // indicador de erro por ícone+rótulo (não só por cor).
    const header = document.createElement('button');
    header.type = 'button';
    header.className = 'acc-header';
    header.setAttribute('aria-expanded', 'false');
    header.setAttribute('aria-controls', painelId);
    // Já revisada (acertou numa revisão) ganha selo verde; ainda pendente fica "Rever".
    const resolvida = q.pendenteRevisao === false;
    const tag = resolvida
        ? '<span class="acc-tag acc-tag--ok">✓ revisada</span>'
        : '<span class="acc-tag">Rever</span>';
    header.setAttribute('aria-label',
        `Questão ${n} — você errou${resolvida ? ', já revisada' : ''}, toque para ver os detalhes`);
    header.innerHTML =
        '<span class="acc-status" aria-hidden="true">✗</span>'
        + `<span class="acc-titulo">Questão ${n}</span>`
        + tag
        + '<span class="acc-chevron" aria-hidden="true">▸</span>';

    const painel = document.createElement('div');
    painel.className = 'acc-panel';
    painel.id = painelId;
    painel.hidden = true;
    painel.appendChild(_accCampo('Pergunta', q.q));
    painel.appendChild(_accLinha('erro', '✗', 'Sua resposta', _accOpcao(q, q.escolhaAluno)));
    painel.appendChild(_accLinha('ok',   '✓', 'Correta',     _accOpcao(q, q.ans)));
    if (q.explicacao) painel.appendChild(_accCampo('Por quê', q.explicacao));

    header.addEventListener('click', () => {
        const aberto = header.getAttribute('aria-expanded') === 'true';
        header.setAttribute('aria-expanded', String(!aberto));
        painel.hidden = aberto;
    });

    li.appendChild(header);
    li.appendChild(painel);
    return li;
}

// Campo empilhado (rótulo em cima, valor embaixo) — Pergunta / Por quê.
function _accCampo(rotulo, valor) {
    const p = document.createElement('p');
    p.className = 'acc-campo';
    const r = document.createElement('span');
    r.className = 'acc-rotulo';
    r.textContent = rotulo;
    const v = document.createElement('span');
    v.className = 'acc-valor';
    v.textContent = valor || '';
    p.append(r, v);
    return p;
}

// Faixa com ícone + rótulo + valor — Sua resposta / Correta (hierarquia por
// rótulo e ícone, não só por cor).
function _accLinha(tipo, icone, rotulo, valor) {
    const div = document.createElement('div');
    div.className = `acc-linha acc-linha--${tipo}`;
    const ic = document.createElement('span');
    ic.className = 'acc-ic';
    ic.setAttribute('aria-hidden', 'true');
    ic.textContent = icone;
    const rot = document.createElement('span');
    rot.className = 'acc-rot';
    rot.textContent = rotulo;
    const txt = document.createElement('span');
    txt.className = 'acc-txt';
    txt.textContent = valor;
    div.append(ic, rot, txt);
    return div;
}

// Texto de uma alternativa por índice; tolera índice ausente (defensivo).
function _accOpcao(q, idx) {
    return (Number.isInteger(idx) && q.opts && q.opts[idx] != null) ? q.opts[idx] : '—';
}

// "Revisar erros": mini-sessão só com as erradas, reusando os objetos (sem Gemini).
function iniciarRevisao() {
    const pendentes = errosSessao.filter(q => q.pendenteRevisao);   // só o que AINDA falta (Fase 1.1)
    if (!pendentes.length) return;
    emRevisao = true;
    revisaoFila = pendentes;      // filter já devolve array novo; os elementos são as mesmas refs de errosSessao
    revisaoTotal = pendentes.length;
    revisaoRespondidas = 0;
    $('resumo-overlay').hidden = true;
    mostrarTela('quiz-view');
    carregarQuestaoRevisao();
}

// Contador/barra da REVISÃO ("Revisão X de X") — reaproveita a barra do topo, zerada.
function atualizarBarraRevisao() {
    const fill = $('meta-fill');
    if (fill) fill.style.width = revisaoTotal ? `${(revisaoRespondidas / revisaoTotal) * 100}%` : '0%';
}
function atualizarContadorRevisao() {
    const el = $('contador-questoes');
    if (el) el.textContent = `Revisão ${Math.min(revisaoRespondidas + 1, revisaoTotal)} de ${revisaoTotal}`;
    atualizarBarraRevisao();
}

// Próxima questão da revisão; quando acabam, volta ao resumo (encerramento).
function carregarQuestaoRevisao() {
    if (!revisaoFila.length) {
        emRevisao = false;
        preencherErros();                     // atualiza botão (pendentes) + selos das revisadas (Fase 1.1)
        $('resumo-overlay').hidden = false;   // volta ao resumo
        return;
    }
    currentQuestion = revisaoFila.shift();
    const fb = $('feedback');
    if (fb) { fb.className = 'feedback-msg'; fb.innerHTML = ''; }
    const subjectEl = $('current-subject');
    if (subjectEl) subjectEl.innerText = 'Revisão de erros';
    atualizarContadorRevisao();
    $('question-display').innerText = currentQuestion.q;
    renderBotoes($('options-display'), currentQuestion.opts, (_opt, idx, btn) => checkAnswer(idx, btn));
    isMissionActive = true;
}

// "ABANDONAR" também encerra a sessão.
function resetSystem() {
    sessaoDeEstudoAberta = false;   // fecha o escopo do exit-intent antes de recarregar
    pararPomodoro();
    _limparPomodoro();              // fim deliberado da sessão: zera o ciclo
    encerrarSessao();
    devolverFila();
    clearInterval(idleInterval);
    location.reload();
}

// Fechar/recarregar a aba com a sessão contínua aberta também a encerra
// (mesmo durante a explicação, quando isMissionActive já é false).
window.addEventListener('beforeunload', () => {
    if (sessaoDeEstudoAberta) encerrarSessao();
});

// ============================================================
//        AVISO DE EXIT-INTENT (lembrete gentil, não bloqueia)
// ============================================================
// Balão na própria tela quando o cursor vai para a barra de abas durante a
// missão. Some sozinho; no máximo 1 por janela de cooldown para não virar spam.
const EXIT_AVISO_COOLDOWN_MS = 18000;   // reaparece a cada nova intenção, mín. ~18s entre avisos
const EXIT_AVISO_DURACAO_MS  = 5000;    // some sozinho após 5s
const EXIT_TOPO_PX           = 12;      // faixa do topo que conta como "saindo por cima"
let _exitAvisoAte   = 0;                 // performance.now() até quando fica em cooldown
let _exitAvisoTimer = null;

function _garantirAvisoSaida() {
    if ($('kaia-exit-aviso')) return;
    const el = document.createElement('div');
    el.id = 'kaia-exit-aviso';
    el.setAttribute('role', 'status');       // anunciado sem roubar foco
    el.setAttribute('aria-live', 'polite');
    el.innerHTML =
        `<strong class="kaia-exit-titulo">Atenção</strong>`
        + `<p>Você está saindo da tela de estudo. Distrações contam no seu tempo de foco.</p>`;
    document.body.appendChild(el);
}

function mostrarAvisoSaida() {
    const agora = performance.now();
    if (agora < _exitAvisoAte) return;                 // ainda em cooldown
    _exitAvisoAte = agora + EXIT_AVISO_COOLDOWN_MS;

    _garantirAvisoSaida();
    const el = $('kaia-exit-aviso');
    el.classList.add('visivel');
    clearTimeout(_exitAvisoTimer);
    _exitAvisoTimer = setTimeout(() => el.classList.remove('visivel'), EXIT_AVISO_DURACAO_MS);

    // Sinal de distração para o Pomodoro adaptativo (paralelo ao tab_change).
    logEvent('exit_intent', { origem: 'mouse_topo' });
}

// ============================================================
//        POMODORO (fixo por enquanto; adaptação vem depois)
// ============================================================
// Ciclo foco → pausa durante a sessão de estudo. A pausa PERSISTE por timestamp
// absoluto (localStorage): recarregar, trocar de aba ou fechar/reabrir não zera —
// o tempo corre mesmo com a aba oculta (anti-burla). O botão "Estou concentrado"
// pula a pausa (registrado para a fase adaptativa). Durante a pausa, os sensores
// de distração ficam suspensos (descanso não é distração).
const POMODORO_FOCO_MS  = 25 * 60 * 1000;   // FOCO 25 min
const POMODORO_PAUSA_MS = 5 * 60 * 1000;    // PAUSA 5 min
const POMODORO_KEY      = 'kaia_pomodoro';

let pausaAtiva      = false;
let pomodoroTicker  = null;

function _lerPomodoro()  { try { return JSON.parse(localStorage.getItem(POMODORO_KEY)); } catch { return null; } }
function _gravarPomodoro(o) { localStorage.setItem(POMODORO_KEY, JSON.stringify(o)); }
function _limparPomodoro() { localStorage.removeItem(POMODORO_KEY); }

function _iniciarFoco() {
    const st = _lerPomodoro() || {};
    _gravarPomodoro({ fase: 'foco', fimTs: Date.now() + POMODORO_FOCO_MS, ciclo: (st.ciclo || 0) + 1 });
}

// Liga o ciclo no começo da missão. Se houver estado válido (recarregou no meio),
// RETOMA de onde parou em vez de reiniciar.
function iniciarPomodoro() {
    const st = _lerPomodoro();
    const focoValido  = st && st.fase === 'foco'  && st.fimTs - Date.now() > 0;
    const pausaValida = st && st.fase === 'pausa' && st.fimTs - Date.now() > 0;
    if (pausaValida) {
        pausaAtiva = true;
        _mostrarPausa(st.fimTs - Date.now());
    } else if (!focoValido) {
        _limparPomodoro();
        _iniciarFoco();
    }
    _ligarTicker();
}

function _ligarTicker() {
    clearInterval(pomodoroTicker);
    pomodoroTicker = setInterval(_tickPomodoro, 500);
}

function pararPomodoro() {
    clearInterval(pomodoroTicker);
    pomodoroTicker = null;
}

function _tickPomodoro() {
    if (!sessaoDeEstudoAberta && !pausaAtiva) { pararPomodoro(); return; }
    const st = _lerPomodoro();
    if (!st) { _iniciarFoco(); return; }
    const restante = st.fimTs - Date.now();
    if (st.fase === 'foco') {
        if (restante <= 0) _entrarPausa();
    } else {
        if (restante <= 0) _concluirPausa();
        else _mostrarPausa(restante);
    }
}

function _entrarPausa() {
    const st = _lerPomodoro() || {};
    const ciclo = st.ciclo || 1;
    _gravarPomodoro({ fase: 'pausa', fimTs: Date.now() + POMODORO_PAUSA_MS, ciclo });
    pausaAtiva = true;                       // suspende exit-intent/idle/tab_change
    logEvent('pomodoro_pausa_inicio', { ciclo, foco_s: POMODORO_FOCO_MS / 1000 });
    _mostrarPausa(POMODORO_PAUSA_MS);
}

function _concluirPausa() {
    const st = _lerPomodoro() || {};
    logEvent('pomodoro_pausa_fim', { ciclo: st.ciclo });
    _fecharPausaERetomarFoco();
}

// Botão "Estou concentrado, continuar": registra o skip (sinal para a adaptação)
// e volta ao foco. A saída sempre funciona — a pausa nunca prende de vez.
function pularPausa() {
    const st = _lerPomodoro() || {};
    const restante_s = Math.max(0, Math.round(((st.fimTs || Date.now()) - Date.now()) / 1000));
    logEvent('pomodoro_skip', { ciclo: st.ciclo, foco_s: POMODORO_FOCO_MS / 1000, restante_s });
    _fecharPausaERetomarFoco();
}

function _fecharPausaERetomarFoco() {
    pausaAtiva = false;
    _esconderPausa();
    idleTime = 0;                            // retoma sensores sem contar o descanso
    if (isMissionActive) setEstado('ESTUDANDO');
    _iniciarFoco();
}

function _garantirOverlayPausa() {
    if ($('kaia-pausa')) return;
    const el = document.createElement('div');
    el.id = 'kaia-pausa';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-labelledby', 'kaia-pausa-titulo');
    el.innerHTML =
        `<div class="kaia-pausa-card">`
        + `<div class="kaia-pausa-tomate" aria-hidden="true">🍅</div>`
        + `<h2 id="kaia-pausa-titulo">Hora de uma pausa</h2>`
        + `<p class="kaia-pausa-sub">Respire um pouco. Você volta rendendo mais.</p>`
        + `<div class="kaia-pausa-contagem"><span id="kaia-pausa-seg">0</span>s</div>`
        + `<button type="button" class="kaia-pausa-skip">Estou concentrado, continuar</button>`
        + `</div>`;
    document.body.appendChild(el);
    el.querySelector('.kaia-pausa-skip').addEventListener('click', pularPausa);
}

function _mostrarPausa(restanteMs) {
    _garantirOverlayPausa();
    $('kaia-pausa').classList.add('aberto');
    $('kaia-pausa-seg').innerText = Math.max(0, Math.ceil(restanteMs / 1000));
}

function _esconderPausa() {
    const el = $('kaia-pausa');
    if (el) el.classList.remove('aberto');
}

// Retoma uma pausa em andamento ao (re)carregar a tela de estudo — cobre fechar/
// reabrir a aba durante a pausa. Só em materias.html; o timestamp já expirado é
// descartado naturalmente (restante <= 0).
function retomarPomodoroSePendente() {
    if (!location.pathname.endsWith('materias.html')) return;
    const st = _lerPomodoro();
    if (st && st.fase === 'pausa' && st.fimTs - Date.now() > 0) {
        pausaAtiva = true;
        _mostrarPausa(st.fimTs - Date.now());
        _ligarTicker();
    }
}

// ============================================================
//     CADERNO — canvas livre de anotações por tema (Etapa 9)
// ============================================================
// Cada tema tem seu canvas; cada aluno vê só o dele.
//  · TEXTO: localStorage (anticrash, síncrono) + PUT /anotacoes com debounce →
//    Supabase (cross-device). O servidor é a fonte de verdade do texto.
//  · IMAGEM: SÓ no localStorage (base64). Nunca vai pro Supabase — o backend
//    ainda filtra tipo!="texto" como 2ª barreira. Em outro dispositivo, o texto
//    vem do servidor e as imagens simplesmente não aparecem.
// Os caminhos de salvamento são ISOLADOS: gravar no localStorage nunca lança
// (retorna bool), então uma imagem que estoure a cota jamais derruba o texto.
const CAD_LARGURA_PADRAO = 200;          // px — largura inicial de um bloco de texto
const CAD_IMG_MAX_LADO   = 1000;         // px — re-encode: maior lado da imagem
const CAD_IMG_QUALIDADE  = 0.7;          // WebP
const CAD_IMG_DISP_LARG  = 240;          // px — largura de exibição da imagem no canvas
const CAD_TETO_IMG       = 500 * 1024;   // 500 KB por imagem (após re-encode)
const CAD_TETO_TEMA      = 2.5 * 1024 * 1024;  // ~2,5 MB de imagens por tema (folga nos ~5 MB)
let cadElementos = [];            // {id, tipo:'texto'|'imagem', x, y, w, h, z, conteudo}
let cadTema      = null;          // tema do canvas carregado agora
let cadSelecao   = null;          // id do bloco selecionado
let cadZ         = 1;             // maior z em uso (ordem de sobreposição)
let cadDirty     = false;         // há mudança de TEXTO ainda não confirmada no servidor
let cadSaveTimer = null;
let cadUltimoPonto = { x: 20, y: 20 };   // última posição do cursor sobre o canvas (p/ colar imagem)
let cadAvisoTimer  = null;

const cadChaveLocal = (tema) => `kaia_anotacoes_${userId}_${tema}`;

function cadCanvas()  { return $('caderno-canvas'); }
function cadAberto()  { const c = $('caderno'); return c && !c.hidden; }

// Abre/fecha o painel. Ao abrir, carrega o caderno do tema atual.
function toggleCaderno() {
    const painel = $('caderno');
    const botao  = $('caderno-toggle');
    if (!painel) return;
    const abrindo = painel.hidden;
    painel.hidden = !abrindo;
    if (botao) botao.setAttribute('aria-pressed', String(abrindo));
    if (abrindo) carregarCaderno(currentTema);
}

// Troca o canvas para um tema (salva o anterior antes, se estiver sujo).
async function carregarCaderno(tema) {
    if (!cadCanvas() || !tema) return;
    if (cadTema && cadTema !== tema && cadDirty) await pushCaderno();

    cadTema = tema;
    cadSelecao = null;
    $('caderno-tema').innerText = tema;

    // 1) Anticrash: o que estiver no localStorage é o ponto de partida.
    let local = null;
    try { local = JSON.parse(localStorage.getItem(cadChaveLocal(tema)) || 'null'); } catch { }

    // 2) Servidor (cross-device) — só TEXTO. As imagens vivem apenas no local.
    let doServidor = null;
    try {
        const r = await apiFetch(`/anotacoes?aluno_id=${encodeURIComponent(userId)}&tema=${encodeURIComponent(tema)}`);
        if (r.ok) doServidor = (await r.json()).elementos || [];
    } catch (e) {
        console.warn('[KaIA] /anotacoes indisponível, usando cópia local:', e);
    }

    const imagensLocais = (local?.elementos || []).filter(e => e.tipo === 'imagem');

    if (local && local.dirty) {
        // Edição local de texto ainda não confirmada vence; imagens já estão nela.
        cadElementos = local.elementos || [];
        cadDirty = true;
        renderCaderno();
        pushCaderno();                       // reconcilia o texto com o servidor
    } else if (doServidor !== null) {
        // Servidor manda no TEXTO; as imagens vêm do local (só existem aqui).
        cadElementos = [...doServidor, ...imagensLocais];
        cadDirty = false;
        gravarLocal(false);                  // reespelha (texto do servidor + imagens locais)
        renderCaderno();
        marcarStatus('salvo');
    } else {
        // Offline: tudo do local.
        cadElementos = local?.elementos || [];
        cadDirty = !!(local && local.dirty);
        renderCaderno();
        marcarStatus(local ? 'offline' : 'salvo');
    }
    cadZ = cadElementos.reduce((m, e) => Math.max(m, e.z || 1), 1);
}

// Redesenha o canvas inteiro a partir de cadElementos.
function renderCaderno() {
    const canvas = cadCanvas();
    if (!canvas) return;
    canvas.innerHTML = '';
    cadElementos.forEach(el => canvas.appendChild(montarBloco(el)));
}

// Cria o DOM de um bloco: alça de arraste + corpo (texto editável ou imagem).
function montarBloco(el) {
    const bloco = document.createElement('div');
    bloco.className = 'cad-el' + (el.tipo === 'imagem' ? ' cad-el-img' : '');
    bloco.dataset.id = el.id;
    bloco.style.left  = `${el.x}px`;
    bloco.style.top   = `${el.y}px`;
    bloco.style.width = `${el.w || CAD_LARGURA_PADRAO}px`;
    bloco.style.zIndex = el.z || 1;
    if (el.id === cadSelecao) bloco.classList.add('sel');

    const grip = document.createElement('div');
    grip.className = 'cad-grip';
    grip.title = 'Arrastar';
    grip.textContent = '⠿';
    grip.addEventListener('pointerdown', (ev) => iniciarArraste(ev, el, bloco));

    let corpo;
    if (el.tipo === 'imagem') {
        corpo = document.createElement('img');
        corpo.className = 'cad-img';
        corpo.src = el.conteudo;               // base64 (só neste dispositivo)
        corpo.alt = 'Anotação em imagem';
        corpo.draggable = false;
    } else {
        corpo = document.createElement('div');
        corpo.className = 'cad-texto';
        corpo.contentEditable = 'true';
        corpo.spellcheck = false;
        corpo.textContent = el.conteudo || '';
        corpo.addEventListener('input', () => {
            el.conteudo = corpo.innerText;
            agendarSalvar();
        });
        corpo.addEventListener('focus', () => selecionar(el.id));
    }

    bloco.addEventListener('pointerdown', () => selecionar(el.id));
    bloco.append(grip, corpo);
    return bloco;
}

function selecionar(id) {
    cadSelecao = id;
    $$('.cad-el', cadCanvas()).forEach(b => b.classList.toggle('sel', b.dataset.id === id));
}

// Clicar num espaço vazio cria um bloco novo já em edição.
function novoBloco(x, y) {
    const el = {
        id: crypto.randomUUID(), tipo: 'texto',
        x: Math.round(x), y: Math.round(y),
        w: CAD_LARGURA_PADRAO, z: ++cadZ, conteudo: ''
    };
    cadElementos.push(el);
    const bloco = montarBloco(el);
    cadCanvas().appendChild(bloco);
    selecionar(el.id);
    bloco.querySelector('.cad-texto').focus();
    agendarSalvar();
}

function removerSelecionado() {
    if (!cadSelecao) return;
    cadElementos = cadElementos.filter(e => e.id !== cadSelecao);
    const alvo = $$('.cad-el', cadCanvas()).find(b => b.dataset.id === cadSelecao);
    if (alvo) alvo.remove();
    cadSelecao = null;
    agendarSalvar();
}

// --- Imagens (Ctrl+V) — SÓ no localStorage ----------------------------------
// bytesDataUrl foi movida para puros.js (testável); carregada antes.

// Re-encode agressivo: WebP, maior lado ≤ 1000px, qualidade 0.7.
async function reencodeParaWebP(blob) {
    const bitmap = await createImageBitmap(blob);
    const escala = Math.min(1, CAD_IMG_MAX_LADO / Math.max(bitmap.width, bitmap.height));
    const w = Math.max(1, Math.round(bitmap.width  * escala));
    const h = Math.max(1, Math.round(bitmap.height * escala));
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    canvas.getContext('2d').drawImage(bitmap, 0, 0, w, h);
    bitmap.close?.();
    return { dataUrl: canvas.toDataURL('image/webp', CAD_IMG_QUALIDADE), w, h };
}

// Valida os tetos (com mensagens específicas) e, se passar, cola no canvas.
async function colarImagemArquivo(blob) {
    let out;
    try {
        out = await reencodeParaWebP(blob);
    } catch (e) {
        console.warn('[KaIA] não consegui processar a imagem:', e);
        avisarCaderno('Não consegui processar essa imagem.');
        return;
    }

    const bytes = bytesDataUrl(out.dataUrl);
    if (bytes > CAD_TETO_IMG) {
        avisarCaderno(`Imagem de ${Math.round(bytes / 1024)} KB — o limite por imagem é `
            + `${Math.round(CAD_TETO_IMG / 1024)} KB. Recorte ou use uma menor.`);
        return;
    }

    const imgs = cadElementos.filter(e => e.tipo === 'imagem');
    const usados = imgs.reduce((s, e) => s + bytesDataUrl(e.conteudo), 0);
    if (usados + bytes > CAD_TETO_TEMA) {
        avisarCaderno(`Este tema já tem ${imgs.length} imagem${imgs.length === 1 ? '' : 's'} `
            + `(${Math.round(usados / 1024)} KB) e não cabe mais. Apague alguma para colar uma nova.`);
        return;
    }

    const dispW = Math.min(out.w, CAD_IMG_DISP_LARG);
    const dispH = Math.round(dispW * out.h / out.w);
    colarImagem(out.dataUrl, cadUltimoPonto.x, cadUltimoPonto.y, dispW, dispH);
}

// Adiciona a imagem; se estourar a cota, desfaz SÓ ela e o texto segue salvo.
function colarImagem(dataUrl, x, y, w, h) {
    const el = {
        id: crypto.randomUUID(), tipo: 'imagem',
        x: Math.round(x), y: Math.round(y), w, h, z: ++cadZ, conteudo: dataUrl
    };
    cadElementos.push(el);

    if (!gravarLocal(true)) {                       // QuotaExceededError com a imagem nova
        cadElementos = cadElementos.filter(e => e.id !== el.id);   // desfaz só a imagem
        gravarLocal(true);                          // regrava SEM ela → texto preservado
        avisarCaderno('Sem espaço neste dispositivo para a imagem. Seu texto foi salvo.');
        return;
    }
    cadCanvas().appendChild(montarBloco(el));
    selecionar(el.id);
    agendarSalvar();                                // PUT só do texto (imagem nunca sobe)
}

// Aviso discreto e temporário no rodapé do caderno.
function avisarCaderno(msg) {
    let el = $('caderno-aviso');
    if (!el) {
        el = document.createElement('div');
        el.id = 'caderno-aviso';
        el.className = 'caderno-aviso';
        const painel = $('caderno');
        if (painel) painel.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('visivel');
    clearTimeout(cadAvisoTimer);
    cadAvisoTimer = setTimeout(() => el.classList.remove('visivel'), 6000);
}

// Arraste pela alça: move o bloco acompanhando o ponteiro.
function iniciarArraste(ev, el, bloco) {
    ev.preventDefault();
    // Tira o foco do bloco que estava em edição para o Delete apagar ESTE.
    if (document.activeElement && document.activeElement.isContentEditable) {
        document.activeElement.blur();
    }
    selecionar(el.id);
    el.z = bloco.style.zIndex = ++cadZ;
    const canvas = cadCanvas();
    const rc = canvas.getBoundingClientRect();
    const dx = ev.clientX - rc.left - el.x;
    const dy = ev.clientY - rc.top  - el.y;

    const mover = (e) => {
        el.x = Math.max(0, Math.min(e.clientX - rc.left - dx, canvas.clientWidth  - 24));
        el.y = Math.max(0, Math.min(e.clientY - rc.top  - dy, canvas.clientHeight - 24));
        bloco.style.left = `${el.x}px`;
        bloco.style.top  = `${el.y}px`;
    };
    const soltar = () => {
        document.removeEventListener('pointermove', mover);
        document.removeEventListener('pointerup', soltar);
        agendarSalvar();
    };
    document.addEventListener('pointermove', mover);
    document.addEventListener('pointerup', soltar);
}

// --- Persistência -----------------------------------------------------------
// NUNCA lança: em QuotaExceededError (ou qualquer falha), devolve false. Assim
// quem chama decide o que fazer (ex.: desfazer só a imagem) sem derrubar o texto.
function gravarLocal(dirty) {
    try {
        localStorage.setItem(cadChaveLocal(cadTema),
            JSON.stringify({ elementos: cadElementos, dirty }));
        return true;
    } catch (e) {
        console.warn('[KaIA] localStorage recusou a gravação:', e?.name || e);
        return false;
    }
}

// Mudou algo: grava local na hora (anticrash) e agenda o PUT (debounce).
function agendarSalvar() {
    cadDirty = true;
    gravarLocal(true);
    marcarStatus('salvando');
    clearTimeout(cadSaveTimer);
    cadSaveTimer = setTimeout(pushCaderno, 800);
}

async function pushCaderno() {
    if (!cadTema) return;
    clearTimeout(cadSaveTimer);
    // Só o texto sobe: imagem fica no dispositivo (não desperdiça banda com base64
    // que o backend descartaria de qualquer forma).
    const soTexto = cadElementos.filter(e => e.tipo === 'texto');
    try {
        const r = await apiFetch(`/anotacoes`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ aluno_id: userId, tema: cadTema, elementos: soTexto })
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        cadDirty = false;
        gravarLocal(false);
        marcarStatus('salvo');
    } catch (e) {
        console.warn('[KaIA] falha ao salvar anotações (mantidas no dispositivo):', e);
        marcarStatus('offline');   // o localStorage segue com tudo; tenta de novo na próxima mudança
    }
}

function marcarStatus(estado) {
    const el = $('caderno-status');
    if (!el) return;
    const rotulo = { salvo: 'salvo', salvando: 'salvando…', offline: 'não salvo' };
    el.dataset.estado = estado;
    el.innerText = rotulo[estado] || estado;
}

// Eventos do canvas: criar em área vazia, deselecionar, apagar com Delete.
document.addEventListener('DOMContentLoaded', () => {
    const canvas = cadCanvas();
    if (!canvas) return;   // só existe em materias.html

    canvas.addEventListener('pointerdown', (e) => {
        if (e.target === canvas) {            // clicou no vazio, não num bloco
            const rc = canvas.getBoundingClientRect();
            novoBloco(e.clientX - rc.left, e.clientY - rc.top);
        }
    });
    // Guarda a última posição do cursor sobre o canvas — a imagem cola ali.
    canvas.addEventListener('pointermove', (e) => {
        const rc = canvas.getBoundingClientRect();
        cadUltimoPonto = {
            x: Math.max(0, Math.min(e.clientX - rc.left, canvas.clientWidth  - 40)),
            y: Math.max(0, Math.min(e.clientY - rc.top,  canvas.clientHeight - 40)),
        };
    });
    // Ctrl+V com imagem: intercepta ANTES do contentEditable, re-encoda e cola.
    document.addEventListener('paste', (e) => {
        if (!cadAberto()) return;
        const imgItem = [...(e.clipboardData?.items || [])].find(i => i.type?.startsWith('image/'));
        if (!imgItem) return;                 // colar texto segue o fluxo normal
        e.preventDefault();
        const blob = imgItem.getAsFile();
        if (blob) colarImagemArquivo(blob);
    });
    // Delete/Backspace apaga o bloco selecionado — só quando NÃO se está digitando.
    document.addEventListener('keydown', (e) => {
        const editando = document.activeElement && document.activeElement.isContentEditable;
        if ((e.key === 'Delete' || e.key === 'Backspace')
            && cadSelecao && cadAberto() && !editando) {
            e.preventDefault();
            removerSelecionado();
        }
    });
    // Salva o que estiver pendente antes de sair.
    window.addEventListener('beforeunload', () => { if (cadDirty) gravarLocal(true); });
});

// ============================================================
//     INICIALIZAÇÃO — ponto de entrada único de todas as páginas
// ============================================================
// Cada `registrar*` é no-op nas páginas que não têm os elementos, então este
// bloco pode rodar em qualquer HTML. A sessão NÃO nasce aqui: só ao iniciar
// uma missão (criarSessao em startMission).
document.addEventListener('DOMContentLoaded', () => {
    // montarRail() e aplicarTexturaPapel() agora rodam no init do comum.js.
    registrarSensores();
    retomarPomodoroSePendente();   // pausa em andamento reaparece ao recarregar/reabrir
    mostrarMetaDiariaMenu();       // "faltam X para a meta de hoje" na tela de matérias
    console.log('[KaIA] Página pronta. Session ID:', sessionId);
});
