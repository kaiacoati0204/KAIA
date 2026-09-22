// ============================================================
//  KaIA — comum.js: base compartilhada por TODAS as páginas
// ============================================================
// Carregado ANTES dos scripts de página em todos os HTML, e
// DEPOIS do config.js (usa window.KAIA_CONFIG e window.supabaseClient).
const API_URL = window.KAIA_CONFIG?.API_URL || 'http://127.0.0.1:5000';

// ============================================================
//   WARM-UP DO BACKEND
// ============================================================
// No plano grátis do Render o backend hiberna após 15 min sem requisição e leva ~50s para voltar;
// carregar a página estática não o acorda. Sem isto a espera cairia no clique em Entrar (/perfil);
// aqui ele acorda enquanto o aluno digita. Dispara e esquece: sem await, erro engolido.
function acordarBackend() {
    try {
        fetch(`${API_URL}/`, { method: 'GET', cache: 'no-store' }).catch(() => {});
    } catch (_) { /* nunca deve atrapalhar o carregamento da página */ }
}
acordarBackend();

// ============================================================
//   BETA: gestão desligada (Dashboard)
// ============================================================
// No beta o dashboard.html fica sem link na rail e sem acesso por URL para TODOS, inclusive admin
// (página e backend intactos). PARA REATIVAR: troque para false.
// responsaveis.html saiu desta lista na Fase 4: agora é liberada por ROLE (ROLES_RESPONSAVEL abaixo).
const BETA_SEM_GESTAO = true;
const PAGINAS_GESTAO  = ['dashboard.html'];

if (BETA_SEM_GESTAO) {
    const _pg = location.pathname.split('/').pop() || 'index.html';
    if (PAGINAS_GESTAO.includes(_pg)) location.replace('materias.html');   // digitar a URL não entra
}

// Quem enxerga o painel "Acompanhar" (responsaveis.html). A guarda de rota da
// própria página repete esta lista INLINE no <head> — ela precisa rodar antes de
// qualquer render, e o comum.js só carrega no fim do <body>. Mudou aqui, mude lá.
const ROLES_RESPONSAVEL = ['professor', 'coordenador', 'pai'];
const ehResponsavel = (u) => ROLES_RESPONSAVEL.includes((u?.role || '').toLowerCase());

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

// Versão do front. SOBE a cada mudança que afete o comportamento medido — é o que
// separa "antes" e "depois" nas análises do beta. Sem ela toda sessão ficava com o
// mesmo rótulo e nenhuma correção era avaliável depois.
const KAIA_VERSAO = 'beta-1.0.0';

// Versão dos termos/privacidade em vigor. SOBE sempre que o texto mudar — é o que
// diz, depois, a QUAL texto cada aluno consentiu.
const KAIA_VERSAO_TERMOS = '2026-09-15';

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

// ============================================================
//  PERSONALIZAÇÃO DE COR + TEXTURA POR MATÉRIA (perfil e matérias)
// ============================================================
// Mora aqui porque DOIS lados usam: o perfil (onde o aluno escolhe) e a tela de
// matérias (que só reflete na faixa do card). Duplicar levaria os dois a divergir.

// Espelha o dict MATERIAS do backend. O front guarda o CÓDIGO ("MAT") nos onclick e
// no session_start, mas a chave da personalização é o NOME ("Matemática") — que é o
// que /perfil/estatisticas devolve em por_materia. Este mapa é a ponte entre os dois.
const MATERIAS_NOMES = {
    MAT: 'Matemática', PORT: 'Português', HIS: 'História',
    GEO: 'Geografia', BIO: 'Biologia', FIS: 'Física',
    QUI: 'Química', FIL: 'Filosofia', SOC: 'Sociologia',
};
const nomeMateria = cod => MATERIAS_NOMES[cod] || cod;

// Mock em localStorage, por aluno. Enquanto não há rota no backend, a escolha vive
// no dispositivo — some se o aluno trocar de máquina.
const CHAVE_CORES = `kaia_cores_materia:${userId}`;

