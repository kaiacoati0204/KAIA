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
async function finalizarLogin(authUser, falhar) {
    let r = await apiFetch(`/perfil?user_id=${encodeURIComponent(authUser.id)}`);
    if (r.status === 404 && authUser.email) {
        r = await apiFetch(`/perfil?email=${encodeURIComponent(authUser.email)}`);
    }
    if (!r.ok) return falhar('Login feito, mas seu perfil não foi encontrado. Fale com o suporte.');
    const u = await r.json();

    sessionStorage.setItem('kaia_usuario', JSON.stringify({
        user_id:   u.user_id,
        email:     u.email,
        nome:      u.nome,
        role:      u.role,
        escola_id: u.escola_id,
        turma_id:  u.turma_id,
    }));
    // A identidade estável usada pelos sensores (sessions/events) é a do perfil real.
    localStorage.setItem('kaia_user_id', u.user_id);

    const hobbies = u.hobbies || [];
    sessionStorage.setItem('hobbies', JSON.stringify(hobbies));
    gravarPerfil({ ...lerPerfil(), email: u.email, hobbies });

    if (u.role === 'aluno') {
        window.location.href = hobbies.length ? 'index.html' : 'hobbies.html';
    } else {
        window.location.href = ROTA_POR_ROLE[u.role] || 'index.html';
    }
}

async function salvarLogin(event) {
    if (event) event.preventDefault();

    const email = $('login-email')?.value.trim() || '';
    const senha = $('login-senha')?.value || '';
    const erro  = $('login-erro');
    const falhar = (msg) => { if (erro) erro.textContent = msg; };

    falhar('');
    if (!email || !senha) return falhar('Preencha email e senha.');
    if (!window.supabaseClient) return falhar('Autenticação indisponível (config.js sem Supabase).');

    try {
        const { data, error } = await window.supabaseClient.auth
            .signInWithPassword({ email, password: senha });
        if (error) return falhar('Email ou senha incorretos');
        await finalizarLogin(data.user, falhar);
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
            // Confirmação de email desligada → já entra.
            await finalizarLogin(data.user, falhar);
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

document.addEventListener('DOMContentLoaded', registrarLuz);
