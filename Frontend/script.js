let idleTime = 0;
let isMissionActive = false;
let currentQuestion = null;
let dynamicLimit = 10; // Tempo padrão (Por Enquanto)
let focusLostAt = null;
let mudancasAba = 0;

// Menu
let aberto = false;
function abrirMenu(){
    let menu = document.getElementById("menu");
    if(aberto == false){
        menu.style.width = "200px";
        aberto = true;
    }else{
        menu.style.width = "0";
        aberto = false;
    }
}

const questions = {
    MAT: [
        { q: "Parte escrita", opts: ["Opção1", "Opção2", "Opção3", "Opção4", "Opção5"], ans: 2 },
    ],
    // Mais perguntas aqui...
};

// --- CÁLCULO DE TEMPO ADAPTÁVEL ---
function calculateReadingTime(text, options) {
    const allText = text + " " + options.join(" ");
    const wordCount = allText.split(/\s+/).length;

    // Média de 200 palavras por minuto (3.3 palavras por segundo)
    // Adicionamos um "buffer" de 5 segundos de segurança
    const readingTime = Math.ceil(wordCount / 3.3) + 5;

    console.log(`Palavras: ${wordCount} | Tempo Adaptado: ${readingTime}s`);
    return readingTime;
}

// ------ PERGUNTAS -----------------

async function enviarPergunta() {

    let pergunta =
        document.getElementById("pergunta").value;

    let respostas =
        document.getElementById("respostas");

    respostas.innerHTML =
        "KaIA pensando...";

    const response = await fetch(
        "http://127.0.0.1:5000/perguntar",
        {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                pergunta: pergunta
            })
        }
    );

    const data = await response.json();

    respostas.innerHTML =
        data.resposta;
}

// ------- MONITOR DE FOCO -----------
setInterval(() => {
    if(isMissionActive) {
        idleTime++;
        document.getElementById('timer').innerText = idleTime;

        // Só escurece se ultrapassar o limite calculado para aquela pergunta específica
        if (idleTime >= dynamicLimit) {
            document.getElementById('overlay').style.opacity = "0.95";
            document.getElementById('system-status').innerText = "FALTA DE INTERAÇÃO";
        }
    }
}, 1000);

document.onmousemove = () => {
    idleTime = 0;
    document.getElementById('overlay').style.opacity = "0";
    if(isMissionActive) document.getElementById('system-status').innerText = "ESTUDANDO";
};

// ------ TEMPO NO LUGAR ERRADO -----------------
document.addEventListener('visibilitychange', () => {
    if (!isMissionActive) return;
  
    if (document.hidden) {
      // saiu da aba
      focusLostAt = performance.now();
      mudancasAba++;
    } else {
      // voltou para a aba
      if (focusLostAt !== null) {
        const duracao_s = (performance.now() - focusLostAt) / 1000;
  
        // Aqui você pode salvar no seu array de eventos depois
        console.log({
          tipo: "tab_change",
          mudancas_aba: mudancasAba,
          tempo_fora_foco_s: parseFloat(duracao_s.toFixed(2))
        });
        focusLostAt = null;
      }
    }
  });

// --- INICIAR MISSÃO ---
function startMission(subject) {
    isMissionActive = true;
    document.getElementById('menu-view').style.display = 'none';
    document.getElementById('quiz-view').style.display = 'block';

    const list = questions[subject];
    currentQuestion = list[Math.floor(Math.random() * list.length)];

    // Define o limite dinâmico com base no texto
    dynamicLimit = calculateReadingTime(currentQuestion.q, currentQuestion.opts);

    document.getElementById('question-display').innerText = currentQuestion.q;
    const optionsDiv = document.getElementById('options-display');
    optionsDiv.innerHTML = "";

    currentQuestion.opts.forEach((opt, idx) => {
        const btn = document.createElement('button');
        btn.className = "option-btn";
        btn.innerText = opt;
        btn.onclick = () => checkAnswer(idx, btn);
        optionsDiv.appendChild(btn);
    });
}

function resetSystem() { location.reload(); }