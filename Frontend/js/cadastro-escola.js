// ============================================================
//  KaIA — cadastro-escola.js: wizard de cadastro da escola (MOCK)
// ============================================================
// Só front: sem rede, sem Supabase, sem comum.js (que acorda o backend).
// Gravar escola, gerar códigos e pagamento são frente separada (Bia + Vitor).

(() => {
    const $ = (id) => document.getElementById(id);

    // Preços dos planos escolares — mesmos valores da landing (index.html); mudou lá, mude aqui.
    const PLANOS_ESCOLA = {
        ara:   { nome: 'Ara',   rotulo: 'Turma', preco: 28.90, minimo: 20 },
        guara: { nome: 'Guará', rotulo: 'Rede',  preco: 23.90, minimo: 80 },
    };

    const UFS = ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA',
                 'PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'];

    const TOTAL_PASSOS = 4;
    const estado = { passo: 1, plano: 'ara' };

    const reais = (v) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
    const inteiro = (id) => {
        const n = parseInt($(id).value, 10);
        return Number.isInteger(n) ? n : 0;
    };
    const texto = (id) => $(id).value.trim();

    // ---- Plano x nº de alunos -------------------------------------------------
    // Devolve o aviso a mostrar (ou null) e se dá pra avançar.
    function checarPlano() {
        const n = inteiro('ce-alunos');
        const p = PLANOS_ESCOLA[estado.plano];
        const ara = PLANOS_ESCOLA.ara;
        if (!n) return { aviso: null, ok: false };
        if (estado.plano === 'guara' && n >= ara.minimo && n < p.minimo) {
            return {
                aviso: `O Guará começa em ${p.minimo} alunos. Com ${n} alunos, o Ara atende sua escola `
                     + `e fica ${reais(n * ara.preco)}/mês.`,
                trocar: true, ok: false,
            };
        }
        if (n < p.minimo) {
            return {
                aviso: `O plano ${p.nome} começa em ${p.minimo} alunos. Ajuste o número para continuar.`,
                ok: false,
            };
        }
        return { aviso: null, ok: true };
    }

    function atualizarPreco() {
        const n = inteiro('ce-alunos');
        const p = PLANOS_ESCOLA[estado.plano];
        $('ce-total').textContent = n ? reais(n * p.preco) : '—';
        $('ce-total-conta').textContent = n ? `${n} × ${reais(p.preco)} por aluno` : '';

        const { aviso, trocar } = checarPlano();
        $('ce-aviso').hidden = !aviso;
        $('ce-aviso-texto').textContent = aviso || '';
        $('ce-aviso-trocar').hidden = !trocar;
    }

    function montarPlanos() {
        const caixa = document.querySelector('.ce-planos');
        caixa.replaceChildren();
        Object.entries(PLANOS_ESCOLA).forEach(([id, p]) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = 'plano plano-escolar ce-plano';
            card.setAttribute('role', 'radio');
            card.dataset.plano = id;
            card.innerHTML = `
                <span class="plano-tipo">ESCOLAR</span>
                <span class="ce-plano-nome">${p.nome}<span class="plano-nome-desc">${p.rotulo}</span></span>
                <span class="ce-plano-preco">${reais(p.preco)}<span>/aluno/mês</span></span>
                <span class="plano-alvo">Mínimo de ${p.minimo} alunos</span>`;
            card.addEventListener('click', () => escolherPlano(id));
            caixa.appendChild(card);
        });
        marcarPlano();
    }

    function marcarPlano() {
        document.querySelectorAll('.ce-plano').forEach((c) => {
            const sel = c.dataset.plano === estado.plano;
            c.classList.toggle('ce-plano-sel', sel);
            c.setAttribute('aria-checked', String(sel));
        });
    }

    function escolherPlano(id) {
        estado.plano = id;
        marcarPlano();
        atualizarPreco();
    }

    // ---- Validação por passo --------------------------------------------------
    const emailOk = (e) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e);

    // Máscara (00) 00000-0000 enquanto digita; com 10 dígitos vira fixo (00) 0000-0000.
    function mascararTelefone(input) {
        const d = input.value.replace(/\D/g, '').slice(0, 11);
        let v = d;
        if (d.length > 2) v = `(${d.slice(0, 2)}) ${d.slice(2)}`;
        else if (d.length) v = `(${d}`;
        if (d.length > 6) {
            const corte = d.length === 11 ? 7 : 6;
            v = `(${d.slice(0, 2)}) ${d.slice(2, corte)}-${d.slice(corte)}`;
        }
        input.value = v;
    }

    function validar(passo) {
        if (passo === 1) {
            if (!texto('ce-escola')) return ['ce-escola', 'Informe o nome da escola.'];
            if (!texto('ce-cidade')) return ['ce-cidade', 'Informe a cidade.'];
            if (!$('ce-estado').value) return ['ce-estado', 'Escolha o estado.'];
            if (inteiro('ce-salas') < 1) return ['ce-salas', 'Informe quantas salas a escola tem.'];
        }
        if (passo === 2) {
            if (!texto('ce-coord-nome')) return ['ce-coord-nome', 'Informe o nome do coordenador.'];
            if (!emailOk(texto('ce-coord-email'))) return ['ce-coord-email', 'Informe um e-mail válido.'];
            if (texto('ce-coord-tel').replace(/\D/g, '').length < 10) {
                return ['ce-coord-tel', 'Informe um telefone com DDD.'];
            }
        }
        if (passo === 3) {
            if (!inteiro('ce-alunos')) return ['ce-alunos', 'Informe o número de alunos.'];
            if (!checarPlano().ok) return ['ce-alunos', ''];   // o aviso âmbar já explica
        }
        return null;
    }

    // ---- Navegação ------------------------------------------------------------
    function montarResumo() {
        const n = inteiro('ce-alunos');
        const p = PLANOS_ESCOLA[estado.plano];
        const linhas = [
            ['Escola', `${texto('ce-escola')} · ${texto('ce-cidade')}/${$('ce-estado').value}`],
            ['Coordenador', texto('ce-coord-nome')],
            ['Plano', `${p.nome} · ${p.rotulo}`],
            ['Alunos', String(n)],
            ['Valor por aluno', `${reais(p.preco)}/mês`],
            ['Total mensal', reais(n * p.preco)],
        ];
        const dl = $('ce-resumo');
        dl.replaceChildren();
        linhas.forEach(([rotulo, valor], i) => {
            const linha = document.createElement('div');
            linha.className = 'ce-resumo-linha' + (i === linhas.length - 1 ? ' ce-resumo-total' : '');
            const dt = document.createElement('dt');
            const dd = document.createElement('dd');
            dt.textContent = rotulo;
            dd.textContent = valor;
            linha.append(dt, dd);
            dl.appendChild(linha);
        });
    }

    function mostrar(passo, focar = true) {
        estado.passo = passo;
        document.querySelectorAll('.ce-passo').forEach((s) => {
            s.hidden = s.dataset.passo !== String(passo);
        });

        const fim = passo === 'fim';
        document.querySelectorAll('.ce-etapa').forEach((li) => {
            const n = Number(li.dataset.etapa);
            li.classList.toggle('ce-feita', fim || n < passo);
            li.classList.toggle('ce-atual', n === passo);
            if (n === passo) li.setAttribute('aria-current', 'step');
            else li.removeAttribute('aria-current');
        });
        const feitos = fim ? TOTAL_PASSOS : passo - 1;
        $('ce-trilho').style.width = `${(feitos / (TOTAL_PASSOS - 1)) * 100}%`;

        $('ce-acoes').hidden = fim;
        $('ce-acoes').classList.toggle('ce-acoes-sozinho', passo === 1);   // sem Voltar: Avançar ocupa a linha
        $('ce-voltar').hidden = passo === 1;
        $('ce-link-login').hidden = passo !== 1;   // "Já tem conta?" só no começo
        $('ce-avancar').textContent = passo === TOTAL_PASSOS ? 'Enviar para a KaIA' : 'Avançar';
        $('ce-erro').textContent = '';

        if (passo === 3) atualizarPreco();
        if (passo === TOTAL_PASSOS) montarResumo();
        // Foco no título do passo: leitor de tela anuncia a troca, teclado não se perde.
        const titulo = document.querySelector(`.ce-passo[data-passo="${passo}"] .ce-titulo`);
        if (titulo && focar) titulo.focus({ preventScroll: true });
    }

    function avancar(event) {
        event.preventDefault();
        const falha = validar(estado.passo);
        if (falha) {
            const [campo, msg] = falha;
            $('ce-erro').textContent = msg;
            $(campo).focus();
            return;
        }
        // PENDENTE (Daniel): integração de pagamento — definir gateway (Mercado Pago
        // / Asaas), modelo de cobrança da escola (boleto / NF / cartão) e emissão de
        // NFS-e. Hoje o fluxo é: cadastro → e-mail pra KaIA → liberação manual.
        // O envio desse e-mail também não existe ainda: "Enviar" só mostra o sucesso mockado.
        mostrar(estado.passo === TOTAL_PASSOS ? 'fim' : estado.passo + 1);
    }

    document.addEventListener('DOMContentLoaded', () => {
        const uf = $('ce-estado');
        UFS.forEach((sigla) => uf.add(new Option(sigla, sigla)));

        montarPlanos();
        $('ce-alunos').addEventListener('input', atualizarPreco);
        // Apagando não remascara: senão o backspace ficaria preso no "-" ou no ")".
        $('ce-coord-tel').addEventListener('input', (e) => {
            if (!e.inputType?.startsWith('delete')) mascararTelefone(e.target);
        });
        $('ce-aviso-trocar').addEventListener('click', () => escolherPlano('ara'));
        $('ce-voltar').addEventListener('click', () => mostrar(estado.passo - 1));
        $('ce-form').addEventListener('submit', avancar);
        // Digitar de novo apaga o erro antigo, sem esperar o próximo clique.
        $('ce-form').addEventListener('input', () => { $('ce-erro').textContent = ''; });

        mostrar(1, false);
    });
})();
