// ============================================================
//  KaIA — script compartilhado por todas as páginas
// ============================================================
// A configuração (API_URL + credenciais do Supabase) vive no config.js, que é
// carregado ANTES deste arquivo em todas as páginas e não vai para o git.
// O fallback mantém a página de pé se o config.js não existir.
const API_URL = window.KAIA_CONFIG?.API_URL || 'http://127.0.0.1:5000';

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
            const r = await fetch(`${API_URL}/intervencao/pendente?session_id=${sessionId}`);
            const data = await r.json();
            if (data && data.pendente) mostrarIntervencao(data.pendente);
        } catch (_) { /* silencioso */ }
    }, 15000);
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

// Botão "Entrar" do login.html.
// Sem senha por enquanto: o e-mail é a identidade. A autenticação de verdade
// (Supabase Auth) entra depois — este fluxo só RESOLVE quem é o usuário.
const ROTA_POR_ROLE = {
    professor:   'responsaveis.html',
    coordenador: 'responsaveis.html',
    pai:         'responsaveis.html',
};

async function salvarLogin(event) {
    if (event) event.preventDefault();

    const email = $('login-email')?.value.trim() || '';
    const erro  = $('login-erro');
    const falhar = (msg) => { if (erro) erro.textContent = msg; };

    falhar('');
    if (!email) return falhar('Digite seu e-mail.');

    try {
        const r = await fetch(`${API_URL}/perfil?email=${encodeURIComponent(email)}`);

        if (r.status === 404) return falhar('E-mail não encontrado. Confira e tente de novo.');
        if (!r.ok)            return falhar('Não foi possível entrar agora. Tente mais tarde.');

        const u = await r.json();

        sessionStorage.setItem('kaia_usuario', JSON.stringify({
            user_id:   u.user_id,
            email:     u.email,
            nome:      u.nome,
            role:      u.role,
            escola_id: u.escola_id,
            turma_id:  u.turma_id,
        }));

        // A identidade estável usada pelos sensores (sessions/events) passa a ser
        // a do perfil real — senão a sessão seria gravada no user_id aleatório.
        localStorage.setItem('kaia_user_id', u.user_id);

        const hobbies = u.hobbies || [];
        sessionStorage.setItem('hobbies', JSON.stringify(hobbies));
        gravarPerfil({ ...lerPerfil(), email: u.email, hobbies });

        if (u.role === 'aluno') {
            window.location.href = hobbies.length ? 'index.html' : 'hobbies.html';
        } else {
            window.location.href = ROTA_POR_ROLE[u.role] || 'index.html';
        }
    } catch (e) {
        console.error('[KaIA] falha no login:', e);
        falhar('Não foi possível conectar ao servidor (a API está rodando em :5000?).');
    }
}

// ============================================================
//                    MENU LATERAL
// ============================================================
// Injetado por JS em toda página com <body data-menu> — assim o markup do menu
// não fica copiado (e divergindo) em cada HTML.
const MENU_LINKS = [
    ['index.html',        'Início'],
    ['perfil.html',       'Perfil'],
    ['materias.html',     'Matérias'],
    ['meu-coati.html',    'Meu Coati'],
    ['responsaveis.html', 'Acompanhar'],
    ['dashboard.html',    'Dashboard'],
];

// O menu lateral antigo (☰) e a saudação flutuante foram substituídos pela
// barra estática (montarRail, abaixo). MENU_LINKS agora alimenta a rail.

// ============================================================
//              BARRA LATERAL ESTÁTICA (rail)
// ============================================================
// Injetada nas páginas com <body data-rail>. Começa estreita (só ícones) e
// expande ao clicar no ícone de menu (classe rail-aberta no body). É uma COLUNA
// real do layout (o body vira flex): empurra o conteúdo em vez de sobrepor.
const RAIL_ICONES = {
    menu:                '<svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>',
    'index.html':        '<svg viewBox="0 0 24 24"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>',
    'login.html':        '<svg viewBox="0 0 24 24"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>',
    'perfil.html':       '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg>',
    'materias.html':     '<svg viewBox="0 0 24 24"><path d="M4 4h13a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4z"/><path d="M4 4v14"/></svg>',
    'meu-coati.html':    '<svg viewBox="0 0 24 24"><path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="M3 7l9 5 9-5"/><path d="M12 12v10"/></svg>',
    'responsaveis.html': '<svg viewBox="0 0 24 24"><line x1="6" y1="20" x2="6" y2="12"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="18" y1="20" x2="18" y2="14"/></svg>',
    'dashboard.html':    '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    sair:                '<svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>',
};

