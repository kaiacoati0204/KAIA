// ============================================================
//  KaIA — materias.js: página de estudo (sessão, sensores, missão/quiz,
//  chat, pomodoro, caderno, intervenções)
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
let lastScrollY     = 0;
let lastScrollTime  = 0;
let lastKeystroke   = 0;
let keystrokeTimer  = null;
let questionShownAt = 0;
let currentQuestion = null;
let currentSubject  = null;   // matéria/tema da questão atual — para "Próxima questão"
let currentTema     = null;

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

// Copy das 9 intervenções (emoji + título + texto).
const INTERVENCOES_MSG = {
    nudge_refoco:          { emoji: '🎯', titulo: 'Foco!',             texto: 'Respira fundo e volta pra questão — você consegue.' },
    pausa_pomodoro:        { emoji: '⏲️', titulo: 'Pausa Pomodoro',    texto: 'Que tal 5 min de pausa? Você volta rendendo mais.' },
    mensagem_motivacional: { emoji: '💪', titulo: 'Você tá indo bem',  texto: 'Cada questão te deixa mais perto do objetivo.' },
    troca_atividade:       { emoji: '🔄', titulo: 'Trocar de tema',    texto: 'Experimenta um tema diferente pra reengajar.' },
    pausa_ativa:           { emoji: '🤸', titulo: 'Pausa ativa',       texto: 'Levanta, alonga, bebe água — 2 minutinhos.' },
    microlearning:         { emoji: '📚', titulo: 'Micro-aprendizado', texto: 'Um resuminho rápido pra destravar o assunto.' },
    alerta_fadiga:         { emoji: '😴', titulo: 'Sinais de cansaço',  texto: 'Talvez seja hora de um descanso de verdade.' },
    badge_foco:            { emoji: '🏅', titulo: 'Badge de Foco!',     texto: 'Mandou bem — continua nesse ritmo!' },
    comparacao_social:     { emoji: '📊', titulo: 'Bora acompanhar',    texto: 'Outros alunos como você já avançaram hoje. Sua vez!' },
};

function _garantirCardIntervencao() {
    if ($('kaia-intervencao')) return;
    const css = document.createElement('style');
    css.textContent = `
      #kaia-intervencao{position:fixed;right:20px;bottom:20px;max-width:320px;z-index:9999;
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
        <button class="k1" data-r="1.0">Ajudou 👍</button>
        <button class="k2" data-r="0.5">Mais ou menos</button>
        <button class="k3" data-r="0.0">Não 👎</button>
      </div>`;
    document.body.appendChild(card);
    $$('#kaia-intervencao button').forEach(b =>
        b.addEventListener('click', () => enviarFeedbackIntervencao(intervencaoAtual, parseFloat(b.dataset.r))));
}

function mostrarIntervencao(intv) {
    _garantirCardIntervencao();
    const info = INTERVENCOES_MSG[intv.intervention_type]
              || { emoji: '💡', titulo: 'Dica', texto: 'Continue focado!' };
    intervencaoAtual = intv.intervention_type;
    intervencaoMostradaEm = performance.now();
    $('kaia-int-titulo').innerText = `${info.emoji} ${info.titulo}`;
    $('kaia-int-texto').innerText  = info.texto;
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
        const timer = $('timer');
        if (timer) timer.innerText = idleTime;
        if (idleTime >= dynamicLimit) setEstado('FALTA DE INTERAÇÃO', true);
    }, 1000);
}