function lerCores() {
    try { return JSON.parse(localStorage.getItem(CHAVE_CORES) || '{}'); }
    catch (_) { return {}; }
}
function gravarCores(mapa) {
    try { localStorage.setItem(CHAVE_CORES, JSON.stringify(mapa)); }
    catch (e) { console.warn('[KaIA] não deu para salvar a cor da matéria:', e); }
}

// ---- TEXTURAS ----
// Tinta translúcida fixa em vez de uma cor derivada da escolhida: o padrão precisa
// aparecer sobre QUALQUER cor que o aluno pegue no seletor, inclusive as escuras.
const TEXTURA_TINTA = 'rgba(43,42,38,0.42)';

// Cada tile é desenhado uma vez e serve aos dois destinos (o <pattern> do gauge no
// perfil e o background das faixas). Os pontos de entrada e saída de cada desenho
// batem com as bordas do tile — é o que faz o padrão emendar sem costura visível.
const TEXTURAS = [
    { id: 'lisa', nome: 'Lisa (só cor)', w: 8, h: 8, tile: () => '' },
    { id: 'listras', nome: 'Listras diagonais', w: 8, h: 8,
      tile: t => `<path d="M-2 2L2 -2M0 8L8 0M6 10L10 6" stroke="${t}" stroke-width="2.6" fill="none"/>` },
    { id: 'pontos', nome: 'Pontos', w: 7, h: 7,
      tile: t => `<circle cx="3.5" cy="3.5" r="1.7" fill="${t}"/>` },
    { id: 'xadrez', nome: 'Xadrez', w: 8, h: 8,
      tile: t => `<rect width="4" height="4" fill="${t}"/><rect x="4" y="4" width="4" height="4" fill="${t}"/>` },
    { id: 'linhas', nome: 'Linhas horizontais', w: 6, h: 6,
      tile: t => `<rect width="6" height="2.6" fill="${t}"/>` },
    { id: 'grade', nome: 'Grade', w: 8, h: 8,
      tile: t => `<rect width="8" height="1.7" fill="${t}"/><rect width="1.7" height="8" fill="${t}"/>` },
    { id: 'ziguezague', nome: 'Ziguezague', w: 8, h: 8,
      tile: t => `<path d="M0 6L4 2L8 6" stroke="${t}" stroke-width="2.1" fill="none"/>` },
    { id: 'ondas', nome: 'Ondas', w: 8, h: 8,
      tile: t => `<path d="M0 5q2 -3.6 4 0t4 0" stroke="${t}" stroke-width="2" fill="none"/>` },
    { id: 'triangulos', nome: 'Triângulos', w: 10, h: 10,
      tile: t => `<path d="M5 1.5L9 8.5H1Z" fill="${t}"/>` },
];
const acharTextura = id => TEXTURAS.find(t => t.id === id) || TEXTURAS[0];

// Tile como <svg> inteiro -> vira background-image de um elemento HTML (as faixas).
function texturaDataUri(id, tinta = TEXTURA_TINTA) {
    const t = acharTextura(id);
    if (!t.tile(tinta)) return '';
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${t.w}" height="${t.h}" `
              + `viewBox="0 0 ${t.w} ${t.h}">${t.tile(tinta)}</svg>`;
    return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
}

// Pinta cor + textura numa faixa já existente. `escolha` é o {cor, textura} salvo;
// sem escolha a faixa some — nunca inventa uma cor que o aluno não pediu.
function pintarFaixa(faixa, escolha) {
    if (!faixa) return false;
    if (!escolha?.cor) {
        faixa.hidden = true;
        faixa.style.backgroundColor = '';
        faixa.style.backgroundImage = '';
        return false;
    }
    faixa.hidden = false;
    // backgroundColor + backgroundImage separados: o atalho `background` zeraria a
    // imagem que acabou de ser posta.
    faixa.style.backgroundColor = escolha.cor;
    faixa.style.backgroundImage = texturaDataUri(escolha.textura || 'lisa');
    return true;
}

