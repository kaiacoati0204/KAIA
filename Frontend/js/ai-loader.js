// ============================================================
//  KaIA — ai-loader.js: ilha React do AI Loader
// ============================================================
// Porte do "AI Loader" do 21st.dev (@beratberkayg) em pt-BR, paleta do Coati e INLINE (o original é
// overlay). A animação é CSS (.kaia-ail* no style.css, 1:1 do original, 5s/3s); o React só quebra a
// palavra em letras com animation-delay em cascata — sem Framer Motion, como o original.
//
// ISOLAMENTO — ilha SÓ visual, nunca toca em sessão, dados ou questões. Monta num <div> próprio dentro
// do container ESTÁVEL `alvo` (.question-wrapper ou #temas-view), nunca em #question-display /
// #temas-display / #options-display: eles levam innerHTML = '' ou innerText, o que arrancaria a raiz
// React sem desmontar (vaza listeners, quebra o render seguinte). Sem o CDN do React, mostrar()
// devolve false e o materias.js mantém o texto simples.
(function () {
    'use strict';

    const MOUNT_ID  = 'kaia-ai-loader-root';
    const TAMANHO   = 180;      // px — mesmo default do componente original
    // Trava de segurança: se quem chamou esquecer de esconder, ele sai sozinho e
    // o texto simples volta a aparecer. Inline o risco é menor que no overlay,
    // mas a rede de proteção continua barata.
    const LIMITE_MS = 45000;

    let raiz  = null;   // root do ReactDOM
    let caixa = null;   // div de montagem (sempre o mesmo nó, movido entre alvos)
    let timer = 0;

    const temReact = () =>
        !!(window.React && window.ReactDOM && typeof window.ReactDOM.createRoot === 'function');

    // Equivalente ao Component.tsx original: letras + esfera girando por cima.
    function Loader(props) {
        const R = window.React;

        const filhos = String(props.palavra).split('').map((ch, i) =>
            R.createElement('span', {
                key: i,
                className: 'kaia-ail__letra',
                style: { animationDelay: (i * 0.1) + 's' },   // a cascata do original
            }, ch === ' ' ? ' ' : ch)
        );
        filhos.push(R.createElement('div', { key: 'esfera', className: 'kaia-ail__esfera' }));

        return R.createElement('div', {
            className: 'kaia-ail',
            role: 'status',
            'aria-live': 'polite',
            'aria-label': props.rotulo,     // leitor de tela lê isto, não as letras soltas
        }, R.createElement('div', {
            className: 'kaia-ail__palco',
            style: { width: props.tamanho + 'px', height: props.tamanho + 'px' },
            'aria-hidden': 'true',          // decorativo: evita "G e r a n d o" no leitor
        }, filhos));
    }

    function garantirCaixa() {
        if (caixa) return;
        caixa = document.createElement('div');
        caixa.id = MOUNT_ID;
        raiz = window.ReactDOM.createRoot(caixa);
    }

    // Mostra o loader dentro de `alvo`. Devolve false se a ilha não estiver
    // disponível — o chamador então mantém o texto simples, sem tela quebrada.
    function mostrar(palavra, rotulo, alvo) {
        if (!temReact()) return false;
        try {
            garantirCaixa();
            const pai = alvo || document.body;
            if (caixa.parentNode !== pai) pai.appendChild(caixa);   // move o nó; raiz segue válida
            raiz.render(window.React.createElement(Loader, {
                palavra: palavra || 'Gerando',
                rotulo:  rotulo  || 'Carregando',
                tamanho: TAMANHO,
            }));
            clearTimeout(timer);
            timer = setTimeout(esconder, LIMITE_MS);
            return true;
        } catch (e) {
            console.warn('[KaIA] AI Loader não montou:', e);
            return false;
        }
    }

    // Render vazio + nó fora do DOM: não deixa espaço em branco no layout. A raiz
    // NÃO é destruída, então o próximo mostrar() só reinsere o mesmo nó.
    function esconder() {
        clearTimeout(timer);
        timer = 0;
        try {
            if (raiz) raiz.render(null);
            if (caixa && caixa.parentNode) caixa.remove();
        } catch (e) {
            console.warn('[KaIA] AI Loader não escondeu:', e);
        }
    }

    window.KaiaAILoader = { mostrar, esconder };
})();
