// ============================================================
//  KaIA — dashboard.js: painel interno (KPIs + gráficos Chart.js)
// ============================================================
// Depende de comum.js ($, $$, apiFetch, userId) e do Chart.js (CDN),
// carregados antes. Só dashboard.html usa. sv() é global (onclick inline no HTML).

// Troca de aba (VISÃO GERAL / SESSÕES / ATENÇÃO / FINANCEIRO)
function sv(id, btn) {
    $$('.view').forEach(v => v.classList.remove('on'));
    $$('.tab').forEach(b => b.classList.remove('on'));
    const view = $('v-' + id);
    view.classList.add('on');
    btn?.classList.add('on');
    if (typeof Chart !== 'undefined') {
        $$('canvas', view).forEach(cv => Chart.getChart(cv)?.resize());
    }
}

// Ícones (SVG interno) dos cartões KPI — nome → markup
const DASH_ICONES = {
    users:'<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    layers:'<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',
    target:'<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/>',
    alert:'<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    calendar:'<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    clock:'<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    list:'<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    check:'<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    smile:'<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>',
    meh:'<circle cx="12" cy="12" r="10"/><line x1="8" y1="15" x2="16" y2="15"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>',
    frown:'<circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>',
    bolt:'<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    dollar:'<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    trend:'<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    grid:'<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
};

// Paleta dos gráficos (espelha as variáveis do style.css)
const DASH_COR = { azul:'#2D4BA5', ouro:'#f3d009', verde:'#57D979', bege:'#c4a186', vermelho:'#f87171', amarelo:'#92400e' };
const COR_TEXTO = { verde:'#057a3a', amarelo:'#92400e', vermelho:'#991b1b' };

// Escapa texto vindo da planilha antes de injetar no HTML.
const esc = (v) => String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num = (v) => Number(v) || 0;
const _rows = (len, fn) => Array.from({ length: len }, (_, i) => fn(i));

// ── FALLBACK: dados de demonstração (espelham as colunas da planilha) ──
const _sph = [2,1,1,0,0,0,1,3,8,15,18,22,19,21,25,28,31,35,42,58,71,65,48,22];
const _aph = [0,0,0,0,0,0,0,1,1,2,2,3,2,3,3,4,4,5,5,7,9,8,6,3];
const _fh  = [35,30,28,25,22,20,25,38,52,61,65,68,64,67,70,72,74,75,72,80,85,83,76,60];
const _ini = [88,102,115,98,121,145,167,141,158,172,189,202,225,241];
const _con = [55,68,74,60,82,99,110,91,105,119,131,140,158,171];
const _mrrE = [299,538,748,1047,1346,1794,2243,2691,3289,3887,4336,4485];
const _mrrI = [299,479,718,1078,1498,1916,2396,2995,3594,4312,4792,4792];
const _l14 = _rows(14, i => {
    const d = new Date();
    d.setDate(d.getDate() - 13 + i);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
});

