// ============================================================
//  KaIA — perfil.js: página do Perfil (o aluno vendo a própria evolução)
// ============================================================
// Depende de comum.js ($, apiFetch), carregado antes. Só perfil.html usa.

async function carregarPerfil() {
    if (!$('nomeUsuario')) return;

    const SEM_DADO = '—';
    const usuario = JSON.parse(sessionStorage.getItem('kaia_usuario') || 'null');

    // 1) Identidade: parte do sessionStorage (login, por aba) e confirma via /perfil.
    $('nomeUsuario').textContent  = usuario?.nome || usuario?.email || SEM_DADO;
    $('emailUsuario').textContent = usuario?.email || SEM_DADO;

    // user_id do perfil EXIBIDO. NÃO usar localStorage.kaia_user_id: ele é
    // compartilhado entre abas (o último login sobrescreve para todas), então
    // discordaria da identidade desta aba. sessionStorage é por aba; o /perfil
    // é a fonte autoritativa.
    let alunoId = usuario?.user_id || null;
    if (usuario?.email) {
        try {
            const r = await apiFetch(`/perfil?email=${encodeURIComponent(usuario.email)}`);
            if (r.ok) {
                const u = await r.json();
                $('nomeUsuario').textContent  = u.nome  || SEM_DADO;
                $('emailUsuario').textContent = u.email || SEM_DADO;
                if (u.user_id) alunoId = u.user_id;
            }
        } catch (e) { console.warn('[KaIA] identidade do perfil:', e); }
    }

    // 2) Estatísticas (Etapa 4.1 C híbrida) do perfil EXIBIDO.
    await carregarEstatisticasPerfil(alunoId);
}

// Preenche "Seu desempenho" (base semanal), "Sua última sessão" (complemento ao
// vivo, com estado vazio) e a "Análise da KaIA" (frases reais vindas do backend).
async function carregarEstatisticasPerfil(alunoId) {
    if (!$('atencaoSemanal')) return;   // no-op fora do perfil
    if (!alunoId) return;               // sem identidade do perfil exibido, não busca

    let D = null;
    try {
        const r = await apiFetch(`/perfil/estatisticas?aluno_id=${encodeURIComponent(alunoId)}`);
        if (r.ok) D = await r.json();
    } catch (e) { console.warn('[KaIA] estatísticas do perfil:', e); }

    // --- BASE semanal (sempre visível) ---
    const d = D?.desempenho;
    if (d) {
        $('atencaoSemanal').textContent = `${d.atencao}%`;
        $('acertoSemanal').textContent  = `${d.acerto}%`;
        $('minSemana').textContent      = `${d.min_semana} min`;
        const sub = $('desempenhoSub');
        if (sub) sub.textContent = `Média de ${d.semanas} semanas · ${d.materias} matérias`;
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
        if (vazia) vazia.style.display = '';
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
            p.textContent = 'Ainda não há dados suficientes para uma análise.';
            box.appendChild(p);
        }
    }
}

// Init da página: comum.js já monta rail + textura; aqui só o Perfil.
document.addEventListener('DOMContentLoaded', carregarPerfil);
