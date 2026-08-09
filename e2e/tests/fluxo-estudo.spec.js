import { test, expect } from '@playwright/test';

// ⚠️ TEMPLATE — não validado pelo Claude (ele não roda navegador). Mostra o padrão
// pra testar páginas INTERNAS sem backend real:
//   1) "fingir logado" injetando a sessão no storage (o app lê de lá);
//   2) mockar as chamadas de API com page.route (respostas canned);
//   3) afirmar que a tela carrega — e, no TODO, que interagir NÃO recarrega a
//      página (a classe do bug que você viveu: feedback recarregava a matéria).
// Ajuste seletores/rotas ao seu fluxo real.

const A = 'aaaaaaaa-0000-0000-0000-00000000000a';

async function fingirLogado(page) {
  await page.addInitScript((uid) => {
    localStorage.setItem('kaia_user_id', uid);
    sessionStorage.setItem('kaia_usuario', JSON.stringify({
      user_id: uid, email: 'aluno@teste.com', nome: 'Aluno', role: 'aluno',
    }));
    sessionStorage.setItem('hobbies', JSON.stringify(['Jogos']));
  }, A);
}

async function mockarBackend(page) {
  await page.route('**/temas', (r) => r.fulfill({ json: { temas: ['Sintaxe', 'Morfologia'] } }));
  await page.route('**/questoes/hoje**', (r) => r.fulfill({ json: { respondidas_hoje: 0, meta: 10 } }));
  await page.route('**/perfil**', (r) => r.fulfill({ json: { user_id: A, hobbies: ['Jogos'] } }));
  await page.route('**/sessions', (r) => r.fulfill({ json: { status: 'ok', session_id: 's1', user_id: A } }));
  await page.route('**/events', (r) => r.fulfill({ json: { status: 'ok', event_id: 'e1' } }));
  await page.route('**/intervencao/pendente**', (r) => r.fulfill({ json: { pendente: null } }));
  // TODO: mockar '**/gerar-questao' com uma questão pra dirigir o quiz.
}

test('matérias carrega logado e mostra o menu inicial', async ({ page }) => {
  const erros = [];
  page.on('pageerror', (e) => erros.push(String(e)));

  await fingirLogado(page);
  await mockarBackend(page);
  await page.goto('/pages/materias.html');

  // #menu-view é a tela inicial (seleção de matéria).
  await expect(page.locator('#menu-view')).toBeVisible();

  await test.info().attach('page-errors.txt', { body: erros.join('\n') || '(nenhum)' });
});

// TODO (a completar por você — é o teste que pega o bug do "feedback recarrega"):
//
// test('responder questão mostra feedback e NÃO recarrega', async ({ page }) => {
//   await fingirLogado(page);
//   await mockarBackend(page);
//   await page.route('**/gerar-questao', (r) => r.fulfill({ json: {
//     q: 'Enunciado?', opts: ['A', 'B', 'C', 'D', 'E'], ans: 0,
//     explicacao: '...', porque_erradas: ['', '', '', '', ''],
//   }}));
//   await page.goto('/pages/materias.html');
//   const urlAntes = page.url();
//   // clicar numa matéria -> tema -> a questão renderiza em #question-display/#options-display
//   // clicar uma opção (.option-btn) -> #feedback fica visível
//   // clicar um feedback de intervenção -> expect(page.url()).toBe(urlAntes)  // não recarregou
// });