function registrarSensores() {
    const quizView = $('quiz-view');

    // --- mouse: qualquer movimento zera a ociosidade ---
    quizView?.addEventListener('mousemove', () => {
        if (!isMissionActive) return;
        idleTime = 0;
        setEstado('ESTUDANDO');
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

    // --- scroll: rajadas rápidas indicam rolagem sem leitura ---
    // Quem rola pode ser a janela OU um container interno, dependendo da página.
    // Listener em FASE DE CAPTURA no document pega o 'scroll' de QUALQUER elemento
    // (scroll não borbulha, mas é capturado na descida). Lemos a posição do alvo.
    const posDoAlvo = (t) =>
        (!t || t === document || t === document.documentElement || t === document.body || t === window)
            ? (window.scrollY || document.documentElement.scrollTop || 0)
            : (t.scrollTop || 0);
    lastScrollY    = window.scrollY || 0;
    lastScrollTime = performance.now();
    let ultimoBurst = 0;   // throttle: no máximo 1 scroll_burst por segundo
    document.addEventListener('scroll', (e) => {
        if (!isMissionActive) return;
        const y      = posDoAlvo(e.target);
        const agora  = performance.now();
        const deltaT = (agora - lastScrollTime) / 1000;
        const px_s   = deltaT > 0 ? Math.abs(y - lastScrollY) / deltaT : 0;
        lastScrollY    = y;      // posição atualizada SEMPRE (velocidade contínua)
        lastScrollTime = agora;

        // O evento 'scroll' dispara a cada frame; sem throttle uma rolagem vira
        // centenas de eventos. Registramos no máximo 1 scroll_burst por segundo.
        if (px_s > 300 && (agora - ultimoBurst) >= 1000) {
            ultimoBurst = agora;
            logEvent('scroll_burst', {
                px_s: parseFloat(px_s.toFixed(1)),
                duracao_s: parseFloat(deltaT.toFixed(2)),
                rolagem_sem_leitura: (px_s > 500 && deltaT > 2)
            });
        }
    }, { capture: true, passive: true });

    // --- teclado: pausas longas e taxa de backspace ---
    let totalTeclas = 0;
    let totalBackspace = 0;
    const taxaBackspace = () =>
        totalTeclas > 0 ? parseFloat((totalBackspace / totalTeclas).toFixed(3)) : 0;

    document.addEventListener('keydown', (e) => {
        if (!isMissionActive) return;
        const agora   = performance.now();
        const pausa_s = (agora - lastKeystroke) / 1000;
        totalTeclas++;
        if (e.key === 'Backspace') totalBackspace++;

        if (lastKeystroke > 0 && pausa_s > 3) {
            logEvent('keystroke_pause', {
                duracao_s: parseFloat(pausa_s.toFixed(2)),
                taxa_backspace: taxaBackspace()
            });
        }
        lastKeystroke = agora;

        // 30s parado depois de digitar também é uma pausa
        clearTimeout(keystrokeTimer);
        keystrokeTimer = setTimeout(() => {
            if (isMissionActive) logEvent('keystroke_pause', { duracao_s: 30, taxa_backspace: taxaBackspace() });
        }, 30000);
    });

    // --- cliques fora da área da questão ---
    document.addEventListener('click', (e) => {
        if (!isMissionActive || !quizView || quizView.contains(e.target)) return;
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
//                    PERGUNTAS - CHAT
// ============================================================
async function enviarPergunta() {
    const respostas = $('respostas');
    respostas.innerHTML = 'KaIA pensando...';
    try {
        const data = await postJSON('/perguntar', {
            pergunta: $('pergunta').value,
            hobbies: lerHobbies()
        });
        respostas.innerHTML = data.resposta;
    } catch (erro) {
        respostas.innerHTML = 'Erro ao conectar com a IA.';
        console.error(erro);
    }
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
    if (filaChave !== chave) { filaQuestoes = []; filaChave = chave; }   // tema novo → lote antigo fora
    if (!filaQuestoes.length) {
        // Em cooldown após falha: serve fallback SEM re-chamar (não spamar endpoint que já falhou).
        if (performance.now() < loteBloqueadoAte) return questaoFallback(subject, tema);
        try {
            const data = await postJSON('/gerar-questao', {
                materia: subject, tema, hobbies: lerHobbies(), quantidade: LOTE_QTD
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

// Troca qual das três telas de materias.html está visível.
function mostrarTela(id) {
    ['menu-view', 'temas-view', 'quiz-view'].forEach(tela => {
        const el = $(tela);
        if (el) el.style.display = (tela === id) ? 'block' : 'none';
    });
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

    let temas = [];
    try {
        const data = await postJSON('/temas', { materia: subject });
        temas = data.temas || [];
    } catch (e) {
        console.warn('[KaIA] /temas indisponível:', e);
    }
    if (!temas.length) {
        temas = TEMAS_FALLBACK[subject] || ['Tema 1', 'Tema 2', 'Tema 3'];
        console.warn('[KaIA] usando temas locais (fallback).');
    }
    renderBotoes(temasBox, temas, (tema) => startMission(subject, tema));
}

// 2) A IA gera a questão e a missão começa.
async function startMission(subject, tema) {
    currentSubject = subject;
    currentTema = tema;
    mostrarTela('quiz-view');
    const fb = $('feedback');
    if (fb) { fb.className = 'feedback-msg'; fb.innerHTML = ''; }
    $('question-display').innerText = 'KaIA criando sua questão...';
    $('options-display').innerHTML  = '';

    currentQuestion = await obterProximaQuestao(subject, tema);   // vem da fila (lote); fallback interno

    // zera os sensores para esta missão
    isMissionActive = true;
    sessaoDeEstudoAberta = true;   // segue ativo na explicação, até ABANDONAR/próxima/Sair
    iniciarPomodoro();             // liga (ou retoma) o ciclo foco/pausa da sessão
    idleTime = 0;
    mudancasAba = 0;
    focusLostAt = null;
    lastKeystroke = 0;
    lastScrollY = window.scrollY;
    lastScrollTime = performance.now();
    clearTimeout(keystrokeTimer);

    // 1 sessão por missão: gera um session_id novo e atualiza streak/contadores
    await criarSessao();
    const features = registrarInicioSessao();
    logEvent('session_start', { materia: subject, tema, features });
    enviarPerfil({ tipo: 'session_start', materia: subject, tema });

    const subjectEl = $('current-subject');
    if (subjectEl) subjectEl.innerText = `${subject} · ${tema}`;

    dynamicLimit = calculateReadingTime(currentQuestion.q, currentQuestion.opts);
    $('question-display').innerText = currentQuestion.q;
    renderBotoes($('options-display'), currentQuestion.opts, (_opt, idx, btn) => checkAnswer(idx, btn));

    questionShownAt = performance.now();
    iniciarIdleMonitor();
    iniciarPollIntervencao();

    // Se o caderno está aberto, troca o canvas para o tema desta missão.
    if (typeof cadAberto === 'function' && cadAberto() && cadTema !== tema) {
        carregarCaderno(tema);
    }
}

// 3) Resposta: registra o tempo, dá o feedback visual e encerra a sessão.
function checkAnswer(idx, btn) {
    if (!isMissionActive) return;
    const acertou = (idx === currentQuestion.ans);

    if (questionShownAt > 0) {
        logEvent('question_answer', {
            tempo_resposta_ms: Math.round(performance.now() - questionShownAt),
            acertou,
            opcao_escolhida: idx,
            tipo_questao: 'objetiva'
        });
    }

    // A missão termina, mas a TELA NÃO SAI: o aluno lê a explicação no ritmo dele.
    isMissionActive = false;
    clearInterval(idleInterval);
    setEstado('RESPONDIDA');   // também baixa o overlay de inatividade, se estava visível
    encerrarSessao();

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

    const proxima = document.createElement('button');
    proxima.type = 'button';
    proxima.className = 'botao-proxima';
    proxima.textContent = 'Próxima questão →';
    proxima.addEventListener('click', proximaQuestao);

    fb.appendChild(bloco);
    fb.appendChild(proxima);
    fb.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// "Próxima questão": gera outra no MESMO tema (mantém o fluxo de estudo em série).
function proximaQuestao() {
    startMission(currentSubject, currentTema);
}

// "ABANDONAR" também encerra a sessão.
function resetSystem() {
    sessaoDeEstudoAberta = false;   // fecha o escopo do exit-intent antes de recarregar
    pararPomodoro();
    _limparPomodoro();              // fim deliberado da sessão: zera o ciclo
    encerrarSessao();
    clearInterval(idleInterval);
    clearTimeout(keystrokeTimer);
    location.reload();
}

// Fechar/recarregar a aba no meio da missão também encerra a sessão.
window.addEventListener('beforeunload', () => {
    if (isMissionActive) encerrarSessao();
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
const POMODORO_FOCO_MS  = 15000;   // FOCO — teste; produção ~25 min
const POMODORO_PAUSA_MS = 15000;   // PAUSA — teste; produção ~5 min
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
    console.log('[KaIA] Página pronta. Session ID:', sessionId);
});
