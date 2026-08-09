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

// Copy dos braços que renderizam como CARD de texto. Os demais do alvo
// (micro_refoco, pausa_ativa, troca_atividade, checkpoint, reancoragem) são AÇÃO —
// mostrarIntervencao desvia antes deste lookup. `texto` é uma LISTA: sorteia uma
// frase a cada disparo. Adicionar/editar frases aqui.
const INTERVENCOES_MSG = {
    auto_monitoramento: {
        emoji: '🧭', titulo: 'Como está seu foco?', texto: [
            'Se a mente vagou, tudo bem — perceber já ajuda. Bora focar nas próximas 3?',
            'Deu uma dispersada? Acontece. Reancora nas próximas 3 questões.',
            'Notou que saiu do foco? Só de perceber você já voltou.',
            'Tudo bem divagar. Respira e escolhe voltar pra questão.',
        ],
    },
    alerta_fadiga: {
        emoji: '😴', titulo: 'Sinais de cansaço', texto: [
            'Talvez seja hora de um descanso de verdade.',
            'Você já estudou bastante hoje — que tal uma pausa maior?',
            'Cansaço é sinal de que rendeu. Vale descansar um pouco.',
            'Seu foco pede uma pausa de verdade. Sem culpa.',
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

function _garantirCardIntervencao() {
    if ($('kaia-intervencao')) return;
    const css = document.createElement('style');
    css.textContent = `
      #kaia-intervencao{max-width:320px;
        background:#1f2937;color:#f9fafb;border-radius:14px;padding:16px 18px;
        box-shadow:0 10px 30px rgba(0,0,0,.35);font-family:inherit;display:none;animation:kaiaIn .25s ease}
      #kaia-intervencao h4{margin:0 0 6px;font-size:15px}
      #kaia-intervencao p{margin:0 0 12px;font-size:13px;line-height:1.4;opacity:.9}
      #kaia-intervencao .kaia-fb{display:flex;gap:8px}
      #kaia-intervencao button{flex:1;border:0;border-radius:8px;padding:7px 0;font-size:13px;cursor:pointer}
      #kaia-intervencao .k1{background:#22c55e;color:#052e13}
      #kaia-intervencao .k2{background:#eab308;color:#3a2e05}
      #kaia-intervencao .k3{background:#ef4444;color:#3a0808}
      @keyframes kaiaIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}`;
    document.head.appendChild(css);
    const card = document.createElement('div');
    card.id = 'kaia-intervencao';
    card.innerHTML = `<h4 id="kaia-int-titulo"></h4><p id="kaia-int-texto"></p>
      <div class="kaia-fb">
        <button type="button" class="k1" data-r="1.0">Ajudou 👍</button>
        <button type="button" class="k2" data-r="0.5">Mais ou menos</button>
        <button type="button" class="k3" data-r="0.0">Não 👎</button>
      </div>`;
    _pilhaNotif().appendChild(card);
    $$('#kaia-intervencao button').forEach(b =>
        b.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            enviarFeedbackIntervencao(intervencaoAtual, parseFloat(b.dataset.r));
        }));
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
              || { emoji: '💡', titulo: 'Dica', texto: 'Continue focado!' };
    $('kaia-int-titulo').innerText = `${info.emoji} ${info.titulo}`;
    $('kaia-int-texto').innerText  = Array.isArray(info.texto) ? _variar(info.texto) : info.texto;
    $('kaia-intervencao').style.display = 'block';
}

function esconderIntervencao() {
    const c = $('kaia-intervencao');
    if (c) c.style.display = 'none';
    intervencaoAtual = null;
}

async function enviarFeedbackIntervencao(tipo, reward) {
    if (!tipo) return;
    const tempo = intervencaoMostradaEm ? (performance.now() - intervencaoMostradaEm) / 1000 : null;
    try {
        await postJSON('/intervencao/feedback', {
            session_id: sessionId, intervention_type: tipo,
            reward, tempo_ate_aceitar_s: tempo
        });
        console.log('[KaIA] feedback enviado:', tipo, reward);
    } catch (e) { console.warn('[KaIA] falha no feedback:', e); }
    esconderIntervencao();
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
            if (data && data.pendente) mostrarIntervencao(data.pendente);
        } catch (_) { /* silencioso */ }
    }, 15000);
}

