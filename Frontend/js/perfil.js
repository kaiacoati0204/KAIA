// ============================================================
//  KaIA — perfil.js: página do Perfil (o aluno vendo a própria evolução)
// ============================================================
// Depende de comum.js ($, apiFetch), carregado antes. Só perfil.html usa.

async function carregarPerfil() {
    if (!$('nomeUsuario')) return;

    const SEM_DADO = '—';
    const usuario = lerUsuario();

    // 1) Identidade: parte do sessionStorage (login, por aba) e confirma via /perfil.
    $('nomeUsuario').textContent  = usuario?.nome || usuario?.email || SEM_DADO;
    $('emailUsuario').textContent = usuario?.email || SEM_DADO;

    // NÃO usar localStorage.kaia_user_id: é compartilhado entre abas e discordaria desta.
    // Sem ?email=: o /perfil tira a identidade do TOKEN, pra ninguém ler perfil alheio.
    try {
        const r = await apiFetch('/perfil');
        if (r.ok) {
            const u = await r.json();
            $('nomeUsuario').textContent  = u.nome  || SEM_DADO;
            $('emailUsuario').textContent = u.email || SEM_DADO;
            mostrarHobbies(u.hobbies);
        }
    } catch (e) { console.warn('[KaIA] identidade do perfil:', e); }

    // 2) Estatísticas (Etapa 4.1 C híbrida).
    await carregarEstatisticasPerfil();
}

// Hobbies do aluno — o dado sempre veio no /perfil e era descartado aqui.
// Sem hobbies (conta nova que pulou o onboarding) o bloco simplesmente não
// aparece: um "—" ali não informaria nada.
function mostrarHobbies(hobbies) {
    const caixa = $('hobbiesUsuario');
    if (!caixa) return;
    caixa.replaceChildren();
    (hobbies || []).forEach(h => {
        const tag = document.createElement('span');
        tag.className = 'perfil-tag';
        tag.textContent = h;
        caixa.appendChild(tag);
    });
}

// "1 semanas · 1 matérias" era o texto de quem acabou de começar — ou seja, de
// todo aluno no primeiro dia de beta. Concorda o número com a palavra.
const pluralizar = (n, singular, plural) => `${n} ${n === 1 ? singular : plural}`;

