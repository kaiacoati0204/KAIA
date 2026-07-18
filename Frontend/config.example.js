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
