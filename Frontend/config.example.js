// ============================================================
//  KaIA — modelo de configuração do frontend
// ============================================================
// O config.js real NÃO vai para o git. Ao clonar o projeto:
//   1. copie este arquivo para config.js
//   2. preencha os valores (Supabase → Settings → API)
//
// CHAVE: use a ANON (JWT, começa com eyJ...) — Settings → API → Project API keys → anon public.
//   - É pública por design (o RLS protege os dados); pode ficar no browser.
//   - NÃO use a sb_publishable_...: o supabase-js @2 carregado via CDN NÃO a envia
//     como apikey, e o login quebra com 400 "No API key found" (já testado a duras penas).
//   - NÃO use a service_role: é segredo (ignora RLS) e nunca vai no frontend.
const KAIA_CONFIG = {
    API_URL: 'http://127.0.0.1:5000',

    SUPABASE_URL: 'https://SEU-PROJETO.supabase.co',
    SUPABASE_ANON_KEY: 'eyJ...COLE_AQUI',
};

// Expõe para os módulos do front (que leem window.KAIA_CONFIG).
window.KAIA_CONFIG = KAIA_CONFIG;

// Cliente do Supabase Auth. Só é criado nas páginas que carregam o supabase-js
// via CDN (login/index/responsaveis) — nas demais fica null, sem quebrar nada.
window.supabaseClient = (typeof supabase !== 'undefined')
    ? supabase.createClient(KAIA_CONFIG.SUPABASE_URL, KAIA_CONFIG.SUPABASE_ANON_KEY)
    : null;