// Preenche "Seu desempenho" (base semanal), "Sua última sessão" (complemento ao
// vivo, com estado vazio) e a "Análise da KaIA" (frases reais vindas do backend).
async function carregarEstatisticasPerfil() {
    const SEM_DADO = '—';
    if (!$('minutosTotais')) return;   // no-op fora do perfil

    // Sem ?aluno_id= e sem guarda: o backend usa o TOKEN, e falha no /perfil não pode cancelar esta busca.
    let D = null, falhou = false;
    try {
        const r = await apiFetch('/perfil/estatisticas');
        if (r.ok) D = await r.json();
        else falhou = true;
    } catch (e) {
        falhou = true;
        console.warn('[KaIA] estatísticas do perfil:', e);
    }

    // --- BASE semanal ---
    const d = D?.desempenho;
    const sub   = $('desempenhoSub');
    const cards = $('desempenhoCards');
    const vazio = $('desempenhoVazio');
    if (d) {
        $('minutosTotais').textContent = `${d.minutos} min`;
        // acerto vem NULO quando o aluno abriu sessões mas ainda não respondeu
        // nada. Interpolar direto escreveria "null%" na cara dele; 0% seria pior
        // ainda, porque afirmaria que ele errou tudo.
        $('acertoSemanal').textContent = (d.acerto === null || d.acerto === undefined)
            ? SEM_DADO : `${d.acerto}%`;
        $('minSemana').textContent     = `${d.min_semana} min`;
        if (sub)   sub.textContent = `Média de ${pluralizar(d.semanas, 'semana', 'semanas')}`
                                   + ` · ${pluralizar(d.materias, 'matéria', 'matérias')}`;
        if (cards) cards.style.display = '';
        if (vazio) vazio.style.display = 'none';
    } else {
        // Em vez de "—" prometendo média: diz se ainda não há histórico ou se falhou ao carregar.
        if (sub)   sub.textContent = '';
        if (cards) cards.style.display = 'none';
        if (vazio) {
            vazio.style.display = '';
            vazio.textContent = falhou
                ? 'Não foi possível carregar seu desempenho agora. Recarregue a página em alguns instantes.'
                : 'Ainda não há histórico semanal para mostrar aqui.';
        }
    }

    // --- COMPLEMENTO: última sessão ou mensagem (nunca fileira de "—") ---
    const u = D?.ultima_sessao;
    const lista = $('ultimaSessaoLista');
    const vazia = $('ultimaSessaoVazia');
    if (u) {
        $('ultimaQuando').textContent     = u.quando ? `· ${u.quando}` : '';
        // O payload ainda traz velocidade_scroll_px_s, mudancas_aba e
        // cliques_fora_area_estudo — de propósito não são exibidos (ver perfil.html).
        $('ultTempoResposta').textContent = `${(u.tempo_resposta_ms / 1000).toFixed(1).replace('.', ',')} s`;
        $('ultForaFoco').textContent      = `${Math.round(u.tempo_fora_foco_s)} s`;
        if (lista) lista.style.display = '';
        if (vazia) vazia.style.display = 'none';
    } else {
        $('ultimaQuando').textContent = '';
        if (lista) lista.style.display = 'none';
        if (vazia) {
            vazia.style.display = '';
            // Quando a chamada FALHA, "nenhuma sessão registrada" é uma afirmação
            // falsa: o aluno pode ter estudado ontem e a página não faz ideia.
            vazia.textContent = falhou
                ? 'Não foi possível carregar sua última sessão agora. Recarregue a página em alguns instantes.'
                : 'Nenhuma sessão registrada ainda. Comece uma missão em Matérias para ver seus sinais.';
        }
    }

    // --- ANÁLISE em velocímetros ---
    montarAnalise(D, falhou);
}

// ============================================================
//  VELOCÍMETROS DA ANÁLISE
// ============================================================
// Arco aberto embaixo: 270° de varredura, do canto inferior esquerdo ao inferior
// direito. Os dois números saem da geometria (centro 60,60 · raio 46) — mexer num
// sem refazer a conta quebra o traçado ou o preenchimento.
const GAUGE_ARCO = 'M 27.47 92.53 A 46 46 0 1 1 92.53 92.53';
const GAUGE_VOLTA = 216.77;   // 270/360 · 2πr

// ---- TEXTURAS ----
// Tinta translúcida fixa em vez de uma cor derivada da escolhida: o padrão precisa
// aparecer sobre QUALQUER cor que o aluno pegue no seletor, inclusive as escuras.
const TEXTURA_TINTA = 'rgba(43,42,38,0.42)';