const DASH_FALLBACK = {
    kpis: [
        {view:'geral', icone:'users',  rotulo:'ATIVOS AGORA',    valor:'247',   subtexto:'sessões em andamento', variacao:'+18%', variacao_tipo:'up'},
        {view:'geral', icone:'layers', rotulo:'QUESTÕES HOJE',   valor:'4.830', subtexto:'via API Gemini',       variacao:'+12%', variacao_tipo:'up'},
        {view:'geral', icone:'target', rotulo:'FOCO MÉDIO',      valor:'73%',   subtexto:'por sessão hoje',      variacao:'estável', variacao_tipo:'neutro'},
        {view:'geral', icone:'alert',  rotulo:'DISTRAÇÕES HOJE', valor:'31',    subtexto:'alertas detectados',   variacao:'+7%',  variacao_tipo:'down'},
        {view:'sessoes', icone:'calendar', rotulo:'SESSÕES NO MÊS',    valor:'3.241',  subtexto:'todas as contas',     variacao:'+31%', variacao_tipo:'up'},
        {view:'sessoes', icone:'clock',    rotulo:'DURAÇÃO MÉDIA',     valor:'47 min', subtexto:'por sessão',          variacao:'meta 45′', variacao_tipo:'neutro'},
        {view:'sessoes', icone:'list',     rotulo:'QUESTÕES / SESSÃO', valor:'19,5',   subtexto:'média geral',         variacao:'+4',   variacao_tipo:'up'},
        {view:'sessoes', icone:'check',    rotulo:'CONCLUSÃO',         valor:'68%',    subtexto:'sessões finalizadas', variacao:'estável', variacao_tipo:'neutro'},
        {view:'atencao', icone:'smile', rotulo:'FOCO ALTO >70%',     valor:'54%',   subtexto:'das sessões hoje', cor:'verde'},
        {view:'atencao', icone:'meh',   rotulo:'FOCO MÉDIO 40–70%',  valor:'31%',   subtexto:'das sessões hoje', cor:'amarelo'},
        {view:'atencao', icone:'frown', rotulo:'FOCO BAIXO <40%',    valor:'15%',   subtexto:'das sessões hoje', variacao:'atenção', variacao_tipo:'down', cor:'vermelho'},
        {view:'atencao', icone:'bolt',  rotulo:'EVENTOS kaia.js / H', valor:'1.840', subtexto:'scroll · key · mouse · tab'},
        {view:'fin', icone:'dollar', rotulo:'MRR',             valor:'R$ 9,3k', subtexto:'receita recorrente/mês', variacao:'+94%', variacao_tipo:'up'},
        {view:'fin', icone:'users',  rotulo:'PAGANTES',        valor:'230',     subtexto:'Essencial + Intensivo',  variacao:'+23',  variacao_tipo:'up'},
        {view:'fin', icone:'trend',  rotulo:'LTV / CAC',       valor:'3,2×',    subtexto:'meta mínima: 3×',        variacao:'ok',   variacao_tipo:'up', cor:'verde'},
        {view:'fin', icone:'grid',   rotulo:'CUSTO API / MÊS', valor:'R$ 460',  subtexto:'5% da receita',          variacao:'saudável', variacao_tipo:'neutro'}
    ],
    sessoes_hora:    _rows(24, i => ({ hora: i + 'h', sessoes: _sph[i], alertas: _aph[i] })),
    foco_hora:       _rows(24, i => ({ hora: i + 'h', foco: _fh[i] })),
    sessoes_14dias:  _rows(14, i => ({ data: _l14[i], iniciadas: _ini[i], concluidas: _con[i] })),
    mrr_mensal:      _rows(12, i => ({ mes: 'M' + (i + 1), essencial: _mrrE[i], intensivo: _mrrI[i] })),
    planos: [{plano:'Free',percentual:62},{plano:'Essencial',percentual:28},{plano:'Intensivo',percentual:10}],
    distribuicao_foco: [{faixa:'Alto',percentual:54},{faixa:'Médio',percentual:31},{faixa:'Baixo',percentual:15}],
    alunos_recentes: [
        {aluno:'Lucas M.',   plano:'Intensivo', foco:'88%', tema:'Biologia'},
        {aluno:'Ana P.',     plano:'Essencial', foco:'65%', tema:'Matemática'},
        {aluno:'João V.',    plano:'Intensivo', foco:'91%', tema:'Redação'},
        {aluno:'Mariana L.', plano:'Free',      foco:'44%', tema:'História'},
        {aluno:'Pedro H.',   plano:'Essencial', foco:'78%', tema:'Química'}
    ],
    alertas_recentes: [
        {nivel:'amarelo',  mensagem:'Ana P. — distração prolongada (+3 min)', tempo:'há 2 min'},
        {nivel:'vermelho', mensagem:'Mariana L. — foco abaixo de 40%',        tempo:'há 5 min'},
        {nivel:'verde',    mensagem:'Lucas M. — sessão concluída (90 min)',   tempo:'há 8 min'},
        {nivel:'amarelo',  mensagem:'Carlos R. — troca de aba detectada',     tempo:'há 12 min'}
    ],
    temas_estudados: [
        {tema:'Matemática',sessoes:342},{tema:'Português',sessoes:298},{tema:'Biologia',sessoes:241},
        {tema:'Redação',sessoes:198},{tema:'História',sessoes:175},{tema:'Química',sessoes:152},{tema:'Física',sessoes:134}
    ],
    eventos_tipo: [
        {tipo:'Scroll passivo',percentual:38},{tipo:'Keystroke ativo',percentual:29},
        {tipo:'Mouse idle >30s',percentual:18},{tipo:'Troca de aba',percentual:15}
    ],
    metas_fase: [
        {meta:'MVP — 50 beta',               percentual:100, cor:'verde'},
        {meta:'Piloto — 250 pagantes',       percentual:92,  cor:'ouro'},
        {meta:'Escala — 500 pagantes',       percentual:46,  cor:'azul'},
        {meta:'Break-even — 250 assinantes', percentual:92,  cor:'bege'}
    ],
    saude_financeira: [
        {indicador:'Margem bruta',valor:'78%',cor:'verde'},
        {indicador:'CAC médio',valor:'R$ 115'},
        {indicador:'LTV médio',valor:'R$ 480'},
        {indicador:'Payback do CAC',valor:'~3,5 meses'},
        {indicador:'Custo variável / usuário',valor:'R$ 2,00 / mês'},
        {indicador:'ARR projetado',valor:'R$ 111k',cor:'verde'}
    ]
};

