// --- Configuração -----------------------------------------------------------------------
// Use 127.0.0.1 (IPv4) em vez de "localhost": no Windows "localhost" pode
// resolver para IPv6 (::1) e o Flask dev server só escuta em IPv4 → "não responde".
const API_URL = (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_URL)
    || 'http://127.0.0.1:5000';

// --- Estado da sessão --------------------------------------
// O session_id "oficial" é criado via POST /sessions e guardado no
// sessionStorage (sobrevive à navegação entre páginas da mesma aba).
let sessionId       = sessionStorage.getItem('kaia_session_id') || null;
let isMissionActive = false;
let idleInterval    = null;

// user_id ESTÁVEL por aluno: vive no localStorage (persiste entre abas e
// sessões). É a identidade do aluno no MVP (até plugarmos o Supabase Auth).
let userId = localStorage.getItem('kaia_user_id');
if (!userId) {
    userId = crypto.randomUUID();
    localStorage.setItem('kaia_user_id', userId);
}

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
//        ABRE A SESSÃO OFICIAL (POST /sessions)
// ============================================================
// Cria uma NOVA sessão (1 por missão). Não envia session_id → o backend gera
// um novo; mantém o user_id estável do aluno.
async function criarSessao() {
    try {
        const resp = await fetch(`${API_URL}/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        sessionId = data.session_id;
        console.log('[KaIA] Nova sessão:', sessionId, '| user:', userId);
    } catch (e) {
        // Fallback offline: não trava a UI (o backend auto-cria a sessão no /events)
        sessionId = crypto.randomUUID();
        console.warn('[KaIA] /sessions indisponível, usando id local:', sessionId, e);
    }
    sessionStorage.setItem('kaia_session_id', sessionId);
    return sessionId;
}

// Marca o fim da sessão atual (grava session_end_ts no backend).
// Usa sendBeacon p/ sobreviver ao fechamento da aba; cai pra fetch keepalive.
function encerrarSessao() {
    if (!sessionId) return;
    const url = `${API_URL}/sessions/${sessionId}/end`;
    if (navigator.sendBeacon) {
        navigator.sendBeacon(url);
    } else {
        fetch(url, { method: 'POST', keepalive: true }).catch(() => {});
    }
}

// --- Fallback local (usado quando o Gemini está indisponível, ex: cota) ------
const TEMAS_FALLBACK = {
    MAT:  ['Álgebra', 'Geometria', 'Trigonometria', 'Funções', 'Probabilidade', 'Estatística'],
    PORT: ['Morfologia', 'Sintaxe', 'Interpretação de Texto', 'Figuras de Linguagem', 'Variação Linguística', 'Gêneros Textuais'],
    HIS:  ['Brasil Colônia', 'Era Vargas', 'Guerras Mundiais', 'Idade Média', 'Revolução Industrial', 'Guerra Fria'],
};

// Questão local p/ a missão iniciar mesmo sem o Gemini — mantém o pipeline testável
function questaoFallback(subject, tema) {
    return {
        q: `[OFFLINE] Questão de teste sobre "${tema}" (${subject}). Escolha uma opção:`,
        opts: ['Opção A', 'Opção B', 'Opção C', 'Opção D', 'Opção E'],
        ans: 0
    };
}

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

    // Envia para o backend (não bloqueia a UI; ignora falha se a API estiver off)
    fetch(`${API_URL}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(event),
        keepalive: true
    }).catch(() => {});
}

// ============================================================
//        CAMADA DE DADOS — PERFIL + FEATURES (Supabase-ready)
// ============================================================
// Tudo é persistido em localStorage sob a chave 'kaia_perfil' e
// espelhado no backend (/perfil). Quando você plugar o Supabase,
// basta trocar `enviarPerfil` por um insert/upsert na tabela `perfis`.

function lerPerfil() {
    return JSON.parse(localStorage.getItem('kaia_perfil') || '{}');
}
function gravarPerfil(perfil) {
    localStorage.setItem('kaia_perfil', JSON.stringify(perfil));
}

