// ============================================================
//  KaIA — modelo de configuração do frontend
// ============================================================
// O config.js real NÃO vai para o git. Ao clonar o projeto:
//   1. copie este arquivo para config.js
//   2. preencha os valores (Supabase → Settings → API)
//
// CHAVE: use a chave ANON no formato JWT (começa com "eyJ...", role=anon).
//   - NÃO use a "publishable" (sb_publishable_...): o supabase-js carregado via
//     CDN NÃO a envia como apikey, e o login quebra com 400 "No API key found".
//   - NÃO use a service_role: é segredo (ignora RLS) e nunca vai no frontend.
//   - No painel: Settings → API → chave "anon"/"public" (pode estar em
//     "Legacy API keys" se o projeto só mostrar as chaves novas por padrão).
const KAIA_CONFIG = {
    API_URL: 'http://127.0.0.1:5000',

    SUPABASE_URL: 'https://SEU-PROJETO.supabase.co',
    SUPABASE_ANON_KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.COLE_AQUI_A_CHAVE_ANON',
};

// Expõe para o script.js (que lê window.KAIA_CONFIG).
window.KAIA_CONFIG = KAIA_CONFIG;

// Cliente do Supabase Auth. Só é criado nas páginas que carregam o supabase-js
// via CDN (login/index/responsaveis) — nas demais fica null, sem quebrar nada.
window.supabaseClient = (typeof supabase !== 'undefined')
    ? supabase.createClient(KAIA_CONFIG.SUPABASE_URL, KAIA_CONFIG.SUPABASE_ANON_KEY)
    : null;
