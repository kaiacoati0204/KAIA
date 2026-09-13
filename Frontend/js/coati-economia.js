// ============================================================
//              ECONOMIA DO COATI (XP + moedas + geladeira)
// ============================================================
// Arquivo separado do comum.js de propósito: se não carregar, quem usa com
// window.kaiaEconomia?.… segue funcionando igual (a questão não depende disto).
//
// Uso:
//   kaiaEconomia.ganharPorAcerto(3)                    → { xp: 30, moedas: 30 }
//   kaiaEconomia.ganharPorAcerto(5, { revisao: true }) → { xp: 35, moedas: 35 }
//   kaiaEconomia.comprarComida('bala')                 → { ok: true } | { ok: false, motivo }
//   kaiaEconomia.consumirDaGeladeira('bala')           → true | false
//   kaiaEconomia.lerSaldo()                            → { xp, moedas, geladeira: { id: qtd } }
//
// Toda mudança dispara o evento 'kaia:economia' no window (detail = saldo novo).

(function () {
    'use strict';

    // ---- CONSTANTES (calibre aqui) ----
    const XP_POR_NIVEL  = 10;    // acerto vale nível × 10 (1→10 … 5→50); moedas = mesmo valor
    const FATOR_REVISAO = 0.7;   // acertou na correção de erro: 70% do valor, Math.floor
    // Folga do foguinho: DESLIGADA nesta versão (nada chama). Fica aqui pra ligar depois.
    const CUSTO_FOLGA_XP = 100;

    // ---- TABELA DE COMIDAS ----
    // reacaoBase: fallback se o emoji de reação não renderizar no navegador (ZWJ/Emoji 11+).
    // Preços pré-beta (calibrar depois): altos de propósito pra uma sessão não comprar a
    // loja toda — as caras viram objetivo. A loja mostra na ordem desta lista.
    const COMIDAS = [
        { id: 'bala',         nome: 'Bala',          emoji: '🍬', preco: 20,   reacao: '😋', reacaoBase: '😋', frase: 'Docinho! Valeu!' },
        { id: 'gelo',         nome: 'Gelo',          emoji: '🧊', preco: 20,   reacao: '🥶', reacaoBase: '😬', frase: 'Brrr, que gelado!' },
        { id: 'cebola',       nome: 'Cebola',        emoji: '🧅', preco: 30,   reacao: '😭', reacaoBase: '😭', frase: 'Por que você fez isso comigo?' },
        { id: 'pimenta',      nome: 'Pimenta',       emoji: '🌶️', preco: 35,   reacao: '🥵', reacaoBase: '😅', frase: 'Tá pegando fogo!' },
        { id: 'hortela',      nome: 'Hortelã',       emoji: '🌿', preco: 35,   reacao: '😮‍💨', reacaoBase: '😌', frase: 'Hálito fresquinho!' },
        { id: 'limao',        nome: 'Limão',         emoji: '🍋', preco: 35,   reacao: '😖', reacaoBase: '😖', frase: 'Aaazedo!' },
        { id: 'cafe',         nome: 'Café',          emoji: '☕', preco: 60,   reacao: '😳', reacaoBase: '😲', frase: 'Agora eu tô ligadão!' },
        { id: 'pirulito',     nome: 'Pirulito',      emoji: '🍭', preco: 90,   reacao: '😵‍💫', reacaoBase: '😵', frase: 'Tudo girando de tanto açúcar!' },
        { id: 'biscoito',     nome: 'Biscoito',      emoji: '🍪', preco: 130,  reacao: '😋', reacaoBase: '😋', frase: 'Crocante, amei!' },
        { id: 'banana',       nome: 'Banana',        emoji: '🍌', preco: 160,  reacao: '😊', reacaoBase: '😊', frase: 'Minha fruta favorita!' },
        { id: 'cupcake',      nome: 'Cupcake',       emoji: '🧁', preco: 280,  reacao: '😍', reacaoBase: '😍', frase: 'Que coisa mais linda!' },
        { id: 'bolo',         nome: 'Bolo',          emoji: '🍰', preco: 500,  reacao: '🤩', reacaoBase: '😃', frase: 'Uau, um bolo só pra mim!' },
        { id: 'bento',        nome: 'Bentô',         emoji: '🍱', preco: 850,  reacao: '😌', reacaoBase: '😌', frase: 'Refeição completa. Que paz.' },
        { id: 'bolo-festa',   nome: 'Bolo de festa', emoji: '🎂', preco: 1400, reacao: '🥳', reacaoBase: '😄', frase: 'É festa! Obrigado!' },
    ];
    const POR_ID = Object.fromEntries(COMIDAS.map((c) => [c.id, c]));

    // ---- PERSISTÊNCIA ----
    // Uma chave por aluno: computador de escola é compartilhado, saldo não pode vazar
    // entre contas. Mesmo user_id que o login grava.
    function chave() {
        let id = null;
        try { id = localStorage.getItem('kaia_user_id'); } catch (_) {}
        return `kaia_economia:${id || 'anonimo'}`;
    }

    const inteiro = (v) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Math.floor(Number(v)) : 0);

    // Lê validando: localStorage é editável e pode vir corrompido — nunca NaN no saldo.
    function lerSaldo() {
        let bruto = null;
        try { bruto = JSON.parse(localStorage.getItem(chave()) || 'null'); } catch (_) {}
        const geladeira = {};
        const g = bruto && typeof bruto.geladeira === 'object' ? bruto.geladeira : {};
        for (const id of Object.keys(g)) {
            if (POR_ID[id] && inteiro(g[id]) > 0) geladeira[id] = inteiro(g[id]);
        }
        return { xp: inteiro(bruto?.xp), moedas: inteiro(bruto?.moedas), geladeira };
    }

    function gravar(saldo) {
        try {
            localStorage.setItem(chave(), JSON.stringify(saldo));
        } catch (e) {
            console.warn('[KaIA] economia: localStorage recusou a gravação:', e?.name || e);
        }
        window.dispatchEvent(new CustomEvent('kaia:economia', { detail: saldo }));
        return saldo;
    }

    // ---- API ----
    function valorDoAcerto(nivel, { revisao = false } = {}) {
        const n = Math.min(5, Math.max(1, Math.round(Number(nivel)) || 1));
        const base = n * XP_POR_NIVEL;
        return revisao ? Math.floor(base * FATOR_REVISAO) : base;
    }

    function ganharPorAcerto(nivel, opcoes = {}) {
        const valor = valorDoAcerto(nivel, opcoes);
        const s = lerSaldo();
        s.xp += valor;
        s.moedas += valor;
        gravar(s);
        return { xp: valor, moedas: valor };
    }

    function comprarComida(id) {
        const comida = POR_ID[id];
        if (!comida) return { ok: false, motivo: 'comida-inexistente' };
        const s = lerSaldo();
        if (s.moedas < comida.preco) return { ok: false, motivo: 'sem-moedas' };
        s.moedas -= comida.preco;
        s.geladeira[id] = (s.geladeira[id] || 0) + 1;
        gravar(s);
        return { ok: true, saldo: s };
    }

    function consumirDaGeladeira(id) {
        const s = lerSaldo();
        if (!s.geladeira[id]) return false;
        s.geladeira[id] -= 1;
        if (!s.geladeira[id]) delete s.geladeira[id];
        gravar(s);
        return true;
    }

    // Outra aba (ex: matérias) mexeu no saldo → avisa esta também.
    window.addEventListener('storage', (e) => {
        if (e.key === chave()) window.dispatchEvent(new CustomEvent('kaia:economia', { detail: lerSaldo() }));
    });

    window.kaiaEconomia = Object.freeze({
        COMIDAS,
        FATOR_REVISAO,
        CUSTO_FOLGA_XP,
        comida: (id) => POR_ID[id] || null,
        valorDoAcerto,
        ganharPorAcerto,
        comprarComida,
        consumirDaGeladeira,
        lerSaldo,
    });
})();