function montarRail() {
    if (!document.body.hasAttribute('data-rail')) return;
    const atual = location.pathname.split('/').pop() || 'index.html';

    const item = (ic, tx) => `<span class="rail-ic">${ic}</span><span class="rail-tx">${tx}</span>`;

    const links = MENU_LINKS.map(([href, rotulo]) => {
        const ativo = href === atual ? ' ativo' : '';
        return `<a href="${href}" class="rail-item${ativo}">${item(RAIL_ICONES[href] || '', rotulo)}</a>`;
    }).join('');

    // Rodapé da rail: identidade do usuário + Sair, separados dos links de nav.
    const u = JSON.parse(sessionStorage.getItem('kaia_usuario') || 'null');
    const nome = u ? (u.nome || u.email || '').trim() : '';
    const inicial = nome ? nome[0].toUpperCase() : '·';
    const saudacao = nome
        ? `<div class="rail-item rail-user"><span class="rail-ic rail-avatar">${inicial}</span><span class="rail-tx">Olá, ${nome}</span></div>`
        : '';
    const rodape =
        `<div class="rail-rodape">${saudacao}`
        + `<button class="rail-item rail-sair" type="button">${item(RAIL_ICONES.sair, 'Sair')}</button>`
        + `</div>`;

    const rail = document.createElement('nav');
    rail.className = 'railnav';
    rail.setAttribute('aria-label', 'Navegação');
    rail.innerHTML =
        `<button class="rail-item rail-toggle" type="button" aria-label="Expandir ou recolher o menu">${item(RAIL_ICONES.menu, 'Menu')}</button>`
        + `<div class="rail-links">${links}</div>`
        + rodape;
    document.body.prepend(rail);

    // Estado (aberta/colapsada) lembrado entre páginas via localStorage.
    if (localStorage.getItem('kaia_rail_aberta') === '1') document.body.classList.add('rail-aberta');
    rail.querySelector('.rail-toggle').addEventListener('click', () => {
        const aberta = document.body.classList.toggle('rail-aberta');
        localStorage.setItem('kaia_rail_aberta', aberta ? '1' : '0');
    });

    // Sair: limpa a sessão (mantém a identidade do dispositivo) e volta ao login.
    rail.querySelector('.rail-sair').addEventListener('click', () => {
        sessionStorage.clear();
        window.location.href = 'login.html';
    });
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
        const r = await fetch(`${API_URL}/anotacoes?aluno_id=${encodeURIComponent(userId)}&tema=${encodeURIComponent(tema)}`);
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
        const r = await fetch(`${API_URL}/anotacoes`, {
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
//        PERFIL — o aluno vendo a própria evolução
// ============================================================
async function carregarPerfil() {
    if (!$('nomeUsuario')) return;

    const SEM_DADO = '—';
    const usuario = JSON.parse(sessionStorage.getItem('kaia_usuario') || 'null');

    // 1) Identidade: parte do sessionStorage (login, por aba) e confirma via /perfil.
    $('nomeUsuario').textContent  = usuario?.nome || usuario?.email || SEM_DADO;
    $('emailUsuario').textContent = usuario?.email || SEM_DADO;

    // user_id do perfil EXIBIDO. NÃO usar localStorage.kaia_user_id: ele é
    // compartilhado entre abas (o último login sobrescreve para todas), então
    // discordaria da identidade desta aba. sessionStorage é por aba; o /perfil
    // é a fonte autoritativa.
    let alunoId = usuario?.user_id || null;
    if (usuario?.email) {
        try {
            const r = await fetch(`${API_URL}/perfil?email=${encodeURIComponent(usuario.email)}`);
            if (r.ok) {
                const u = await r.json();
                $('nomeUsuario').textContent  = u.nome  || SEM_DADO;
                $('emailUsuario').textContent = u.email || SEM_DADO;
                if (u.user_id) alunoId = u.user_id;
            }
        } catch (e) { console.warn('[KaIA] identidade do perfil:', e); }
    }

    // 2) Estatísticas (Etapa 4.1 C híbrida) do perfil EXIBIDO.
    await carregarEstatisticasPerfil(alunoId);
}

// Preenche "Seu desempenho" (base semanal), "Sua última sessão" (complemento ao
// vivo, com estado vazio) e a "Análise da KaIA" (frases reais vindas do backend).
async function carregarEstatisticasPerfil(alunoId) {
    if (!$('atencaoSemanal')) return;   // no-op fora do perfil
    if (!alunoId) return;               // sem identidade do perfil exibido, não busca

    let D = null;
    try {
        const r = await fetch(`${API_URL}/perfil/estatisticas?aluno_id=${encodeURIComponent(alunoId)}`);
        if (r.ok) D = await r.json();
    } catch (e) { console.warn('[KaIA] estatísticas do perfil:', e); }

    // --- BASE semanal (sempre visível) ---
    const d = D?.desempenho;
    if (d) {
        $('atencaoSemanal').textContent = `${d.atencao}%`;
        $('acertoSemanal').textContent  = `${d.acerto}%`;
        $('minSemana').textContent      = `${d.min_semana} min`;
        const sub = $('desempenhoSub');
        if (sub) sub.textContent = `Média de ${d.semanas} semanas · ${d.materias} matérias`;
    }

    // --- COMPLEMENTO: última sessão ou mensagem (nunca fileira de "—") ---
    const u = D?.ultima_sessao;
    const lista = $('ultimaSessaoLista');
    const vazia = $('ultimaSessaoVazia');
    if (u) {
        $('ultimaQuando').textContent     = u.quando ? `· ${u.quando}` : '';
        $('ultTempoResposta').textContent = `${(u.tempo_resposta_ms / 1000).toFixed(1).replace('.', ',')} s`;
        $('ultScroll').textContent        = `${Math.round(u.velocidade_scroll_px_s)} px/s`;
        $('ultAbas').textContent          = `${u.mudancas_aba}`;
        $('ultForaFoco').textContent      = `${Math.round(u.tempo_fora_foco_s)} s`;
        $('ultCliques').textContent       = `${u.cliques_fora_area_estudo}`;
        if (lista) lista.style.display = '';
        if (vazia) vazia.style.display = 'none';
    } else {
        $('ultimaQuando').textContent = '';
        if (lista) lista.style.display = 'none';
        if (vazia) vazia.style.display = '';
    }

    // --- ANÁLISE (frases reais por regras; sem placeholder) ---
    const box = $('analiseIA');
    if (box) {
        box.innerHTML = '';
        const frases = D?.analise || [];
        if (frases.length) {
            const ul = document.createElement('ul');
            frases.forEach(f => {
                const li = document.createElement('li');
                li.textContent = f;
                ul.appendChild(li);
            });
            box.appendChild(ul);
        } else {
            const p = document.createElement('p');
            p.textContent = 'Ainda não há dados suficientes para uma análise.';
            box.appendChild(p);
        }
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
        'Focado':'pi', 'Cansaço':'pe', 'Distraído Gradual':'pe', 'Distraído Imediato':'pf',
        // Estados preditos (dashboard sobre Supabase): verde/âmbar para engajado/distraído.
        'Engajado':'pi', 'Distraído':'pe', 'Muito distr.':'pf'
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
    if (D?.fonte === 'supabase') el.textContent = `SUPABASE · ${D.total_sessoes} SESSÕES · ${D.periodo}`;
    else if (D?.fonte === 'base_sintetica') el.textContent = `BASE SINTÉTICA · ${D.total_sessoes} SESSÕES · ${D.periodo}`;
    else if (D?.fonte === 'planilha_manual') el.textContent = 'PLANILHA MANUAL';
    else el.textContent = 'DADOS DE DEMONSTRAÇÃO';
}

// Aviso explícito de amostra pequena: com poucas sessões, médias e distribuições
// (ainda mais as predições do RF) não são estatisticamente confiáveis. Injeta uma
// faixa no topo do corpo do dashboard em vez de mostrar 3 pontos como se fosse tendência.
function _avisoAmostra(D) {
    if (!D || !D.amostra_pequena) return;
    const body = document.querySelector('.db-body');
    if (!body || $('db-amostra')) return;
    const n = D.total_sessoes ?? 0;
    const pred = D.sessoes_preditas;
    const faixa = document.createElement('div');
    faixa.id = 'db-amostra';
    faixa.className = 'db-amostra';
    faixa.textContent = `⚠ Amostra pequena: ${n} sessões`
        + (pred != null ? ` (${pred} com predição do modelo)` : '')
        + ' — médias e distribuições têm baixa confiança estatística.';
    body.prepend(faixa);
}

// Estado de acesso negado (403): o backend barrou por não ser admin.
function _dashboardNegado() {
    const shell = document.querySelector('.shell');
    if (shell) shell.innerHTML =
        '<div class="db-negado"><h1>Acesso restrito</h1>'
        + '<p>O dashboard interno é exclusivo da equipe (perfil admin).</p>'
        + '<a href="index.html">Voltar ao início</a></div>';
}

// ── GRÁFICOS (Chart.js) ──
function _buildCharts(D) {
    if (typeof Chart === 'undefined') return;
    const { azul: AZ, ouro: GR, verde: VD, bege: BE, vermelho: RE } = DASH_COR;
    // Cor do vão entre fatias = fundo do card (--card), NUNCA branco puro (regra fixa).
    const CARD = getComputedStyle(document.documentElement).getPropertyValue('--card').trim() || '#fbf6ec';

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
    new Chart($('c2'), { type:'doughnut', data:{ labels:lab(pl,'plano'), datasets:[{ data:col(pl,'percentual'), backgroundColor:[AZ,GR,VD,BE], borderWidth:3, borderColor:CARD, hoverOffset:6 }]}, options:rosca });

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
    new Chart($('c5'), { type:'doughnut', data:{ labels:lab(df,'faixa'), datasets:[{ data:col(df,'percentual'), backgroundColor:[VD,GR,RE], borderWidth:3, borderColor:CARD, hoverOffset:6 }]}, options:rosca });

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
    // 1) busca os dados reais (via backend); tolera falha → FALLBACK.
    // Manda a identidade que o front afirma (uuid do perfil) no header. É o que o
    // backend usa para checar perfis.role == 'admin' e responder 403 se não for.
    let D = {};
    try {
        const r = await fetch(`${API_URL}/dashboard/dados`, {
            headers: { 'X-Kaia-User': userId }
        });
        if (r.status === 403) { _dashboardNegado(); return; }
        if (r.ok) D = await r.json();
    } catch (e) {
        console.warn('[KaIA Dashboard] backend indisponível — usando dados demo:', e);
    }

    // 2) tabelas, listas e KPIs
    _renderFonte(D);
    _avisoAmostra(D);
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
// Textura de papel: aplica a preferência (localStorage) em TODA página. O toggle
// que grava a preferência vive nas Configurações do perfil. Desligada por padrão.
function aplicarTexturaPapel() {
    document.body.classList.toggle('textura-papel', localStorage.getItem('kaia_textura_papel') === '1');
}

document.addEventListener('DOMContentLoaded', () => {
    montarRail();
    aplicarTexturaPapel();
    registrarHobbies();
    registrarLuz();
    registrarSensores();
    carregarPerfil();
    if (document.body.classList.contains('dashboard-page')) iniciarDashboard();
    console.log('[KaIA] Página pronta. Session ID:', sessionId);
});
