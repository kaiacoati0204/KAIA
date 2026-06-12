// --- Configuração -----------------------------------------------------------------------
// Use 127.0.0.1 (IPv4) em vez de "localhost": no Windows "localhost" pode
// resolver para IPv6 (::1) e o Flask dev server só escuta em IPv4 → "não responde".
const API_URL = (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_URL)
    || 'http://127.0.0.1:5000';

// --- Estado da sessão --------------------------------------
let sessionId       = crypto.randomUUID();
let isMissionActive = false;
let idleInterval    = null;

// --- Estado dos sensores -----------------------------------
let idleTime        = 0;
let dynamicLimit    = 10;

let focusLostAt     = null;
let mudancasAba     = 0;

let lastScrollY     = 0;
let lastScrollTime  = 0;

let lastKeystroke   = 0;
let keystrokeTimer  = null;

// --- Questão atual -----------------------------------------
let currentQuestion = null;

// --- Banco de questões -------------------------------------
const questions = {
    MAT: [
        { q: "Parte escrita", opts: ["Opção1", "Opção2", "Opção3", "Opção4", "Opção5"], ans: 2 },
        // mais perguntas aqui...
    ],
    PORT: [
        { q: "Parte escrita", opts: ["Opção1", "Opção2", "Opção3", "Opção4", "Opção5"], ans: 0 },
        // mais perguntas aqui...
    ],
    HIS: [
        { q: "Parte escrita", opts: ["Opção1", "Opção2", "Opção3", "Opção4", "Opção5"], ans: 1 },
        // mais perguntas aqui...
    ],
};

