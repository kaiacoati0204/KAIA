// Camada A — funções PURAS (sem DOM). Ambiente node (padrão).
// Importa puros.js (side-effect) -> popula globalThis, que é o que o browser vê.
import { describe, it, expect } from 'vitest';
import '../js/puros.js';

const { calculateReadingTime, bytesDataUrl } = globalThis;

describe('calculateReadingTime', () => {
  it('conta palavras (enunciado + alternativas) e soma o piso de 5s', () => {
    // 'a b c' + 'd e f' = 6 palavras -> ceil(6/3.3)=2, +5 = 7
    expect(calculateReadingTime('a b c', ['d', 'e f'])).toBe(7);
  });

  it('cresce com texto mais longo', () => {
    const curto = calculateReadingTime('uma questao', ['a']);
    const longo = calculateReadingTime(
      'uma questao bem mais longa com varias palavras', ['alternativa a', 'alternativa b']);
    expect(longo).toBeGreaterThan(curto);
  });

  it('nunca fica abaixo do piso de 5s', () => {
    expect(calculateReadingTime('', [''])).toBeGreaterThanOrEqual(5);
  });
});

describe('bytesDataUrl', () => {
  it('desconta o padding "=" do base64 (SGk= -> 2 bytes)', () => {
    expect(bytesDataUrl('data:image/png;base64,SGk=')).toBe(2);
  });

  it('funciona sem o prefixo data:', () => {
    expect(bytesDataUrl('SGk=')).toBe(2);
  });

  it('desconta padding duplo "==" ', () => {
    // "TWE=" -> 2 bytes; "TQ==" -> 1 byte
    expect(bytesDataUrl('data:x;base64,TQ==')).toBe(1);
  });
});