// Snapshot NÃO-mutável das features (apenas leitura, p/ enviar junto dos dados)
function snapshotFeatures() {
    const agora   = new Date();
    const perfil  = lerPerfil();
    const dias    = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sab'];
    const hh      = String(agora.getHours()).padStart(2, '0');
    const mm      = String(agora.getMinutes()).padStart(2, '0');

    // duracao_pausa_anterior_min — minutos desde a última sessão registrada
    let duracaoPausa = null;
    if (perfil.ultima_sessao_ts) {
        duracaoPausa = parseFloat(((agora.getTime() - perfil.ultima_sessao_ts) / 60000).toFixed(2));
    }

    // dias_para_prova — só se o usuário informou a data (onboarding/calendário)
    let diasParaProva = null;
    if (perfil.data_prova) {
        const prova = new Date(perfil.data_prova);
        diasParaProva = Math.max(0, Math.ceil((prova - agora) / 86400000));
    }

    return {
        horario_inicio:             `${hh}:${mm}`,                       // TIME   — extraído do relógio
        sessoes_no_dia:             perfil.sessoes_no_dia || 0,          // INTEGER— contador local
        dia_semana:                 dias[agora.getDay()],                // ENUM   — derivado do timestamp
        dias_para_prova:            diasParaProva,                       // INTEGER— null se não informado
        sequencia_dias_estudo:      perfil.sequencia_dias_estudo || 0,   // INTEGER— streak
        duracao_pausa_anterior_min: duracaoPausa,                        // FLOAT  — intervalo entre sessões
        ambiente_dispositivo:       perfil.ambiente_dispositivo || null  // ENUM   — auto-declarado (onboarding)
    };
}

// Mutável: chamado quando uma sessão de ESTUDO começa (atualiza streak/contadores)
function registrarInicioSessao() {
    const agora   = new Date();
    const perfil  = lerPerfil();
    const hojeStr = agora.toISOString().slice(0, 10);

    if (perfil.ultimo_dia_estudo === hojeStr) {
        perfil.sessoes_no_dia = (perfil.sessoes_no_dia || 0) + 1;       // mais uma sessão hoje
    } else {
        const ontem = new Date(agora);
        ontem.setDate(ontem.getDate() - 1);
        const ontemStr = ontem.toISOString().slice(0, 10);
        // manteve o hábito se estudou ontem; senão zera o streak
        perfil.sequencia_dias_estudo =
            (perfil.ultimo_dia_estudo === ontemStr) ? (perfil.sequencia_dias_estudo || 0) + 1 : 1;
        perfil.sessoes_no_dia = 1;
    }

    perfil.ultimo_dia_estudo = hojeStr;
    perfil.ultima_sessao_ts  = agora.getTime();
    gravarPerfil(perfil);
    return snapshotFeatures();
}

// Hooks de onboarding (chame quando tiver os campos no formulário)
function definirAmbiente(valor)  { const p = lerPerfil(); p.ambiente_dispositivo = valor; gravarPerfil(p); } // 'silencioso' | 'ruido_moderado' | 'ruido_alto'
function definirDataProva(iso)   { const p = lerPerfil(); p.data_prova = iso;            gravarPerfil(p); } // 'AAAA-MM-DD'

// Envia o pacote completo (login + hobbies + features) para o backend
async function enviarPerfil(extra = {}) {
    const payload = {
        session_id: sessionId,
        user_id:    userId,
        ts:         new Date().toISOString(),
        perfil:     lerPerfil(),
        hobbies:    historicoDeCliques,
        features:   snapshotFeatures(),
        ...extra
    };
    try {
        await fetch(`${API_URL}/perfil`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            keepalive: true
        });
    } catch (e) {
        console.warn('[KaIA] /perfil indisponível (salvo só localmente):', e);
    }
}

