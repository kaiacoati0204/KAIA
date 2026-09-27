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

describe('nivelComDecaimento', () => {
  const { nivelComDecaimento } = globalThis;
  const AGORA = Date.parse('2026-09-27T12:00:00Z');
  const diasAtras = (d) => AGORA - d * 86400000;

  it('sem registro, começa no 2', () => {
    expect(nivelComDecaimento(null, AGORA)).toBe(2);
    expect(nivelComDecaimento({}, AGORA)).toBe(2);
  });

  it('mantém o nível de quem praticou há pouco', () => {
    expect(nivelComDecaimento({ nivel: 4, em: diasAtras(3) }, AGORA)).toBe(4);
    expect(nivelComDecaimento({ nivel: 4, em: diasAtras(13) }, AGORA)).toBe(4);
  });

  it('cai UM nível por janela sem praticar — não volta ao piso', () => {
    expect(nivelComDecaimento({ nivel: 5, em: diasAtras(14) }, AGORA)).toBe(4);
    expect(nivelComDecaimento({ nivel: 5, em: diasAtras(30) }, AGORA)).toBe(3);
  });

  it('nunca desce abaixo do mínimo nem sobe acima do máximo', () => {
    expect(nivelComDecaimento({ nivel: 2, em: diasAtras(365) }, AGORA)).toBe(1);
    expect(nivelComDecaimento({ nivel: 9, em: AGORA }, AGORA)).toBe(5);
  });

  it('registro do futuro (relógio torto) não sobe o nível', () => {
    expect(nivelComDecaimento({ nivel: 3, em: AGORA + 86400000 }, AGORA)).toBe(3);
  });
});
