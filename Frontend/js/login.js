// ============================================================
//  KaIA — login.js: login + cadastro (páginas login/cadastro)
// ============================================================
// Depende de comum.js (apiFetch, $, lerPerfil, gravarPerfil) e do config.js
// (window.supabaseClient), carregados ANTES deste arquivo.

// Botão "Entrar" do login.html.
// Autentica no Supabase Auth (email + senha) e, com o user.id do Auth, busca o
// perfil (nome/role/hobbies) no backend. O cadastro é feito manualmente no
// painel do Supabase — aqui o aluno só ENTRA.
const ROTA_POR_ROLE = {
    professor:   'responsaveis.html',
    coordenador: 'responsaveis.html',
    pai:         'responsaveis.html',
};

// Passos comuns ao login e ao cadastro: com o usuário já autenticado no Auth,
// busca o perfil no backend (por id; fallback por email), guarda a sessão do
// app e redireciona por role.
// `lembrar` (Fase 3): o padrão do app é sessionStorage — a identidade morre com
// a aba. Com "lembre de mim" existe TAMBÉM uma cópia em localStorage + a flag
// kaia_lembrar, que é o que restaurarSessao() lê ao voltar. Ver lerUsuario() no
// comum.js, que consulta os dois na ordem certa.
async function finalizarLogin(authUser, falhar, lembrar = false) {
    let r = await apiFetch(`/perfil?user_id=${encodeURIComponent(authUser.id)}`);
    if (r.status === 404 && authUser.email) {
        r = await apiFetch(`/perfil?email=${encodeURIComponent(authUser.email)}`);
    }
    if (!r.ok) return falhar('Login feito, mas seu perfil não foi encontrado. Fale com o suporte.');
    const u = await r.json();

    const usuario = JSON.stringify({
        user_id:   u.user_id,
        email:     u.email,
        nome:      u.nome,
        role:      u.role,
        escola_id: u.escola_id,
        turma_id:  u.turma_id,
    });
    sessionStorage.setItem('kaia_usuario', usuario);   // a aba atual sempre precisa
    if (lembrar) {
        localStorage.setItem('kaia_lembrar', '1');
        localStorage.setItem('kaia_usuario', usuario);
    } else {
        localStorage.removeItem('kaia_lembrar');
        localStorage.removeItem('kaia_usuario');       // limpa um "lembrar" anterior
    }
    // A identidade estável usada pelos sensores (sessions/events) é a do perfil real.
    localStorage.setItem('kaia_user_id', u.user_id);

    const hobbies = u.hobbies || [];
    sessionStorage.setItem('hobbies', JSON.stringify(hobbies));
    gravarPerfil({ ...lerPerfil(), email: u.email, hobbies });

    // A home de quem ENTROU é materias.html. O index.html virou a landing
    // pública (sem guarda de login): mandar o aluno recém-logado para lá seria
    // devolvê-lo à página de vendas em vez de abrir o produto.
    if (u.role === 'aluno') {
        window.location.href = hobbies.length ? 'materias.html' : 'hobbies.html';
    } else {
        window.location.href = ROTA_POR_ROLE[u.role] || 'materias.html';
    }
}

async function salvarLogin(event) {
    if (event) event.preventDefault();

    const email   = $('login-email')?.value.trim() || '';
    const senha   = $('login-senha')?.value || '';
    const lembrar = $('login-lembrar')?.checked || false;
    const erro    = $('login-erro');
    const falhar = (msg) => { if (erro) erro.textContent = msg; };

    falhar('');
    if (!email || !senha) return falhar('Preencha email e senha.');
    if (!window.supabaseClient) return falhar('Autenticação indisponível (config.js sem Supabase).');

    try {
        const { data, error } = await window.supabaseClient.auth
            .signInWithPassword({ email, password: senha });
        if (error) return falhar('Email ou senha incorretos');
        await finalizarLogin(data.user, falhar, lembrar);
    } catch (e) {
        console.error('[KaIA] falha no login:', e);
        falhar('Não foi possível conectar. Tente novamente.');
    }
}

