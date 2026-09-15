// ============================================================
//                 MEU COATI — tela (saldos, geladeira, carinho)
// ============================================================
// Só a interface. Saldo e regras moram no coati-economia.js; o <model-viewer> é
// intocado — daqui só escutamos eventos de ponteiro nele.
//
// PENDENTE (Bia): sistema de fome, decidir depois. Hoje o coati sempre aceita.

(function () {
    'use strict';

    const eco = window.kaiaEconomia;
    const $ = (id) => document.getElementById(id);

    // ---- CONSTANTES ----
    // clique vs arrasto no model-viewer: ele gira com arrasto (camera-controls), então
    // só vira carinho um toque CURTO e PARADO. Acima disso é giro.
    const CARINHO_MAX_PX = 6;
    const CARINHO_MAX_MS = 350;
    const ARRASTO_MIN_PX = 5;      // na lista: abaixo disso é clique, não arrasto
    const BALAO_MS       = 2600;   // tempo de leitura do balão antes de sumir

    const FRASES_CARINHO = [
        'Hehe, que carinho bom!',
        'Adoro quando você faz isso!',
        'Você é meu humano favorito!',
        'Tô feliz que você voltou!',
    ];

    // ---- FALLBACK DE EMOJI ----
    // Emojis novos (😮‍💨 😵‍💫 🥵 🪙…) viram quadradinho ou dois glifos em navegador antigo.
    // Teste no canvas: ZWJ que não junta fica ~2× mais largo; glifo ausente não tem cor.
    const _cacheEmoji = {};
    function emojiRenderiza(e) {
        if (e in _cacheEmoji) return _cacheEmoji[e];
        let ok = true;
        try {
            const c = document.createElement('canvas');
            c.width = c.height = 32;
            const ctx = c.getContext('2d', { willReadFrequently: true });
            ctx.font = '24px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif';
            ctx.textBaseline = 'top';
            if (e.includes('‍')) {
                const primeiro = e.split('‍')[0];
                ok = ctx.measureText(e).width < ctx.measureText(primeiro).width * 1.5;
            }
            if (ok) {
                ctx.fillText(e, 0, 0);
                const px = ctx.getImageData(0, 0, 32, 32).data;
                ok = false;
                for (let i = 0; i < px.length; i += 4) {
                    if (px[i + 3] && (Math.abs(px[i] - px[i + 1]) > 20 || Math.abs(px[i + 1] - px[i + 2]) > 20)) { ok = true; break; }
                }
            }
        } catch (_) { ok = true; }   // sem canvas: confia no navegador
        return (_cacheEmoji[e] = ok);
    }
    const reacaoDe = (c) => (emojiRenderiza(c.reacao) ? c.reacao : c.reacaoBase);
    const ICONE_MOEDA = () => (emojiRenderiza('🪙') ? '🪙' : '💰');

    // ---- BALÃO DE REAÇÃO ----
    let _timerBalao = 0;
    function mostrarBalao(emoji, frase) {
        const balao = $('mc-balao');
        $('mc-balao-emoji').textContent = emoji;
        $('mc-balao-frase').textContent = frase;
        balao.hidden = false;
        balao.classList.remove('mc-balao-ativo');
        void balao.offsetWidth;   // reinicia a animação se chegar outra reação em cima
        balao.classList.add('mc-balao-ativo');
        clearTimeout(_timerBalao);
        _timerBalao = setTimeout(() => { balao.hidden = true; }, BALAO_MS);
    }

    function alimentar(id, origem) {
        const c = eco.comida(id);
        if (!c) return;
        if (origem === 'loja') {
            // arrastar direto da loja = compra e já dá
            if (!eco.comprarComida(id).ok) return;
        }
        if (!eco.consumirDaGeladeira(id)) return;
        mostrarBalao(reacaoDe(c), c.frase);
    }

    // ---- SALDOS ----
    function renderSaldos(s) {
        $('mc-xp').textContent = s.xp;
        $('mc-moedas').textContent = s.moedas;
        $('mc-moeda-ic').textContent = ICONE_MOEDA();
        // Foguinho: SÓ LEITURA do perfil. Não grava sequencia_dias_estudo (feature do modelo).
        let fogo = 0;
        try { fogo = JSON.parse(localStorage.getItem('kaia_perfil') || '{}').sequencia_dias_estudo || 0; } catch (_) {}
        $('mc-fogo').textContent = fogo;
    }

    // ---- LOJA / GELADEIRA ----
    function itemHTML(c, origem, s) {
        const moeda = ICONE_MOEDA();
        if (origem === 'loja') {
            const falta = c.preco - s.moedas;
            const bloqueada = falta > 0;
            return `<li class="mc-item${bloqueada ? ' mc-bloqueada' : ''}" data-id="${c.id}" data-origem="loja"${bloqueada ? ' aria-disabled="true"' : ''}>
                <span class="mc-item-emoji" aria-hidden="true">${c.emoji}</span>
                <span class="mc-item-tx"><strong>${c.nome}</strong><small>${moeda} ${c.preco}${bloqueada ? ` · faltam ${falta}` : ''}</small></span>
                <button class="mc-btn" type="button" data-acao="comprar"${bloqueada ? ' disabled' : ''} aria-label="Comprar ${c.nome} por ${c.preco} moedas">Comprar</button>
            </li>`;
        }
        return `<li class="mc-item" data-id="${c.id}" data-origem="geladeira">
            <span class="mc-item-emoji" aria-hidden="true">${c.emoji}</span>
            <span class="mc-item-tx"><strong>${c.nome}</strong><small>× ${s.geladeira[c.id]}</small></span>
            <button class="mc-btn mc-btn-dar" type="button" data-acao="dar" aria-label="Dar ${c.nome} pro coati">Dar</button>
        </li>`;
    }

    function renderListas(s) {
        $('mc-lista-loja').innerHTML = eco.COMIDAS.map((c) => itemHTML(c, 'loja', s)).join('');
        const naGeladeira = eco.COMIDAS.filter((c) => s.geladeira[c.id]);
        $('mc-lista-geladeira').innerHTML = naGeladeira.map((c) => itemHTML(c, 'geladeira', s)).join('');
        $('mc-geladeira-vazia').hidden = naGeladeira.length > 0;
        const total = naGeladeira.reduce((n, c) => n + s.geladeira[c.id], 0);
        $('mc-geladeira-qtd').textContent = total ? `(${total})` : '';
    }

    function render(s = eco.lerSaldo()) {
        renderSaldos(s);
        renderListas(s);
    }

    // Botões (teclado também alimenta, sem precisar arrastar — acessibilidade).
    function ligarBotoes() {
        document.querySelector('.mc-geladeira').addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-acao]');
            if (!btn || btn.disabled) return;
            const id = btn.closest('.mc-item').dataset.id;
            if (btn.dataset.acao === 'comprar') {
                eco.comprarComida(id);   // re-render vem pelo evento 'kaia:economia'
            } else {
                alimentar(id, 'geladeira');
            }
        });
    }

    // ---- ABAS ----
    function ligarAbas() {
        const abas = [$('mc-aba-loja'), $('mc-aba-geladeira')];
        const selecionar = (aba) => {
            abas.forEach((a) => {
                const ativa = a === aba;
                a.setAttribute('aria-selected', String(ativa));
                a.tabIndex = ativa ? 0 : -1;
                $(a.getAttribute('aria-controls')).hidden = !ativa;
            });
        };
        abas.forEach((a, i) => {
            a.addEventListener('click', () => selecionar(a));
            a.addEventListener('keydown', (e) => {
                if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
                const outra = abas[(i + 1) % abas.length];
                selecionar(outra);
                outra.focus();
            });
        });
    }

    // ---- ARRASTAR COMIDA ATÉ A MOLDURA ----
    // Pointer events (não o drag nativo do HTML5): funcionam com mouse E dedo.
    // Vale soltar só na moldura; em cima do model-viewer não conta.
    function ligarArrasto() {
        const moldura = $('mc-moldura');
        const visor = moldura.querySelector('model-viewer');
        const fantasma = $('mc-fantasma');
        let ativo = null;   // { id, origem, x0, y0, arrastando }

        const dentro = (el, x, y) => {
            const r = el.getBoundingClientRect();
            return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
        };
        const naMoldura = (x, y) => dentro(moldura, x, y) && !dentro(visor, x, y);

        document.querySelector('.mc-geladeira').addEventListener('pointerdown', (e) => {
            const item = e.target.closest('.mc-item');
            if (!item || e.target.closest('button') || item.classList.contains('mc-bloqueada')) return;
            if (e.button !== 0) return;
            ativo = { id: item.dataset.id, origem: item.dataset.origem, x0: e.clientX, y0: e.clientY, arrastando: false, item };
            item.setPointerCapture(e.pointerId);
        });

        document.addEventListener('pointermove', (e) => {
            if (!ativo) return;
            if (!ativo.arrastando) {
                if (Math.hypot(e.clientX - ativo.x0, e.clientY - ativo.y0) < ARRASTO_MIN_PX) return;
                ativo.arrastando = true;
                fantasma.textContent = eco.comida(ativo.id).emoji;
                fantasma.hidden = false;
                ativo.item.classList.add('mc-arrastando');
                moldura.classList.add('mc-moldura-espera');
            }
            fantasma.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
            moldura.classList.toggle('mc-moldura-sobre', naMoldura(e.clientX, e.clientY));
        });

        const soltar = (e, cancelado) => {
            if (!ativo) return;
            const { id, origem, arrastando, item } = ativo;
            ativo = null;
            fantasma.hidden = true;
            item.classList.remove('mc-arrastando');
            moldura.classList.remove('mc-moldura-espera', 'mc-moldura-sobre');
            if (arrastando && !cancelado && naMoldura(e.clientX, e.clientY)) alimentar(id, origem);
        };
        document.addEventListener('pointerup', (e) => soltar(e, false));
        document.addEventListener('pointercancel', (e) => soltar(e, true));
    }

    // ---- CARINHO (clique curto no coati) ----
    function ligarCarinho() {
        const visor = document.querySelector('.mc-moldura model-viewer');
        let inicio = null;
        // capture: pega o evento antes do controle de câmera do model-viewer
        visor.addEventListener('pointerdown', (e) => {
            inicio = e.isPrimary ? { x: e.clientX, y: e.clientY, t: performance.now() } : null;
        }, true);
        visor.addEventListener('pointerup', (e) => {
            if (!inicio) return;
            const parado = Math.hypot(e.clientX - inicio.x, e.clientY - inicio.y) <= CARINHO_MAX_PX;
            const curto = performance.now() - inicio.t <= CARINHO_MAX_MS;
            inicio = null;
            if (parado && curto) {
                mostrarBalao('😊', FRASES_CARINHO[Math.floor(Math.random() * FRASES_CARINHO.length)]);
            }
        }, true);
        visor.addEventListener('pointercancel', () => { inicio = null; }, true);
    }

    // ---- INIT ----
    document.addEventListener('DOMContentLoaded', () => {
        ligarCarinho();   // carinho não depende da economia
        if (!eco) {
            console.warn('[KaIA] coati-economia.js não carregou — tela do coati sem loja.');
            document.querySelector('.mc-geladeira')?.setAttribute('hidden', '');
            return;
        }
        render();
        ligarAbas();
        ligarBotoes();
        ligarArrasto();
        window.addEventListener('kaia:economia', (e) => render(e.detail));
    });
})();
