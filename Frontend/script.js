// --- Configuração -----------------------------------------------------------------------
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
//                  CORE: logEvent
// ============================================================
function logEvent(type, payload) {
    const event = {
        session_id: sessionId,
        ts: new Date().toISOString(),
        event_type: type,
        payload
    };

    console.log('[KaIA Event]', event);
}

// ==================================================================================================
//                          MENU
// ===================================================================================================
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
//                       HOBBIES
// ============================================================
let historicoDeCliques = JSON.parse(sessionStorage.getItem('hobbies') || '[]');
const botoes = document.querySelectorAll('.botao-hobbies');

botoes.forEach(botao => {
    botao.addEventListener('click', function (evento) {
        evento.preventDefault();
        const nome = this.getAttribute('data-nome');

        if (historicoDeCliques.includes(nome)) {
            // já estava selecionado → remove
            historicoDeCliques = historicoDeCliques.filter(h => h !== nome);
            this.classList.remove('selecionado');
        } else {
            // não estava → adiciona
            historicoDeCliques.push(nome);
            this.classList.add('selecionado');
        }

        console.log('Hobbies:', historicoDeCliques);
    });
});

function salvarHobbies() {
    sessionStorage.setItem('hobbies', JSON.stringify(historicoDeCliques));
    window.location.href = 'index.html';
}

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
//                  FAÇA-SE A LUZ
// ============================================================
const luz = document.getElementById('luzFundo');
const container = document.querySelector('.tela-login');
let luzX = window.innerWidth / 2;
let luzY = window.innerHeight / 2;
const raioFuga = 200; 

container.addEventListener('mousemove', (e) => {
    const mouseX = e.clientX;
    const mouseY = e.clientY;
    const dx = luzX - mouseX;
    const dy = luzY - mouseY;
    const distancia = Math.sqrt(dx * dx + dy * dy);
    if (distancia < raioFuga) {
        const forca = (raioFuga - distancia) / raioFuga;
        const direcaoX = dx / distancia;
        const direcaoY = dy / distancia;

        luzX += direcaoX * forca * 30;
        luzY += direcaoY * forca * 30;
        luzX = Math.max(50, Math.min(window.innerWidth - 50, luzX));
        luzY = Math.max(50, Math.min(window.innerHeight - 50, luzY));
        luz.style.left = `${luzX}px`;
        luz.style.top = `${luzY}px`;
    }
});

// ============================================================
//                  CÁLCULO DE TEMPO ADAPTÁVEL
// ============================================================
function calculateReadingTime(text, options) {
    const allText   = text + ' ' + options.join(' ');
    const wordCount = allText.split(/\s+/).length;
    const readingTime = Math.ceil(wordCount / 3.3) + 5;
    console.log(`Palavras: ${wordCount} | Tempo adaptado: ${readingTime}s`);
    return readingTime;
}