// Cada tile é desenhado uma vez e serve aos dois destinos (o <pattern> do gauge e o
// background da faixa). Os pontos de entrada e saída de cada desenho batem com as
// bordas do tile — é o que faz o padrão emendar sem costura visível.
const TEXTURAS = [
    { id: 'lisa', nome: 'Lisa (só cor)', w: 8, h: 8, tile: () => '' },
    { id: 'listras', nome: 'Listras diagonais', w: 8, h: 8,
      tile: t => `<path d="M-2 2L2 -2M0 8L8 0M6 10L10 6" stroke="${t}" stroke-width="2.6" fill="none"/>` },
    { id: 'pontos', nome: 'Pontos', w: 7, h: 7,
      tile: t => `<circle cx="3.5" cy="3.5" r="1.7" fill="${t}"/>` },
    { id: 'xadrez', nome: 'Xadrez', w: 8, h: 8,
      tile: t => `<rect width="4" height="4" fill="${t}"/><rect x="4" y="4" width="4" height="4" fill="${t}"/>` },
    { id: 'linhas', nome: 'Linhas horizontais', w: 6, h: 6,
      tile: t => `<rect width="6" height="2.6" fill="${t}"/>` },
    { id: 'grade', nome: 'Grade', w: 8, h: 8,
      tile: t => `<rect width="8" height="1.7" fill="${t}"/><rect width="1.7" height="8" fill="${t}"/>` },
    { id: 'ziguezague', nome: 'Ziguezague', w: 8, h: 8,
      tile: t => `<path d="M0 6L4 2L8 6" stroke="${t}" stroke-width="2.1" fill="none"/>` },
    { id: 'ondas', nome: 'Ondas', w: 8, h: 8,
      tile: t => `<path d="M0 5q2 -3.6 4 0t4 0" stroke="${t}" stroke-width="2" fill="none"/>` },
    { id: 'triangulos', nome: 'Triângulos', w: 10, h: 10,
      tile: t => `<path d="M5 1.5L9 8.5H1Z" fill="${t}"/>` },
];
const _textura = id => TEXTURAS.find(t => t.id === id) || TEXTURAS[0];

// Tile como <svg> inteiro -> vira background-image da faixa (elemento HTML).
function _texturaDataUri(id, tinta = TEXTURA_TINTA) {
    const t = _textura(id);
    if (!t.tile(tinta)) return '';
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${t.w}" height="${t.h}" `
              + `viewBox="0 0 ${t.w} ${t.h}">${t.tile(tinta)}</svg>`;
    return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
}

let _gaugeSeq = 0;

// Desenha um velocímetro dentro de `slot`. A textura entra como SEGUNDA passada por
// cima do arco colorido: a cor continua sólida embaixo e o padrão só a escurece.
// `animar` sai como false em toda REPINTURA (mexer na cor, trocar a textura): sem
// isso o arco refazia a varredura inteira a cada clique no seletor — movimento
// repetido e sem informação nova, o oposto do que o público precisa.
function montarGauge(slot, { valor, cor, textura = 'lisa', rotulo = '', animar = true }) {
    if (!slot) return;
    const pct = Math.max(0, Math.min(100, Number(valor) || 0));
    const t = _textura(textura);
    const marca = t.tile(TEXTURA_TINTA);
    const id = `tex${++_gaugeSeq}`;
    const falta = GAUGE_VOLTA * (1 - pct / 100);
    const off = animar ? GAUGE_VOLTA : falta;

    slot.innerHTML = `
      <svg class="gauge-svg" viewBox="0 0 120 106" role="img">
        <defs>${marca ? `<pattern id="${id}" patternUnits="userSpaceOnUse"
              width="${t.w}" height="${t.h}">${marca}</pattern>` : ''}</defs>
        <path class="gauge-trilho" d="${GAUGE_ARCO}"></path>
        <path class="gauge-valor" d="${GAUGE_ARCO}" stroke="${cor}"
              stroke-dasharray="${GAUGE_VOLTA}" stroke-dashoffset="${off}"></path>
        ${marca ? `<path class="gauge-valor gauge-tex" d="${GAUGE_ARCO}" stroke="url(#${id})"
              stroke-dasharray="${GAUGE_VOLTA}" stroke-dashoffset="${off}"></path>` : ''}
        <text class="gauge-num" x="60" y="66" text-anchor="middle">${pct}%</text>
      </svg>`;

    // aria-label por setAttribute: `rotulo` carrega nome de matéria vindo do
    // backend e não pode ser interpolado como HTML.
    slot.firstElementChild.setAttribute('aria-label', `${rotulo}: ${pct} por cento`);

    // Duplo rAF: o primeiro deixa o dashoffset cheio pintar, o segundo dispara a
    // transição. Sem isso o arco nasce preenchido e não há animação.
    if (!animar) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {
        slot.querySelectorAll('.gauge-valor').forEach(p => { p.style.strokeDashoffset = falta; });
    }));
}

