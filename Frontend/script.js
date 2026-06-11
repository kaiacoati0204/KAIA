// ============================================================
//  KaIA — Frontend Event Tracker
//  Sprint 1 · Jun/2026
// ============================================================

// --- Configuração ------------------------------------------
const API_URL = (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_URL)
    || 'http://localhost:5000';

// --- Estado da sessão --------------------------------------
let sessionId       = crypto.randomUUID();
let isMissionActive = false;
let idleInterval    = null;

// --- Estado dos sensores -----------------------------------
let idleTime        = 0;
let dynamicLimit    = 10;

let focusLostAt     = null;
let mudancasAba     = 0;

let lastScrollY     = 0;
let lastScrollTime  = 0;

let lastKeystroke   = 0;
let keystrokeTimer  = null;

// --- Questão atual -----------------------------------------
let currentQuestion = null;

// --- Banco de questões -------------------------------------
// Adicione perguntas reais substituindo "Parte escrita" e as opções.
// ans = índice (0-based) da opção correta.
const questions = {
    MAT: [
        { q: "Parte escrita", opts: ["Opção1", "Opção2", "Opção3", "Opção4", "Opção5"], ans: 2 },
        // mais perguntas aqui...
    ],
    PORT: [
        { q: "Parte escrita", opts: ["Opção1", "Opção2", "Opção3", "Opção4", "Opção5"], ans: 0 },
        // mais perguntas aqui...
    ],
    HIS: [
        { q: "Parte escrita", opts: ["Opção1", "Opção2", "Opção3", "Opção4", "Opção5"], ans: 1 },
        // mais perguntas aqui...
    ],
};

// ============================================================
//  CORE: logEvent
//  Centraliza todos os eventos — console em dev, POST quando
//  o endpoint /events estiver pronto no backend.
// ============================================================
function logEvent(type, payload) {
    const event = {
        session_id: sessionId,
        ts: new Date().toISOString(),
        event_type: type,
        payload
    };

    console.log('[KaIA Event]', event);

    // Descomentar quando o backend estiver pronto:
    // fetch(`${API_URL}/events`, {
    //     method: 'POST',
    //     headers: { 'Content-Type': 'application/json' },
    //     body: JSON.stringify(event)
    // }).catch(err => console.error('[KaIA] Erro ao enviar evento:', err));
}

// ============================================================
//  MENU
// ============================================================
let aberto = false;

function abrirMenu() {
    const menu = document.getElementById('menu');
    if (!aberto) {
        menu.style.width = '200px';
        aberto = true;
    } else {
        menu.style.width = '0';
        aberto = false;
    }
}

// ============================================================
//  HOBBIES
// ============================================================
let historicoDeCliques = [];
const botoes     = document.querySelectorAll('.botao-hobbies');
const campoTexto = document.getElementById('resultado-clique');

botoes.forEach(botao => {
    botao.addEventListener('click', function (evento) {
        evento.preventDefault();
        const oQueFoiClicado = this.getAttribute('data-nome');
        historicoDeCliques.push(oQueFoiClicado);
        console.log('Histórico atual:', historicoDeCliques);
        if (campoTexto) campoTexto.innerText = 'Você clicou em: ' + historicoDeCliques.join(', ');
    });
});

async function enviarParaIA(historicoBotoes) {
    if (campoTexto) campoTexto.innerText = 'A KaIA está pensando...';
    try {
        const resposta = await fetch(`${API_URL}/pergunta-ia`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: `O usuário escolheu os seguintes hobbies/opções no site: ${historicoBotoes.join(', ')}. 
                         Responda a questão com referências a esses hobbies para que o aluno entenda adequadamente.`
            })
        });
        const dados = await resposta.json();
        if (campoTexto) campoTexto.innerText = dados.respostaDaIA;
    } catch (erro) {
        if (campoTexto) campoTexto.innerText = 'Houve um erro ao conversar com a IA.';
        console.error(erro);
    }
}

// ============================================================
//  CÁLCULO DE TEMPO ADAPTÁVEL
// ============================================================
function calculateReadingTime(text, options) {
    const allText   = text + ' ' + options.join(' ');
    const wordCount = allText.split(/\s+/).length;
    const readingTime = Math.ceil(wordCount / 3.3) + 5;
    console.log(`Palavras: ${wordCount} | Tempo adaptado: ${readingTime}s`);
    return readingTime;
}

