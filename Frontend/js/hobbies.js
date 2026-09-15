// ============================================================
//  KaIA — hobbies.js: onboarding de hobbies (seleção inicial)
// ============================================================
// Depende de comum.js (lerHobbies, lerPerfil, gravarPerfil, enviarPerfil).
// salvarHobbies() é global (onclick inline no HTML). Só hobbies.html usa.

// A lista vive aqui (e não no HTML) para que o backend e a página de onboarding
// compartilhem a mesma fonte de verdade — os hobbies alimentam o prompt da IA.
// Categorias são SÓ visuais: o que se grava e envia continua a lista plana de nomes.
const HOBBIES_POR_CATEGORIA = [
    ['Esportes e movimento', ['Futebol', 'Basquete', 'Vôlei', 'Natação', 'Corrida', 'Ciclismo', 'Academia', 'Yoga', 'Dança']],
    ['Artes e trabalhos manuais', ['Pintar', 'Desenho', 'Escultura', 'Fotografia', 'Tricô', 'Crochê', 'Costura']],
    ['Jogos', ['RPG', 'Videogames', 'Jogos de Tabuleiro', 'Xadrez', 'Quebra-cabeças']],
    ['Cozinha', ['Culinária', 'Confeitaria', 'Churrasco']],
    ['Música', ['Música', 'Cantar', 'Violão', 'Piano', 'Bateria']],
    ['Leitura e escrita', ['Leitura', 'Escrita', 'Poesia']],
    ['Telas e histórias', ['Cinema/Filme', 'Séries', 'Anime', 'Mangá']],
    ['Tecnologia', ['Programação', 'Robótica', 'Modelagem 3D', 'Impressão 3D']],
    ['Ar livre', ['Jardinagem', 'Pesca', 'Camping', 'Trilhas', 'Viagens']],
    ['Outros interesses', ['Astronomia', 'Colecionismo', 'Origami', 'Idiomas', 'Voluntariado']],
];
const HOBBIES = HOBBIES_POR_CATEGORIA.flatMap(([, itens]) => itens);

let hobbiesSelecionados = lerHobbies();

function registrarHobbies() {
    const box = document.querySelector('.grupos-hobbies');
    if (!box) return;

    box.innerHTML = '';
    HOBBIES_POR_CATEGORIA.forEach(([titulo, itens], i) => {
        const grupo = document.createElement('section');
        grupo.className = 'grupo-hobbies';
        grupo.setAttribute('aria-labelledby', `hobbies-cat-${i}`);

        const h2 = document.createElement('h2');
        h2.className = 'hobbies-categoria';
        h2.id = `hobbies-cat-${i}`;
        h2.textContent = titulo;

        const grade = document.createElement('div');
        grade.className = 'botoes-hobbies';
        itens.forEach(nome => grade.appendChild(criarBotaoHobbie(nome)));

        grupo.append(h2, grade);
        box.appendChild(grupo);
    });
}

function criarBotaoHobbie(nome) {
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.className = 'botao-hobbies';
    botao.textContent = nome;
    botao.classList.toggle('selecionado', hobbiesSelecionados.includes(nome));
    botao.setAttribute('aria-pressed', String(hobbiesSelecionados.includes(nome)));   // leitor de tela ouve o estado, não só a cor

    botao.addEventListener('click', () => {
        const jaTinha = hobbiesSelecionados.includes(nome);
        hobbiesSelecionados = jaTinha
            ? hobbiesSelecionados.filter(h => h !== nome)
            : [...hobbiesSelecionados, nome];
        botao.classList.toggle('selecionado', !jaTinha);
        botao.setAttribute('aria-pressed', String(!jaTinha));
    });
    return botao;
}

function salvarHobbies() {
    sessionStorage.setItem('hobbies', JSON.stringify(hobbiesSelecionados));
    gravarPerfil({ ...lerPerfil(), hobbies: hobbiesSelecionados });
    enviarPerfil({ tipo: 'hobbies' });
    window.location.href = 'materias.html';   // home do aluno logado (index virou landing pública)
}

document.addEventListener('DOMContentLoaded', registrarHobbies);