// ============================================================
//                      PERGUNTAS - CHAT
// ============================================================
async function enviarPergunta() {
    const pergunta  = document.getElementById('pergunta').value;
    const respostas = document.getElementById('respostas');
    respostas.innerHTML = 'KaIA pensando...';
    try {
        const response = await fetch(`${API_URL}/perguntar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pergunta, hobbies: historicoDeCliques })
        });
        const data = await response.json();
        respostas.innerHTML = data.resposta;
    } catch (erro) {
        respostas.innerHTML = 'Erro ao conectar com a IA.';
        console.error(erro);
    }
}

// ============================================================
//              MONITOR DE OCIOSIDADE (idleTime)
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

// ================================================================================================
// -------------------- EVENTOS LISTENER -------------------------------
// ================================================================================================


// ============================================================
//                    MOVIMENTO DO MOUSE
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
//              VISIBILITYCHANGE - TROCAS DE ABAS
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
//                           SCROLL
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
//                      TECLADO ESCREVENDO
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
                    ? parseFloat((totalBackspace / totalTeclas).toFixed(3)): 0});
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
//                  CLIQUES FORA DA ÁREA 
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
//                  TEMPO DE RESPOSTA POR QUESTÃO
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
//                      COPIAR / COLAR
// ============================================================
function registrarCopiarColar() {
    ['copy', 'paste'].forEach(tipo => {
        document.addEventListener(tipo, () => {
            if (!isMissionActive) return;
            logEvent('copy_paste', { action: tipo });
        });
    });
}

// ================================================================
//                          INICIAR MISSÃO
// =================================================================
let currentSubject = null;

// Busca os Subtemas com a IA
async function abrirMateria(subject) {
    currentSubject = subject;
    const temasView = document.getElementById('temas-view');
    const temasBox  = document.getElementById('temas-display');

    document.getElementById('menu-view').style.display = 'none';
    temasView.style.display = 'block';
    temasBox.innerHTML = 'KaIA montando os temas...';
    try {
        const r = await fetch(`${API_URL}/temas`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ materia: subject })
        });
        const data = await r.json();
        temasBox.innerHTML = '';
        (data.temas || []).forEach(tema => {
            const btn = document.createElement('button');
            btn.className = 'option-btn';
            btn.innerText = tema;
            btn.onclick = () => startMission(subject, tema);
            temasBox.appendChild(btn);
        });
    } catch (e) {
        temasBox.innerHTML = 'Erro ao carregar os temas.';
        console.error(e);
    }
}
// 2) IA gera a questão
async function startMission(subject, tema) {
    document.getElementById('temas-view').style.display = 'none';
    document.getElementById('quiz-view').style.display  = 'block';
    document.getElementById('question-display').innerText = 'KaIA criando sua questão...';
    document.getElementById('options-display').innerHTML  = '';
    try {
        const r = await fetch(`${API_URL}/gerar-questao`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ materia: subject, tema, hobbies: historicoDeCliques })
        });
        currentQuestion = await r.json();
        if (currentQuestion.erro) throw new Error(currentQuestion.erro);
    } catch (e) {
        document.getElementById('question-display').innerText = 'Erro ao gerar a questão.';
        console.error(e);
        return;
    }
    isMissionActive = true;
    idleTime = 0; mudancasAba = 0; focusLostAt = null;
    lastScrollY = window.scrollY; lastScrollTime = performance.now();
    lastKeystroke = 0;
    if (keystrokeTimer) clearTimeout(keystrokeTimer);
    sessionId = crypto.randomUUID();

    const subjectEl = document.getElementById('current-subject');
    if (subjectEl) subjectEl.innerText = `${subject} · ${tema}`;

    dynamicLimit = calculateReadingTime(currentQuestion.q, currentQuestion.opts);
    document.getElementById('question-display').innerText = currentQuestion.q;

    const optionsDiv = document.getElementById('options-display');
    optionsDiv.innerHTML = '';
    currentQuestion.opts.forEach((opt, idx) => {
        const btn = document.createElement('button');
        btn.className = 'option-btn';
        btn.innerText = opt;
        btn.onclick = () => checkAnswer(idx, btn);
        optionsDiv.appendChild(btn);
    });

    questionShownAt = performance.now();
    iniciarIdleMonitor();
}

// ==============================================================
//                      VERIFICAR RESPOSTA
// ==============================================================
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

// =================================================================
//                              RESET
// ==============================================================
function resetSystem() {
    if (idleInterval)   clearInterval(idleInterval);
    if (keystrokeTimer) clearTimeout(keystrokeTimer);
    location.reload();
}

// ====================================================================================
//                  INICIALIZAÇÃO — registra todos os listeners 
// ===================================================================================
document.addEventListener('DOMContentLoaded', () => {
    registrarMouseMove();
    registrarScroll();
    registrarTeclado();
    registrarCliquesForaDaArea();
    registrarCopiarColar();
    console.log('[KaIA] Listeners registrados. Session ID:', sessionId);
});