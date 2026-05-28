let idleTime = 0;
let isMissionActive = false;
let currentQuestion = null;
let dynamicLimit = 10; // Tempo padrão inicial

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
        { q: "Parte escrita", opts: ["Opção1", "Opção2", "Opção3", "Opção4", "Opção5"], ans: 1 },
    ],
    // Adicione mais perguntas aqui...
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

// --- MONITOR DE FOCO ---
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