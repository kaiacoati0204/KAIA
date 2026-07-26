// ============================================================
//  KaIA — hobbies.js: onboarding de hobbies (seleção inicial)
// ============================================================
// Depende de comum.js (lerHobbies, lerPerfil, gravarPerfil, enviarPerfil).
// salvarHobbies() é global (onclick inline no HTML). Só hobbies.html usa.

// A lista vive aqui (e não no HTML) para que o backend e a página de onboarding
// compartilhem a mesma fonte de verdade — os hobbies alimentam o prompt da IA.
const HOBBIES = [
    'Futebol', 'Basquete', 'Vôlei', 'Natação', 'Corrida', 'Ciclismo', 'Academia', 'Yoga', 'Dança',
    'Tricô', 'Crochê', 'Costura', 'Pintar', 'Desenho', 'Escultura', 'Fotografia',
    'RPG', 'Videogames', 'Jogos de Tabuleiro', 'Xadrez', 'Quebra-cabeças',
    'Culinária', 'Confeitaria', 'Churrasco',
    'Música', 'Cantar', 'Violão', 'Piano', 'Bateria',
    'Leitura', 'Escrita', 'Poesia',
    'Cinema/Filme', 'Séries', 'Anime', 'Mangá',
    'Programação', 'Robótica', 'Modelagem 3D', 'Impressão 3D',
    'Jardinagem', 'Pesca', 'Camping', 'Trilhas', 'Viagens', 'Astronomia',
    'Colecionismo', 'Origami', 'Idiomas', 'Voluntariado',
];

let hobbiesSelecionados = lerHobbies();

function registrarHobbies() {
    const box = document.querySelector('.botoes-hobbies');
    if (!box) return;

    box.innerHTML = '';
    HOBBIES.forEach(nome => {
        const botao = document.createElement('button');
        botao.type = 'button';
        botao.className = 'botao-hobbies';
        botao.textContent = nome;
        botao.classList.toggle('selecionado', hobbiesSelecionados.includes(nome));

        botao.addEventListener('click', () => {
            const jaTinha = hobbiesSelecionados.includes(nome);
            hobbiesSelecionados = jaTinha
                ? hobbiesSelecionados.filter(h => h !== nome)
                : [...hobbiesSelecionados, nome];
            botao.classList.toggle('selecionado', !jaTinha);
        });

        box.appendChild(botao);
    });
}

function salvarHobbies() {
    sessionStorage.setItem('hobbies', JSON.stringify(hobbiesSelecionados));
    gravarPerfil({ ...lerPerfil(), hobbies: hobbiesSelecionados });
    enviarPerfil({ tipo: 'hobbies' });
    window.location.href = 'index.html';
}

document.addEventListener('DOMContentLoaded', registrarHobbies);