// ============================================================
//                  CORE: logEvent
// ============================================================
function logEvent(type, payload) {
    const event = {
        session_id: sessionId,
        ts: new Date().toISOString(),
        event_type: type,
        payload
    };

    console.log('[KaIA Event]', event);

    // Envia para o backend (não bloqueia a UI; ignora falha se a API estiver off)
    fetch(`${API_URL}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(event),
        keepalive: true
    }).catch(() => {});
}

// ============================================================
//        CAMADA DE DADOS — PERFIL + FEATURES (Supabase-ready)
// ============================================================
// Tudo é persistido em localStorage sob a chave 'kaia_perfil' e
// espelhado no backend (/perfil). Quando você plugar o Supabase,
// basta trocar `enviarPerfil` por um insert/upsert na tabela `perfis`.

function lerPerfil() {
    return JSON.parse(localStorage.getItem('kaia_perfil') || '{}');
}
function gravarPerfil(perfil) {
    localStorage.setItem('kaia_perfil', JSON.stringify(perfil));
}

// Snapshot NÃO-mutável das features (apenas leitura, p/ enviar junto dos dados)
function snapshotFeatures() {
    const agora   = new Date();
    const perfil  = lerPerfil();
    const dias    = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sab'];
    const hh      = String(agora.getHours()).padStart(2, '0');
    const mm      = String(agora.getMinutes()).padStart(2, '0');

    // duracao_pausa_anterior_min — minutos desde a última sessão registrada
    let duracaoPausa = null;
    if (perfil.ultima_sessao_ts) {
        duracaoPausa = parseFloat(((agora.getTime() - perfil.ultima_sessao_ts) / 60000).toFixed(2));
    }

    // dias_para_prova — só se o usuário informou a data (onboarding/calendário)
    let diasParaProva = null;
    if (perfil.data_prova) {
        const prova = new Date(perfil.data_prova);
        diasParaProva = Math.max(0, Math.ceil((prova - agora) / 86400000));
    }

    return {
        horario_inicio:             `${hh}:${mm}`,                       // TIME   — extraído do relógio
        sessoes_no_dia:             perfil.sessoes_no_dia || 0,          // INTEGER— contador local
        dia_semana:                 dias[agora.getDay()],                // ENUM   — derivado do timestamp
        dias_para_prova:            diasParaProva,                       // INTEGER— null se não informado
        sequencia_dias_estudo:      perfil.sequencia_dias_estudo || 0,   // INTEGER— streak
        duracao_pausa_anterior_min: duracaoPausa,                        // FLOAT  — intervalo entre sessões
        ambiente_dispositivo:       perfil.ambiente_dispositivo || null  // ENUM   — auto-declarado (onboarding)
    };
}

// Mutável: chamado quando uma sessão de ESTUDO começa (atualiza streak/contadores)
function registrarInicioSessao() {
    const agora   = new Date();
    const perfil  = lerPerfil();
    const hojeStr = agora.toISOString().slice(0, 10);

    if (perfil.ultimo_dia_estudo === hojeStr) {
        perfil.sessoes_no_dia = (perfil.sessoes_no_dia || 0) + 1;       // mais uma sessão hoje
    } else {
        const ontem = new Date(agora);
        ontem.setDate(ontem.getDate() - 1);
        const ontemStr = ontem.toISOString().slice(0, 10);
        // manteve o hábito se estudou ontem; senão zera o streak
        perfil.sequencia_dias_estudo =
            (perfil.ultimo_dia_estudo === ontemStr) ? (perfil.sequencia_dias_estudo || 0) + 1 : 1;
        perfil.sessoes_no_dia = 1;
    }

    perfil.ultimo_dia_estudo = hojeStr;
    perfil.ultima_sessao_ts  = agora.getTime();
    gravarPerfil(perfil);
    return snapshotFeatures();
}

// Hooks de onboarding (chame quando tiver os campos no formulário)
function definirAmbiente(valor)  { const p = lerPerfil(); p.ambiente_dispositivo = valor; gravarPerfil(p); } // 'silencioso' | 'ruido_moderado' | 'ruido_alto'
function definirDataProva(iso)   { const p = lerPerfil(); p.data_prova = iso;            gravarPerfil(p); } // 'AAAA-MM-DD'

// Envia o pacote completo (login + hobbies + features) para o backend
async function enviarPerfil(extra = {}) {
    const payload = {
        session_id: sessionId,
        ts:         new Date().toISOString(),
        perfil:     lerPerfil(),
        hobbies:    historicoDeCliques,
        features:   snapshotFeatures(),
        ...extra
    };
    try {
        await fetch(`${API_URL}/perfil`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            keepalive: true
        });
    } catch (e) {
        console.warn('[KaIA] /perfil indisponível (salvo só localmente):', e);
    }
}

// Chamado pelo botão "Entrar" / "Criar conta" do login.html
function salvarLogin(event) {
    if (event) event.preventDefault();
    const email = document.getElementById('login-email')?.value.trim() || '';
    // OBS: a senha NÃO é guardada em texto puro — no Supabase use o Auth (supabase.auth.signIn)
    const perfil = lerPerfil();
    perfil.email = email;
    gravarPerfil(perfil);
    enviarPerfil({ tipo: 'login', email });
    window.location.href = 'hobbies.html';
}

// ==================================================================================================
//                          MENU
// ===================================================================================================
let aberto = false;

function abrirMenu() {
    const menu = document.getElementById('menu');
    if (!aberto) {
        menu.style.width = '200px';
        aberto = true;
    } else {
        menu.style.width = '0';
        aberto = false;
    }
}

// ============================================================
//                       HOBBIES
// ============================================================
let historicoDeCliques = JSON.parse(sessionStorage.getItem('hobbies') || '[]');
const botoes = document.querySelectorAll('.botao-hobbies');

botoes.forEach(botao => {
    botao.addEventListener('click', function (evento) {
        evento.preventDefault();
        const nome = this.getAttribute('data-nome');

        if (historicoDeCliques.includes(nome)) {
            // já estava selecionado → remove
            historicoDeCliques = historicoDeCliques.filter(h => h !== nome);
            this.classList.remove('selecionado');
        } else {
            // não estava → adiciona
            historicoDeCliques.push(nome);
            this.classList.add('selecionado');
        }

        console.log('Hobbies:', historicoDeCliques);
    });
});

function salvarHobbies() {
    sessionStorage.setItem('hobbies', JSON.stringify(historicoDeCliques));
    const perfil = lerPerfil();
    perfil.hobbies = historicoDeCliques;
    gravarPerfil(perfil);
    enviarPerfil({ tipo: 'hobbies' });
    window.location.href = 'index.html';
}

async function enviarParaIA(historicoBotoes) {
    if (campoTexto) campoTexto.innerText = 'A KaIA está pensando...';
    try {
        const resposta = await fetch(`${API_URL}/pergunta-ia`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: `O usuário escolheu os seguintes hobbies/opções no site: ${historicoBotoes.join(', ')}. 
                         Responda a questão com referências a esses hobbies para que o aluno entenda adequadamente.`
            })
        });
        const dados = await resposta.json();
        if (campoTexto) campoTexto.innerText = dados.respostaDaIA;
    } catch (erro) {
        if (campoTexto) campoTexto.innerText = 'Houve um erro ao conversar com a IA.';
        console.error(erro);
    }
}

// ============================================================
//                  FAÇA-SE A LUZ
// ============================================================
const luz = document.getElementById('luzFundo');
const container = document.querySelector('.tela-login');

// Só ativa a luz se a página realmente tiver o elemento (evita travar
// o script inteiro em páginas sem .tela-login, como o index.html).
if (luz && container) {
    let luzX = window.innerWidth / 2;
    let luzY = window.innerHeight / 2;
    const raioFuga = 300;

    container.addEventListener('mousemove', (e) => {
        const mouseX = e.clientX;
        const mouseY = e.clientY;
        const dx = luzX - mouseX;
        const dy = luzY - mouseY;
        const distancia = Math.sqrt(dx * dx + dy * dy);
        if (distancia < raioFuga) {
            const forca = (raioFuga - distancia) / raioFuga;
            const direcaoX = dx / distancia;
            const direcaoY = dy / distancia;

            luzX += direcaoX * forca * 30;
            luzY += direcaoY * forca * 30;
            luzX = Math.max(50, Math.min(window.innerWidth - 50, luzX));
            luzY = Math.max(50, Math.min(window.innerHeight - 50, luzY));
            luz.style.left = `${luzX}px`;
            luz.style.top = `${luzY}px`;
        }
    });
}

// ============================================================
//                  CÁLCULO DE TEMPO ADAPTÁVEL
// ============================================================
function calculateReadingTime(text, options) {
    const allText   = text + ' ' + options.join(' ');
    const wordCount = allText.split(/\s+/).length;
    const readingTime = Math.ceil(wordCount / 3.3) + 5;
    console.log(`Palavras: ${wordCount} | Tempo adaptado: ${readingTime}s`);
    return readingTime;
}

// ============================================================
//                      PERGUNTAS - CHAT
// ============================================================
async function enviarPergunta() {
    const pergunta  = document.getElementById('pergunta').value;
    const respostas = document.getElementById('respostas');
    respostas.innerHTML = 'KaIA pensando...';
    try {
        const response = await fetch(`${API_URL}/perguntar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pergunta, hobbies: historicoDeCliques })
        });
        const data = await response.json();
        respostas.innerHTML = data.resposta;
    } catch (erro) {
        respostas.innerHTML = 'Erro ao conectar com a IA.';
        console.error(erro);
    }
}

