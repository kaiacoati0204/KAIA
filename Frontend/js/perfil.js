// ============================================================
//  KaIA — perfil.js: página do Perfil (o aluno vendo a própria evolução)
// ============================================================
// Depende de comum.js ($, apiFetch), carregado antes. Só perfil.html usa.

async function carregarPerfil() {
    if (!$('nomeUsuario')) return;

    const SEM_DADO = '—';
    const usuario = lerUsuario();

    // 1) Identidade: parte do sessionStorage (login, por aba) e confirma via /perfil.
    $('nomeUsuario').textContent  = usuario?.nome || usuario?.email || SEM_DADO;
    $('emailUsuario').textContent = usuario?.email || SEM_DADO;

    // user_id do perfil EXIBIDO. NÃO usar localStorage.kaia_user_id: ele é
    // compartilhado entre abas (o último login sobrescreve para todas), então
    // discordaria da identidade desta aba. sessionStorage é por aba; o /perfil
    // é a fonte autoritativa.
    // lerUsuario() preserva essa regra: a sessionStorage continua tendo
    // prioridade, e a cópia do "lembre de mim" só entra quando a aba não tem
    // identidade nenhuma (aí ela é a única resposta possível, melhor que "—").
    // O ?email= saiu: o backend NUNCA leu esse parâmetro. O GET /perfil tira a
    // identidade do TOKEN (sub, com o e-mail como fallback) justamente para que
    // ninguém leia o perfil alheio trocando a query string. Mandá-lo sugeria o
    // contrário de como a rota funciona.
    try {
        const r = await apiFetch('/perfil');
        if (r.ok) {
            const u = await r.json();
            $('nomeUsuario').textContent  = u.nome  || SEM_DADO;
            $('emailUsuario').textContent = u.email || SEM_DADO;
            mostrarHobbies(u.hobbies);
        }
    } catch (e) { console.warn('[KaIA] identidade do perfil:', e); }

    // 2) Estatísticas (Etapa 4.1 C híbrida).
    await carregarEstatisticasPerfil();
}

// Hobbies do aluno — o dado sempre veio no /perfil e era descartado aqui.
// Sem hobbies (conta nova que pulou o onboarding) o bloco simplesmente não
// aparece: um "—" ali não informaria nada.
function mostrarHobbies(hobbies) {
    const caixa = $('hobbiesUsuario');
    if (!caixa) return;
    caixa.replaceChildren();
    (hobbies || []).forEach(h => {
        const tag = document.createElement('span');
        tag.className = 'perfil-tag';
        tag.textContent = h;
        caixa.appendChild(tag);
    });
}

// "1 semanas · 1 matérias" era o texto de quem acabou de começar — ou seja, de
// todo aluno no primeiro dia de beta. Concorda o número com a palavra.
const pluralizar = (n, singular, plural) => `${n} ${n === 1 ? singular : plural}`;