// ============================================================
//  PERSONALIZAÇÃO DE COR + TEXTURA POR MATÉRIA
// ============================================================
// Mock em localStorage, por aluno (`userId` vem do comum.js). Enquanto não há rota
// no backend, a escolha vive no dispositivo — some se o aluno trocar de máquina.
// PENDENTE (Bia): faixa de cor por matéria na tela de estudo (materias) — ler a
// mesma chave do localStorage que o perfil salva.
const CHAVE_CORES = `kaia_cores_materia:${typeof userId !== 'undefined' ? userId : 'anon'}`;

function lerCores() {
    try { return JSON.parse(localStorage.getItem(CHAVE_CORES) || '{}'); }
    catch (_) { return {}; }
}
function gravarCores(mapa) {
    try { localStorage.setItem(CHAVE_CORES, JSON.stringify(mapa)); }
    catch (e) { console.warn('[KaIA] não deu para salvar a cor da matéria:', e); }
}

// ---- Recados por POSIÇÃO na lista (o backend já manda ordenado por acerto desc) ----
// O da pior matéria é sempre CONVITE, nunca cobrança: quem já vai mal na matéria não
// precisa de um card confirmando isso.
const RECADOS_MELHOR = ['Seu ponto forte! 💪', 'Mandando muito bem aqui', 'Tá voando nessa!'];
const RECADOS_PIOR = ['Que tal um carinho extra aqui?', 'Um pouquinho mais de foco aqui',
                      'Bora reforçar essa?'];
const RECADOS_NEUTROS = ['Continue firme!', 'Tá evoluindo!', 'No caminho certo',
                         'Cada questão conta', 'Devagar e sempre'];

const RECADO_MELHOR = { frases: RECADOS_MELHOR, cor: 'var(--acerto-tx)', classe: 'bom' };
const RECADO_PIOR   = { frases: RECADOS_PIOR,   cor: 'var(--alerta-tx)', classe: 'reforco' };

const _sortear = lista => lista[Math.floor(Math.random() * lista.length)];

// Os neutros são EMBARALHADOS uma vez por montagem e depois percorridos em ordem:
// sorteio solto repetiria a mesma frase em dois cards vizinhos da mesma tela.
// Fisher-Yates de verdade — o sort(() => Math.random() - 0.5) é enviesado.
let _neutrosDaVez = [...RECADOS_NEUTROS];
function _embaralharNeutros() {
    _neutrosDaVez = [...RECADOS_NEUTROS];
    for (let i = _neutrosDaVez.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [_neutrosDaVez[i], _neutrosDaVez[j]] = [_neutrosDaVez[j], _neutrosDaVez[i]];
    }
}

// Ícone de paleta em traço (currentColor) — mesmo partido dos ícones das 7.
const ICONE_PALETA = `
  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" aria-hidden="true">
    <path d="M12 3a9 9 0 1 0 0 18 2 2 0 0 0 1.6-3.2 2 2 0 0 1 1.6-3.2H18a3 3 0 0 0 3-3A9 9 0 0 0 12 3Z"
          stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"></path>
    <circle cx="7.6" cy="12.4" r="1.1" fill="currentColor"></circle>
    <circle cx="9.9" cy="8.4" r="1.1" fill="currentColor"></circle>
    <circle cx="14.3" cy="8" r="1.1" fill="currentColor"></circle>
  </svg>`;

// Cor que o velocímetro usa quando a matéria NÃO foi personalizada: a automática,
// pela posição na lista. Em hex (não var()) porque o <input type="color"> só
// aceita hex e precisa abrir já no tom que o card está mostrando.
const COR_AUTO_HEX = { bom: '#2f5d3a', reforco: '#7a5f14', neutro: '#2d4ba5' };

