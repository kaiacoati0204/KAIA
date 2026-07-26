// ============================================================
//  KaIA — modelo de configuração do frontend
// ============================================================
// O config.js real NÃO vai para o git. Ao clonar o projeto:
//   1. copie este arquivo para config.js
//   2. preencha os valores (Supabase → Settings → API Keys)
//
// Use sempre a chave PUBLISHABLE (anon). NUNCA a service_role: ela ignora RLS.
const KAIA_CONFIG = {
    API_URL: 'http://127.0.0.1:5000',

    SUPABASE_URL: 'https://SEU-PROJETO.supabase.co',
    SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_...',
};

// Expõe para o script.js (que lê window.KAIA_CONFIG).
window.KAIA_CONFIG = KAIA_CONFIG;

// Cliente do Supabase Auth. Só é criado nas páginas que carregam o supabase-js
// via CDN (login/index/responsaveis) — nas demais fica null, sem quebrar nada.
window.supabaseClient = (typeof supabase !== 'undefined')
    ? supabase.createClient(KAIA_CONFIG.SUPABASE_URL, KAIA_CONFIG.SUPABASE_PUBLISHABLE_KEY)
    : null;