// ============================================================
//   SEQUÊNCIA GUIADA — base das intervenções com AÇÃO (Passos 3 e 4)
// ============================================================
// Overlay curto: timer + passos rotativos + retomada. Reusa o flag pausaAtiva
// (suspende idle/aba/exit). Base da pausa ativa (movimento) e do micro-refoco
// (respiração). idx cicla os passos (modulo) — cobre roteiro e respiração.
let _seqTimer = null;

function _garantirOverlaySeq() {
    if ($('kaia-seq')) return;
    const css = document.createElement('style');
    css.textContent = `
      #kaia-seq{position:fixed;inset:0;display:none;place-items:center;z-index:60;background:rgba(26,43,76,.45)}
      #kaia-seq.aberto{display:grid}
      #kaia-seq .kaia-seq-card{background:var(--card,#fbf6ec);color:var(--tinta,#2b2a26);max-width:340px;
        text-align:center;border-radius:16px;padding:24px 22px;box-shadow:0 12px 40px rgba(26,43,76,.25)}
      #kaia-seq h2{margin:0 0 4px;color:var(--profundo,#1a2b4c);font-size:18px}
      #kaia-seq .kaia-seq-passo{margin:10px 0;font-size:16px;min-height:2.6em}
      #kaia-seq .kaia-seq-seg{font-size:30px;font-weight:700;color:var(--profundo,#1a2b4c)}
      #kaia-seq button{margin-top:14px;border:0;border-radius:10px;padding:9px 16px;
        background:var(--vd-uniao,#57d979);color:var(--profundo,#1a2b4c);font-size:14px;cursor:pointer}`;
    document.head.appendChild(css);
    const el = document.createElement('div');
    el.id = 'kaia-seq';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.innerHTML = `<div class="kaia-seq-card">
        <h2 id="kaia-seq-titulo"></h2>
        <p class="kaia-seq-passo" id="kaia-seq-passo"></p>
        <div class="kaia-seq-seg"><span id="kaia-seq-seg">0</span>s</div>
        <button type="button" id="kaia-seq-voltar">Voltar agora</button>
      </div>`;
    document.body.appendChild(el);
    $('kaia-seq-voltar').addEventListener('click', encerrarSequenciaGuiada);
}

function iniciarSequenciaGuiada({ titulo, passos, duracaoMs, passoMs }) {
    _garantirOverlaySeq();
    pausaAtiva = true;                       // suspende idle/aba/exit durante a sequência
    $('kaia-seq-titulo').innerText = titulo;
    $('kaia-seq').classList.add('aberto');
    const fim = performance.now() + duracaoMs;
    const tick = () => {
        const restante = Math.max(0, fim - performance.now());
        $('kaia-seq-seg').innerText = Math.ceil(restante / 1000);
        $('kaia-seq-passo').innerText = passos[Math.floor((duracaoMs - restante) / passoMs) % passos.length];
        if (restante <= 0) return encerrarSequenciaGuiada();
        _seqTimer = setTimeout(tick, 250);
    };
    tick();
}

function encerrarSequenciaGuiada() {
    clearTimeout(_seqTimer);
    const el = $('kaia-seq');
    if (el) el.classList.remove('aberto');
    pausaAtiva = false;
    idleTime = 0;                            // retoma os sensores sem contar o descanso
    if (isMissionActive) setEstado('ESTUDANDO');
    esconderIntervencao();                   // libera o polling (intervencaoAtual = null)
}

// Pausa ativa (movimento) — Passo 3.
function iniciarPausaAtiva() {
    iniciarSequenciaGuiada({
        titulo: _variar(['🤸 Pausa ativa', '🤸 Hora de mexer o corpo', '🤸 Levanta e respira']),
        passos: ['Levanta e alonga os ombros 🙆', 'Olha pra longe — janela, parede 👀',
                 'Bebe uma água 💧', 'Respira fundo, 3 vezes 🌬️'],
        duracaoMs: 90 * 1000, passoMs: 22.5 * 1000,
    });
}