// Pinta gauge + faixa de um card. Chamada na montagem E a cada mexida no painel,
// por isso lê o localStorage toda vez em vez de receber a escolha pronta.
function _pintarCard(card, item, papel, animar = true) {
    const salvo = lerCores()[item.materia];
    const classe = papel ? papel.classe : 'neutro';
    const cor = salvo?.cor || COR_AUTO_HEX[classe];
    const textura = salvo?.textura || 'lisa';

    montarGauge(card.querySelector('.gauge-slot'),
                { valor: item.acerto, cor, textura, rotulo: item.materia, animar });

    // backgroundColor + backgroundImage separados: o atalho `background` zeraria a
    // imagem que acabou de ser posta.
    const faixa = card.querySelector('.materia-faixa');
    faixa.style.backgroundColor = cor;
    faixa.style.backgroundImage = _texturaDataUri(textura);
    return { cor, textura };
}

function _cardMateria(item, papel, neutroIdx) {
    const card = document.createElement('article');
    card.className = 'materia-card';

    const botao = document.createElement('button');
    botao.type = 'button';
    botao.className = 'materia-paleta';
    botao.title = 'Personalizar cor e textura';
    botao.setAttribute('aria-label', `Personalizar cor e textura de ${item.materia}`);
    botao.setAttribute('aria-expanded', 'false');
    botao.innerHTML = ICONE_PALETA;

    const slot = document.createElement('div');
    slot.className = 'gauge-slot';

    const nome = document.createElement('p');
    nome.className = 'materia-nome';
    nome.textContent = item.materia;

    const recado = document.createElement('p');
    recado.className = `materia-recado materia-recado--${papel ? papel.classe : 'neutro'}`;
    recado.textContent = papel ? _sortear(papel.frases)
                               : _neutrosDaVez[neutroIdx % _neutrosDaVez.length];

    const faixa = document.createElement('span');
    faixa.className = 'materia-faixa';

    card.append(botao, slot, nome, recado, faixa);
    _pintarCard(card, item, papel);
    botao.addEventListener('click', () => abrirPaleta(botao, card, item, papel));
    return card;
}

// ---- Painel de personalização (um por vez, na raiz do body) ----
// Vai no <body>, não dentro do card: o card tem largura de ~155px e recorta o que
// passa dele. Posicionado em coordenadas de página, então acompanha o scroll sozinho.
let _paletaAberta = null;

function fecharPaleta({ devolverFoco = true } = {}) {
    if (!_paletaAberta) return;
    const { painel, botao, onDoc, onTecla, onResize } = _paletaAberta;
    document.removeEventListener('pointerdown', onDoc, true);
    document.removeEventListener('keydown', onTecla, true);
    window.removeEventListener('resize', onResize);
    painel.remove();
    botao.setAttribute('aria-expanded', 'false');
    _paletaAberta = null;
    if (devolverFoco) botao.focus();
}

// Ancora no CARD, não no botão: aberto a partir do botão o painel cobria o próprio
// velocímetro que o aluno está tentando pintar.
function _posicionarPaleta(painel, card) {
    const r = card.getBoundingClientRect();
    const larg = painel.offsetWidth;
    const alt = painel.offsetHeight;
    const margem = 8;
    const janela = document.documentElement.clientHeight;

    let x = r.right + window.scrollX - larg;
    x = Math.min(x, window.scrollX + document.documentElement.clientWidth - larg - margem);
    x = Math.max(x, window.scrollX + margem);

    // Vira pra cima quando não cabe embaixo (cards da última fileira).
    const cabeEmbaixo = r.bottom + alt + margem <= janela;
    const y = cabeEmbaixo ? r.bottom + 6 : Math.max(margem, r.top - alt - 6);
    painel.style.left = `${x}px`;
    painel.style.top = `${y + window.scrollY}px`;
}