// ============================================================
//  PERGUNTAS (chat livre)
// ============================================================
async function enviarPergunta() {
    const pergunta  = document.getElementById('pergunta').value;
    const respostas = document.getElementById('respostas');
    respostas.innerHTML = 'KaIA pensando...';
    try {
        const response = await fetch(`${API_URL}/perguntar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pergunta })
        });
        const data = await response.json();
        respostas.innerHTML = data.resposta;
    } catch (erro) {
        respostas.innerHTML = 'Erro ao conectar com a IA.';
        console.error(erro);
    }
}

// ============================================================
//  MONITOR DE OCIOSIDADE (idleTime)
// ============================================================
function iniciarIdleMonitor() {
    if (idleInterval) clearInterval(idleInterval);

    idleInterval = setInterval(() => {
        if (!isMissionActive) return;

        idleTime++;
        const timerEl = document.getElementById('timer');
        if (timerEl) timerEl.innerText = idleTime;

        if (idleTime >= dynamicLimit) {
            document.getElementById('overlay').style.opacity   = '0.95';
            document.getElementById('system-status').innerText = 'FALTA DE INTERAÇÃO';
        }
    }, 1000);
}

// ============================================================
//  EVENT LISTENER 1: MOVIMENTO DO MOUSE
//  FIX: restrito ao quiz-view, não ao documento inteiro.
// ============================================================
function registrarMouseMove() {
    const quizView = document.getElementById('quiz-view');
    if (!quizView) return;

    quizView.addEventListener('mousemove', () => {
        if (!isMissionActive) return;
        idleTime = 0;
        document.getElementById('overlay').style.opacity   = '0';
        document.getElementById('system-status').innerText = 'ESTUDANDO';
    });
}

// ============================================================
//  EVENT LISTENER 2: VISIBILITYCHANGE (troca de aba)
//  Captura: mudancas_aba, tempo_fora_foco_s
// ============================================================
document.addEventListener('visibilitychange', () => {
    if (!isMissionActive) return;

    if (document.hidden) {
        focusLostAt = performance.now();
        mudancasAba++;
    } else {
        if (focusLostAt !== null) {
            const duracao_s = (performance.now() - focusLostAt) / 1000;
            logEvent('tab_change', {
                mudancas_aba: mudancasAba,
                tempo_fora_foco_s: parseFloat(duracao_s.toFixed(2))
            });
            focusLostAt = null;
        }
    }
});

// ============================================================
//  EVENT LISTENER 3: SCROLL
//  Captura: velocidade_scroll_px_s, rolagem_sem_leitura
// ============================================================
function registrarScroll() {
    const quizView = document.getElementById('quiz-view');
    if (!quizView) return;

    lastScrollY    = window.scrollY;
    lastScrollTime = performance.now();

    window.addEventListener('scroll', (e) => {
        if (!isMissionActive) return;
    
        const now    = performance.now();
        const deltaT = (now - lastScrollTime) / 1000;
    
        if (deltaT > 0) {
            const deltaY = Math.abs(window.scrollY - lastScrollY);
            const px_s   = deltaY / deltaT;
    
            // Log para você ver o valor real durante o teste
            console.log('[scroll]', { deltaY, deltaT: deltaT.toFixed(3), px_s: px_s.toFixed(1) });
    
            if (px_s > 300) {
                logEvent('scroll_burst', {
                    px_s: parseFloat(px_s.toFixed(1)),
                    duracao_s: parseFloat(deltaT.toFixed(2)),
                    rolagem_sem_leitura: (px_s > 500 && deltaT > 2)
                });
            }
        }
    
        lastScrollY    = window.scrollY;
        lastScrollTime = now;
    }, { passive: true });
}

// ============================================================
//  EVENT LISTENER 4: TECLADO
//  Captura: pausas_digitacao_s, taxa_backspace
// ============================================================
function registrarTeclado() {
    let totalTeclas    = 0;
    let totalBackspace = 0;

    document.addEventListener('keydown', (e) => {
        if (!isMissionActive) return;

        const now     = performance.now();
        const pausa_s = (now - lastKeystroke) / 1000;

        totalTeclas++;
        if (e.key === 'Backspace') totalBackspace++;

        if (lastKeystroke > 0 && pausa_s > 3) {
            logEvent('keystroke_pause', {
                duracao_s: parseFloat(pausa_s.toFixed(2)),
                taxa_backspace: totalTeclas > 0
                    ? parseFloat((totalBackspace / totalTeclas).toFixed(3))
                    : 0
            });
        }

        lastKeystroke = now;

        if (keystrokeTimer) clearTimeout(keystrokeTimer);
        keystrokeTimer = setTimeout(() => {
            if (!isMissionActive) return;
            logEvent('keystroke_pause', {
                duracao_s: 30,
                taxa_backspace: totalTeclas > 0
                    ? parseFloat((totalBackspace / totalTeclas).toFixed(3))
                    : 0
            });
        }, 30000);
    });
}

// ============================================================
//  EVENT LISTENER 5: CLIQUES FORA DA ÁREA DE ESTUDO
//  Captura: cliques_fora_area_estudo
// ============================================================
function registrarCliquesForaDaArea() {
    document.addEventListener('click', (e) => {
        if (!isMissionActive) return;

        const quizView = document.getElementById('quiz-view');
        if (quizView && !quizView.contains(e.target)) {
            logEvent('click_outside', {
                x: e.clientX,
                y: e.clientY
            });
        }
    });
}

// ============================================================
//  EVENT LISTENER 6: TEMPO DE RESPOSTA POR QUESTÃO
//  Captura: tempo_resposta_ms, acertou
// ============================================================
let questionShownAt = 0;

function registrarTempoDeResposta(acertou, opcaoEscolhida) {
    if (questionShownAt === 0) return;
    const tempo_resposta_ms = Math.round(performance.now() - questionShownAt);
    logEvent('question_answer', {
        tempo_resposta_ms,
        acertou,
        opcao_escolhida: opcaoEscolhida,
        tipo_questao: 'objetiva'
    });
}

// ============================================================
//  EVENT LISTENER 7: COPIAR / COLAR
//  Captura: copiar_colar_detectado
// ============================================================
function registrarCopiarColar() {
    ['copy', 'paste'].forEach(tipo => {
        document.addEventListener(tipo, () => {
            if (!isMissionActive) return;
            logEvent('copy_paste', { action: tipo });
        });
    });
}

// ============================================================
//  INICIAR MISSÃO
// ============================================================
function startMission(subject) {
    // Valida se a matéria existe no banco de questões
    const list = questions[subject];
    if (!list || list.length === 0) {
        console.error(`[KaIA] Nenhuma questão encontrada para: "${subject}"`);
        alert(`Ainda não há questões cadastradas para esta matéria.`);
        return;
    }

    // Reset completo de estado
    isMissionActive = true;
    idleTime        = 0;
    mudancasAba     = 0;
    focusLostAt     = null;
    lastScrollY     = window.scrollY;
    lastScrollTime  = performance.now();
    lastKeystroke   = 0;
    if (keystrokeTimer) clearTimeout(keystrokeTimer);

    // Nova sessionId para cada missão
    sessionId = crypto.randomUUID();
    console.log('[KaIA] Nova sessão iniciada:', sessionId, '| Matéria:', subject);

    // UI
    document.getElementById('menu-view').style.display = 'none';
    document.getElementById('quiz-view').style.display = 'block';

    // Atualiza label da missão no quiz-view
    const subjectEl = document.getElementById('current-subject');
    if (subjectEl) subjectEl.innerText = subject;

    // Sorteia questão
    currentQuestion = list[Math.floor(Math.random() * list.length)];

    // Tempo adaptável
    dynamicLimit = calculateReadingTime(currentQuestion.q, currentQuestion.opts);

    // Exibe questão e opções
    document.getElementById('question-display').innerText = currentQuestion.q;
    const optionsDiv = document.getElementById('options-display');
    optionsDiv.innerHTML = '';

    currentQuestion.opts.forEach((opt, idx) => {
        const btn     = document.createElement('button');
        btn.className = 'option-btn';
        btn.innerText = opt;
        btn.onclick   = () => checkAnswer(idx, btn);
        optionsDiv.appendChild(btn);
    });

    // Marca quando a questão apareceu (para tempo_resposta_ms)
    questionShownAt = performance.now();

    // Inicia o monitor de ociosidade
    iniciarIdleMonitor();
}

// ============================================================
//  VERIFICAR RESPOSTA
// ============================================================
function checkAnswer(idx, btn) {
    if (!isMissionActive) return;

    const acertou = (idx === currentQuestion.ans);
    registrarTempoDeResposta(acertou, idx);

    // Feedback visual
    btn.style.background = acertou ? '#27ae60' : '#e74c3c';

    // Desativa missão e volta ao menu após 1.5s
    isMissionActive = false;
    setTimeout(() => {
        document.getElementById('quiz-view').style.display  = 'none';
        document.getElementById('menu-view').style.display  = 'block';
        if (idleInterval) clearInterval(idleInterval);
        document.getElementById('overlay').style.opacity    = '0';
        document.getElementById('system-status').innerText  = 'AGUARDANDO';
    }, 1500);
}

// ============================================================
//  RESET
// ============================================================
function resetSystem() {
    if (idleInterval)   clearInterval(idleInterval);
    if (keystrokeTimer) clearTimeout(keystrokeTimer);
    location.reload();
}

// ============================================================
//  INICIALIZAÇÃO — registra todos os listeners uma única vez
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    registrarMouseMove();
    registrarScroll();
    registrarTeclado();
    registrarCliquesForaDaArea();
    registrarCopiarColar();
    console.log('[KaIA] Listeners registrados. Session ID:', sessionId);
});