// Micro-refoco (respiração) — Passo 4 · barra no TOPO: mensagem + barra que cai
// linearmente com o tempo restante (sem números). Não usa o overlay central.
let _mrInterval = null;

function _garantirBarraMicroRefoco() {
    if ($('kaia-mr')) return;
    const css = document.createElement('style');
    css.textContent = `
      #kaia-mr{position:fixed;top:0;left:0;right:0;z-index:70;display:none;text-align:center;
        background:var(--card,#fbf6ec);box-shadow:0 4px 20px rgba(26,43,76,.15);padding:12px 16px 10px}
      #kaia-mr.aberto{display:block}
      #kaia-mr .kaia-mr-msg{color:var(--profundo,#1a2b4c);font-size:15px;font-weight:600;margin-bottom:8px}
      #kaia-mr .kaia-mr-track{height:6px;max-width:520px;margin:0 auto;border-radius:99px;overflow:hidden;background:var(--marfim,#f4ecdd)}
      #kaia-mr .kaia-mr-fill{height:100%;width:100%;border-radius:99px;background:var(--vd-uniao,#57d979)}
      #kaia-mr .kaia-mr-pular{position:absolute;top:8px;right:12px;border:0;background:transparent;
        color:var(--tinta,#2b2a26);opacity:.6;font-size:13px;cursor:pointer;text-decoration:underline}
      #kaia-mr .kaia-mr-pular:hover{opacity:1}`;
    document.head.appendChild(css);
    const el = document.createElement('div');
    el.id = 'kaia-mr';
    el.setAttribute('role', 'status');
    el.innerHTML = `<button type="button" class="kaia-mr-pular" id="kaia-mr-pular">Pular</button>
      <div class="kaia-mr-msg" id="kaia-mr-msg"></div>
      <div class="kaia-mr-track"><div class="kaia-mr-fill" id="kaia-mr-fill"></div></div>`;
    document.body.appendChild(el);
    $('kaia-mr-pular').addEventListener('click', encerrarMicroRefoco);
}

function iniciarMicroRefoco() {
    _garantirBarraMicroRefoco();
    pausaAtiva = true;                         // suspende idle/aba/exit durante a respiração
    const passos = ['Inspira… 🌬️', 'Segura…', 'Expira devagar…'];
    const dur = 30 * 1000, passoMs = 4 * 1000;
    $('kaia-mr').classList.add('aberto');
    $('kaia-mr-msg').innerText = passos[0];
    // barra começa cheia e cai linearmente até 0 no fim (via transition CSS, sem números)
    const fill = $('kaia-mr-fill');
    fill.style.transition = 'none';
    fill.style.width = '100%';
    void fill.offsetWidth;                     // reflow p/ reiniciar a queda a cada disparo
    fill.style.transition = `width ${dur}ms linear`;
    fill.style.width = '0%';
    // a mensagem troca por fase da respiração
    const inicio = performance.now();
    clearInterval(_mrInterval);
    _mrInterval = setInterval(() => {
        const passado = performance.now() - inicio;
        if (passado >= dur) return encerrarMicroRefoco();
        $('kaia-mr-msg').innerText = passos[Math.floor(passado / passoMs) % passos.length];
    }, 200);
}

function encerrarMicroRefoco() {
    clearInterval(_mrInterval);
    const el = $('kaia-mr');
    if (el) el.classList.remove('aberto');
    pausaAtiva = false;
    idleTime = 0;                              // retoma sensores sem contar a respiração
    if (isMissionActive) setEstado('ESTUDANDO');
    esconderIntervencao();
}

// Troca de tema (intervenção com AÇÃO — Passo 5): modal CENTRAL (como a pausa
// ativa, maior). Escolhe o tema-alvo ao aparecer e MOSTRA qual será; oferece a
// ESCOLHA "Trocar" / "Continuar" (dá agência ao aluno).
let _trocaTemaAlvo = null;