// Hobbies selecionados (sessionStorage 'hobbies'): a página de hobbies grava, e
// matérias/perfil leem para mandar ao backend (alimentam o prompt da IA).
const lerHobbies = () => JSON.parse(sessionStorage.getItem('hobbies') || '[]');

// Usuário logado: sessionStorage (morre com a aba) primeiro, por ser a mais fresca; o fallback na cópia
// do "lembre de mim" (Fase 3) em localStorage faz uma aba nova reconhecer quem está logado.
const lerUsuario = () => JSON.parse(
    sessionStorage.getItem('kaia_usuario') || localStorage.getItem('kaia_usuario') || 'null'
);

// ============================================================
//                    NAVEGAÇÃO (rail)
// ============================================================
// MENU_LINKS alimenta a barra lateral estática (montarRail) — fica aqui para
// o markup do menu não ser copiado (e divergir) em cada HTML.
// Sem "Início": o index.html virou landing pública e jogava o aluno pra fora; Matérias é a home.
const MENU_LINKS = [
    ['materias.html',     'Matérias'],
    ['perfil.html',       'Perfil'],
    ['meu-coati.html',    'Meu Coati'],
    ['responsaveis.html', 'Acompanhar'],
    ['escola.html',       'Turmas'],
    ['dashboard.html',    'Dashboard'],
];

// ============================================================
//              BARRA LATERAL ESTÁTICA (rail)
// ============================================================
// Injetada nas páginas com <body data-rail>. Começa estreita (só ícones) e
// expande ao clicar no ícone de menu (classe rail-aberta no body). É uma COLUNA
// real do layout (o body vira flex): empurra o conteúdo em vez de sobrepor.
const RAIL_ICONES = {
    menu:                '<svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>',
    'login.html':        '<svg viewBox="0 0 24 24"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>',
    'perfil.html':       '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg>',
    'materias.html':     '<svg viewBox="0 0 24 24"><path d="M4 4h13a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4z"/><path d="M4 4v14"/></svg>',
    'meu-coati.html':    '<svg viewBox="0 0 24 24"><path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="M3 7l9 5 9-5"/><path d="M12 12v10"/></svg>',
    'responsaveis.html': '<svg viewBox="0 0 24 24"><line x1="6" y1="20" x2="6" y2="12"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="18" y1="20" x2="18" y2="14"/></svg>',
    'escola.html':       '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.5 3-5.5 6.5-5.5s6.5 2 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18.5 14.8c2 .7 3 2.5 3 5.2"/></svg>',
    'dashboard.html':    '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    sair:                '<svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>',
};