// ============================================================
//              MONITOR DE OCIOSIDADE (idleTime)
// ============================================================
function iniciarIdleMonitor() {
    if (idleInterval) clearInterval(idleInterval);

    idleInterval = setInterval(() => {
        if (!isMissionActive) return;
        idleTime++;
        const timerEl = document.getElementById('timer');
        if (timerEl) timerEl.innerText = idleTime;
        if (idleTime >= dynamicLimit) {
            document.getElementById('overlay').style.opacity   = '0.95';
            document.getElementById('system-status').innerText = 'FALTA DE INTERAÇÃO';
        }
    }, 1000);
}

// ================================================================================================
// -------------------- EVENTOS LISTENER -------------------------------
// ================================================================================================


// ============================================================
//                    MOVIMENTO DO MOUSE
// ============================================================
function registrarMouseMove() {
    const quizView = document.getElementById('quiz-view');
    if (!quizView) return;

    quizView.addEventListener('mousemove', () => {
        if (!isMissionActive) return;
        idleTime = 0;
        document.getElementById('overlay').style.opacity   = '0';
        document.getElementById('system-status').innerText = 'ESTUDANDO';
    });
}

// ============================================================
//              VISIBILITYCHANGE - TROCAS DE ABAS
// ============================================================
document.addEventListener('visibilitychange', () => {
    if (!isMissionActive) return;

    if (document.hidden) {
        focusLostAt = performance.now();
        mudancasAba++;
    } else {
        if (focusLostAt !== null) {
            const duracao_s = (performance.now() - focusLostAt) / 1000;
            logEvent('tab_change', {
                mudancas_aba: mudancasAba,
                tempo_fora_foco_s: parseFloat(duracao_s.toFixed(2))
            });
            focusLostAt = null;
        }
    }
});