// Devolve o bloco da planilha se tiver linhas; senão o FALLBACK.
const _bloco = (D, nome) =>
    (D && Array.isArray(D[nome]) && D[nome].length) ? D[nome] : DASH_FALLBACK[nome];

// Preenche um container por id (no-op se a página não tiver o elemento).
function _preencher(id, html) {
    const box = $(id);
    if (box) box.innerHTML = html;
}

// ── RENDERIZADORES (planilha → HTML) ──
function _renderKPIs(kpis) {
    const chipCls = { up:'cu', down:'cd', neutro:'co' };
    ['geral', 'sessoes', 'atencao', 'fin'].forEach(view => {
        // Fallback POR ABA: a base sintética não tem dados financeiros, então a
        // aba "fin" não vem no payload — nesse caso usamos os KPIs de demo.
        let linhas = kpis.filter(k => k.view === view);
        if (!linhas.length) linhas = DASH_FALLBACK.kpis.filter(k => k.view === view);

        _preencher('kpi-' + view, linhas.map(k => {
            const cor  = COR_TEXTO[k.cor] ? ` style="color:${COR_TEXTO[k.cor]}"` : '';
            const chip = k.variacao
                ? `<span class="chip ${chipCls[k.variacao_tipo] || 'co'}">${esc(k.variacao)}</span>` : '';
            return `<div class="kpi">
                <div class="kl"><svg viewBox="0 0 24 24">${DASH_ICONES[k.icone] || DASH_ICONES.target}</svg>${esc(k.rotulo)}</div>
                <div class="kv"${cor}>${esc(k.valor)}</div>
                <div class="kf"><span class="ks">${esc(k.subtexto)}</span>${chip}</div>
            </div>`;
        }).join(''));
    });
}

function _renderLegenda(id, linhas, cores) {
    _preencher(id, linhas.map((l, i) =>
        `<div class="li"><div class="ls" style="background:${cores[i % cores.length]}"></div>${esc(l)}</div>`
    ).join(''));
}

function _renderAlunos(linhas) {
    // pi = verde, pe = âmbar, pf = azul. Cobre os planos (demo) e os perfis da base sintética.
    const cls = {
        Free:'pf', Essencial:'pe', Intensivo:'pi',
        'Focado':'pi', 'Cansaço':'pe', 'Distraído Gradual':'pe', 'Distraído Imediato':'pf',
        // Estados preditos (dashboard sobre Supabase): verde/âmbar para engajado/distraído.
        'Engajado':'pi', 'Distraído':'pe', 'Muito distr.':'pf'
    };
    _preencher('alunos-recentes', linhas.map(a =>
        `<tr><td>${esc(a.aluno)}</td><td><span class="pp ${cls[a.plano] || 'pf'}">${esc(a.plano)}</span></td>
         <td>${esc(a.foco)}</td><td>${esc(a.tema)}</td></tr>`).join(''));
}