// Chamado pelo botão "Entrar" / "Criar conta" do login.html
function salvarLogin(event) {
    if (event) event.preventDefault();
    const email = document.getElementById('login-email')?.value.trim() || '';
    // OBS: a senha NÃO é guardada em texto puro — no Supabase use o Auth (supabase.auth.signIn)
    const perfil = lerPerfil();
    perfil.email = email;
    gravarPerfil(perfil);
    enviarPerfil({ tipo: 'login', email });
    window.location.href = 'hobbies.html';
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
    const perfil = lerPerfil();
    perfil.hobbies = historicoDeCliques;
    gravarPerfil(perfil);
    enviarPerfil({ tipo: 'hobbies' });
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

// Só ativa a luz se a página realmente tiver o elemento (evita travar
// o script inteiro em páginas sem .tela-login, como o index.html).
if (luz && container) {
    let luzX = window.innerWidth / 2;
    let luzY = window.innerHeight / 2;
    const raioFuga = 300;

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
}

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
    let temas = [];
    try {
        const r = await fetch(`${API_URL}/temas`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ materia: subject })
        });
        const data = await r.json();
        temas = data.temas || [];
    } catch (e) {
        console.warn('[KaIA] /temas indisponível:', e);
    }
    // Fallback: Gemini falhou/estourou cota → usa temas locais p/ não travar o fluxo
    if (!temas.length) {
        temas = TEMAS_FALLBACK[subject] || ['Tema 1', 'Tema 2', 'Tema 3'];
        console.warn('[KaIA] usando temas locais (fallback).');
    }
    temasBox.innerHTML = '';
    temas.forEach(tema => {
        const btn = document.createElement('button');
        btn.className = 'option-btn';
        btn.innerText = tema;
        btn.onclick = () => startMission(subject, tema);
        temasBox.appendChild(btn);
    });
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
        if (!currentQuestion || currentQuestion.erro || !Array.isArray(currentQuestion.opts)) {
            throw new Error(currentQuestion && currentQuestion.erro ? currentQuestion.erro : 'formato inválido');
        }
    } catch (e) {
        // Fallback: Gemini indisponível (ex: cota) → questão local, missão inicia mesmo assim
        console.warn('[KaIA] /gerar-questao indisponível, usando questão local:', e);
        currentQuestion = questaoFallback(subject, tema);
    }
    isMissionActive = true;
    idleTime = 0; mudancasAba = 0; focusLostAt = null;
    lastScrollY = window.scrollY; lastScrollTime = performance.now();
    lastKeystroke = 0;
    if (keystrokeTimer) clearTimeout(keystrokeTimer);

    // 1 sessão por missão: cria uma nova em `sessions` (gera session_id novo)
    await criarSessao();

    // Atualiza features da sessão (streak, sessões no dia, pausa) e envia o perfil
    const features = registrarInicioSessao();
    logEvent('session_start', { materia: subject, tema, features });
    enviarPerfil({ tipo: 'session_start', materia: subject, tema });

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

    // Desativa missão, encerra a sessão (session_end_ts) e volta ao menu após 1.5s
    isMissionActive = false;
    encerrarSessao();
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
    encerrarSessao();   // ABANDONAR também encerra a sessão
    if (idleInterval)   clearInterval(idleInterval);
    if (keystrokeTimer) clearTimeout(keystrokeTimer);
    location.reload();
}

// Fechar/recarregar a aba no meio da missão também encerra a sessão
window.addEventListener('beforeunload', () => {
    if (isMissionActive) encerrarSessao();
});

// ====================================================================================
//                  INICIALIZAÇÃO — registra todos os listeners 
// ===================================================================================
document.addEventListener('DOMContentLoaded', () => {
    // sessão NÃO é criada no load — só ao iniciar uma missão (criarSessao em startMission)
    registrarMouseMove();
    registrarScroll();
    registrarTeclado();
    registrarCliquesForaDaArea();
    registrarCopiarColar();
    console.log('[KaIA] Listeners registrados. Session ID:', sessionId);
});


// ============================================================================

// Troca de aba (VISÃO GERAL / SESSÕES / ATENÇÃO / FINANCEIRO)
function sv(id, btn) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('on'));
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('on'));
    const view = document.getElementById('v-' + id);
    view.classList.add('on');
    if (btn) btn.classList.add('on');
    if (typeof Chart !== 'undefined') {
        view.querySelectorAll('canvas').forEach(cv => Chart.getChart(cv)?.resize());
    }
}

// Ícones (SVG interno) usados nos cartões KPI — nome → markup
const DASH_ICONES = {
    users:'<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    layers:'<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',
    target:'<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/>',
    alert:'<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    calendar:'<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    clock:'<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    list:'<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    check:'<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    smile:'<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>',
    meh:'<circle cx="12" cy="12" r="10"/><line x1="8" y1="15" x2="16" y2="15"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>',
    frown:'<circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>',
    bolt:'<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    dollar:'<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    trend:'<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    grid:'<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
};

