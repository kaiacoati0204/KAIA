// ============================================================
//  Gera o Frontend/config.js a partir de variáveis de ambiente
// ============================================================
// O config.js não vai para o git (está no .gitignore), então o Render clona o
// repositório SEM ele — e sem ele o front quebra inteiro: API_URL cai no fallback
// 127.0.0.1:5000 (o PC do aluno) e window.supabaseClient fica null, matando o login
// nas 9 páginas. Este script é o build command do Static Site.
//
// Uso:
//   KAIA_API_URL=... KAIA_SUPABASE_URL=... KAIA_SUPABASE_ANON_KEY=... node Frontend/gerar-config.js
//
// Recusa rodar sem as três variáveis — assim um `node` sem querer na sua máquina
// não sobrescreve o config.js local de desenvolvimento.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const AQUI = path.dirname(fileURLToPath(import.meta.url));

const OBRIGATORIAS = ['KAIA_API_URL', 'KAIA_SUPABASE_URL', 'KAIA_SUPABASE_ANON_KEY'];
const faltando = OBRIGATORIAS.filter((v) => !process.env[v]);

if (faltando.length) {
    console.error('[KaIA] config.js NAO gerado — faltam variaveis: ' + faltando.join(', '));
    console.error('       No Render: Static Site -> Environment.');
    process.exit(1);
}

const { KAIA_API_URL, KAIA_SUPABASE_URL, KAIA_SUPABASE_ANON_KEY } = process.env;

// A anon key é pública por design (o RLS é quem protege) — pode ficar no browser.
const conteudo = `// GERADO NO BUILD por Frontend/gerar-config.js — nao edite a mao.
const KAIA_CONFIG = {
    API_URL: ${JSON.stringify(KAIA_API_URL.replace(/\/+$/, ''))},

    SUPABASE_URL: ${JSON.stringify(KAIA_SUPABASE_URL.replace(/\/+$/, ''))},
    SUPABASE_ANON_KEY: ${JSON.stringify(KAIA_SUPABASE_ANON_KEY)},
};

window.KAIA_CONFIG = KAIA_CONFIG;

window.supabaseClient = (typeof supabase !== 'undefined')
    ? supabase.createClient(KAIA_CONFIG.SUPABASE_URL, KAIA_CONFIG.SUPABASE_ANON_KEY)
    : null;
`;

const alvo = path.join(AQUI, 'config.js');
fs.writeFileSync(alvo, conteudo, 'utf8');
console.log('[KaIA] config.js gerado -> API_URL=' + KAIA_API_URL);