function _renderAlertas(linhas) {
    const mapa = {
        vermelho: { cls:'ar', ico:'<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>' },
        amarelo:  { cls:'ay', ico:'<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>' },
        verde:    { cls:'ag', ico:'<polyline points="20 6 9 17 4 12"/>' }
    };
    _preencher('alertas-recentes', linhas.map(a => {
        const m = mapa[a.nivel] || mapa.amarelo;
        return `<div class="ai"><div class="aico ${m.cls}"><svg viewBox="0 0 24 24">${m.ico}</svg></div>
            <div class="ab"><div class="at">${esc(a.mensagem)}</div><div class="ats">${esc(a.tempo)}</div></div></div>`;
    }).join(''));
}

function _renderEventos(linhas) {
    const fills = ['fb', 'fv', 'fg', 'fe'];
    _preencher('eventos-tipo', linhas.map((e, i) =>
        `<div class="er"><span class="elb">${esc(e.tipo)}</span>
         <div class="etr"><div class="efi ${fills[i % fills.length]}" style="width:${num(e.percentual)}%"></div></div>
         <span class="ep">${num(e.percentual)}%</span></div>`).join(''));
}

function _renderMetas(linhas) {
    const fill = { verde:'fv', ouro:'fg', azul:'fb', bege:'fe' };
    _preencher('metas-fase', linhas.map(m => {
        const pct = num(m.percentual);
        return `<div class="pr"><div class="pdot" style="background:${DASH_COR[m.cor] || DASH_COR.azul}"></div>
            <div class="pinfo"><div class="ptop"><span>${esc(m.meta)}</span><span>${pct}%</span></div>
            <div class="ptr"><div class="pfi ${fill[m.cor] || 'fb'}" style="width:${pct}%"></div></div></div></div>`;
    }).join(''));
}

function _renderSaude(linhas) {
    _preencher('saude-financeira', linhas.map(s => {
        const cor = COR_TEXTO[s.cor] ? ` style="color:${COR_TEXTO[s.cor]}"` : '';
        return `<tr><td>${esc(s.indicador)}</td><td${cor}>${esc(s.valor)}</td></tr>`;
    }).join(''));
}

// Mostra de onde vieram os dados (base real x demo) na etiqueta do topo.
function _renderFonte(D) {
    const el = $('fonte-dados');
    if (!el) return;
    if (D?.fonte === 'supabase') el.textContent = `SUPABASE · ${D.total_sessoes} SESSÕES · ${D.periodo}`;
    else if (D?.fonte === 'base_sintetica') el.textContent = `BASE SINTÉTICA · ${D.total_sessoes} SESSÕES · ${D.periodo}`;
    else if (D?.fonte === 'planilha_manual') el.textContent = 'PLANILHA MANUAL';
    else el.textContent = 'DADOS DE DEMONSTRAÇÃO';
}

// Aviso explícito de amostra pequena: com poucas sessões, médias e distribuições
// (ainda mais as predições do RF) não são estatisticamente confiáveis. Injeta uma
// faixa no topo do corpo do dashboard em vez de mostrar 3 pontos como se fosse tendência.
function _avisoAmostra(D) {
    if (!D || !D.amostra_pequena) return;
    const body = document.querySelector('.db-body');
    if (!body || $('db-amostra')) return;
    const n = D.total_sessoes ?? 0;
    const pred = D.sessoes_preditas;
    const faixa = document.createElement('div');
    faixa.id = 'db-amostra';
    faixa.className = 'db-amostra';
    faixa.textContent = `⚠ Amostra pequena: ${n} sessões`
        + (pred != null ? ` (${pred} com predição do modelo)` : '')
        + ' — médias e distribuições têm baixa confiança estatística.';
    body.prepend(faixa);
}