// Paleta (mesma do style.css) para os gráficos
const DASH_COR = { azul:'#2D4BA5', ouro:'#f3d009', verde:'#57D979', bege:'#c4a186', vermelho:'#f87171', amarelo:'#92400e' };

// escapa texto vindo da planilha antes de injetar no HTML
function esc(v){ return String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// helper: monta lista de objetos a partir de arrays paralelos (para o FALLBACK)
function _rows(len, fn){ return Array.from({length:len}, (_,i)=>fn(i)); }

// Rótulos de datas dos últimos 14 dias (para o FALLBACK do gráfico de 14 dias)
function _labels14(){
    return _rows(14, i => { const d=new Date(); d.setDate(d.getDate()-13+i);
        return d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'}); });
}

// ── FALLBACK: dados de demonstração (espelham as colunas da planilha) ──
const _sph=[2,1,1,0,0,0,1,3,8,15,18,22,19,21,25,28,31,35,42,58,71,65,48,22];
const _aph=[0,0,0,0,0,0,0,1,1,2,2,3,2,3,3,4,4,5,5,7,9,8,6,3];
const _fh =[35,30,28,25,22,20,25,38,52,61,65,68,64,67,70,72,74,75,72,80,85,83,76,60];
const _l14=_labels14();
const _ini=[88,102,115,98,121,145,167,141,158,172,189,202,225,241];
const _con=[55,68,74,60,82,99,110,91,105,119,131,140,158,171];
const _mrrE=[299,538,748,1047,1346,1794,2243,2691,3289,3887,4336,4485];
const _mrrI=[299,479,718,1078,1498,1916,2396,2995,3594,4312,4792,4792];

const DASH_FALLBACK = {
    kpis: [
        {view:'geral', icone:'users',  rotulo:'ATIVOS AGORA',     valor:'247',    subtexto:'sessões em andamento', variacao:'+18%', variacao_tipo:'up'},
        {view:'geral', icone:'layers', rotulo:'QUESTÕES HOJE',    valor:'4.830',  subtexto:'via API Gemini',       variacao:'+12%', variacao_tipo:'up'},
        {view:'geral', icone:'target', rotulo:'FOCO MÉDIO',       valor:'73%',    subtexto:'por sessão hoje',      variacao:'estável', variacao_tipo:'neutro'},
        {view:'geral', icone:'alert',  rotulo:'DISTRAÇÕES HOJE',  valor:'31',     subtexto:'alertas detectados',   variacao:'+7%',  variacao_tipo:'down'},
        {view:'sessoes', icone:'calendar', rotulo:'SESSÕES NO MÊS',    valor:'3.241',  subtexto:'todas as contas', variacao:'+31%', variacao_tipo:'up'},
        {view:'sessoes', icone:'clock',    rotulo:'DURAÇÃO MÉDIA',     valor:'47 min', subtexto:'por sessão',      variacao:'meta 45′', variacao_tipo:'neutro'},
        {view:'sessoes', icone:'list',     rotulo:'QUESTÕES / SESSÃO', valor:'19,5',   subtexto:'média geral',     variacao:'+4',   variacao_tipo:'up'},
        {view:'sessoes', icone:'check',    rotulo:'CONCLUSÃO',         valor:'68%',    subtexto:'sessões finalizadas', variacao:'estável', variacao_tipo:'neutro'},
        {view:'atencao', icone:'smile', rotulo:'FOCO ALTO >70%',     valor:'54%', subtexto:'das sessões hoje', cor:'verde'},
        {view:'atencao', icone:'meh',   rotulo:'FOCO MÉDIO 40–70%',  valor:'31%', subtexto:'das sessões hoje', cor:'amarelo'},
        {view:'atencao', icone:'frown', rotulo:'FOCO BAIXO <40%',    valor:'15%', subtexto:'das sessões hoje', variacao:'atenção', variacao_tipo:'down', cor:'vermelho'},
        {view:'atencao', icone:'bolt',  rotulo:'EVENTOS kaia.js / H', valor:'1.840', subtexto:'scroll · key · mouse · tab'},
        {view:'fin', icone:'dollar', rotulo:'MRR',           valor:'R$ 9,3k', subtexto:'receita recorrente/mês', variacao:'+94%', variacao_tipo:'up'},
        {view:'fin', icone:'users',  rotulo:'PAGANTES',      valor:'230',     subtexto:'Essencial + Intensivo',  variacao:'+23',  variacao_tipo:'up'},
        {view:'fin', icone:'trend',  rotulo:'LTV / CAC',     valor:'3,2×',    subtexto:'meta mínima: 3×',        variacao:'ok',   variacao_tipo:'up', cor:'verde'},
        {view:'fin', icone:'grid',   rotulo:'CUSTO API / MÊS', valor:'R$ 460', subtexto:'5% da receita',         variacao:'saudável', variacao_tipo:'neutro'}
    ],
    sessoes_hora:    _rows(24, i=>({hora:i+'h', sessoes:_sph[i], alertas:_aph[i]})),
    planos:          [{plano:'Free',percentual:62},{plano:'Essencial',percentual:28},{plano:'Intensivo',percentual:10}],
    alunos_recentes: [
        {aluno:'Lucas M.',  plano:'Intensivo', foco:'88%', tema:'Biologia'},
        {aluno:'Ana P.',    plano:'Essencial', foco:'65%', tema:'Matemática'},
        {aluno:'João V.',   plano:'Intensivo', foco:'91%', tema:'Redação'},
        {aluno:'Mariana L.',plano:'Free',      foco:'44%', tema:'História'},
        {aluno:'Pedro H.',  plano:'Essencial', foco:'78%', tema:'Química'}
    ],
    alertas_recentes: [
        {nivel:'amarelo',  mensagem:'Ana P. — distração prolongada (+3 min)', tempo:'há 2 min'},
        {nivel:'vermelho', mensagem:'Mariana L. — foco abaixo de 40%',        tempo:'há 5 min'},
        {nivel:'verde',    mensagem:'Lucas M. — sessão concluída (90 min)',   tempo:'há 8 min'},
        {nivel:'amarelo',  mensagem:'Carlos R. — troca de aba detectada',     tempo:'há 12 min'}
    ],
    sessoes_14dias:  _rows(14, i=>({data:_l14[i], iniciadas:_ini[i], concluidas:_con[i]})),
    temas_estudados: [
        {tema:'Matemática',sessoes:342},{tema:'Português',sessoes:298},{tema:'Biologia',sessoes:241},
        {tema:'Redação',sessoes:198},{tema:'História',sessoes:175},{tema:'Química',sessoes:152},{tema:'Física',sessoes:134}
    ],
    distribuicao_foco: [{faixa:'Alto',percentual:54},{faixa:'Médio',percentual:31},{faixa:'Baixo',percentual:15}],
    eventos_tipo: [
        {tipo:'Scroll passivo',percentual:38},{tipo:'Keystroke ativo',percentual:29},
        {tipo:'Mouse idle >30s',percentual:18},{tipo:'Troca de aba',percentual:15}
    ],
    foco_hora: _rows(24, i=>({hora:i+'h', foco:_fh[i]})),
    mrr_mensal: _rows(12, i=>({mes:'M'+(i+1), essencial:_mrrE[i], intensivo:_mrrI[i]})),
    metas_fase: [
        {meta:'MVP — 50 beta',            percentual:100, cor:'verde'},
        {meta:'Piloto — 250 pagantes',    percentual:92,  cor:'ouro'},
        {meta:'Escala — 500 pagantes',    percentual:46,  cor:'azul'},
        {meta:'Break-even — 250 assinantes', percentual:92, cor:'bege'}
    ],
    saude_financeira: [
        {indicador:'Margem bruta',valor:'78%',cor:'verde'},
        {indicador:'CAC médio',valor:'R$ 115'},
        {indicador:'LTV médio',valor:'R$ 480'},
        {indicador:'Payback do CAC',valor:'~3,5 meses'},
        {indicador:'Custo variável / usuário',valor:'R$ 2,00 / mês'},
        {indicador:'ARR projetado',valor:'R$ 111k',cor:'verde'}
    ]
};

// devolve o bloco da planilha se tiver linhas; senão o FALLBACK
function _bloco(D, nome){
    return (D && Array.isArray(D[nome]) && D[nome].length) ? D[nome] : DASH_FALLBACK[nome];
}

// ── RENDERIZADORES (planilha → HTML) ──
function _renderKPIs(kpis){
    const chipCls = {up:'cu', down:'cd', neutro:'co'};
    const corHex  = {verde:'#057a3a', amarelo:'#92400e', vermelho:'#991b1b'};
    ['geral','sessoes','atencao','fin'].forEach(view => {
        const box = document.getElementById('kpi-' + view);
        if (!box) return;
        // Fallback POR ABA: a base sintética não tem dados financeiros, então a
        // aba "fin" não vem no payload — nesse caso usamos os KPIs de demo.
        let linhas = kpis.filter(k => k.view === view);
        if (!linhas.length) linhas = DASH_FALLBACK.kpis.filter(k => k.view === view);
        box.innerHTML = linhas.map(k => {
            const icon = DASH_ICONES[k.icone] || DASH_ICONES.target;
            const corV = k.cor && corHex[k.cor] ? ` style="color:${corHex[k.cor]}"` : '';
            const chip = k.variacao
                ? `<span class="chip ${chipCls[k.variacao_tipo] || 'co'}">${esc(k.variacao)}</span>` : '';
            return `<div class="kpi">
                <div class="kl"><svg viewBox="0 0 24 24">${icon}</svg>${esc(k.rotulo)}</div>
                <div class="kv"${corV}>${esc(k.valor)}</div>
                <div class="kf"><span class="ks">${esc(k.subtexto)}</span>${chip}</div>
            </div>`;
        }).join('');
    });
}

function _renderLegenda(id, linhas, cores){
    const box = document.getElementById(id);
    if (!box) return;
    box.innerHTML = linhas.map((l,i) =>
        `<div class="li"><div class="ls" style="background:${cores[i%cores.length]}"></div>${esc(l)}</div>`
    ).join('');
}

function _renderAlunos(linhas){
    const box = document.getElementById('alunos-recentes');
    if (!box) return;
    // pi = verde, pe = âmbar, pf = azul. Cobre tanto os planos (demo) quanto
    // os perfis da base sintética.
    const cls = {
        Free:'pf', Essencial:'pe', Intensivo:'pi',
        'Focado':'pi', 'Cansaço':'pe', 'Distraído Gradual':'pe', 'Distraído Imediato':'pf'
    };
    box.innerHTML = linhas.map(a =>
        `<tr><td>${esc(a.aluno)}</td><td><span class="pp ${cls[a.plano]||'pf'}">${esc(a.plano)}</span></td>
         <td>${esc(a.foco)}</td><td>${esc(a.tema)}</td></tr>`).join('');
}

function _renderAlertas(linhas){
    const box = document.getElementById('alertas-recentes');
    if (!box) return;
    const mapa = {
        vermelho:{cls:'ar', ico:'<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'},
        amarelo :{cls:'ay', ico:'<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>'},
        verde   :{cls:'ag', ico:'<polyline points="20 6 9 17 4 12"/>'}
    };
    box.innerHTML = linhas.map(a => {
        const m = mapa[a.nivel] || mapa.amarelo;
        return `<div class="ai"><div class="aico ${m.cls}"><svg viewBox="0 0 24 24">${m.ico}</svg></div>
            <div class="ab"><div class="at">${esc(a.mensagem)}</div><div class="ats">${esc(a.tempo)}</div></div></div>`;
    }).join('');
}

function _renderEventos(linhas){
    const box = document.getElementById('eventos-tipo');
    if (!box) return;
    const fills = ['fb','fv','fg','fe'];
    box.innerHTML = linhas.map((e,i) =>
        `<div class="er"><span class="elb">${esc(e.tipo)}</span>
         <div class="etr"><div class="efi ${fills[i%fills.length]}" style="width:${Number(e.percentual)||0}%"></div></div>
         <span class="ep">${Number(e.percentual)||0}%</span></div>`).join('');
}

function _renderMetas(linhas){
    const box = document.getElementById('metas-fase');
    if (!box) return;
    const fill = {verde:'fv', ouro:'fg', azul:'fb', bege:'fe'};
    box.innerHTML = linhas.map(m => {
        const cor = DASH_COR[m.cor] || DASH_COR.azul;
        const pct = Number(m.percentual)||0;
        return `<div class="pr"><div class="pdot" style="background:${cor}"></div>
            <div class="pinfo"><div class="ptop"><span>${esc(m.meta)}</span><span>${pct}%</span></div>
            <div class="ptr"><div class="pfi ${fill[m.cor]||'fb'}" style="width:${pct}%"></div></div></div></div>`;
    }).join('');
}

function _renderSaude(linhas){
    const box = document.getElementById('saude-financeira');
    if (!box) return;
    const corHex = {verde:'#057a3a', vermelho:'#991b1b'};
    box.innerHTML = linhas.map(s => {
        const cor = s.cor && corHex[s.cor] ? ` style="color:${corHex[s.cor]}"` : '';
        return `<tr><td>${esc(s.indicador)}</td><td${cor}>${esc(s.valor)}</td></tr>`;
    }).join('');
}

// ── GRÁFICOS (Chart.js) ──
function _buildCharts(D){
    if (typeof Chart === 'undefined') return;
    const {azul:AZ, ouro:GR, verde:VD, bege:BE, vermelho:RE} = DASH_COR;
    const tk={color:'#aaa',font:{size:10,family:'Plus Jakarta Sans'}};
    const gr={color:'rgba(26,43,76,.05)'};
    const nl={legend:{display:false}};
    const base={responsive:true,maintainAspectRatio:false,plugins:nl};
    const col = (rows,k)=>rows.map(r=>Number(r[k])||0);
    const lab = (rows,k)=>rows.map(r=>r[k]);

    const sh = _bloco(D,'sessoes_hora');
    new Chart(document.getElementById('c1'),{type:'bar',data:{labels:lab(sh,'hora'),datasets:[
        {data:col(sh,'sessoes'),backgroundColor:AZ,borderRadius:3,order:2},
        {type:'line',data:col(sh,'alertas'),borderColor:GR,backgroundColor:'transparent',tension:.4,pointRadius:2,pointBackgroundColor:GR,borderWidth:2,order:1}
    ]},options:{...base,scales:{x:{ticks:{...tk,maxRotation:0,maxTicksLimit:8},grid:{display:false}},y:{ticks:tk,grid:gr,beginAtZero:true}}}});

    const pl = _bloco(D,'planos');
    _renderLegenda('lg-planos', pl.map(p=>`${p.plano} ${p.percentual}%`), [AZ,GR,VD,BE]);
    new Chart(document.getElementById('c2'),{type:'doughnut',data:{labels:lab(pl,'plano'),datasets:[{data:col(pl,'percentual'),backgroundColor:[AZ,GR,VD,BE],borderWidth:3,borderColor:'#fff',hoverOffset:6}]},options:{...base,cutout:'70%'}});

    const s14 = _bloco(D,'sessoes_14dias');
    new Chart(document.getElementById('c3'),{type:'line',data:{labels:lab(s14,'data'),datasets:[
        {data:col(s14,'iniciadas'),borderColor:AZ,backgroundColor:'rgba(45,75,165,.07)',fill:true,tension:.35,pointRadius:3,pointBackgroundColor:AZ,borderWidth:2},
        {data:col(s14,'concluidas'),borderColor:VD,backgroundColor:'rgba(87,217,121,.07)',fill:true,tension:.35,pointRadius:3,pointBackgroundColor:VD,borderDash:[4,3],borderWidth:2}
    ]},options:{...base,scales:{x:{ticks:tk,grid:{display:false}},y:{ticks:tk,grid:gr}}}});

    const te = _bloco(D,'temas_estudados');
    // afterFit reserva largura fixa para o eixo de categorias. Sem isso o
    // Chart.js mede o rótulo com a fonte de fallback (a webfont carrega depois)
    // e corta o 1º caractere dos nomes longos (ex.: "Vídeo-aula").
    new Chart(document.getElementById('c4'),{type:'bar',data:{labels:lab(te,'tema'),datasets:[{data:col(te,'sessoes'),backgroundColor:[AZ,GR,VD,BE,AZ,GR,VD],borderRadius:3}]},options:{...base,indexAxis:'y',scales:{x:{ticks:tk,grid:gr},y:{afterFit:s=>{s.width=96;},ticks:{...tk,font:{size:10,weight:'600',family:'Plus Jakarta Sans'}},grid:{display:false}}}}});

    const df = _bloco(D,'distribuicao_foco');
    _renderLegenda('lg-foco', df.map(f=>`${f.faixa} ${f.percentual}%`), [VD,GR,RE]);
    new Chart(document.getElementById('c5'),{type:'doughnut',data:{labels:lab(df,'faixa'),datasets:[{data:col(df,'percentual'),backgroundColor:[VD,GR,RE],borderWidth:3,borderColor:'#fff',hoverOffset:6}]},options:{...base,cutout:'70%'}});

    const fhr = _bloco(D,'foco_hora');
    new Chart(document.getElementById('c6'),{type:'line',data:{labels:lab(fhr,'hora'),datasets:[{data:col(fhr,'foco'),borderColor:VD,backgroundColor:'rgba(87,217,121,.1)',fill:true,tension:.4,pointRadius:0,borderWidth:2}]},options:{...base,scales:{x:{ticks:{...tk,maxTicksLimit:8},grid:{display:false}},y:{min:0,max:100,ticks:{...tk,callback:v=>v+'%'},grid:gr}}}});

    const mr = _bloco(D,'mrr_mensal');
    new Chart(document.getElementById('c7'),{type:'bar',data:{labels:lab(mr,'mes'),datasets:[
        {data:col(mr,'essencial'),backgroundColor:GR,borderRadius:3,stack:'r'},
        {data:col(mr,'intensivo'),backgroundColor:VD,borderRadius:3,stack:'r'}
    ]},options:{...base,scales:{x:{ticks:{...tk,autoSkip:false},grid:{display:false},stacked:true},y:{ticks:{...tk,callback:v=>'R$'+Math.round(v/1000)+'k'},grid:gr,stacked:true,beginAtZero:true}}}});
}

// Relógio "AO VIVO" do topo
function _dashClock(){
    const el = document.getElementById('clk');
    if (!el) return;
    el.textContent = new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
}

// Permite abrir uma aba direto pela URL: dashboard.html#atencao
const DASH_VIEWS = ['geral','sessoes','atencao','fin'];
function _aplicarHash(){
    const id = (location.hash || '').replace('#','');
    if (!DASH_VIEWS.includes(id)) return;
    const btn = Array.from(document.querySelectorAll('.tab'))
        .find(b => (b.getAttribute('onclick') || '').includes(`'${id}'`));
    sv(id, btn);
}

// Mostra de onde vieram os dados (base real x demo) na etiqueta do topo
function _renderFonte(D){
    const el = document.getElementById('fonte-dados');
    if (!el) return;
    if (D && D.fonte === 'base_sintetica') {
        el.textContent = `BASE SINTÉTICA · ${D.total_sessoes} SESSÕES · ${D.periodo}`;
    } else if (D && D.fonte === 'planilha_manual') {
        el.textContent = 'PLANILHA MANUAL';
    } else {
        el.textContent = 'DADOS DE DEMONSTRAÇÃO';
    }
}

async function iniciarDashboard(){
    // 1) busca os dados da planilha (via backend); tolera falha → FALLBACK
    let D = {};
    try {
        const r = await fetch(`${API_URL}/dashboard/dados`);
        if (r.ok) D = await r.json();
    } catch (e) {
        console.warn('[KaIA Dashboard] backend/planilha indisponível — usando dados demo:', e);
    }
    _renderFonte(D);
    // 2) renderiza tabelas/listas/KPIs
    _renderKPIs(_bloco(D,'kpis'));
    _renderAlunos(_bloco(D,'alunos_recentes'));
    _renderAlertas(_bloco(D,'alertas_recentes'));
    _renderEventos(_bloco(D,'eventos_tipo'));
    _renderMetas(_bloco(D,'metas_fase'));
    _renderSaude(_bloco(D,'saude_financeira'));
    // 3) monta os gráficos
    _buildCharts(D);
    // 4) relógio
    _dashClock();
    setInterval(_dashClock, 1000);
    // 5) abre a aba indicada na URL (ex.: dashboard.html#atencao)
    _aplicarHash();
    window.addEventListener('hashchange', _aplicarHash);
}

// Só dispara na página do dashboard
document.addEventListener('DOMContentLoaded', () => {
    if (document.body.classList.contains('dashboard-page')) iniciarDashboard();
});