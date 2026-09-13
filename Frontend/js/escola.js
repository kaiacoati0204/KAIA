// ============================================================
//  KaIA — escola.js: painel do coordenador (MOCK)
// ============================================================
// Depende de comum.js (só pela rail). Dados de ESCOLA_DEMO, estado só na memória:
// copiar/gerar/renovar/mover/remover não chamam o backend (frente separada, Bia + Vitor).

(() => {
    const $ = (id) => document.getElementById(id);
    const DIA_MS = 24 * 60 * 60 * 1000;
    const VALIDADE_PROFESSOR_DIAS = 1;
    const VALIDADE_ALUNO_DIAS = 7;
    const ALERTA_DIAS = 2;   // faltando isso ou menos, a validade vai para o tom de alerta suave

    const agora = Date.now();

    // PENDENTE (Bia + Vitor/Daniel): como o aluno entra na lista — auto-cadastro (usa o
    // código e põe o próprio nome) ou o coordenador pré-cadastra. No mock os alunos já
    // aparecem com nome, sem assumir nenhum dos dois.
    const ESCOLA_DEMO = {
        nome: 'Colégio Vale Verde',
        plano: { nome: 'Ara', rotulo: 'Turma' },
        professor: { codigo: 'PROF-7K3M', expiraEm: agora + VALIDADE_PROFESSOR_DIAS * DIA_MS },
        turmas: [
            {
                id: 't-7a', nome: '7º ano A', turno: 'Manhã',
                codigo: '7A-K3F9', expiraEm: agora + 5 * DIA_MS,
                alunos: [
                    { id: 'a1', nome: 'Ana Beatriz Rocha' },
                    { id: 'a2', nome: 'Bruno Carvalho' },
                    { id: 'a3', nome: 'Camila Duarte' },
                    { id: 'a4', nome: 'Diego Nascimento' },
                ],
            },
            {
                id: 't-8b', nome: '8º ano B', turno: 'Tarde',
                codigo: '8B-P2QX', expiraEm: agora + 2 * DIA_MS,
                alunos: [
                    { id: 'a5', nome: 'Eduarda Lima' },
                    { id: 'a6', nome: 'Felipe Moreira' },
                    { id: 'a7', nome: 'Gabriela Souza' },
                ],
            },
            {
                id: 't-9c', nome: '9º ano C', turno: 'Manhã',
                codigo: '9C-W7HD', expiraEm: agora + 0.4 * DIA_MS,
                alunos: [
                    { id: 'a8', nome: 'Heitor Almeida' },
                    { id: 'a9', nome: 'Isabela Freitas' },
                    { id: 'a10', nome: 'João Pedro Santos' },
                    { id: 'a11', nome: 'Larissa Oliveira' },
                    { id: 'a12', nome: 'Matheus Ribeiro' },
                ],
            },
        ],
    };

    const escola = structuredClone(ESCOLA_DEMO);
    // UI que precisa sobreviver ao re-render: turmas expandidas e a ação aberta num aluno.
    const ui = { abertas: new Set(), acao: null, editando: null };

    // ---- utilidades -----------------------------------------------------------
    const ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';   // sem 0/O e 1/I: código é ditado em sala
    const sufixo = () => Array.from({ length: 4 }, () => ALFABETO[Math.floor(Math.random() * ALFABETO.length)]).join('');

    const el = (tag, classe, texto) => {
        const e = document.createElement(tag);
        if (classe) e.className = classe;
        if (texto !== undefined) e.textContent = texto;
        return e;
    };

    function validade(expiraEm) {
        const ms = expiraEm - Date.now();
        const dias = Math.ceil(ms / DIA_MS);
        if (ms <= 0) return { texto: 'Expirado', alerta: true };
        if (ms < DIA_MS) return { texto: 'Expira hoje', alerta: true };
        return { texto: `Expira em ${dias} ${dias === 1 ? 'dia' : 'dias'}`, alerta: dias <= ALERTA_DIAS };
    }

    const dataHora = (ts) => new Date(ts).toLocaleString('pt-BR', {
        day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });

    let _avisoTimer = null;
    function avisar(msg) {
        const p = $('ep-aviso');
        p.textContent = msg;
        p.classList.add('ep-aviso-on');
        clearTimeout(_avisoTimer);
        _avisoTimer = setTimeout(() => p.classList.remove('ep-aviso-on'), 3200);
    }

    async function copiar(texto, botao) {
        let ok = false;
        try {
            await navigator.clipboard.writeText(texto);
            ok = true;
        } catch (_) {
            // Sem permissão de clipboard (http/file://): fallback pelo textarea.
            const t = el('textarea');
            t.value = texto;
            t.setAttribute('readonly', '');
            t.style.position = 'fixed';
            t.style.opacity = '0';
            document.body.appendChild(t);
            t.select();
            try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
            t.remove();
        }
        if (!ok) return avisar(`Não deu pra copiar. O código é ${texto}.`);
        const original = botao.textContent;
        botao.textContent = 'Copiado!';
        setTimeout(() => { botao.textContent = original; }, 1800);
        avisar(`Código ${texto} copiado.`);
    }

    // ---- topo + código de professor --------------------------------------------
    function renderTopo() {
        const total = escola.turmas.reduce((s, t) => s + t.alunos.length, 0);
        $('ep-escola').textContent = escola.nome;
        const nT = escola.turmas.length;
        $('ep-plano').textContent = `Plano ${escola.plano.nome} · ${escola.plano.rotulo}`;
        // Alunos que JÁ entraram nas turmas — não é o número contratado no plano.
        $('ep-contagem').textContent = `${nT} ${nT === 1 ? 'turma' : 'turmas'} · ${total} ${total === 1 ? 'aluno' : 'alunos'}`;
    }

    function renderProfessor() {
        const p = escola.professor;
        const v = validade(p.expiraEm);
        $('ep-prof-codigo').textContent = p.codigo;
        const val = $('ep-prof-validade');
        val.textContent = v.texto === 'Expirado' ? 'Expirado' : `Válido até ${dataHora(p.expiraEm)}`;
        val.classList.toggle('ep-validade-alerta', v.texto === 'Expirado');
    }

    function gerarCodigoProfessor() {
        escola.professor = { codigo: `PROF-${sufixo()}`, expiraEm: Date.now() + VALIDADE_PROFESSOR_DIAS * DIA_MS };
        $('ep-prof-confirma').hidden = true;
        renderProfessor();
        $('ep-prof-gerar').focus();
        avisar(`Novo código de professor: ${escola.professor.codigo}. O anterior não vale mais.`);
    }

    // ---- turmas ----------------------------------------------------------------
    const acharTurma = (id) => escola.turmas.find((t) => t.id === id);
    // Mesma regra no criar e no renomear; `exceto` deixa a turma manter o próprio nome.
    const nomeRepetido = (nome, exceto) =>
        escola.turmas.some((t) => t !== exceto && t.nome.toLowerCase() === nome.toLowerCase());

    // Prefixo do código sai do nome ("6º ano D" → "6D"), só com letras/dígitos do ALFABETO.
    function codigoTurma(nome) {
        const limpo = nome.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        const prefixo = (limpo.match(/[0-9]|\b[A-Za-z]\b/g) || [])   // dígitos e letras soltas
            .map((c) => c.toUpperCase()).filter((c) => ALFABETO.includes(c)).join('').slice(0, 2) || 'T';
        let codigo;
        do { codigo = `${prefixo}-${sufixo()}`; } while (escola.turmas.some((t) => t.codigo === codigo));
        return codigo;
    }

    function abrirNovaTurma(abrir) {
        $('ep-nova').hidden = !abrir;
        $('ep-nova-abrir').setAttribute('aria-expanded', String(abrir));
        $('ep-nova-erro').textContent = '';
        if (abrir) $('ep-nova-nome').focus();
        else { $('ep-nova').reset(); $('ep-nova-abrir').focus(); }
    }

    function criarTurma(event) {
        event.preventDefault();
        const nome = $('ep-nova-nome').value.trim();
        const erro = $('ep-nova-erro');
        if (!nome) { erro.textContent = 'Dê um nome pra turma.'; return $('ep-nova-nome').focus(); }
        if (nomeRepetido(nome)) {
            erro.textContent = 'Já existe uma turma com esse nome.';
            return $('ep-nova-nome').focus();
        }
        // PENDENTE (Daniel): impacto de criar/remover turma e alunos no preço e na
        // cobrança — hoje o mock não recalcula nada.
        const turma = {
            id: `t-${Date.now()}`, nome, turno: $('ep-nova-turno').value,
            codigo: codigoTurma(nome), expiraEm: Date.now() + VALIDADE_ALUNO_DIAS * DIA_MS,
            alunos: [],
        };
        escola.turmas.push(turma);
        $('ep-nova').reset();
        $('ep-nova').hidden = true;
        $('ep-nova-abrir').setAttribute('aria-expanded', 'false');
        renderTopo();
        renderTurmas(`[data-copiar="${turma.id}"]`);   // próximo passo natural: copiar o código novo
        document.querySelector(`[data-copiar="${turma.id}"]`)?.closest('.ep-turma')
            ?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' });
        avisar(`Turma ${turma.nome} criada com o código ${turma.codigo}.`);
    }

    function renovar(turma) {
        turma.expiraEm = Date.now() + VALIDADE_ALUNO_DIAS * DIA_MS;
        renderTurmas(`[data-renovar="${turma.id}"]`);
        avisar(`Código de ${turma.nome} renovado por 7 dias.`);
    }

    function salvarRenomear(event, turma, form) {
        event.preventDefault();
        const nome = form.querySelector('input').value.trim();
        const erro = form.querySelector('.ep-erro');
        if (!nome) { erro.textContent = 'Dê um nome pra turma.'; return form.querySelector('input').focus(); }
        if (nomeRepetido(nome, turma)) {
            erro.textContent = 'Já existe uma turma com esse nome.';
            return form.querySelector('input').focus();
        }
        // PENDENTE (Vitor): confirmar se, ao renomear turma (ex: virada de ano), o código de
        // aluno deve mesmo ser mantido — hoje o mock mantém.
        // Só o rótulo muda: código, validade e alunos ficam. Quem já anotou o código não perde o acesso.
        const antigo = turma.nome;
        turma.nome = nome;
        turma.turno = form.querySelector('select').value;
        ui.editando = null;
        renderTurmas(`[data-renomear="${turma.id}"]`);
        avisar(antigo === nome ? `Turma ${nome} atualizada.` : `${antigo} agora se chama ${nome}. O código continua ${turma.codigo}.`);
    }

    function formRenomear(turma) {
        const form = el('form', 'ep-renomear');
        form.noValidate = true;
        const campos = el('div', 'ep-nova-campos');

        const cNome = el('div', 'ep-campo');
        const lNome = el('label', null, 'Nome da turma');
        const iNome = el('input', 'ep-select');
        iNome.type = 'text';
        iNome.id = `ep-renomear-${turma.id}`;
        iNome.value = turma.nome;
        iNome.autocomplete = 'off';
        lNome.htmlFor = iNome.id;
        cNome.append(lNome, iNome);

        const cTurno = el('div', 'ep-campo');
        const lTurno = el('label', null, 'Turno');
        const sTurno = el('select', 'ep-select');
        sTurno.id = `ep-renomear-turno-${turma.id}`;
        ['Manhã', 'Tarde', 'Noite', 'Integral'].forEach((t) => sTurno.add(new Option(t, t, false, t === turma.turno)));
        lTurno.htmlFor = sTurno.id;
        cTurno.append(lTurno, sTurno);
        campos.append(cNome, cTurno);

        const erro = el('p', 'ep-erro');
        erro.setAttribute('role', 'alert');
        const botoes = el('div', 'ep-acoes');
        const ok = el('button', 'ep-btn', 'Salvar');
        ok.type = 'submit';
        const cancelar = el('button', 'ep-btn ep-btn-texto', 'Cancelar');
        cancelar.type = 'button';
        cancelar.addEventListener('click', () => { ui.editando = null; renderTurmas(`[data-renomear="${turma.id}"]`); });
        botoes.append(ok, cancelar);

        form.append(campos, erro, botoes);
        form.addEventListener('submit', (e) => salvarRenomear(e, turma, form));
        return form;
    }

    function moverAluno(origem, alunoId, destinoId) {
        const destino = acharTurma(destinoId);
        const i = origem.alunos.findIndex((a) => a.id === alunoId);
        if (!destino || i < 0) return;
        // PENDENTE (Bia + Vitor/Daniel): o que acontece com o histórico do aluno (atenção,
        // acertos) ao mudar de turma — vai junto, fica na turma antiga ou zera. O mock só
        // troca o nome de lista.
        const [aluno] = origem.alunos.splice(i, 1);
        destino.alunos.push(aluno);
        ui.acao = null;
        renderTopo();
        renderTurmas(`[data-gerenciar="${origem.id}"]`);
        avisar(`${aluno.nome} foi para ${destino.nome}.`);
    }

    function removerAluno(turma, alunoId) {
        const i = turma.alunos.findIndex((a) => a.id === alunoId);
        if (i < 0) return;
        // PENDENTE (Bia + Vitor/Daniel): o que acontece com o histórico do aluno removido
        // (apaga, anonimiza, guarda por quanto tempo) — decisão com peso de LGPD, aluno menor.
        const [aluno] = turma.alunos.splice(i, 1);
        ui.acao = null;
        renderTopo();
        renderTurmas(`[data-gerenciar="${turma.id}"]`);
        avisar(`${aluno.nome} foi removido(a) de ${turma.nome}.`);
    }

    function renderAluno(turma, aluno) {
        const li = el('li', 'ep-aluno');
        const linha = el('div', 'ep-aluno-linha');
        linha.appendChild(el('span', 'ep-aluno-nome', aluno.nome));

        const acoes = el('div', 'ep-acoes ep-acoes-aluno');
        const outras = escola.turmas.filter((t) => t.id !== turma.id);
        const bMover = el('button', 'ep-btn ep-btn-peq', 'Mover');
        bMover.type = 'button';
        bMover.dataset.mover = aluno.id;
        bMover.setAttribute('aria-label', `Mover ${aluno.nome} de turma`);
        bMover.disabled = !outras.length;
        bMover.addEventListener('click', () => {
            ui.acao = { alunoId: aluno.id, tipo: 'mover' };
            renderTurmas(`#ep-destino-${aluno.id}`);
        });
        const bRemover = el('button', 'ep-btn ep-btn-peq ep-btn-texto', 'Remover');
        bRemover.type = 'button';
        bRemover.dataset.remover = aluno.id;
        bRemover.setAttribute('aria-label', `Remover ${aluno.nome} da turma`);
        bRemover.addEventListener('click', () => {
            ui.acao = { alunoId: aluno.id, tipo: 'remover' };
            renderTurmas(`[data-remover-sim="${aluno.id}"]`);
        });
        acoes.append(bMover, bRemover);
        linha.appendChild(acoes);
        li.appendChild(linha);

        const cancelar = (foco) => {
            const b = el('button', 'ep-btn ep-btn-peq ep-btn-texto', 'Cancelar');
            b.type = 'button';
            b.addEventListener('click', () => { ui.acao = null; renderTurmas(foco); });
            return b;
        };

        if (ui.acao?.alunoId === aluno.id && ui.acao.tipo === 'mover') {
            const caixa = el('div', 'ep-confirma ep-confirma-aluno');
            const rotulo = el('label', null, `Mover ${aluno.nome} para`);
            rotulo.htmlFor = `ep-destino-${aluno.id}`;
            const sel = el('select', 'ep-select');
            sel.id = `ep-destino-${aluno.id}`;
            outras.forEach((t) => sel.add(new Option(`${t.nome} · ${t.turno}`, t.id)));
            const ok = el('button', 'ep-btn ep-btn-peq', 'Mover');
            ok.type = 'button';
            ok.addEventListener('click', () => moverAluno(turma, aluno.id, sel.value));
            const botoes = el('div', 'ep-acoes');
            botoes.append(ok, cancelar(`[data-mover="${aluno.id}"]`));
            caixa.append(rotulo, sel, botoes);
            li.appendChild(caixa);
        }

        if (ui.acao?.alunoId === aluno.id && ui.acao.tipo === 'remover') {
            const caixa = el('div', 'ep-confirma ep-confirma-aluno');
            caixa.appendChild(el('p', null, `Remover ${aluno.nome} de ${turma.nome}?`));
            const ok = el('button', 'ep-btn ep-btn-peq', 'Remover');
            ok.type = 'button';
            ok.dataset.removerSim = aluno.id;
            ok.addEventListener('click', () => removerAluno(turma, aluno.id));
            const botoes = el('div', 'ep-acoes');
            botoes.append(ok, cancelar(`[data-remover="${aluno.id}"]`));
            caixa.appendChild(botoes);
            li.appendChild(caixa);
        }
        return li;
    }

    function renderTurma(turma) {
        const li = el('li', 'ep-turma');
        const v = validade(turma.expiraEm);
        const aberta = ui.abertas.has(turma.id);

        const editando = ui.editando === turma.id;
        const cab = el('div', 'ep-turma-cab');
        const info = el('div', 'ep-turma-info');
        const n = turma.alunos.length;
        if (editando) {
            info.appendChild(formRenomear(turma));
        } else {
            info.appendChild(el('h3', 'ep-turma-nome', turma.nome));
            info.appendChild(el('p', 'ep-turma-meta', `${turma.turno} · ${n} ${n === 1 ? 'aluno' : 'alunos'}`));
        }

        const cod = el('div', 'ep-turma-codigo');
        cod.appendChild(el('span', 'ep-rotulo', 'Código de aluno'));
        cod.appendChild(el('code', 'ep-codigo', turma.codigo));
        cod.appendChild(el('span', `ep-validade${v.alerta ? ' ep-validade-alerta' : ''}`, v.texto));
        cab.append(info, cod);
        li.appendChild(cab);

        const acoes = el('div', 'ep-acoes');
        const bCopiar = el('button', 'ep-btn', 'Copiar código');
        bCopiar.type = 'button';
        bCopiar.dataset.copiar = turma.id;
        bCopiar.setAttribute('aria-label', `Copiar código de ${turma.nome}`);
        bCopiar.addEventListener('click', () => copiar(turma.codigo, bCopiar));

        const bRenovar = el('button', 'ep-btn', 'Renovar 7 dias');
        bRenovar.type = 'button';
        bRenovar.dataset.renovar = turma.id;
        bRenovar.setAttribute('aria-label', `Renovar código de ${turma.nome} por 7 dias`);
        bRenovar.addEventListener('click', () => renovar(turma));

        const bRenomear = el('button', 'ep-btn', 'Renomear');
        bRenomear.type = 'button';
        bRenomear.dataset.renomear = turma.id;
        bRenomear.setAttribute('aria-label', `Renomear ${turma.nome}`);
        bRenomear.addEventListener('click', () => {
            ui.editando = turma.id;
            ui.acao = null;
            renderTurmas(`#ep-renomear-${turma.id}`);
        });

        const listaId = `ep-alunos-${turma.id}`;
        const bGerenciar = el('button', 'ep-btn ep-btn-texto ep-btn-gerenciar', aberta ? 'Fechar alunos' : 'Gerenciar alunos');
        bGerenciar.type = 'button';
        bGerenciar.dataset.gerenciar = turma.id;
        bGerenciar.setAttribute('aria-expanded', String(aberta));
        bGerenciar.setAttribute('aria-controls', listaId);
        bGerenciar.addEventListener('click', () => {
            if (aberta) ui.abertas.delete(turma.id); else ui.abertas.add(turma.id);
            ui.acao = null;
            renderTurmas(`[data-gerenciar="${turma.id}"]`);
        });
        acoes.append(bCopiar, bRenovar, bRenomear, bGerenciar);
        if (!editando) li.appendChild(acoes);   // editando: só Salvar/Cancelar, sem ação concorrente

        const lista = el('div', 'ep-alunos');
        lista.id = listaId;
        lista.hidden = !aberta;
        if (aberta) {
            if (!turma.alunos.length) {
                lista.appendChild(el('p', 'ep-vazio', 'Nenhum aluno nesta turma ainda.'));
            } else {
                const ul = el('ul', 'ep-alunos-lista');
                turma.alunos.forEach((a) => ul.appendChild(renderAluno(turma, a)));
                lista.appendChild(ul);
            }
        }
        li.appendChild(lista);
        return li;
    }

    // Re-render inteiro (mock pequeno) e devolve o foco ao seletor pedido, pro teclado não se perder.
    function renderTurmas(focarEm) {
        const ul = $('ep-turmas');
        ul.replaceChildren(...escola.turmas.map(renderTurma));
        if (focarEm) ul.querySelector(focarEm)?.focus();
    }

    document.addEventListener('DOMContentLoaded', () => {
        renderTopo();
        renderProfessor();
        renderTurmas();

        $('ep-prof-copiar').addEventListener('click', (e) => copiar(escola.professor.codigo, e.currentTarget));
        $('ep-prof-gerar').addEventListener('click', () => {
            $('ep-prof-confirma').hidden = false;
            $('ep-prof-gerar-sim').focus();
        });
        $('ep-prof-gerar-sim').addEventListener('click', gerarCodigoProfessor);
        $('ep-nova-abrir').addEventListener('click', () => abrirNovaTurma($('ep-nova').hidden));
        $('ep-nova-cancelar').addEventListener('click', () => abrirNovaTurma(false));
        $('ep-nova').addEventListener('submit', criarTurma);
        $('ep-prof-gerar-nao').addEventListener('click', () => {
            $('ep-prof-confirma').hidden = true;
            $('ep-prof-gerar').focus();
        });
    });
})();