// Estado de acesso negado (403): o backend barrou por não ser admin.
function _dashboardNegado() {
    const shell = document.querySelector('.shell');
    if (shell) shell.innerHTML =
        '<div class="db-negado"><h1>Acesso restrito</h1>'
        + '<p>O dashboard interno é exclusivo da equipe (perfil admin).</p>'
        + '<a href="index.html">Voltar ao início</a></div>';
}

// ── GRÁFICOS (Chart.js) ──
function _buildCharts(D) {
    if (typeof Chart === 'undefined') return;
    const { azul: AZ, ouro: GR, verde: VD, bege: BE, vermelho: RE } = DASH_COR;
    // Cor do vão entre fatias = fundo do card (--card), NUNCA branco puro (regra fixa).
    const CARD = getComputedStyle(document.documentElement).getPropertyValue('--card').trim() || '#fbf6ec';

    const tk   = { color:'#aaa', font:{ size:10, family:'Plus Jakarta Sans' } };
    const gr   = { color:'rgba(26,43,76,.05)' };
    const base = { responsive:true, maintainAspectRatio:false, plugins:{ legend:{ display:false } } };
    const col  = (rows, k) => rows.map(r => num(r[k]));
    const lab  = (rows, k) => rows.map(r => r[k]);
    const rosca = { ...base, cutout:'70%' };

    const sh = _bloco(D, 'sessoes_hora');
    new Chart($('c1'), { type:'bar', data:{ labels:lab(sh,'hora'), datasets:[
        { data:col(sh,'sessoes'), backgroundColor:AZ, borderRadius:3, order:2 },
        { type:'line', data:col(sh,'alertas'), borderColor:GR, backgroundColor:'transparent', tension:.4, pointRadius:2, pointBackgroundColor:GR, borderWidth:2, order:1 }
    ]}, options:{ ...base, scales:{ x:{ ticks:{ ...tk, maxRotation:0, maxTicksLimit:8 }, grid:{ display:false } }, y:{ ticks:tk, grid:gr, beginAtZero:true } } } });

    const pl = _bloco(D, 'planos');
    _renderLegenda('lg-planos', pl.map(p => `${p.plano} ${p.percentual}%`), [AZ, GR, VD, BE]);
    new Chart($('c2'), { type:'doughnut', data:{ labels:lab(pl,'plano'), datasets:[{ data:col(pl,'percentual'), backgroundColor:[AZ,GR,VD,BE], borderWidth:3, borderColor:CARD, hoverOffset:6 }]}, options:rosca });

    const s14 = _bloco(D, 'sessoes_14dias');
    new Chart($('c3'), { type:'line', data:{ labels:lab(s14,'data'), datasets:[
        { data:col(s14,'iniciadas'),  borderColor:AZ, backgroundColor:'rgba(45,75,165,.07)', fill:true, tension:.35, pointRadius:3, pointBackgroundColor:AZ, borderWidth:2 },
        { data:col(s14,'concluidas'), borderColor:VD, backgroundColor:'rgba(87,217,121,.07)', fill:true, tension:.35, pointRadius:3, pointBackgroundColor:VD, borderDash:[4,3], borderWidth:2 }
    ]}, options:{ ...base, scales:{ x:{ ticks:tk, grid:{ display:false } }, y:{ ticks:tk, grid:gr } } } });

    // afterFit reserva largura fixa para o eixo de categorias. Sem isso o Chart.js
    // mede o rótulo com a fonte de fallback (a webfont carrega depois) e corta o
    // 1º caractere dos nomes longos (ex.: "Vídeo-aula").
    const te = _bloco(D, 'temas_estudados');
    new Chart($('c4'), { type:'bar', data:{ labels:lab(te,'tema'), datasets:[{ data:col(te,'sessoes'), backgroundColor:[AZ,GR,VD,BE,AZ,GR,VD], borderRadius:3 }]},
        options:{ ...base, indexAxis:'y', scales:{ x:{ ticks:tk, grid:gr }, y:{ afterFit:s => { s.width = 96; }, ticks:{ ...tk, font:{ size:10, weight:'600', family:'Plus Jakarta Sans' } }, grid:{ display:false } } } } });

    const df = _bloco(D, 'distribuicao_foco');
    _renderLegenda('lg-foco', df.map(f => `${f.faixa} ${f.percentual}%`), [VD, GR, RE]);
    new Chart($('c5'), { type:'doughnut', data:{ labels:lab(df,'faixa'), datasets:[{ data:col(df,'percentual'), backgroundColor:[VD,GR,RE], borderWidth:3, borderColor:CARD, hoverOffset:6 }]}, options:rosca });

    const fhr = _bloco(D, 'foco_hora');
    new Chart($('c6'), { type:'line', data:{ labels:lab(fhr,'hora'), datasets:[{ data:col(fhr,'foco'), borderColor:VD, backgroundColor:'rgba(87,217,121,.1)', fill:true, tension:.4, pointRadius:0, borderWidth:2 }]},
        options:{ ...base, scales:{ x:{ ticks:{ ...tk, maxTicksLimit:8 }, grid:{ display:false } }, y:{ min:0, max:100, ticks:{ ...tk, callback:v => v + '%' }, grid:gr } } } });

    const mr = _bloco(D, 'mrr_mensal');
    new Chart($('c7'), { type:'bar', data:{ labels:lab(mr,'mes'), datasets:[
        { data:col(mr,'essencial'), backgroundColor:GR, borderRadius:3, stack:'r' },
        { data:col(mr,'intensivo'), backgroundColor:VD, borderRadius:3, stack:'r' }
    ]}, options:{ ...base, scales:{ x:{ ticks:{ ...tk, autoSkip:false }, grid:{ display:false }, stacked:true }, y:{ ticks:{ ...tk, callback:v => 'R$' + Math.round(v / 1000) + 'k' }, grid:gr, stacked:true, beginAtZero:true } } } });
}