// ============================================================
//                           SCROLL
// ============================================================
function registrarScroll() {
    const quizView = document.getElementById('quiz-view');
    if (!quizView) return;

    lastScrollY    = window.scrollY;
    lastScrollTime = performance.now();

    window.addEventListener('scroll', (e) => {
        if (!isMissionActive) return;
    
        const now    = performance.now();
        const deltaT = (now - lastScrollTime) / 1000;
    
        if (deltaT > 0) {
            const deltaY = Math.abs(window.scrollY - lastScrollY);
            const px_s   = deltaY / deltaT;
    
            // Log para você ver o valor real durante o teste
            console.log('[scroll]', { deltaY, deltaT: deltaT.toFixed(3), px_s: px_s.toFixed(1) });
    
            if (px_s > 300) {
                logEvent('scroll_burst', {
                    px_s: parseFloat(px_s.toFixed(1)),
                    duracao_s: parseFloat(deltaT.toFixed(2)),
                    rolagem_sem_leitura: (px_s > 500 && deltaT > 2)
                });
            }
        }
    
        lastScrollY    = window.scrollY;
        lastScrollTime = now;
    }, { passive: true });
}

// ============================================================
//                      TECLADO ESCREVENDO
// ============================================================
function registrarTeclado() {
    let totalTeclas    = 0;
    let totalBackspace = 0;

    document.addEventListener('keydown', (e) => {
        if (!isMissionActive) return;
        const now     = performance.now();
        const pausa_s = (now - lastKeystroke) / 1000;
        totalTeclas++;
        if (e.key === 'Backspace') totalBackspace++;

        if (lastKeystroke > 0 && pausa_s > 3) {
            logEvent('keystroke_pause', {
                duracao_s: parseFloat(pausa_s.toFixed(2)),
                taxa_backspace: totalTeclas > 0
                    ? parseFloat((totalBackspace / totalTeclas).toFixed(3)): 0});
        }
        lastKeystroke = now;

        if (keystrokeTimer) clearTimeout(keystrokeTimer);
        keystrokeTimer = setTimeout(() => {
            if (!isMissionActive) return;
            logEvent('keystroke_pause', {
                duracao_s: 30,
                taxa_backspace: totalTeclas > 0
                    ? parseFloat((totalBackspace / totalTeclas).toFixed(3))
                    : 0
            });
        }, 30000);
    });
}

// ============================================================
//                  CLIQUES FORA DA ÁREA 
// ============================================================
function registrarCliquesForaDaArea() {
    document.addEventListener('click', (e) => {
        if (!isMissionActive) return;

        const quizView = document.getElementById('quiz-view');
        if (quizView && !quizView.contains(e.target)) {
            logEvent('click_outside', {
                x: e.clientX,
                y: e.clientY
            });
        }
    });
}

// ============================================================
//                  TEMPO DE RESPOSTA POR QUESTÃO
// ============================================================
let questionShownAt = 0;

function registrarTempoDeResposta(acertou, opcaoEscolhida) {
    if (questionShownAt === 0) return;
    const tempo_resposta_ms = Math.round(performance.now() - questionShownAt);
    logEvent('question_answer', {
        tempo_resposta_ms,
        acertou,
        opcao_escolhida: opcaoEscolhida,
        tipo_questao: 'objetiva'
    });
}

// ============================================================
//                      COPIAR / COLAR
// ============================================================
function registrarCopiarColar() {
    ['copy', 'paste'].forEach(tipo => {
        document.addEventListener(tipo, () => {
            if (!isMissionActive) return;
            logEvent('copy_paste', { action: tipo });
        });
    });
}

// ================================================================
//                          INICIAR MISSÃO
// =================================================================
let currentSubject = null;