// Cadastro (auto-signup do aluno). Cria a conta no Supabase Auth com o nome no
// metadata — o trigger no banco usa isso para preencher perfis.nome. Com a
// confirmação de email DESLIGADA, o signUp já devolve sessão e entra direto; se
// estiver LIGADA, avisa para confirmar por email antes de logar.
async function criarConta(event) {
    if (event) event.preventDefault();

    const nome  = $('cad-nome')?.value.trim() || '';
    const email = $('cad-email')?.value.trim() || '';
    const senha = $('cad-senha')?.value || '';
    const erro  = $('cad-erro');
    const okmsg = $('cad-ok');
    const falhar = (msg) => { if (erro) erro.textContent = msg; if (okmsg) okmsg.textContent = ''; };

    falhar('');
    if (!nome || !email || !senha) return falhar('Preencha nome, email e senha.');
    if (senha.length < 6) return falhar('A senha precisa ter ao menos 6 caracteres.');
    if (!window.supabaseClient) return falhar('Cadastro indisponível (config.js sem Supabase).');

    try {
        const { data, error } = await window.supabaseClient.auth.signUp({
            email, password: senha, options: { data: { nome } },
        });
        if (error) {
            const jaExiste = /registered|already/i.test(error.message || '');
            return falhar(jaExiste ? 'Este email já tem conta. Faça login.'
                                   : 'Não foi possível criar a conta. Tente outro email.');
        }
        if (data.session) {
            // Confirmação de email desligada → já entra. Sem "lembrar": o
            // cadastro não tem a caixa (fica no escopo do login, Fase 3).
            await finalizarLogin(data.user, falhar, false);
        } else if (okmsg) {
            // Confirmação ligada → precisa confirmar por email antes de logar.
            okmsg.textContent = 'Conta criada! Confirme pelo email e depois faça login.';
        }
    } catch (e) {
        console.error('[KaIA] falha no cadastro:', e);
        falhar('Não foi possível conectar. Tente novamente.');
    }
}

// ============================================================
//        "LEMBRE DE MIM" — restauração de sessão (Fase 3)
// ============================================================
// Roda ao abrir o login. O token do Supabase SEMPRE persistiu em localStorage
// (persistSession é o default do createClient) — o que faltava era o app
// reconhecer isso, porque a identidade (kaia_usuario) morria com a aba. São dois
// caminhos, e o segundo é o que dá sentido à caixa desmarcada:
//   com a flag  → refaz finalizarLogin a partir da sessão viva e entra direto;
//   sem a flag  → signOut(), derrubando token residual. Sem isso, "não lembrar"
//                 não significaria nada: a sessão do Supabase seguiria válida.
// Falha silenciosa de propósito: qualquer problema aqui só deixa o formulário
// normal na tela — nunca trava a entrada.
async function restaurarSessao() {
    const cliente = window.supabaseClient;
    if (!cliente) return;

    let sessao = null;
    try {
        sessao = (await cliente.auth.getSession())?.data?.session || null;
    } catch (_) { return; }
    if (!sessao) return;

    if (localStorage.getItem('kaia_lembrar') !== '1') {
        try { await cliente.auth.signOut(); } catch (_) {}
        localStorage.removeItem('kaia_usuario');
        return;
    }
    // Refaz o /perfil em vez de confiar na cópia local: nome/role/turma podem ter
    // mudado desde o último login. Se falhar, cai no formulário sem alarde.
    try {
        await finalizarLogin(sessao.user, () => {}, true);
    } catch (e) {
        console.warn('[KaIA] não deu para restaurar a sessão:', e);
    }
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
//        PRELOADER — garantia de saída
// ============================================================
// O visual (degradê + fades das saudações) é 100% CSS: #kaia-preloader no
// style.css. Este JS NÃO anima nada — ele só garante que o overlay saia, porque
// ele cobre o formulário e não pode prender o acesso em nenhum cenário: CSS que
// não carregou, animação que não rodou, aba aberta em segundo plano.
// Também deixa pular a abertura com um clique ou uma tecla — quem já viu não
// precisa esperar de novo.
// Acoplado ao CSS: precisa ficar DEPOIS do fim da animação (#kaia-preloader sai em
// 3,5s + 0,45s de fade = 3,95s). Se mudar o ritmo no style.css, ajuste aqui também.
const PRE_MS = 4250;

function registrarPreloader() {
    const pre = document.getElementById('kaia-preloader');
    if (!pre) return;   // páginas sem preloader: no-op

    const sair = () => { if (pre.parentNode) pre.remove(); };
    setTimeout(sair, PRE_MS);                                  // rede de segurança
    pre.addEventListener('click', sair);                       // pular clicando
    document.addEventListener('keydown', sair, { once: true }); // ou com qualquer tecla
}

document.addEventListener('DOMContentLoaded', () => {
    registrarLuz();
    registrarPreloader();
    // Só no login: o cadastro carrega este mesmo arquivo e não deve pular etapa.
    if ($('login-lembrar')) restaurarSessao();
});