function abrirPaleta(botao, card, item, papel) {
    const jaEra = _paletaAberta && _paletaAberta.botao === botao;
    fecharPaleta({ devolverFoco: false });
    if (jaEra) { botao.focus(); return; }   // clicar de novo no mesmo botão fecha

    const atual = _pintarCard(card, item, papel, false);
    const painel = document.createElement('div');
    painel.className = 'paleta-painel';
    painel.setAttribute('role', 'dialog');
    painel.setAttribute('aria-label', `Personalizar ${item.materia}`);

    // --- cor ---
    const linha = document.createElement('div');
    linha.className = 'paleta-linha';
    const rot = document.createElement('label');
    rot.className = 'paleta-rotulo';
    rot.textContent = 'Cor';
    const cor = document.createElement('input');
    cor.type = 'color';
    cor.className = 'paleta-cor';
    cor.value = atual.cor;
    rot.htmlFor = cor.id = `cor-${++_gaugeSeq}`;
    linha.append(rot, cor);

    // --- texturas (radio nativo: navegação por setas e leitura de grupo de graça) ---
    const grupo = document.createElement('div');
    grupo.className = 'paleta-texturas';
    grupo.setAttribute('role', 'radiogroup');
    grupo.setAttribute('aria-label', 'Textura');
    const nomeGrupo = `tex-${_gaugeSeq}`;
    TEXTURAS.forEach(t => {
        const chip = document.createElement('label');
        chip.className = 'tex-chip';
        chip.title = t.nome;
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = nomeGrupo;
        radio.value = t.id;
        radio.checked = t.id === atual.textura;
        radio.setAttribute('aria-label', t.nome);
        const vista = document.createElement('span');
        vista.className = 'tex-vista';
        vista.setAttribute('aria-hidden', 'true');
        chip.append(radio, vista);
        grupo.appendChild(chip);
    });

    const acoes = document.createElement('div');
    acoes.className = 'paleta-acoes';
    const limpar = document.createElement('button');
    limpar.type = 'button';
    limpar.className = 'paleta-limpar';
    limpar.textContent = 'Voltar ao automático';
    const pronto = document.createElement('button');
    pronto.type = 'button';
    pronto.className = 'paleta-pronto';
    pronto.textContent = 'Pronto';
    acoes.append(limpar, pronto);

    painel.append(linha, grupo, acoes);
    document.body.appendChild(painel);

    // As amostras usam a COR ESCOLHIDA, não uma neutra: assim o aluno vê o par
    // cor+textura que vai ficar, em vez de adivinhar.
    const repintarVistas = () => {
        grupo.querySelectorAll('.tex-chip').forEach((chip, i) => {
            const v = chip.querySelector('.tex-vista');
            v.style.backgroundColor = cor.value;
            v.style.backgroundImage = _texturaDataUri(TEXTURAS[i].id);
        });
    };
    const aplicar = () => {
        const mapa = lerCores();
        mapa[item.materia] = {
            cor: cor.value,
            textura: grupo.querySelector('input:checked')?.value || 'lisa',
        };
        gravarCores(mapa);
        _pintarCard(card, item, papel, false);
        repintarVistas();
    };

    repintarVistas();
    _posicionarPaleta(painel, card);
    botao.setAttribute('aria-expanded', 'true');

    cor.addEventListener('input', aplicar);
    grupo.addEventListener('change', aplicar);
    limpar.addEventListener('click', () => {
        const mapa = lerCores();
        delete mapa[item.materia];
        gravarCores(mapa);
        const volta = _pintarCard(card, item, papel, false);
        cor.value = volta.cor;
        grupo.querySelector(`input[value="${volta.textura}"]`).checked = true;
        repintarVistas();
    });
    pronto.addEventListener('click', () => fecharPaleta());

    // Clique fora fecha. Em `pointerdown` na fase de captura pra decidir antes de
    // qualquer handler da página; o botão sai da conta porque ele tem o próprio
    // toggle (senão fecharia e reabriria no mesmo clique).
    const onDoc = (e) => {
        if (!painel.contains(e.target) && !botao.contains(e.target)) fecharPaleta({ devolverFoco: false });
    };
    const onTecla = (e) => { if (e.key === 'Escape') { e.stopPropagation(); fecharPaleta(); } };
    const onResize = () => _posicionarPaleta(painel, card);
    document.addEventListener('pointerdown', onDoc, true);
    document.addEventListener('keydown', onTecla, true);
    window.addEventListener('resize', onResize);

    _paletaAberta = { painel, botao, onDoc, onTecla, onResize };
    cor.focus();
}