// Busca os Subtemas com a IA
async function abrirMateria(subject) {
    currentSubject = subject;
    const temasView = document.getElementById('temas-view');
    const temasBox  = document.getElementById('temas-display');

    document.getElementById('menu-view').style.display = 'none';
    temasView.style.display = 'block';
    temasBox.innerHTML = 'KaIA montando os temas...';
    try {
        const r = await fetch(`${API_URL}/temas`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ materia: subject })
        });
        const data = await r.json();
        temasBox.innerHTML = '';
        (data.temas || []).forEach(tema => {
            const btn = document.createElement('button');
            btn.className = 'option-btn';
            btn.innerText = tema;
            btn.onclick = () => startMission(subject, tema);
            temasBox.appendChild(btn);
        });
    } catch (e) {
        temasBox.innerHTML = 'Erro ao carregar os temas.';
        console.error(e);
    }
}
// 2) IA gera a questão
async function startMission(subject, tema) {
    document.getElementById('temas-view').style.display = 'none';
    document.getElementById('quiz-view').style.display  = 'block';
    document.getElementById('question-display').innerText = 'KaIA criando sua questão...';
    document.getElementById('options-display').innerHTML  = '';
    try {
        const r = await fetch(`${API_URL}/gerar-questao`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ materia: subject, tema, hobbies: historicoDeCliques })
        });
        currentQuestion = await r.json();
        if (currentQuestion.erro) throw new Error(currentQuestion.erro);
    } catch (e) {
        document.getElementById('question-display').innerText = 'Erro ao gerar a questão.';
        console.error(e);
        return;
    }
    isMissionActive = true;
    idleTime = 0; mudancasAba = 0; focusLostAt = null;
    lastScrollY = window.scrollY; lastScrollTime = performance.now();
    lastKeystroke = 0;
    if (keystrokeTimer) clearTimeout(keystrokeTimer);
    sessionId = crypto.randomUUID();

    // Atualiza features da sessão (streak, sessões no dia, pausa) e envia o perfil
    const features = registrarInicioSessao();
    logEvent('session_start', { materia: subject, tema, features });
    enviarPerfil({ tipo: 'session_start', materia: subject, tema });

    const subjectEl = document.getElementById('current-subject');
    if (subjectEl) subjectEl.innerText = `${subject} · ${tema}`;

    dynamicLimit = calculateReadingTime(currentQuestion.q, currentQuestion.opts);
    document.getElementById('question-display').innerText = currentQuestion.q;

    const optionsDiv = document.getElementById('options-display');
    optionsDiv.innerHTML = '';
    currentQuestion.opts.forEach((opt, idx) => {
        const btn = document.createElement('button');
        btn.className = 'option-btn';
        btn.innerText = opt;
        btn.onclick = () => checkAnswer(idx, btn);
        optionsDiv.appendChild(btn);
    });

    questionShownAt = performance.now();
    iniciarIdleMonitor();
}

// ==============================================================
//                      VERIFICAR RESPOSTA
// ==============================================================
function checkAnswer(idx, btn) {
    if (!isMissionActive) return;

    const acertou = (idx === currentQuestion.ans);
    registrarTempoDeResposta(acertou, idx);

    // Feedback visual
    btn.style.background = acertou ? '#27ae60' : '#e74c3c';

    // Desativa missão e volta ao menu após 1.5s
    isMissionActive = false;
    setTimeout(() => {
        document.getElementById('quiz-view').style.display  = 'none';
        document.getElementById('menu-view').style.display  = 'block';
        if (idleInterval) clearInterval(idleInterval);
        document.getElementById('overlay').style.opacity    = '0';
        document.getElementById('system-status').innerText  = 'AGUARDANDO';
    }, 1500);
}

// =================================================================
//                              RESET
// ==============================================================
function resetSystem() {
    if (idleInterval)   clearInterval(idleInterval);
    if (keystrokeTimer) clearTimeout(keystrokeTimer);
    location.reload();
}

// ====================================================================================
//                  INICIALIZAÇÃO — registra todos os listeners 
// ===================================================================================
document.addEventListener('DOMContentLoaded', () => {
    registrarMouseMove();
    registrarScroll();
    registrarTeclado();
    registrarCliquesForaDaArea();
    registrarCopiarColar();
    console.log('[KaIA] Listeners registrados. Session ID:', sessionId);
});