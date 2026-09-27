// ============================================================
//  KaIA — puros.js: funções puras / utilitárias, SEM estado e SEM
//  side-effects no load. Fonte única compartilhada entre:
//   - o browser  -> expõe como globais (via globalThis), como eram antes;
//   - os testes  -> Vitest importa este arquivo (side-effect) e lê de globalThis.
//  Carregar ANTES de materias.js.
// ============================================================
(function (raiz) {
    'use strict';

    // Tempo de leitura estimado (s) — vira o limite de ociosidade da questão.
    function calculateReadingTime(text, options) {
        const palavras = (text + ' ' + options.join(' ')).split(/\s+/).length;
        return Math.ceil(palavras / 3.3) + 5;
    }

    // Bytes reais que um data URL base64 ocupa depois de decodificado.
    function bytesDataUrl(dataUrl) {
        const virgula = dataUrl.indexOf(',');
        const b64 = virgula >= 0 ? dataUrl.slice(virgula + 1) : dataUrl;
        const pad = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0;
        return Math.floor(b64.length * 3 / 4) - pad;
    }

    // Cria a lista de botões (temas ou alternativas) dentro de um container.
    function renderBotoes(container, itens, aoClicar) {
        container.innerHTML = '';
        itens.forEach((item, idx) => {
            const btn = document.createElement('button');
            btn.className = 'option-btn';
            btn.innerText = typeof item === 'string' ? item : item.texto;
            btn.onclick = () => aoClicar(item, idx, btn);
            container.appendChild(btn);
        });
    }

    // Nível guardado por matéria, envelhecido pelo tempo sem praticar. Fica aqui (e não
    // em materias.js) porque é pura: dado o registro e o agora, devolve o nível -- e por
    // isso dá para testar o decaimento sem mexer em localStorage.
    //
    // Cai UM nível a cada janela sem tocar na matéria, em vez de voltar ao piso: modelar
    // esquecimento é razoável, mandar quem estava no 4 de volta ao 2 não é -- e
    // reconquistar custa uma rodada de questões fáceis demais, que é convite ao tédio.
    function nivelComDecaimento(reg, agora, janelaDias = 14, min = 1, max = 5) {
        if (!reg || !Number.isInteger(reg.nivel)) return 2;
        const dias = Math.max(0, (agora - (reg.em || 0)) / 86400000);
        const quedas = Math.floor(dias / janelaDias);
        return Math.max(min, Math.min(reg.nivel - quedas, max));
    }

    raiz.calculateReadingTime = calculateReadingTime;
    raiz.bytesDataUrl = bytesDataUrl;
    raiz.renderBotoes = renderBotoes;
    raiz.nivelComDecaimento = nivelComDecaimento;
})(globalThis);