// PENDENTE (Vitor): dado por matéria.
// O /perfil/estatisticas JÁ calcula isso (a consulta `por_materia` em app.py devolve
// materia + acerto ordenado desc), mas só usa pra montar frase — nada por matéria entra
// no JSON. Basta serializar `por_materia: [{materia, acerto}]` que a grade liga sozinha.
// Não dá pra extrair das frases de `analise`: o número vive dentro do texto.
// Enquanto não vier, a grade fica [hidden] — a regra do "só se existe".
// Preview local sem backend: abrir perfil.html?mock=1
const MOCK_POR_MATERIA = [
    { materia: 'Matemática', acerto: 88 },
    { materia: 'Biologia',   acerto: 74 },
    { materia: 'História',   acerto: 61 },
    { materia: 'Química',    acerto: 52 },
    { materia: 'Filosofia',  acerto: 37 },
];

function montarAnalise(D, falhou) {
    const cardGeral = $('cardGeral');
    if (!cardGeral) return;

    const vazia = $('analiseVazia');
    const acerto = D?.desempenho?.acerto;
    const temGeral = acerto !== null && acerto !== undefined;

    // --- Card principal ---
    if (temGeral) {
        montarGauge($('gaugeGeral'), {
            valor: acerto,
            cor: 'var(--azul-coati)',
            rotulo: 'Acerto médio geral',
        });
        // PENDENTE (Vitor): `recomendacao` como campo próprio. Hoje a recomendação vem
        // grudada no número dentro de analise[0] ("Seu acerto médio é 55% — ..."), e
        // fatiar a frase no front quebra no primeiro ajuste de texto do backend.
        $('analiseRecomendacao').textContent = D?.recomendacao || D?.analise?.[0] || '';
    }
    cardGeral.hidden = !temGeral;

    // --- Grade por matéria (só com dado) ---
    const usarMock = new URLSearchParams(location.search).has('mock');
    const lista = D?.por_materia || (usarMock ? MOCK_POR_MATERIA : null);
    const grade = $('materiasGrade');
    fecharPaleta({ devolverFoco: false });   // remontar a grade deixaria o painel órfão
    grade.replaceChildren();

    if (lista?.length) {
        // A última só vira "precisa de reforço" se de fato acertar MENOS que a
        // primeira. Com tudo empatado (ou uma matéria só), apontar a última seria
        // inventar um pior que não existe — aí ela recebe recado neutro.
        const ultima = lista.length > 1 && lista[lista.length - 1].acerto < lista[0].acerto
            ? lista.length - 1 : -1;
        _embaralharNeutros();
        let neutro = 0;
        lista.forEach((item, i) => {
            const papel = i === 0 ? RECADO_MELHOR : i === ultima ? RECADO_PIOR : null;
            grade.appendChild(_cardMateria(item, papel, papel ? 0 : neutro++));
        });
    }
    grade.hidden = !lista?.length;

    // --- Nada a mostrar: frase calma, nunca gauge vazio ---
    const nada = !temGeral && !lista?.length;
    vazia.hidden = !nada;
    if (nada) {
        vazia.textContent = falhou
            ? 'Não foi possível carregar sua análise agora.'
            : 'Ainda juntando seus dados. Responda algumas questões e sua análise aparece aqui.';
    }
}

// Init da página: comum.js já monta rail + textura; aqui só o Perfil.
document.addEventListener('DOMContentLoaded', carregarPerfil);