// Permite abrir uma aba direto pela URL: dashboard.html#atencao
const DASH_VIEWS = ['geral', 'sessoes', 'atencao', 'fin'];
function _aplicarHash() {
    const id = (location.hash || '').replace('#', '');
    if (!DASH_VIEWS.includes(id)) return;
    sv(id, $$('.tab').find(b => (b.getAttribute('onclick') || '').includes(`'${id}'`)));
}

function _dashClock() {
    const el = $('clk');
    if (el) el.textContent = new Date().toLocaleString('pt-BR',
        { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit' });
}

async function iniciarDashboard() {
    // 1) busca os dados reais (via backend); tolera falha → FALLBACK.
    // Manda a identidade que o front afirma (uuid do perfil) no header. É o que o
    // backend usa para checar perfis.role == 'admin' e responder 403 se não for.
    let D = {};
    try {
        const r = await apiFetch(`/dashboard/dados`, {
            headers: { 'X-Kaia-User': userId }
        });
        if (r.status === 403) { _dashboardNegado(); return; }
        if (r.ok) D = await r.json();
    } catch (e) {
        console.warn('[KaIA Dashboard] backend indisponível — usando dados demo:', e);
    }

    // 2) tabelas, listas e KPIs
    _renderFonte(D);
    _avisoAmostra(D);
    _renderKPIs(_bloco(D, 'kpis'));
    _renderAlunos(_bloco(D, 'alunos_recentes'));
    _renderAlertas(_bloco(D, 'alertas_recentes'));
    _renderEventos(_bloco(D, 'eventos_tipo'));
    _renderMetas(_bloco(D, 'metas_fase'));
    _renderSaude(_bloco(D, 'saude_financeira'));

    // 3) gráficos, relógio e a aba indicada na URL
    _buildCharts(D);
    _dashClock();
    setInterval(_dashClock, 1000);
    _aplicarHash();
    window.addEventListener('hashchange', _aplicarHash);
}

// Só dashboard.html carrega este arquivo; comum.js já montou a rail.
document.addEventListener('DOMContentLoaded', iniciarDashboard);