function montarRail() {
    if (!document.body.hasAttribute('data-rail')) return;
    const atual = location.pathname.split('/').pop() || 'index.html';

    const item = (ic, tx) => `<span class="rail-ic">${ic}</span><span class="rail-tx">${tx}</span>`;

    const u = lerUsuario();
    const links = MENU_LINKS
        .filter(([href]) => !(BETA_SEM_GESTAO && PAGINAS_GESTAO.includes(href)))
        // "Acompanhar" só para quem tem painel. Sem isto o aluno veria um link que
        // a guarda de rota rejeita — pior que não mostrar.
        .filter(([href]) => href !== 'responsaveis.html' || ehResponsavel(u))
        // "Turmas" só para coordenador: mostra dados de vários alunos (mesma regra da guarda da escola.html).
        .filter(([href]) => href !== 'escola.html' || (u?.role || '').toLowerCase() === 'coordenador')
        .map(([href, rotulo]) => {
            const ativo = href === atual ? ' ativo' : '';
            return `<a href="${href}" class="rail-item${ativo}">${item(RAIL_ICONES[href] || '', rotulo)}</a>`;
        }).join('');

    // Rodapé da rail: identidade do usuário + Sair, separados dos links de nav.
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

    // Sair: signOut best-effort, limpa sessionStorage e derruba TAMBÉM o "lembre de mim" (Fase 3),
    // senão o próximo a abrir o navegador entraria na conta de quem saiu.
    rail.querySelector('.rail-sair').addEventListener('click', async () => {
        try { await window.supabaseClient?.auth.signOut(); } catch (_) {}
        localStorage.removeItem('kaia_lembrar');
        localStorage.removeItem('kaia_usuario');
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
// DOCK NA RAIL — barra q aumenta perto do cursor
// ============================================================
// JS puro (não o componente React original) pra não reconstruir a rail toda;
// muda width/height do svg em vez de scale() pra não embaçar o ícone.
const DOCK_RAIO      = 92;    // px de alcance no eixo Y (a rail é vertical, não horizontal)
const DOCK_AMP       = 0.34;  // crescimento máximo, no centro (1.34x)
const DOCK_DESLOC    = 10;    // px de deslocamento para a direita, no centro
const DOCK_ICONE_PX  = 20;    // tamanho base do svg — igual ao .rail-ic svg do style.css

function ativarDockRail() {
    try {
        const rail = document.querySelector('.railnav');
        if (!rail) return;   // login/cadastro não têm rail
        // Público TEA/TDAH: quem pediu menos movimento não recebe movimento ambiente.
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

        const icones = () => rail.querySelectorAll('.rail-item .rail-ic');
        let frame   = 0;
        let cursorY = 0;

        const aplicar = () => {
            frame = 0;
            icones().forEach((ic) => {
                const r = ic.getBoundingClientRect();
                const dist = Math.abs(cursorY - (r.top + r.height / 2));
                const f = Math.max(0, 1 - dist / DOCK_RAIO);
                const suave = f * f * (3 - 2 * f);   // smoothstep: curva em S, sem degrau

                // Desloca para a direita (afasta da borda da rail, como a dock que
                // "salta"). translate NÃO desfoca — só reposiciona.
                ic.style.transform = `translateX(${(DOCK_DESLOC * suave).toFixed(2)}px)`;

                // Tamanho via width/height, não scale() (ver topo da seção).
                const svg = ic.querySelector('svg');
                if (svg) {
                    const px = (DOCK_ICONE_PX * (1 + DOCK_AMP * suave)).toFixed(2);
                    svg.style.width  = `${px}px`;
                    svg.style.height = `${px}px`;
                }
            });
        };

        rail.addEventListener('mousemove', (e) => {
            cursorY = e.clientY;
            if (!frame) frame = requestAnimationFrame(aplicar);   // no máximo 1 cálculo por frame
        });

        rail.addEventListener('mouseleave', () => {
            cancelAnimationFrame(frame);
            frame = 0;
            icones().forEach((ic) => {
                ic.style.transform = '';
                const svg = ic.querySelector('svg');
                if (svg) { svg.style.width = ''; svg.style.height = ''; }   // volta ao CSS
            });
        });
    } catch (e) {
        // Nunca deixa o efeito derrubar o init: a barra segue funcionando sem ele.
        console.warn('[KaIA] dock da rail não ativou:', e);
    }
}

// Textura de papel: aplica a preferência (localStorage) em TODA página. O toggle
// que grava a preferência vive nas Configurações do perfil. Desligada por padrão.
function aplicarTexturaPapel() {
    document.body.classList.toggle('textura-papel', localStorage.getItem('kaia_textura_papel') === '1');
}

// Roda em toda página (comum.js é carregado em todas). Ambas se auto-protegem:
// sem <body data-rail> a rail é no-op — seguro em login/cadastro.
document.addEventListener('DOMContentLoaded', () => {
    montarRail();
    ativarDockRail();      // só efeito visual, depois da rail montada; se falhar, avisa e segue
    aplicarTexturaPapel();
});
