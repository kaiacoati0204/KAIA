// ============================================================
//  KaIA — script compartilhado por todas as páginas
// ============================================================
// 127.0.0.1 (e não "localhost"): no Windows "localhost" pode resolver para
// IPv6 (::1) e o Flask dev server só escuta em IPv4 → "não responde".
const API_URL = 'http://127.0.0.1:5000';

// --- Atalhos de DOM ---------------------------------------------------------
const $  = (id) => document.getElementById(id);
const $$ = (sel, raiz = document) => Array.from(raiz.querySelectorAll(sel));

// POST em JSON. Quem chama decide se trata o erro — nada aqui derruba a UI.
function postJSON(rota, corpo, keepalive = false) {
    return fetch(`${API_URL}${rota}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
        keepalive
    }).then(r => r.json());
}

// --- Estado da sessão -------------------------------------------------------
// session_id: criado via POST /sessions, vive no sessionStorage (1 por aba).
// user_id: identidade estável do aluno, vive no localStorage (até o Supabase Auth).
let sessionId       = sessionStorage.getItem('kaia_session_id') || null;
let isMissionActive = false;
let idleInterval    = null;

let userId = localStorage.getItem('kaia_user_id');
if (!userId) {
    userId = crypto.randomUUID();
    localStorage.setItem('kaia_user_id', userId);
}

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
//        CAMADA DE DADOS — PERFIL + FEATURES (Supabase-ready)
// ============================================================
// Persistido em localStorage sob 'kaia_perfil' e espelhado no backend (/perfil).
// Para plugar o Supabase, basta trocar `enviarPerfil` por um upsert em `perfis`.
const lerPerfil    = () => JSON.parse(localStorage.getItem('kaia_perfil') || '{}');
const gravarPerfil = (p) => localStorage.setItem('kaia_perfil', JSON.stringify(p));

// Snapshot NÃO-mutável das features (só leitura, para enviar junto dos dados).
function snapshotFeatures() {
    const agora  = new Date();
    const perfil = lerPerfil();
    const dias   = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sab'];
    const hora   = `${String(agora.getHours()).padStart(2, '0')}:${String(agora.getMinutes()).padStart(2, '0')}`;

    return {
        horario_inicio:             hora,                                 // TIME    — do relógio
        sessoes_no_dia:             perfil.sessoes_no_dia || 0,           // INTEGER — contador local
        dia_semana:                 dias[agora.getDay()],                 // ENUM    — do timestamp
        sequencia_dias_estudo:      perfil.sequencia_dias_estudo || 0,    // INTEGER — streak
        ambiente_dispositivo:       perfil.ambiente_dispositivo || null,  // ENUM    — auto-declarado
        // minutos desde a última sessão registrada
        duracao_pausa_anterior_min: perfil.ultima_sessao_ts
            ? parseFloat(((agora - perfil.ultima_sessao_ts) / 60000).toFixed(2)) : null,
        // só existe se o aluno informou a data no onboarding
        dias_para_prova: perfil.data_prova
            ? Math.max(0, Math.ceil((new Date(perfil.data_prova) - agora) / 86400000)) : null
    };
}

// Mutável: chamado quando uma sessão de ESTUDO começa (atualiza streak/contadores).
function registrarInicioSessao() {
    const agora   = new Date();
    const perfil  = lerPerfil();
    const hojeStr = agora.toISOString().slice(0, 10);

    if (perfil.ultimo_dia_estudo === hojeStr) {
        perfil.sessoes_no_dia = (perfil.sessoes_no_dia || 0) + 1;
    } else {
        const ontem = new Date(agora);
        ontem.setDate(ontem.getDate() - 1);
        // manteve o hábito se estudou ontem; senão zera o streak
        perfil.sequencia_dias_estudo = (perfil.ultimo_dia_estudo === ontem.toISOString().slice(0, 10))
            ? (perfil.sequencia_dias_estudo || 0) + 1 : 1;
        perfil.sessoes_no_dia = 1;
    }

    perfil.ultimo_dia_estudo = hojeStr;
    perfil.ultima_sessao_ts  = agora.getTime();
    gravarPerfil(perfil);
    return snapshotFeatures();
}

// Hooks de onboarding: 'silencioso' | 'ruido_moderado' | 'ruido_alto' e 'AAAA-MM-DD'
const definirAmbiente  = (valor) => gravarPerfil({ ...lerPerfil(), ambiente_dispositivo: valor });
const definirDataProva = (iso)   => gravarPerfil({ ...lerPerfil(), data_prova: iso });

// Envia o pacote completo (login + hobbies + features) para o backend.
function enviarPerfil(extra = {}) {
    return postJSON('/perfil', {
        session_id: sessionId,
        user_id:    userId,
        ts:         new Date().toISOString(),
        perfil:     lerPerfil(),
        hobbies:    hobbiesSelecionados,
        features:   snapshotFeatures(),
        ...extra
    }, true).catch(e => console.warn('[KaIA] /perfil indisponível (salvo só localmente):', e));
}

// Botão "Entrar" do login.html. A senha NÃO é guardada — use o Supabase Auth.
function salvarLogin(event) {
    if (event) event.preventDefault();
    const email = $('login-email')?.value.trim() || '';
    gravarPerfil({ ...lerPerfil(), email });
    enviarPerfil({ tipo: 'login', email });
    window.location.href = 'hobbies.html';
}

// ============================================================
//                    MENU LATERAL
// ============================================================
// Injetado por JS em toda página com <body data-menu> — assim o markup do menu
// não fica copiado (e divergindo) em cada HTML.
const MENU_LINKS = [
    ['index.html',        'Início'],
    ['login.html',        'Login'],
    ['perfil.html',       'Perfil'],
    ['materias.html',     'Matérias'],
    ['meu-coati.html',    'Meu Coati'],
    ['responsaveis.html', 'Professor/Responsável'],
    ['dashboard.html',    'Dashboard'],
];

function montarMenu() {
    if (!document.body.hasAttribute('data-menu')) return;
    const atual = location.pathname.split('/').pop() || 'index.html';

    const nav = document.createElement('nav');
    nav.className = 'menu';
    nav.id = 'menu';
    nav.innerHTML = '<h1>- KaIA</h1>' + MENU_LINKS
        .map(([href, rotulo]) => `<a href="${href}"${href === atual ? ' class="ativo"' : ''}>${rotulo}</a>`)
        .join('');

    const botao = document.createElement('span');
    botao.className = 'botao';
    botao.textContent = '☰';
    botao.addEventListener('click', abrirMenu);

    document.body.prepend(nav, botao);
}

function abrirMenu() {
    const menu = $('menu');
    if (menu) menu.style.width = (menu.style.width === '250px') ? '0px' : '250px';
}

// ============================================================
//                       HOBBIES
// ============================================================
// A lista vive aqui (e não no HTML) para que o backend e a página de onboarding
// compartilhem a mesma fonte de verdade — os hobbies alimentam o prompt da IA.
const HOBBIES = [
    'Futebol', 'Basquete', 'Vôlei', 'Natação', 'Corrida', 'Ciclismo', 'Academia', 'Yoga', 'Dança',
    'Tricô', 'Crochê', 'Costura', 'Pintar', 'Desenho', 'Escultura', 'Fotografia',
    'RPG', 'Videogames', 'Jogos de Tabuleiro', 'Xadrez', 'Quebra-cabeças',
    'Culinária', 'Confeitaria', 'Churrasco',
    'Música', 'Cantar', 'Violão', 'Piano', 'Bateria',
    'Leitura', 'Escrita', 'Poesia',
    'Cinema/Filme', 'Séries', 'Anime', 'Mangá',
    'Programação', 'Robótica', 'Modelagem 3D', 'Impressão 3D',
    'Jardinagem', 'Pesca', 'Camping', 'Trilhas', 'Viagens', 'Astronomia',
    'Colecionismo', 'Origami', 'Idiomas', 'Voluntariado',
];

let hobbiesSelecionados = JSON.parse(sessionStorage.getItem('hobbies') || '[]');

function registrarHobbies() {
    const box = document.querySelector('.botoes-hobbies');
    if (!box) return;

    box.innerHTML = '';
    HOBBIES.forEach(nome => {
        const botao = document.createElement('button');
        botao.type = 'button';
        botao.className = 'botao-hobbies';
        botao.textContent = nome;
        botao.classList.toggle('selecionado', hobbiesSelecionados.includes(nome));

        botao.addEventListener('click', () => {
            const jaTinha = hobbiesSelecionados.includes(nome);
            hobbiesSelecionados = jaTinha
                ? hobbiesSelecionados.filter(h => h !== nome)
                : [...hobbiesSelecionados, nome];
            botao.classList.toggle('selecionado', !jaTinha);
            console.log('Hobbies:', hobbiesSelecionados);
        });

        box.appendChild(botao);
    });
}

function salvarHobbies() {
    sessionStorage.setItem('hobbies', JSON.stringify(hobbiesSelecionados));
    gravarPerfil({ ...lerPerfil(), hobbies: hobbiesSelecionados });
    enviarPerfil({ tipo: 'hobbies' });
    window.location.href = 'index.html';
}

// ============================================================
//                     FAÇA-SE A LUZ
// ============================================================
// A luz foge do mouse. Só liga na página que tem o elemento (login).
function registrarLuz() {
    const luz = $('luzFundo');
    const container = document.querySelector('.tela-login');
    if (!luz || !container) return;

    const raioFuga = 300;
    let luzX = window.innerWidth / 2;
    let luzY = window.innerHeight / 2;

    container.addEventListener('mousemove', (e) => {
        const dx = luzX - e.clientX;
        const dy = luzY - e.clientY;
        const distancia = Math.hypot(dx, dy);
        if (distancia >= raioFuga || distancia === 0) return;

        const forca = (raioFuga - distancia) / raioFuga;
        luzX = Math.max(50, Math.min(window.innerWidth  - 50, luzX + (dx / distancia) * forca * 30));
        luzY = Math.max(50, Math.min(window.innerHeight - 50, luzY + (dy / distancia) * forca * 30));
        luz.style.left = `${luzX}px`;
        luz.style.top  = `${luzY}px`;
    });
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
    console.log(`Palavras: ${palavras} | Tempo adaptado: ${segundos}s`);
    return segundos;
}

function iniciarIdleMonitor() {
    clearInterval(idleInterval);
    idleInterval = setInterval(() => {
        if (!isMissionActive) return;
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
        if (!isMissionActive) return;
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

    // --- scroll: rajadas rápidas indicam rolagem sem leitura ---
    lastScrollY    = window.scrollY;
    lastScrollTime = performance.now();
    window.addEventListener('scroll', () => {
        if (!isMissionActive) return;
        const agora  = performance.now();
        const deltaT = (agora - lastScrollTime) / 1000;
        const px_s   = deltaT > 0 ? Math.abs(window.scrollY - lastScrollY) / deltaT : 0;

        if (px_s > 300) {
            logEvent('scroll_burst', {
                px_s: parseFloat(px_s.toFixed(1)),
                duracao_s: parseFloat(deltaT.toFixed(2)),
                rolagem_sem_leitura: (px_s > 500 && deltaT > 2)
            });
        }
        lastScrollY    = window.scrollY;
        lastScrollTime = agora;
    }, { passive: true });

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
            hobbies: hobbiesSelecionados
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
};

const questaoFallback = (subject, tema) => ({
    q: `[OFFLINE] Questão de teste sobre "${tema}" (${subject}). Escolha uma opção:`,
    opts: ['Opção A', 'Opção B', 'Opção C', 'Opção D', 'Opção E'],
    ans: 0
});

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
    mostrarTela('quiz-view');
    $('question-display').innerText = 'KaIA criando sua questão...';
    $('options-display').innerHTML  = '';

    try {
        currentQuestion = await postJSON('/gerar-questao', {
            materia: subject, tema, hobbies: hobbiesSelecionados
        });
        if (!currentQuestion || currentQuestion.erro || !Array.isArray(currentQuestion.opts)) {
            throw new Error(currentQuestion?.erro || 'formato inválido');
        }
    } catch (e) {
        console.warn('[KaIA] /gerar-questao indisponível, usando questão local:', e);
        currentQuestion = questaoFallback(subject, tema);
    }

    // zera os sensores para esta missão
    isMissionActive = true;
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

    btn.style.background = acertou ? '#27ae60' : '#e74c3c';
    isMissionActive = false;
    encerrarSessao();

    setTimeout(() => {
        mostrarTela('menu-view');
        clearInterval(idleInterval);
        setEstado('AGUARDANDO');
    }, 1500);
}

// "ABANDONAR" também encerra a sessão.
function resetSystem() {
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
//        PERFIL — o aluno vendo a própria evolução
// ============================================================
async function carregarPerfil() {
    if (!$('nomeUsuario')) return;
    try {
        const r = await fetch(`${API_URL}/perfil`);
        if (!r.ok) return;
        const u = await r.json();

        const campos = {
            nomeUsuario:   u.nome,
            emailUsuario:  u.email,
            perfilUsuario: u.perfil,
            tempoResposta: `${u.tempo_resposta_ms} ms`,
            scrollUsuario: `${u.velocidade_scroll_px_s} px/s`,
        };
        Object.entries(campos).forEach(([id, valor]) => {
            const el = $(id);
            if (el && valor != null) el.textContent = valor;
        });
    } catch (e) {
        console.warn('[KaIA] Erro ao carregar dados do perfil:', e);
    }
}

// ============================================================
//                  DASHBOARD INTERNO
// ============================================================
// Troca de aba (VISÃO GERAL / SESSÕES / ATENÇÃO / FINANCEIRO)
function sv(id, btn) {
    $$('.view').forEach(v => v.classList.remove('on'));
    $$('.tab').forEach(b => b.classList.remove('on'));
    const view = $('v-' + id);
    view.classList.add('on');
    btn?.classList.add('on');
    if (typeof Chart !== 'undefined') {
        $$('canvas', view).forEach(cv => Chart.getChart(cv)?.resize());
    }
}

// Ícones (SVG interno) dos cartões KPI — nome → markup
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

// Paleta dos gráficos (espelha as variáveis do style.css)
const DASH_COR = { azul:'#2D4BA5', ouro:'#f3d009', verde:'#57D979', bege:'#c4a186', vermelho:'#f87171', amarelo:'#92400e' };
const COR_TEXTO = { verde:'#057a3a', amarelo:'#92400e', vermelho:'#991b1b' };

// Escapa texto vindo da planilha antes de injetar no HTML.
const esc = (v) => String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num = (v) => Number(v) || 0;
const _rows = (len, fn) => Array.from({ length: len }, (_, i) => fn(i));

// ── FALLBACK: dados de demonstração (espelham as colunas da planilha) ──
const _sph = [2,1,1,0,0,0,1,3,8,15,18,22,19,21,25,28,31,35,42,58,71,65,48,22];
const _aph = [0,0,0,0,0,0,0,1,1,2,2,3,2,3,3,4,4,5,5,7,9,8,6,3];
const _fh  = [35,30,28,25,22,20,25,38,52,61,65,68,64,67,70,72,74,75,72,80,85,83,76,60];
const _ini = [88,102,115,98,121,145,167,141,158,172,189,202,225,241];
const _con = [55,68,74,60,82,99,110,91,105,119,131,140,158,171];
const _mrrE = [299,538,748,1047,1346,1794,2243,2691,3289,3887,4336,4485];
const _mrrI = [299,479,718,1078,1498,1916,2396,2995,3594,4312,4792,4792];
const _l14 = _rows(14, i => {
    const d = new Date();
    d.setDate(d.getDate() - 13 + i);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
});

const DASH_FALLBACK = {
    kpis: [
        {view:'geral', icone:'users',  rotulo:'ATIVOS AGORA',    valor:'247',   subtexto:'sessões em andamento', variacao:'+18%', variacao_tipo:'up'},
        {view:'geral', icone:'layers', rotulo:'QUESTÕES HOJE',   valor:'4.830', subtexto:'via API Gemini',       variacao:'+12%', variacao_tipo:'up'},
        {view:'geral', icone:'target', rotulo:'FOCO MÉDIO',      valor:'73%',   subtexto:'por sessão hoje',      variacao:'estável', variacao_tipo:'neutro'},
        {view:'geral', icone:'alert',  rotulo:'DISTRAÇÕES HOJE', valor:'31',    subtexto:'alertas detectados',   variacao:'+7%',  variacao_tipo:'down'},
        {view:'sessoes', icone:'calendar', rotulo:'SESSÕES NO MÊS',    valor:'3.241',  subtexto:'todas as contas',     variacao:'+31%', variacao_tipo:'up'},
        {view:'sessoes', icone:'clock',    rotulo:'DURAÇÃO MÉDIA',     valor:'47 min', subtexto:'por sessão',          variacao:'meta 45′', variacao_tipo:'neutro'},
        {view:'sessoes', icone:'list',     rotulo:'QUESTÕES / SESSÃO', valor:'19,5',   subtexto:'média geral',         variacao:'+4',   variacao_tipo:'up'},
        {view:'sessoes', icone:'check',    rotulo:'CONCLUSÃO',         valor:'68%',    subtexto:'sessões finalizadas', variacao:'estável', variacao_tipo:'neutro'},
        {view:'atencao', icone:'smile', rotulo:'FOCO ALTO >70%',     valor:'54%',   subtexto:'das sessões hoje', cor:'verde'},
        {view:'atencao', icone:'meh',   rotulo:'FOCO MÉDIO 40–70%',  valor:'31%',   subtexto:'das sessões hoje', cor:'amarelo'},
        {view:'atencao', icone:'frown', rotulo:'FOCO BAIXO <40%',    valor:'15%',   subtexto:'das sessões hoje', variacao:'atenção', variacao_tipo:'down', cor:'vermelho'},
        {view:'atencao', icone:'bolt',  rotulo:'EVENTOS kaia.js / H', valor:'1.840', subtexto:'scroll · key · mouse · tab'},
        {view:'fin', icone:'dollar', rotulo:'MRR',             valor:'R$ 9,3k', subtexto:'receita recorrente/mês', variacao:'+94%', variacao_tipo:'up'},
        {view:'fin', icone:'users',  rotulo:'PAGANTES',        valor:'230',     subtexto:'Essencial + Intensivo',  variacao:'+23',  variacao_tipo:'up'},
        {view:'fin', icone:'trend',  rotulo:'LTV / CAC',       valor:'3,2×',    subtexto:'meta mínima: 3×',        variacao:'ok',   variacao_tipo:'up', cor:'verde'},
        {view:'fin', icone:'grid',   rotulo:'CUSTO API / MÊS', valor:'R$ 460',  subtexto:'5% da receita',          variacao:'saudável', variacao_tipo:'neutro'}
    ],
    sessoes_hora:    _rows(24, i => ({ hora: i + 'h', sessoes: _sph[i], alertas: _aph[i] })),
    foco_hora:       _rows(24, i => ({ hora: i + 'h', foco: _fh[i] })),
    sessoes_14dias:  _rows(14, i => ({ data: _l14[i], iniciadas: _ini[i], concluidas: _con[i] })),
    mrr_mensal:      _rows(12, i => ({ mes: 'M' + (i + 1), essencial: _mrrE[i], intensivo: _mrrI[i] })),
    planos: [{plano:'Free',percentual:62},{plano:'Essencial',percentual:28},{plano:'Intensivo',percentual:10}],
    distribuicao_foco: [{faixa:'Alto',percentual:54},{faixa:'Médio',percentual:31},{faixa:'Baixo',percentual:15}],
    alunos_recentes: [
        {aluno:'Lucas M.',   plano:'Intensivo', foco:'88%', tema:'Biologia'},
        {aluno:'Ana P.',     plano:'Essencial', foco:'65%', tema:'Matemática'},
        {aluno:'João V.',    plano:'Intensivo', foco:'91%', tema:'Redação'},
        {aluno:'Mariana L.', plano:'Free',      foco:'44%', tema:'História'},
        {aluno:'Pedro H.',   plano:'Essencial', foco:'78%', tema:'Química'}
    ],
    alertas_recentes: [
        {nivel:'amarelo',  mensagem:'Ana P. — distração prolongada (+3 min)', tempo:'há 2 min'},
        {nivel:'vermelho', mensagem:'Mariana L. — foco abaixo de 40%',        tempo:'há 5 min'},
        {nivel:'verde',    mensagem:'Lucas M. — sessão concluída (90 min)',   tempo:'há 8 min'},
        {nivel:'amarelo',  mensagem:'Carlos R. — troca de aba detectada',     tempo:'há 12 min'}
    ],
    temas_estudados: [
        {tema:'Matemática',sessoes:342},{tema:'Português',sessoes:298},{tema:'Biologia',sessoes:241},
        {tema:'Redação',sessoes:198},{tema:'História',sessoes:175},{tema:'Química',sessoes:152},{tema:'Física',sessoes:134}
    ],
    eventos_tipo: [
        {tipo:'Scroll passivo',percentual:38},{tipo:'Keystroke ativo',percentual:29},
        {tipo:'Mouse idle >30s',percentual:18},{tipo:'Troca de aba',percentual:15}
    ],
    metas_fase: [
        {meta:'MVP — 50 beta',               percentual:100, cor:'verde'},
        {meta:'Piloto — 250 pagantes',       percentual:92,  cor:'ouro'},
        {meta:'Escala — 500 pagantes',       percentual:46,  cor:'azul'},
        {meta:'Break-even — 250 assinantes', percentual:92,  cor:'bege'}
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

// Devolve o bloco da planilha se tiver linhas; senão o FALLBACK.
const _bloco = (D, nome) =>
    (D && Array.isArray(D[nome]) && D[nome].length) ? D[nome] : DASH_FALLBACK[nome];

// Preenche um container por id (no-op se a página não tiver o elemento).
function _preencher(id, html) {
    const box = $(id);
    if (box) box.innerHTML = html;
}

// ── RENDERIZADORES (planilha → HTML) ──
function _renderKPIs(kpis) {
    const chipCls = { up:'cu', down:'cd', neutro:'co' };
    ['geral', 'sessoes', 'atencao', 'fin'].forEach(view => {
        // Fallback POR ABA: a base sintética não tem dados financeiros, então a
        // aba "fin" não vem no payload — nesse caso usamos os KPIs de demo.
        let linhas = kpis.filter(k => k.view === view);
        if (!linhas.length) linhas = DASH_FALLBACK.kpis.filter(k => k.view === view);

        _preencher('kpi-' + view, linhas.map(k => {
            const cor  = COR_TEXTO[k.cor] ? ` style="color:${COR_TEXTO[k.cor]}"` : '';
            const chip = k.variacao
                ? `<span class="chip ${chipCls[k.variacao_tipo] || 'co'}">${esc(k.variacao)}</span>` : '';
            return `<div class="kpi">
                <div class="kl"><svg viewBox="0 0 24 24">${DASH_ICONES[k.icone] || DASH_ICONES.target}</svg>${esc(k.rotulo)}</div>
                <div class="kv"${cor}>${esc(k.valor)}</div>
                <div class="kf"><span class="ks">${esc(k.subtexto)}</span>${chip}</div>
            </div>`;
        }).join(''));
    });
}

function _renderLegenda(id, linhas, cores) {
    _preencher(id, linhas.map((l, i) =>
        `<div class="li"><div class="ls" style="background:${cores[i % cores.length]}"></div>${esc(l)}</div>`
    ).join(''));
}

function _renderAlunos(linhas) {
    // pi = verde, pe = âmbar, pf = azul. Cobre os planos (demo) e os perfis da base sintética.
    const cls = {
        Free:'pf', Essencial:'pe', Intensivo:'pi',
        'Focado':'pi', 'Cansaço':'pe', 'Distraído Gradual':'pe', 'Distraído Imediato':'pf'
    };
    _preencher('alunos-recentes', linhas.map(a =>
        `<tr><td>${esc(a.aluno)}</td><td><span class="pp ${cls[a.plano] || 'pf'}">${esc(a.plano)}</span></td>
         <td>${esc(a.foco)}</td><td>${esc(a.tema)}</td></tr>`).join(''));
}

function _renderAlertas(linhas) {
    const mapa = {
        vermelho: { cls:'ar', ico:'<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>' },
        amarelo:  { cls:'ay', ico:'<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>' },
        verde:    { cls:'ag', ico:'<polyline points="20 6 9 17 4 12"/>' }
    };
    _preencher('alertas-recentes', linhas.map(a => {
        const m = mapa[a.nivel] || mapa.amarelo;
        return `<div class="ai"><div class="aico ${m.cls}"><svg viewBox="0 0 24 24">${m.ico}</svg></div>
            <div class="ab"><div class="at">${esc(a.mensagem)}</div><div class="ats">${esc(a.tempo)}</div></div></div>`;
    }).join(''));
}

function _renderEventos(linhas) {
    const fills = ['fb', 'fv', 'fg', 'fe'];
    _preencher('eventos-tipo', linhas.map((e, i) =>
        `<div class="er"><span class="elb">${esc(e.tipo)}</span>
         <div class="etr"><div class="efi ${fills[i % fills.length]}" style="width:${num(e.percentual)}%"></div></div>
         <span class="ep">${num(e.percentual)}%</span></div>`).join(''));
}

function _renderMetas(linhas) {
    const fill = { verde:'fv', ouro:'fg', azul:'fb', bege:'fe' };
    _preencher('metas-fase', linhas.map(m => {
        const pct = num(m.percentual);
        return `<div class="pr"><div class="pdot" style="background:${DASH_COR[m.cor] || DASH_COR.azul}"></div>
            <div class="pinfo"><div class="ptop"><span>${esc(m.meta)}</span><span>${pct}%</span></div>
            <div class="ptr"><div class="pfi ${fill[m.cor] || 'fb'}" style="width:${pct}%"></div></div></div></div>`;
    }).join(''));
}

function _renderSaude(linhas) {
    _preencher('saude-financeira', linhas.map(s => {
        const cor = COR_TEXTO[s.cor] ? ` style="color:${COR_TEXTO[s.cor]}"` : '';
        return `<tr><td>${esc(s.indicador)}</td><td${cor}>${esc(s.valor)}</td></tr>`;
    }).join(''));
}

// Mostra de onde vieram os dados (base real x demo) na etiqueta do topo.
function _renderFonte(D) {
    const el = $('fonte-dados');
    if (!el) return;
    if (D?.fonte === 'base_sintetica') el.textContent = `BASE SINTÉTICA · ${D.total_sessoes} SESSÕES · ${D.periodo}`;
    else if (D?.fonte === 'planilha_manual') el.textContent = 'PLANILHA MANUAL';
    else el.textContent = 'DADOS DE DEMONSTRAÇÃO';
}

// ── GRÁFICOS (Chart.js) ──
function _buildCharts(D) {
    if (typeof Chart === 'undefined') return;
    const { azul: AZ, ouro: GR, verde: VD, bege: BE, vermelho: RE } = DASH_COR;

    const tk   = { color:'#aaa', font:{ size:10, family:'Plus Jakarta Sans' } };
    const gr   = { color:'rgba(26,43,76,.05)' };
    const base = { responsive:true, maintainAspectRatio:false, plugins:{ legend:{ display:false } } };
    const col  = (rows, k) => rows.map(r => num(r[k]));
    const lab  = (rows, k) => rows.map(r => r[k]);
    const rosca = { ...base, cutout:'70%' };

    const sh = _bloco(D, 'sessoes_hora');
    new Chart($('c1'), { type:'bar', data:{ labels:lab(sh,'hora'), datasets:[
        { data:col(sh,'sessoes'), backgroundColor:AZ, borderRadius:3, order:2 },
        { type:'line', data:col(sh,'alertas'), borderColor:GR, backgroundColor:'transparent', tension:.4, pointRadius:2, pointBackgroundColor:GR, borderWidth:2, order:1 }
    ]}, options:{ ...base, scales:{ x:{ ticks:{ ...tk, maxRotation:0, maxTicksLimit:8 }, grid:{ display:false } }, y:{ ticks:tk, grid:gr, beginAtZero:true } } } });

    const pl = _bloco(D, 'planos');
    _renderLegenda('lg-planos', pl.map(p => `${p.plano} ${p.percentual}%`), [AZ, GR, VD, BE]);
    new Chart($('c2'), { type:'doughnut', data:{ labels:lab(pl,'plano'), datasets:[{ data:col(pl,'percentual'), backgroundColor:[AZ,GR,VD,BE], borderWidth:3, borderColor:'#fff', hoverOffset:6 }]}, options:rosca });

    const s14 = _bloco(D, 'sessoes_14dias');
    new Chart($('c3'), { type:'line', data:{ labels:lab(s14,'data'), datasets:[
        { data:col(s14,'iniciadas'),  borderColor:AZ, backgroundColor:'rgba(45,75,165,.07)', fill:true, tension:.35, pointRadius:3, pointBackgroundColor:AZ, borderWidth:2 },
        { data:col(s14,'concluidas'), borderColor:VD, backgroundColor:'rgba(87,217,121,.07)', fill:true, tension:.35, pointRadius:3, pointBackgroundColor:VD, borderDash:[4,3], borderWidth:2 }
    ]}, options:{ ...base, scales:{ x:{ ticks:tk, grid:{ display:false } }, y:{ ticks:tk, grid:gr } } } });

    // afterFit reserva largura fixa para o eixo de categorias. Sem isso o Chart.js
    // mede o rótulo com a fonte de fallback (a webfont carrega depois) e corta o
    // 1º caractere dos nomes longos (ex.: "Vídeo-aula").
    const te = _bloco(D, 'temas_estudados');
    new Chart($('c4'), { type:'bar', data:{ labels:lab(te,'tema'), datasets:[{ data:col(te,'sessoes'), backgroundColor:[AZ,GR,VD,BE,AZ,GR,VD], borderRadius:3 }]},
        options:{ ...base, indexAxis:'y', scales:{ x:{ ticks:tk, grid:gr }, y:{ afterFit:s => { s.width = 96; }, ticks:{ ...tk, font:{ size:10, weight:'600', family:'Plus Jakarta Sans' } }, grid:{ display:false } } } } });

    const df = _bloco(D, 'distribuicao_foco');
    _renderLegenda('lg-foco', df.map(f => `${f.faixa} ${f.percentual}%`), [VD, GR, RE]);
    new Chart($('c5'), { type:'doughnut', data:{ labels:lab(df,'faixa'), datasets:[{ data:col(df,'percentual'), backgroundColor:[VD,GR,RE], borderWidth:3, borderColor:'#fff', hoverOffset:6 }]}, options:rosca });

    const fhr = _bloco(D, 'foco_hora');
    new Chart($('c6'), { type:'line', data:{ labels:lab(fhr,'hora'), datasets:[{ data:col(fhr,'foco'), borderColor:VD, backgroundColor:'rgba(87,217,121,.1)', fill:true, tension:.4, pointRadius:0, borderWidth:2 }]},
        options:{ ...base, scales:{ x:{ ticks:{ ...tk, maxTicksLimit:8 }, grid:{ display:false } }, y:{ min:0, max:100, ticks:{ ...tk, callback:v => v + '%' }, grid:gr } } } });

    const mr = _bloco(D, 'mrr_mensal');
    new Chart($('c7'), { type:'bar', data:{ labels:lab(mr,'mes'), datasets:[
        { data:col(mr,'essencial'), backgroundColor:GR, borderRadius:3, stack:'r' },
        { data:col(mr,'intensivo'), backgroundColor:VD, borderRadius:3, stack:'r' }
    ]}, options:{ ...base, scales:{ x:{ ticks:{ ...tk, autoSkip:false }, grid:{ display:false }, stacked:true }, y:{ ticks:{ ...tk, callback:v => 'R$' + Math.round(v / 1000) + 'k' }, grid:gr, stacked:true, beginAtZero:true } } } });
}

// Permite abrir uma aba direto pela URL: dashboard.html#atencao
const DASH_VIEWS = ['geral', 'sessoes', 'atencao', 'fin'];
function _aplicarHash() {
    const id = (location.hash || '').replace('#', '');
    if (!DASH_VIEWS.includes(id)) return;
    sv(id, $$('.tab').find(b => (b.getAttribute('onclick') || '').includes(`'${id}'`)));
}

function _dashClock() {
    const el = $('clk');
    if (el) el.textContent = new Date().toLocaleString('pt-BR',
        { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit' });
}

async function iniciarDashboard() {
    // 1) busca os dados da planilha (via backend); tolera falha → FALLBACK
    let D = {};
    try {
        const r = await fetch(`${API_URL}/dashboard/dados`);
        if (r.ok) D = await r.json();
    } catch (e) {
        console.warn('[KaIA Dashboard] backend/planilha indisponível — usando dados demo:', e);
    }

    // 2) tabelas, listas e KPIs
    _renderFonte(D);
    _renderKPIs(_bloco(D, 'kpis'));
    _renderAlunos(_bloco(D, 'alunos_recentes'));
    _renderAlertas(_bloco(D, 'alertas_recentes'));
    _renderEventos(_bloco(D, 'eventos_tipo'));
    _renderMetas(_bloco(D, 'metas_fase'));
    _renderSaude(_bloco(D, 'saude_financeira'));

    // 3) gráficos, relógio e a aba indicada na URL
    _buildCharts(D);
    _dashClock();
    setInterval(_dashClock, 1000);
    _aplicarHash();
    window.addEventListener('hashchange', _aplicarHash);
}

// ============================================================
//     INICIALIZAÇÃO — ponto de entrada único de todas as páginas
// ============================================================
// Cada `registrar*` é no-op nas páginas que não têm os elementos, então este
// bloco pode rodar em qualquer HTML. A sessão NÃO nasce aqui: só ao iniciar
// uma missão (criarSessao em startMission).
document.addEventListener('DOMContentLoaded', () => {
    montarMenu();
    registrarHobbies();
    registrarLuz();
    registrarSensores();
    carregarPerfil();
    if (document.body.classList.contains('dashboard-page')) iniciarDashboard();
    console.log('[KaIA] Página pronta. Session ID:', sessionId);
});
