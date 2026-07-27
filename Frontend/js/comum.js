// ============================================================
//  KaIA — comum.js: base compartilhada por TODAS as páginas
// ============================================================
// Carregado ANTES do script.js (e dos scripts de página) em todos os HTML, e
// DEPOIS do config.js (usa window.KAIA_CONFIG e window.supabaseClient).
const API_URL = window.KAIA_CONFIG?.API_URL || 'http://127.0.0.1:5000';

// ============================================================
//   BETA: gestão desligada (Acompanhar / Dashboard)
// ============================================================
// Durante o beta, os painéis de professor/responsável (responsaveis.html) e de
// admin (dashboard.html) ficam SEM entrada na rail e SEM acesso por URL — para
// TODOS, inclusive admin. Páginas e backend seguem intactos.
// PARA REATIVAR: troque para false (volta o link na rail e o acesso).
const BETA_SEM_GESTAO = true;
const PAGINAS_GESTAO  = ['responsaveis.html', 'dashboard.html'];

if (BETA_SEM_GESTAO) {
    const _pg = location.pathname.split('/').pop() || 'index.html';
    if (PAGINAS_GESTAO.includes(_pg)) location.replace('index.html');   // digitar a URL não entra
}

// --- Atalhos de DOM ---------------------------------------------------------
const $  = (id) => document.getElementById(id);
const $$ = (sel, raiz = document) => Array.from(raiz.querySelectorAll(sel));

// Helper CENTRAL de chamada ao backend: anexa o JWT do Supabase
// (Authorization: Bearer <token>) automaticamente em toda requisição. Sem
// sessão/token, segue sem o header — a rota do backend decide (401 se exigir).
async function apiFetch(rota, options = {}) {
    const headers = { ...(options.headers || {}) };
    try {
        const sess = await window.supabaseClient?.auth.getSession();
        const token = sess?.data?.session?.access_token;
        if (token) headers['Authorization'] = `Bearer ${token}`;
    } catch (_) { /* sem token → segue sem ele */ }
    return fetch(`${API_URL}${rota}`, { ...options, headers });
}

// POST em JSON, já com o token anexado. Quem chama decide se trata o erro.
async function postJSON(rota, corpo, keepalive = false) {
    const r = await apiFetch(rota, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
        keepalive,
    });
    return r.json();
}

// --- Identidade estável do aluno (localStorage, até o Supabase Auth) --------
let userId = localStorage.getItem('kaia_user_id');
if (!userId) {
    userId = crypto.randomUUID();
    localStorage.setItem('kaia_user_id', userId);
}

// --- Acessores do perfil local (localStorage 'kaia_perfil') -----------------
const lerPerfil    = () => JSON.parse(localStorage.getItem('kaia_perfil') || '{}');
const gravarPerfil = (p) => localStorage.setItem('kaia_perfil', JSON.stringify(p));

// Hobbies selecionados (sessionStorage 'hobbies'): a página de hobbies grava, e
// matérias/perfil leem para mandar ao backend (alimentam o prompt da IA).
const lerHobbies = () => JSON.parse(sessionStorage.getItem('hobbies') || '[]');

// ============================================================
//                    NAVEGAÇÃO (rail)
// ============================================================
// MENU_LINKS alimenta a barra lateral estática (montarRail) — fica aqui para
// o markup do menu não ser copiado (e divergir) em cada HTML.
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

    const links = MENU_LINKS
        .filter(([href]) => !(BETA_SEM_GESTAO && PAGINAS_GESTAO.includes(href)))
        .map(([href, rotulo]) => {
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

    // Sair: encerra a sessão do Supabase Auth, limpa o sessionStorage e volta ao
    // login. O signOut é best-effort (não trava o logout se o cliente faltar).
    rail.querySelector('.rail-sair').addEventListener('click', async () => {
        try { await window.supabaseClient?.auth.signOut(); } catch (_) {}
        sessionStorage.clear();
        window.location.href = 'login.html';
    });
}

// ============================================================
//        CAMADA DE DADOS — PERFIL + FEATURES (Supabase-ready)
// ============================================================
// Persistido em localStorage sob 'kaia_perfil' e espelhado no backend (/perfil).
// Para plugar o Supabase, basta trocar `enviarPerfil` por um upsert em `perfis`.

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
        // minutos desde a última sessão registrada
        duracao_pausa_anterior_min: perfil.ultima_sessao_ts
            ? parseFloat(((agora - perfil.ultima_sessao_ts) / 60000).toFixed(2)) : null
    };
}

// Chamado quando uma sessão de ESTUDO começa. Atualiza só o bookkeeping da sessão
// (sessões no dia + timestamp). A STREAK não é mais tocada aqui — ela conta um dia
// só quando a meta diária é atingida (ver registrarMetaDiaria).
function registrarInicioSessao() {
    const agora   = new Date();
    const perfil  = lerPerfil();
    const hojeStr = agora.toISOString().slice(0, 10);

    perfil.sessoes_no_dia = (perfil.ultimo_dia_sessao === hojeStr)
        ? (perfil.sessoes_no_dia || 0) + 1 : 1;
    perfil.ultimo_dia_sessao = hojeStr;
    perfil.ultima_sessao_ts  = agora.getTime();
    gravarPerfil(perfil);
    return snapshotFeatures();
}

// Conta UM dia na streak — só quando a meta diária é atingida (não ao abrir a
// sessão). Idempotente no dia: chamar de novo hoje não incrementa. Devolve a streak.
function registrarMetaDiaria() {
    const agora   = new Date();
    const perfil  = lerPerfil();
    const hojeStr = agora.toISOString().slice(0, 10);
    if (perfil.ultimo_dia_estudo === hojeStr) return perfil.sequencia_dias_estudo || 0;   // já contou hoje

    const ontem = new Date(agora);
    ontem.setDate(ontem.getDate() - 1);
    // manteve o hábito se bateu a meta ontem; senão recomeça em 1
    perfil.sequencia_dias_estudo = (perfil.ultimo_dia_estudo === ontem.toISOString().slice(0, 10))
        ? (perfil.sequencia_dias_estudo || 0) + 1 : 1;
    perfil.ultimo_dia_estudo = hojeStr;
    gravarPerfil(perfil);
    return perfil.sequencia_dias_estudo;
}


// Envia o pacote completo (login + hobbies + features) para o backend.
// Lê session_id/hobbies do sessionStorage (não de globais de página) para ser
// autocontido no comum.js — mesmo valor que os globais sessionId/hobbiesSelecionados.
function enviarPerfil(extra = {}) {
    return postJSON('/perfil', {
        session_id: sessionStorage.getItem('kaia_session_id') || null,
        user_id:    userId,
        ts:         new Date().toISOString(),
        perfil:     lerPerfil(),
        hobbies:    lerHobbies(),
        features:   snapshotFeatures(),
        ...extra
    }, true).catch(e => console.warn('[KaIA] /perfil indisponível (salvo só localmente):', e));
}

// ============================================================
//                    INIT COMPARTILHADO
// ============================================================
// Textura de papel: aplica a preferência (localStorage) em TODA página. O toggle
// que grava a preferência vive nas Configurações do perfil. Desligada por padrão.
function aplicarTexturaPapel() {
    document.body.classList.toggle('textura-papel', localStorage.getItem('kaia_textura_papel') === '1');
}

// Roda em toda página (comum.js é carregado em todas). Ambas se auto-protegem:
// sem <body data-rail> a rail é no-op — seguro em login/cadastro.
document.addEventListener('DOMContentLoaded', () => {
    montarRail();
    aplicarTexturaPapel();
});
