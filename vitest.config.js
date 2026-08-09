import { defineConfig } from 'vitest/config';

// Só os testes de front ficam sob Frontend/tests. Ambiente padrão = node
// (camada A); os de DOM trocam para jsdom via `// @vitest-environment jsdom`.
export default defineConfig({
  test: {
    include: ['Frontend/tests/**/*.test.js'],
  },
});