// Preenche "Seu desempenho" (base semanal), "Sua última sessão" (complemento ao
// vivo, com estado vazio) e a "Análise da KaIA" (frases reais vindas do backend).
async function carregarEstatisticasPerfil() {
    const SEM_DADO = '—';
    if (!$('minutosTotais')) return;   // no-op fora do perfil

    // Sem o ?aluno_id= e sem a guarda que existia aqui. Os dois eram o mesmo
    // engano: o backend identifica o aluno pelo TOKEN, então o parâmetro nunca
    // foi lido — e a guarda `if (!alunoId) return` chegava a CANCELAR a busca
    // quando o /perfil falhava, mesmo com um token perfeitamente válido que
    // teria trazido as estatísticas. Falhar numa rota derrubava a outra, sem
    // nada na tela explicando.
    let D = null, falhou = false;
    try {
        const r = await apiFetch('/perfil/estatisticas');
        if (r.ok) D = await r.json();
        else falhou = true;
    } catch (e) {
        falhou = true;
        console.warn('[KaIA] estatísticas do perfil:', e);
    }

    // --- BASE semanal ---
    const d = D?.desempenho;
    const sub   = $('desempenhoSub');
    const cards = $('desempenhoCards');
    const vazio = $('desempenhoVazio');
    if (d) {
        $('minutosTotais').textContent = `${d.minutos} min`;
        // acerto vem NULO quando o aluno abriu sessões mas ainda não respondeu
        // nada. Interpolar direto escreveria "null%" na cara dele; 0% seria pior
        // ainda, porque afirmaria que ele errou tudo.
        $('acertoSemanal').textContent = (d.acerto === null || d.acerto === undefined)
            ? SEM_DADO : `${d.acerto}%`;
        $('minSemana').textContent     = `${d.min_semana} min`;
        if (sub)   sub.textContent = `Média de ${pluralizar(d.semanas, 'semana', 'semanas')}`
                                   + ` · ${pluralizar(d.materias, 'matéria', 'matérias')}`;
        if (cards) cards.style.display = '';
        if (vazio) vazio.style.display = 'none';
    } else {
        // Antes ficava a fileira de "—" com o subtítulo "Média das últimas
        // semanas" — prometendo uma média que não existia. Agora a seção diz o
        // que está acontecendo, e distingue os DOIS casos: o backend respondeu
        // que ainda não há histórico, ou nem deu para perguntar.
        if (sub)   sub.textContent = '';
        if (cards) cards.style.display = 'none';
        if (vazio) {
            vazio.style.display = '';
            vazio.textContent = falhou
                ? 'Não foi possível carregar seu desempenho agora. Recarregue a página em alguns instantes.'
                : 'Ainda não há histórico semanal para mostrar aqui.';
        }
    }

    // --- COMPLEMENTO: última sessão ou mensagem (nunca fileira de "—") ---
    const u = D?.ultima_sessao;
    const lista = $('ultimaSessaoLista');
    const vazia = $('ultimaSessaoVazia');
    if (u) {
        $('ultimaQuando').textContent     = u.quando ? `· ${u.quando}` : '';
        $('ultTempoResposta').textContent = `${(u.tempo_resposta_ms / 1000).toFixed(1).replace('.', ',')} s`;
        $('ultScroll').textContent        = `${Math.round(u.velocidade_scroll_px_s)} px/s`;
        $('ultAbas').textContent          = `${u.mudancas_aba}`;
        $('ultForaFoco').textContent      = `${Math.round(u.tempo_fora_foco_s)} s`;
        $('ultCliques').textContent       = `${u.cliques_fora_area_estudo}`;
        if (lista) lista.style.display = '';
        if (vazia) vazia.style.display = 'none';
    } else {
        $('ultimaQuando').textContent = '';
        if (lista) lista.style.display = 'none';
        if (vazia) {
            vazia.style.display = '';
            // Quando a chamada FALHA, "nenhuma sessão registrada" é uma afirmação
            // falsa: o aluno pode ter estudado ontem e a página não faz ideia.
            vazia.textContent = falhou
                ? 'Não foi possível carregar sua última sessão agora. Recarregue a página em alguns instantes.'
                : 'Nenhuma sessão registrada ainda. Comece uma missão em Matérias para ver seus sinais.';
        }
    }

    // --- ANÁLISE (frases reais por regras; sem placeholder) ---
    const box = $('analiseIA');
    if (box) {
        box.innerHTML = '';
        const frases = D?.analise || [];
        if (frases.length) {
            const ul = document.createElement('ul');
            frases.forEach(f => {
                const li = document.createElement('li');
                li.textContent = f;
                ul.appendChild(li);
            });
            box.appendChild(ul);
        } else {
            const p = document.createElement('p');
            // Mesma distinção das outras duas seções: "não há o que analisar" e
            // "não deu para perguntar" são coisas diferentes para quem lê.
            p.textContent = falhou
                ? 'Não foi possível carregar sua análise agora.'
                : 'Ainda não há dados suficientes para uma análise.';
            box.appendChild(p);
        }
    }
}

// Init da página: comum.js já monta rail + textura; aqui só o Perfil.
document.addEventListener('DOMContentLoaded', carregarPerfil);