function _garantirCardTroca() {
    if ($('kaia-troca')) return;
    const css = document.createElement('style');
    css.textContent = `
      #kaia-troca{position:fixed;inset:0;display:none;place-items:center;z-index:60;background:rgba(26,43,76,.45)}
      #kaia-troca.aberto{display:grid}
      #kaia-troca .kaia-troca-card{background:var(--card,#fbf6ec);color:var(--tinta,#2b2a26);max-width:440px;width:90%;
        text-align:center;border-radius:16px;padding:26px 24px;box-shadow:0 12px 40px rgba(26,43,76,.25)}
      #kaia-troca h2{margin:0 0 8px;font-size:19px;color:var(--profundo,#1a2b4c)}
      #kaia-troca p{margin:0 0 10px;font-size:14px;line-height:1.5;opacity:.9}
      #kaia-troca .kaia-troca-alvo{margin:14px 0 18px;font-size:15px;opacity:1}
      #kaia-troca .kaia-troca-alvo strong{color:var(--profundo,#1a2b4c)}
      #kaia-troca .kaia-troca-btns{display:flex;gap:10px}
      #kaia-troca button{flex:1;border:0;border-radius:10px;padding:11px 0;font-size:14px;cursor:pointer}
      #kaia-troca .sim{background:var(--vd-uniao,#57d979);color:var(--profundo,#1a2b4c)}
      #kaia-troca .nao{background:transparent;color:var(--tinta,#2b2a26);border:1px solid var(--profundo,#1a2b4c)}`;
    document.head.appendChild(css);
    const el = document.createElement('div');
    el.id = 'kaia-troca';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.innerHTML = `<div class="kaia-troca-card">
        <h2>🔄 Que tal trocar de tema?</h2>
        <p id="kaia-troca-sub"></p>
        <p class="kaia-troca-alvo">Ir para: <strong id="kaia-troca-tema"></strong></p>
        <div class="kaia-troca-btns">
          <button type="button" class="sim" id="kaia-troca-sim">Trocar de tema</button>
          <button type="button" class="nao" id="kaia-troca-nao">Continuar aqui</button>
        </div>
      </div>`;
    document.body.appendChild(el);
    $('kaia-troca-sim').addEventListener('click', () => { _esconderTroca(); esconderIntervencao(); _trocarTema(); });
    $('kaia-troca-nao').addEventListener('click', () => { _esconderTroca(); esconderIntervencao(); });
}

function _esconderTroca() { const c = $('kaia-troca'); if (c) c.classList.remove('aberto'); }

