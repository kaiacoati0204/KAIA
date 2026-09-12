// ============================================================
//  KaIA — login.js: login + cadastro (páginas login/cadastro)
// ============================================================
// Depende de comum.js (apiFetch, $, lerPerfil, gravarPerfil) e do config.js
// (window.supabaseClient), carregados ANTES deste arquivo.

// Destino pós-login por role (o aluno tem regra própria em finalizarLogin).
const ROTA_POR_ROLE = {
    professor:   'responsaveis.html',
    coordenador: 'responsaveis.html',
    pai:         'responsaveis.html',
};

// ---- Rede fora do ar NÃO é credencial errada -------------------------------
// signIn/signUp devolvem `error` pra qualquer falha; tratar tudo como senha errada esconde queda do Supabase.
//   rede ....... AuthRetryableFetchError · status 0   · "Failed to fetch"
//   credencial . AuthApiError            · status 400 · "Invalid login credentials"
function _authForaDoAr(error) {
    return error?.status === 0
        || error?.name === 'AuthRetryableFetchError'
        || /failed to fetch|networkerror|load failed/i.test(error?.message || '');
}
const MSG_AUTH_FORA = 'Não foi possível falar com o servidor de login. '
    + 'Verifique sua conexão — o Supabase '
    + 'pode estar pausado ou fora do ar.';

// Login e cadastro, já autenticados: busca o perfil (id; fallback email), guarda a sessão e redireciona por role.
// `lembrar` (Fase 3): o padrão é sessionStorage (morre com a aba); "lembre de mim" grava também cópia em
// localStorage + flag kaia_lembrar, lida por restaurarSessao(). lerUsuario() (comum.js) lê os dois na ordem certa.
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

// Botão "Entrar" do login.html: autentica no Supabase Auth e busca o perfil no backend.
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
        if (error) {
            if (_authForaDoAr(error)) {
                console.error('[KaIA] servidor de auth inacessível:', error);
                return falhar(MSG_AUTH_FORA);
            }
            return falhar('Email ou senha incorretos');
        }
        await finalizarLogin(data.user, falhar, lembrar);
    } catch (e) {
        console.error('[KaIA] falha no login:', e);
        falhar('Não foi possível conectar. Tente novamente.');
    }
}

// Cadastro (auto-signup do aluno): nome vai no metadata, que o trigger do banco usa para preencher perfis.nome.
// Confirmação de email DESLIGADA → signUp já devolve sessão e entra; LIGADA → avisa para confirmar antes.
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
    if (!$('cad-termos')?.checked) return falhar('É preciso aceitar os termos para criar a conta.');
    if (senha.length < 6) return falhar('A senha precisa ter ao menos 6 caracteres.');
    if (!window.supabaseClient) return falhar('Cadastro indisponível (config.js sem Supabase).');

    try {
        const { data, error } = await window.supabaseClient.auth.signUp({
            email, password: senha, options: { data: { nome } },
        });
        if (error) {
            if (_authForaDoAr(error)) {
                console.error('[KaIA] servidor de auth inacessível:', error);
                return falhar(MSG_AUTH_FORA);
            }
            const jaExiste = /registered|already/i.test(error.message || '');
            return falhar(jaExiste ? 'Este email já tem conta. Faça login.'
                                   : 'Não foi possível criar a conta. Tente outro email.');
        }
        if (data.session) {
            // Confirmação de email desligada → já entra. Sem "lembrar": o
            // cadastro não tem a caixa (fica no escopo do login, Fase 3).
            await finalizarLogin(data.user, falhar, false);
            // Registra o aceite (quem, quando, qual versão): público menor de idade + coleta de
            // comportamento, e isso não se reconstrói depois. O backend grava o PRIMEIRO e não sobrescreve.
            try {
                await postJSON('/perfil', { user_id: data.user.id, versao_termos: KAIA_VERSAO_TERMOS });
            } catch (e) {
                console.warn('[KaIA] aceite dos termos não registrado:', e);
            }
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
// Roda ao abrir o login. O token do Supabase sempre persiste em localStorage (persistSession default).
// Com a flag kaia_lembrar refaz finalizarLogin e entra direto; sem ela faz signOut() do token residual,
// senão "não lembrar" não significaria nada. Falha silenciosa de propósito: nunca trava a entrada.
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
//        OLHO DA SENHA — mostrar/ocultar
// ============================================================
// Visível SEMPRE que o campo tem texto (reavaliado a cada digitação/foco): o olho nativo do Edge
// some ao sair do campo e não volta, e quem errou a senha ficava sem ele. Serve login e cadastro.
function registrarOlhoSenha() {
    document.querySelectorAll('.campo-senha').forEach((campo) => {
        const input = campo.querySelector('input');
        const olho  = campo.querySelector('.olho-senha');
        if (!input || !olho) return;

        const mostrar = (visivel) => {
            input.type = visivel ? 'text' : 'password';
            olho.setAttribute('aria-pressed', String(visivel));
            olho.setAttribute('aria-label', visivel ? 'Ocultar senha' : 'Mostrar senha');
        };
        const sincronizar = () => {
            const temTexto = input.value.length > 0;
            olho.hidden = !temTexto;
            if (!temTexto) mostrar(false);   // apagou tudo: volta a ocultar
        };

        // Sem isto o clique tira o foco do campo antes de alternar, e o cursor
        // de quem está digitando pula para fora.
        olho.addEventListener('mousedown', (e) => e.preventDefault());
        olho.addEventListener('click', () => {
            mostrar(input.type === 'password');
            input.focus();
        });
        ['input', 'focus', 'change'].forEach((ev) => input.addEventListener(ev, sincronizar));
        sincronizar();
    });
}

// ============================================================
//        PRELOADER — garantia de saída
// ============================================================
// A animação é 100% CSS (#kaia-preloader no style.css); este JS só garante que o overlay saia, pois ele
// cobre o formulário (CSS que não carregou, aba em segundo plano), e deixa pular com clique ou tecla.
// Acoplado ao CSS: PRE_MS fica DEPOIS do fim (3,5s + 0,45s de fade = 3,95s). Mudou lá, ajuste aqui.
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
    registrarOlhoSenha();
    // Só no login: o cadastro carrega este mesmo arquivo e não deve pular etapa.
    if ($('login-lembrar')) restaurarSessao();
});
