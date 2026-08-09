// @vitest-environment jsdom
// Camada B — funções que mexem no DOM. Ambiente jsdom (DOM simulado).
import { describe, it, expect } from 'vitest';
import '../js/puros.js';

const { renderBotoes } = globalThis;

describe('renderBotoes (jsdom)', () => {
  it('cria um botão por item, com a classe option-btn', () => {
    const box = document.createElement('div');
    renderBotoes(box, ['Álgebra', 'Geometria'], () => {});
    const botoes = box.querySelectorAll('button.option-btn');
    expect(botoes.length).toBe(2);
    expect(botoes[0].innerText).toBe('Álgebra');
  });

  it('itens objeto usam .texto e o clique dispara o callback com (item, idx, btn)', () => {
    const box = document.createElement('div');
    const cliques = [];
    const item = { texto: 'Continuar' };
    renderBotoes(box, [item], (it, idx, btn) => cliques.push([it, idx, btn.tagName]));
    const btn = box.querySelector('button');
    expect(btn.innerText).toBe('Continuar');
    btn.onclick();
    expect(cliques).toEqual([[item, 0, 'BUTTON']]);
  });

  it('limpa o container antes de renderizar', () => {
    const box = document.createElement('div');
    box.innerHTML = '<span>lixo</span>';
    renderBotoes(box, ['X'], () => {});
    expect(box.querySelector('span')).toBeNull();
    expect(box.querySelectorAll('button').length).toBe(1);
  });
});
