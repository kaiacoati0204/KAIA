// ============================================================
//  KaIA — modelo de configuração do frontend
// ============================================================
// O config.js real NÃO vai para o git. Ao clonar o projeto:
//   1. copie este arquivo para config.js
//   2. preencha os valores (Supabase → Settings → API)
//
// CHAVE: use a PUBLISHABLE (sb_publishable_...) — Settings → API Keys.
//   - É pública por design (o RLS protege os dados); pode ficar no browser.
//   - Testado: o supabase-js @2 (via CDN) a envia como apikey e o login funciona
//     (POST /auth/v1/token → 200). Se algum dia der 400 "No API key found",
//     confira se o supabase-js do CDN está no @2 (versões antigas não tratam o
//     formato novo sb_publishable_).
//   - NÃO use a service_role: é segredo (ignora RLS) e nunca vai no frontend.
const KAIA_CONFIG = {
    API_URL: 'http://127.0.0.1:5000',

    SUPABASE_URL: 'https://SEU-PROJETO.supabase.co',
    SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_COLE_AQUI',
};

// Expõe para os módulos do front (que leem window.KAIA_CONFIG).
window.KAIA_CONFIG = KAIA_CONFIG;

// Cliente do Supabase Auth. Só é criado nas páginas que carregam o supabase-js
// via CDN (login/index/responsaveis) — nas demais fica null, sem quebrar nada.
window.supabaseClient = (typeof supabase !== 'undefined')
    ? supabase.createClient(KAIA_CONFIG.SUPABASE_URL, KAIA_CONFIG.SUPABASE_PUBLISHABLE_KEY)
    : null;
