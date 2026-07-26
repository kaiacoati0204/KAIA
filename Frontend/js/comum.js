// ============================================================
//  KaIA — comum.js: base compartilhada por TODAS as páginas
// ============================================================
// Carregado ANTES do script.js (e dos scripts de página) em todos os HTML, e
// DEPOIS do config.js (usa window.KAIA_CONFIG e window.supabaseClient).
const API_URL = window.KAIA_CONFIG?.API_URL || 'http://127.0.0.1:5000';

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
