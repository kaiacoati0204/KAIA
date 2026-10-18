// ============================================================
//  KaIA — coati-loader.js: a espera da IA
// ============================================================
// O coati correndo e uma frase que troca sozinha, no lugar da esfera girante.
// Baunilha, sem framework: a esfera era a única ilha React do projeto, e os dois
// CDNs saíram do materias.html junto com ela.
//
// ISOLAMENTO — só visual, nunca toca sessão, dados ou questões. Monta num <div>
// próprio dentro do container ESTÁVEL `alvo` (.question-wrapper ou #temas-view),
// nunca em #question-display / #temas-display / #options-display: esses levam
// innerHTML = '' e arrancariam o nó no meio de uma troca de frase.
//
// LEITOR DE TELA — quem anuncia é um elemento separado, com texto FIXO. As
// frases ficam em aria-hidden: dentro de aria-live elas interromperiam a leitura
// a cada 4,8s, que é o oposto de ajudar.
(function () {
    'use strict';

    const MOUNT_ID  = 'kaia-coati-loader-root';
    // Trava de segurança: se quem chamou esquecer de esconder, ele sai sozinho e
    // o texto simples volta a aparecer.
    const LIMITE_MS = 45000;

    // ---- AS FRASES ---- texto puro, uma por linha: é aqui que se edita.
    const FRASES = [
        'Pausas curtas ajudam a fixar o que você acabou de estudar.',
        'Uma questão de cada vez rende mais que uma maratona.',
        'Errar e entender por quê é o que faz a nota subir.',
        'O Coati não corre atrás de você — ele espera no caminho de volta.',
        'Sua régua de ritmo é sua: a KaIA compara você com você.',
        'Ninguém estuda bem com fome nem com sono.',
        'Reler não é estudar. Responder é.',
    ];

    // 4,8s em opacidade cheia (o piso pedido é 4,5s) e 0,45s de fade de cada
    // lado — nunca corte seco. O 450 aqui e o `transition` do .kaia-cload__frase
    // no style.css são o MESMO número: mudou um, muda o outro.
    const VISIVEL_MS = 4800;
    const FADE_MS    = 450;

    let caixa = null, frase = null, relogio = 0, limite = 0, anterior = -1;

    // Sorteia sem repetir a frase anterior.
    function sortear() {
        if (FRASES.length < 2) return 0;
        let i;
        do { i = Math.floor(Math.random() * FRASES.length); } while (i === anterior);
        anterior = i;
        return i;
    }

    function montar() {
        if (caixa) return;
        caixa = document.createElement('div');
        caixa.id = MOUNT_ID;
        caixa.className = 'kaia-cload';

        // Texto FIXO e anunciado uma vez. Vem antes no DOM para o leitor de tela
        // chegar nele primeiro.
        const leitor = document.createElement('span');
        leitor.className = 'kaia-cload__leitor';
        leitor.setAttribute('role', 'status');
        leitor.textContent = 'Gerando questão';

        // MASTER NO AFFINITY. Mudança de arte se faz lá e se reexporta neste
        // mesmo nome e tamanho — este PNG tem 420px de largura para servir os
        // 140px de uso em telas 3x, e AMPLIÁ-LO só borra.
        const coati = document.createElement('img');
        coati.className = 'kaia-cload__coati';
        coati.src = '../assets/Correndinho-Coati.png';
        coati.alt = '';            // quem nomeia o que acontece é o role="status"
        // Só a PROPORÇÃO (4:3, de 420x315): reserva a caixa antes de a imagem
        // chegar e evita o salto de layout. Quem manda no tamanho é o
        // `width` do .kaia-cload__coati no style.css, com height:auto.
        coati.width = 170;
        coati.height = 128;

        frase = document.createElement('p');
        frase.className = 'kaia-cload__frase';
        frase.setAttribute('aria-hidden', 'true');   // decorativa
        frase.textContent = FRASES[sortear()];

        caixa.append(leitor, coati, frase);
    }

    function trocar() {
        if (!frase) return;
        frase.classList.add('kaia-cload__frase--saindo');
        relogio = setTimeout(function () {
            frase.textContent = FRASES[sortear()];
            frase.classList.remove('kaia-cload__frase--saindo');
            relogio = setTimeout(trocar, VISIVEL_MS + FADE_MS);
        }, FADE_MS);
    }

    // Mostra o loader dentro de `alvo`. Devolve false se não montou — o chamador
    // então mantém o texto simples, sem tela quebrada.
    function mostrar(rotulo, alvo) {
        try {
            montar();
            // Tudo escrito ANTES de entrar no DOM: mexer no role="status" com ele
            // já na página dispararia um segundo anúncio.
            if (rotulo) caixa.firstChild.textContent = rotulo;
            anterior = -1;
            frase.classList.remove('kaia-cload__frase--saindo');
            frase.textContent = FRASES[sortear()];
            const pai = alvo || document.body;
            if (caixa.parentNode !== pai) pai.appendChild(caixa);
            clearTimeout(relogio);
            relogio = setTimeout(trocar, VISIVEL_MS + FADE_MS);
            clearTimeout(limite);
            limite = setTimeout(esconder, LIMITE_MS);
            return true;
        } catch (e) {
            console.warn('[KaIA] coati de espera não montou:', e);
            return false;
        }
    }

    // Tira o nó do DOM e para os dois relógios: sem timer girando atrás de um
    // elemento que ninguém vê.
    function esconder() {
        clearTimeout(relogio); relogio = 0;
        clearTimeout(limite);  limite  = 0;
        try {
            if (caixa && caixa.parentNode) caixa.remove();
        } catch (e) {
            console.warn('[KaIA] coati de espera não escondeu:', e);
        }
    }

    window.KaiaCoatiLoader = { mostrar, esconder };
})();