function mostrarTrocaTema() {
    _garantirCardTroca();
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
let _cpQuestao = null;

function _questaoCheckpoint() {
    const recentes = historicoQuestoes.slice(-3);   // conteúdo RECENTE (últimas ~3 respondidas)
    return recentes.length ? recentes[Math.floor(Math.random() * recentes.length)] : null;
}

function _garantirEstiloCheckpoint() {
    if ($('kaia-cp-css')) return;
    const css = document.createElement('style');
    css.id = 'kaia-cp-css';
    css.textContent = `
      #kaia-cp{background:var(--card,#fbf6ec);border:1px solid var(--vd-uniao,#57d979);border-radius:14px;
        padding:16px 18px;margin-bottom:16px;box-shadow:0 6px 24px rgba(26,43,76,.12)}
      #kaia-cp .kaia-cp-topo{font-size:13px;font-weight:700;color:var(--profundo,#1a2b4c);margin-bottom:8px}
      #kaia-cp .kaia-cp-q{margin:0 0 12px;font-size:15px;line-height:1.4;color:var(--tinta,#2b2a26)}
      #kaia-cp .kaia-cp-opts{display:flex;flex-direction:column;gap:8px}
      #kaia-cp .kaia-cp-opt{text-align:left;border:1px solid var(--profundo,#1a2b4c);background:var(--marfim,#f4ecdd);
        color:var(--tinta,#2b2a26);border-radius:8px;padding:9px 12px;font-size:14px;cursor:pointer}
      #kaia-cp .kaia-cp-opt:disabled{cursor:default;opacity:.7}
      #kaia-cp .kaia-cp-fb{margin:10px 0 0;font-size:14px;min-height:1.2em}
      #kaia-cp .kaia-cp-voltar{margin-top:10px;border:0;border-radius:10px;padding:9px 16px;display:none;
        background:var(--vd-uniao,#57d979);color:var(--profundo,#1a2b4c);font-size:14px;cursor:pointer}
      .question-wrapper.kaia-cp-dim{opacity:.35;transition:opacity .25s}
      .question-wrapper.kaia-cp-realce{box-shadow:0 0 0 3px var(--vd-uniao,#57d979);border-radius:14px;transition:box-shadow .3s}`;
    document.head.appendChild(css);
}

function checkpointRecuperacao() {
    const q = _questaoCheckpoint();
    const lado = document.querySelector('.quiz-lado-questao');
    if (!q || !Array.isArray(q.opts) || !lado) { esconderIntervencao(); return; }   // sem histórico -> não intervém
    const antigo = $('kaia-cp');
    if (antigo) antigo.remove();             // evita duplicar se re-disparar
    _garantirEstiloCheckpoint();
    pausaAtiva = true;                        // suspende sensores durante o checkpoint
    _cpQuestao = q;

    const wrap = document.querySelector('.question-wrapper');
    if (wrap) wrap.classList.add('kaia-cp-dim');   // atenua a questão atual (foco no checkpoint)

    const card = document.createElement('div');
    card.id = 'kaia-cp';
    card.setAttribute('role', 'group');
    const topo = document.createElement('div');
    topo.className = 'kaia-cp-topo';
    topo.textContent = _variar([
        '🎯 Pausa relâmpago — recupere isto:',
        '🎯 Rapidinho: você lembra desta?',
        '🎯 Só pra fixar — responde essa:',
        '🎯 Mini-check do que você já viu:',
    ]);
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
    $('kaia-cp-fb').textContent = acertou
        ? 'Isso! 🎯 De volta pro foco.'
        : `Sem problema — era: ${_cpQuestao ? _cpQuestao.opts[_cpQuestao.ans] : ''}.`;
    $$('#kaia-cp .kaia-cp-opt').forEach(b => b.disabled = true);   // trava após responder
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
    esconderIntervencao();                   // libera o polling (intervencaoAtual = null)
}

// ============================================================
//   REANCORAGEM POR DESTAQUE (intervenção com AÇÃO — Passo 7)
// ============================================================
// NÃO mostra card: um backdrop suave escurece o entorno (nav/rail) e a área da
// questão é ELEVADA acima dele (fica clara). Reduz a competição visual → reancora
// na tarefa (segmenting effect). NÃO pausa sensores (é refoco, não descanso).
// Reverte sozinho em REANCORA_MS. Sutil de propósito (regra TEA/TDAH: tirar
// estímulo, não adicionar — nada pisca).
const REANCORA_MS = 4000;
let _reancoraTimer = null;

function _garantirEstiloReancora() {
    if ($('kaia-reancora-css')) return;
    const css = document.createElement('style');
    css.id = 'kaia-reancora-css';
    css.textContent = `
      body.kaia-reancorar::before{content:'';position:fixed;inset:0;background:rgba(26,43,76,.42);z-index:40;pointer-events:none}
      body.kaia-reancorar .question-wrapper{position:relative;z-index:41;background:var(--card,#fbf6ec);
        border-radius:14px;box-shadow:0 10px 40px rgba(26,43,76,.25)}`;
    document.head.appendChild(css);
}

function reancorarDestaque() {
    esconderIntervencao();                   // não é card; o cooldown já segura novo disparo
    if (!document.querySelector('.question-wrapper')) return;
    _garantirEstiloReancora();
    document.body.classList.add('kaia-reancorar');
    clearTimeout(_reancoraTimer);
    _reancoraTimer = setTimeout(() => document.body.classList.remove('kaia-reancorar'), REANCORA_MS);
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

// Tempo de leitura estimado — vira o limite de ociosidade daquela questão.
function calculateReadingTime(text, options) {
    const palavras = (text + ' ' + options.join(' ')).split(/\s+/).length;
    const segundos = Math.ceil(palavras / 3.3) + 5;
    return segundos;
}

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
        if (idleTime >= dynamicLimit) setEstado('FALTA DE INTERAÇÃO', true);
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

// Cria a lista de botões (temas ou alternativas) dentro de um container.
function renderBotoes(container, itens, aoClicar) {
    container.innerHTML = '';
    itens.forEach((item, idx) => {
        const btn = document.createElement('button');
        btn.className = 'option-btn';
        btn.innerText = typeof item === 'string' ? item : item.texto;
        btn.onclick = () => aoClicar(item, idx, btn);
        container.appendChild(btn);
    });
}

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
    el.textContent = '🎯 Meta de hoje alcançada — 10 questões!';
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
    else errosSessao.push(currentQuestion);   // guarda para a revisão (Parte 7)
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
let probeTimeout = null;

function _garantirCardProbe() {
    if ($('kaia-probe')) return;
    const st = document.createElement('style');
    st.textContent = `
      #kaia-probe{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:60;
        max-width:340px;width:calc(100% - 32px);background:var(--card);color:var(--tinta);
        border:1px solid var(--border);border-radius:14px;padding:14px 16px;
        box-shadow:0 8px 30px rgba(var(--profundo-rgb),.14);display:none}
      #kaia-probe .probe-q{margin:0 0 10px;font-size:14px;color:var(--profundo);font-weight:600}
      #kaia-probe .probe-btns{display:flex;flex-direction:column;gap:6px}
      #kaia-probe button{border:1px solid var(--border);background:var(--marfim);color:var(--tinta);
        border-radius:9px;padding:8px 10px;font-size:13px;cursor:pointer;text-align:left}
      #kaia-probe button:hover{border-color:var(--profundo)}
    `;
    document.head.appendChild(st);
    const card = document.createElement('div');
    card.id = 'kaia-probe';
    card.innerHTML =
        '<p class="probe-q">Rapidinho: sua mente estava na questão agora?</p>'
        + '<div class="probe-btns">'
        + '<button type="button" data-estado="engajado">Sim, estava focado</button>'
        + '<button type="button" data-estado="distraido">Minha mente estava viajando</button>'
        + '<button type="button" data-estado="muito_distraido">Fui ver outra coisa</button>'
        + '</div>';
    document.body.appendChild(card);
    $$('#kaia-probe button').forEach(b =>
        b.addEventListener('click', () => responderProbe(b.dataset.estado)));
}

function dispararProbe() {
    _garantirCardProbe();
    $('kaia-probe').style.display = 'block';
    clearTimeout(probeTimeout);
    probeTimeout = setTimeout(esconderProbe, 25000);   // o momento passa se for ignorado
}

function esconderProbe() {
    clearTimeout(probeTimeout);
    const c = $('kaia-probe');
    if (c) c.style.display = 'none';
}

function responderProbe(estado) {
    logEvent('probe_atencao', {
        estado,
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
// Popula a lista de questões erradas + o botão "Revisar erros" no resumo final.
function preencherErros() {
    const sec = $('resumo-erros'), lista = $('resumo-erros-lista'), btn = $('btn-revisar');
    if (!sec || !lista || !btn) return;
    if (!errosSessao.length) { sec.hidden = true; btn.hidden = true; return; }
    lista.innerHTML = '';
    errosSessao.forEach(q => {
        const li = document.createElement('li');
        li.textContent = `${q.q} — correta: ${q.opts[q.ans]}`;
        lista.appendChild(li);
    });
    sec.hidden = false;
    btn.textContent = `Revisar erros (${errosSessao.length})`;
    btn.hidden = false;
}

// "Revisar erros": mini-sessão só com as erradas, reusando os objetos (sem Gemini).
function iniciarRevisao() {
    if (!errosSessao.length) return;
    emRevisao = true;
    revisaoFila = errosSessao.slice();
    revisaoTotal = errosSessao.length;
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
// Tamanho real (em bytes) que um data URL base64 ocupa depois de decodificado.
function bytesDataUrl(dataUrl) {
    const virgula = dataUrl.indexOf(',');
    const b64 = virgula >= 0 ? dataUrl.slice(virgula + 1) : dataUrl;
    const pad = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0;
    return Math.floor(b64.length * 3 / 4) - pad;
}

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
