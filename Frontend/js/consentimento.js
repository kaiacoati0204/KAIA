// ==== PÁGINA DO RESPONSÁVEL (LGPD art. 14) ====
// Aberta por link: consentimento.html?t=<token>. O token É a credencial — a página não
// exige login, porque quem autoriza é o responsável, que não tem conta na KaIA.

const TOKEN = new URLSearchParams(location.search).get('t') || '';

const mostrar = (id, visivel) => { const el = $(id); if (el) el.hidden = !visivel; };

function falharPagina(msg) {
    mostrar('cons-carregando', false);
    mostrar('cons-form', false);
    mostrar('cons-invalido', true);
    if (msg) $('cons-invalido-msg').textContent = msg;
}

// Máscara só visual: o backend valida os dígitos verificadores de verdade.
function formatarCpf(v) {
    const d = (v || '').replace(/\D/g, '').slice(0, 11);
    return d.replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d)/, '$1.$2')
            .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
}

async function carregar() {
    if (!TOKEN) return falharPagina('Este link está incompleto.');
    try {
        const r = await fetch(`${API_URL}/consentimento/${encodeURIComponent(TOKEN)}`);
        if (!r.ok) return falharPagina('Este link não é válido.');
        const d = await r.json();
        if (d.expirado) return falharPagina('Este link expirou.');
        if (d.status !== 'pendente') {
            return concluir(d.status === 'aprovado' ? 'aprovado' : 'recusado', true);
        }
        $('cons-aluno').textContent = d.aluno || 'O estudante';
        mostrar('cons-carregando', false);
        mostrar('cons-form', true);
    } catch (_) {
        falharPagina('Não foi possível conectar. Tente novamente mais tarde.');
    }
}

function concluir(status, jaEra) {
    mostrar('cons-carregando', false);
    mostrar('cons-form', false);
    mostrar('cons-pronto', true);
    const aprovado = status === 'aprovado';
    $('cons-pronto-titulo').textContent = aprovado ? 'Autorização registrada'
                                                   : 'Autorização não concedida';
    $('cons-pronto-msg').textContent = aprovado
        ? (jaEra ? 'Esta autorização já havia sido registrada. O estudante pode usar a plataforma.'
                 : 'Pronto! O estudante já pode usar a plataforma. Você pode retirar a autorização '
                   + 'a qualquer momento pelo e-mail privacidade@kaia.com.br.')
        : 'Nenhum dado de uso do estudante será coletado. Se mudar de ideia, peça um link novo a ele.';
}

async function responder(aceito) {
    const erro = $('cons-erro');
    erro.textContent = '';
    const corpo = { aceito };
    if (aceito) {
        if (!$('cons-declaro').checked) {
            erro.textContent = 'É preciso marcar a declaração para autorizar.';
            return;
        }
        corpo.responsavel_nome = $('cons-nome').value.trim();
        corpo.cpf = $('cons-cpf').value;
        corpo.parentesco = $('cons-parentesco').value;
    }
    try {
        const r = await fetch(`${API_URL}/consentimento/${encodeURIComponent(TOKEN)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(corpo),
        });
        const d = await r.json();
        if (!r.ok) { erro.textContent = d.erro || 'Não foi possível registrar.'; return; }
        concluir(d.status, false);
    } catch (_) {
        erro.textContent = 'Não foi possível conectar. Tente novamente.';
    }
}

$('cons-cpf')?.addEventListener('input', (e) => { e.target.value = formatarCpf(e.target.value); });
$('cons-form')?.addEventListener('submit', (e) => { e.preventDefault(); responder(true); });
$('cons-recusar')?.addEventListener('click', () => responder(false));
carregar();
