// ============================================================
//  KaIA — constelação das faixas da landing
// ============================================================
// Padrão de pontos e linhas desenhado POR CIMA do fundo da faixa (o fundo em si
// não muda). Serve duas faixas: o herói e a do título "Conheça a KaIA". Reage
// ao cursor; nada clicável.
//
// Carregado com defer DEPOIS do comum.js: as cores saem de getComputedStyle
// lendo --azul-coati, e esse token só vale o tema certo depois
// que o comum.js põe o data-luz no <html>. Nenhum hex mora aqui de propósito —
// é o defeito do letreiro (PNG com #1a2b4c assado dentro) que não se repete.

(function () {
    'use strict';

    const ESPACO = 46;          // espaçamento da grade, px
    const JITTER = 0.55;        // desvio aleatório, fração do espaçamento
    const RAIO_MIN = 1, RAIO_MAX = 2.3;
    const D_PERTO = 120;        // ponto acende dentro disto do cursor
    const ALFA_PONTO = 0.30;    // opacidade de repouso
    const ALFA_PERTO = 0.62;    // opacidade com o cursor por perto
    const RAIO_PERTO = 1.45;    // o ponto aceso também cresce
    const D_LINHA = 72;         // liga pontos a menos disto
    const D_EMPURRA = 170;      // cursor empurra dentro disto
    const EMPURRA = 22;         // deslocamento máximo, px (antes da força)
    const DERIVA = 3.4;         // amplitude da deriva lenta, px
    const RAMPA = 0.12;         // fração da largura em que o alfa sobe de 0 a 1
    const MIN_LARGURA = 860;    // abaixo disto o canvas nem existe
    const SEMENTE = 0x5ca1a;    // ver aleatorio() logo abaixo

    // SEMENTE FIXA, e não Math.random(). Com sorteio, cada carregamento
    // desenhava uma grade diferente — e um contraste medido uma vez só vale se
    // o desenho não mudar a cada visita. Já nos queimou: a faixa do título no
    // tema 3 oscilava de 4,48 a 5,02 entre renders, atravessando o piso.
    // Agora mesma largura -> mesmo desenho, sempre, e o número medido é o
    // número que o aluno vê. mulberry32, escrito aqui, sem dependência nova.
    function aleatorio(semente) {
        let a = semente >>> 0;
        return function () {
            a = (a + 0x6D2B79F5) >>> 0;
            let t = a;
            t = Math.imul(t ^ (t >>> 15), t | 1);
            t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    // Cada faixa com a sua força. O herói tem fundo --surface, mais claro que o
    // --marfim da outra, então o mesmo alfa pesa mais lá; a diferença entre 1.3
    // e 1.0 é medida, não chutada (ver o relatório da rodada).
    // `alvo` = a máscara acompanha o RETÂNGULO daquele bloco. Só o herói usa:
    // lá o conteúdo (h1 + subtítulo + botão) é um bloco centrado de 720px numa
    // faixa de 1920, e a elipse precisa cobrir os três.
    // A faixa do título usa a elipse FIXA: o .content-header dela é um bloco de
    // largura inteira (1652 de 1780), e medi-lo faria a máscara engolir a faixa
    // toda — a constelação ficava 5x a 14x mais fraca que a do herói, contra os
    // 1.3x que a diferença de força pede. Medido.
    // `dentro` = raio normalizado abaixo do qual a máscara apaga TUDO. O herói
    // fica nos 0.78 originais; a faixa do título sobe para 0.95 porque ali a
    // margem de contraste é a mais estreita dos quatro temas (fundo --marfim
    // #8897ba contra texto --profundo #1a2340 no tema 3) e qualquer ponto que
    // escape perto de uma letra derruba o número. Medido, não chutado.
    const FAIXAS = [
        { sel: '.lp-hero', forca: 1.3, alvo: '.lp-hero-inner', dentro: 0.78 },
        { sel: '.lp-faixa-titulo', forca: 1.0, alvo: null, dentro: 0.95 }
    ];

    // Trava 1: no celular nenhuma faixa ganha canvas. matchMedia com a MESMA
    // condição do CSS (max-width: 860px) e não innerWidth, que conta a barra de
    // rolagem e faria os dois discordarem em volta do corte.
    const semCanvas = matchMedia('(max-width: ' + MIN_LARGURA + 'px)').matches;

    FAIXAS.forEach(function (cfg) {
        const faixa = document.querySelector(cfg.sel);
        if (!faixa) return;
        const canvas = faixa.querySelector(':scope > .lp-constelacao');
        if (!canvas) return;
        if (semCanvas) { canvas.remove(); return; }
        try {
            montarFaixa(faixa, canvas, cfg.forca, cfg.alvo, cfg.dentro);
        } catch (e) {
            // Se qualquer coisa falhar, a faixa continua legível exatamente como
            // é sem o canvas. Tira o elemento e segue a vida.
            try { canvas.remove(); } catch (_) { }
            console.warn('[KaIA] constelação não iniciou em ' + cfg.sel + ':', e);
        }
    });

    function montarFaixa(faixa, canvas, FORCA, seletorAlvo, DENTRO) {
        const ctx = canvas.getContext('2d');
        if (!ctx) throw new Error('sem contexto 2d');

        const reduzir = matchMedia('(prefers-reduced-motion: reduce)');
        let pontos = [], larg = 0, alt = 0;
        let mx = 0, my = 0, mrx = 1, mry = 1;      // elipse da máscara
        let rafId = null, visivel = true, t0 = performance.now();
        const mouse = { x: -1e4, y: -1e4 };

        // UMA cor só: --azul-coati na base E no realce. Antes a base era o
        // --profundo e o realce o azul-coati, o que dava a "acesa" pela troca de
        // matiz. Com a mesma cor nos dois, quem acende é a OPACIDADE (0.30 ->
        // 0.62) e o RAIO (x1.45): o ponto perto do cursor fica mais sólido e um
        // pouco maior, em vez de mudar de cor.
        let corPonto = '0,0,0';
        function lerCores() {
            const cs = getComputedStyle(document.documentElement);
            corPonto = hexParaRgb(cs.getPropertyValue('--azul-coati').trim());
        }
        function hexParaRgb(h) {
            h = h.replace('#', '');
            if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
            const n = parseInt(h, 16);
            return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(',');
        }

        function montar() {
            const r = faixa.getBoundingClientRect();
            larg = Math.max(1, Math.round(r.width));
            alt = Math.max(1, Math.round(r.height));
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            canvas.width = Math.round(larg * dpr);
            canvas.height = Math.round(alt * dpr);
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            lerCores();

            // A máscara se dimensiona pelo BLOCO DE CONTEÚDO inteiro, não pelo
            // título: no herói o bloco é h1 + subtítulo + botão, e medir só o h1
            // deixaria o botão dentro do padrão. Com folga de 28px em volta.
            const alvo = seletorAlvo ? faixa.querySelector(seletorAlvo) : null;
            if (alvo) {
                const a = alvo.getBoundingClientRect();
                mx = a.left - r.left + a.width / 2;
                my = a.top - r.top + a.height / 2;
                mrx = Math.max(60, a.width / 2 + 28);
                mry = Math.max(40, a.height / 2 + 28);
            } else {
                mx = larg / 2; my = alt / 2;
                mrx = Math.min(420, larg * 0.42);
                mry = Math.min(120, alt * 0.46);
            }

            // o gerador reinicia na mesma semente a cada remontagem: a grade é
            // função só das dimensões, nunca do acaso.
            const rnd = aleatorio(SEMENTE);
            pontos = [];
            for (let y = ESPACO / 2; y < alt + ESPACO; y += ESPACO) {
                for (let x = ESPACO / 2; x < larg + ESPACO; x += ESPACO) {
                    pontos.push({
                        bx: x + (rnd() * 2 - 1) * ESPACO * JITTER,
                        by: y + (rnd() * 2 - 1) * ESPACO * JITTER,
                        r: RAIO_MIN + rnd() * (RAIO_MAX - RAIO_MIN),
                        f: 0.6 + rnd() * 0.8,
                        x: 0, y: 0, m: 1, perto: false
                    });
                }
            }
        }

        // A MÁSCARA NÃO É ENFEITE. O conteúdo fica no meio da faixa; sem abrir um
        // buraco atrás dele, pontos e linhas entram no meio dos glifos e o
        // contraste LOCAL desaba — e o auditor de CSS não enxerga isso, porque lê
        // cor computada e é cego para canvas. Dentro de 0.78 do raio apaga tudo,
        // a partir de 1.45 desenha cheio, entre os dois sobe linear. Vale para
        // ponto e para linha (nesta, pelo ponto médio). DENTRO vem da faixa.
        function mascara(x, y) {
            const dx = (x - mx) / mrx, dy = (y - my) / mry;
            const d = Math.sqrt(dx * dx + dy * dy);
            if (d <= DENTRO) return 0;
            if (d >= 1.45) return 1;
            return (d - DENTRO) / (1.45 - DENTRO);
        }

        // RAMPA DAS PONTAS. A faixa deixou de sangrar até a borda da tela (o vw
        // criava barra de rolagem), então ela termina num limite visível. Sem
        // esmaecer, o padrão acabaria em corte seco nas duas pontas.
        function rampa(x) {
            const d = RAMPA * larg;
            if (d <= 0) return 1;
            if (x < d) return Math.max(0, x / d);
            if (x > larg - d) return Math.max(0, (larg - x) / d);
            return 1;
        }

        function desenhar(agora) {
            const t = (agora - t0) / 1000;
            ctx.clearRect(0, 0, larg, alt);

            for (let i = 0; i < pontos.length; i++) {
                const p = pontos[i];
                let x = p.bx + Math.sin(t * 0.35 * p.f + i) * DERIVA;
                let y = p.by + Math.cos(t * 0.29 * p.f + i * 1.7) * DERIVA;

                const ddx = x - mouse.x, ddy = y - mouse.y;
                const dist = Math.hypot(ddx, ddy);
                if (dist < D_EMPURRA && dist > 0.01) {
                    const f = (1 - dist / D_EMPURRA) * EMPURRA * FORCA;
                    x += (ddx / dist) * f;
                    y += (ddy / dist) * f;
                }
                p.x = x; p.y = y;
                p.m = mascara(x, y) * rampa(x);
                p.perto = dist < D_PERTO;
            }

            ctx.lineWidth = 1;
            for (let i = 0; i < pontos.length; i++) {
                const a = pontos[i];
                for (let j = i + 1; j < pontos.length; j++) {
                    const b = pontos[j];
                    const dx = a.x - b.x;
                    if (dx > D_LINHA || dx < -D_LINHA) continue;   // poda barata
                    const dy = a.y - b.y;
                    if (dy > D_LINHA || dy < -D_LINHA) continue;
                    const d = Math.hypot(dx, dy);
                    if (d >= D_LINHA) continue;
                    const mx2 = (a.x + b.x) / 2;
                    const m = mascara(mx2, (a.y + b.y) / 2) * rampa(mx2);
                    if (m <= 0) continue;
                    const alfa = Math.min(0.30, (1 - d / D_LINHA) * 0.17 * FORCA) * m;
                    if (alfa <= 0.004) continue;
                    ctx.strokeStyle = 'rgba(' + corPonto + ',' + alfa.toFixed(3) + ')';
                    ctx.beginPath();
                    ctx.moveTo(a.x, a.y);
                    ctx.lineTo(b.x, b.y);
                    ctx.stroke();
                }
            }

            for (let i = 0; i < pontos.length; i++) {
                const p = pontos[i];
                if (p.m <= 0) continue;
                const alfa = (p.perto ? ALFA_PERTO : ALFA_PONTO) * FORCA * p.m;
                ctx.fillStyle = 'rgba(' + corPonto + ','
                    + Math.min(1, alfa).toFixed(3) + ')';
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.perto ? p.r * RAIO_PERTO : p.r, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        function quadro(ts) {
            desenhar(ts);
            rafId = requestAnimationFrame(quadro);
        }

        // O LOOP SÓ RODA COM A FAIXA NA TELA. Não é economia de enfeite: é um rAF
        // a 60fps sobre centenas de pontos, e deixá-lo girando com a faixa fora
        // de vista gasta bateria do aluno sem desenhar nada que ele veja. Cada
        // faixa tem o seu observador, então uma para sem parar a outra. Mesma
        // razão para parar quando a aba perde o foco.
        function ligar() {
            if (rafId !== null || !visivel || reduzir.matches) return;
            t0 = performance.now();
            rafId = requestAnimationFrame(quadro);
        }
        function desligar() {
            if (rafId === null) return;
            cancelAnimationFrame(rafId);
            rafId = null;
            if (window.__kaiaConstelacaoLog) console.log('[KaIA] constelação: rAF cancelado');
        }

        montar();
        desenhar(performance.now());   // trava 2: um quadro sempre, mesmo parado

        new ResizeObserver(function () {
            montar();
            if (rafId === null) desenhar(performance.now());
        }).observe(faixa);

        new IntersectionObserver(function (es) {
            visivel = es[0].isIntersecting;
            if (visivel) ligar(); else desligar();
        }, { threshold: 0 }).observe(faixa);

        document.addEventListener('visibilitychange', function () {
            if (document.hidden) desligar(); else ligar();
        });

        // Trava 2: com movimento reduzido fica no quadro único. O 'change' cobre
        // quem muda a preferência com a página aberta.
        reduzir.addEventListener('change', function () {
            if (reduzir.matches) desligar(); else ligar();
        });

        faixa.addEventListener('pointermove', function (e) {
            const r = faixa.getBoundingClientRect();
            mouse.x = e.clientX - r.left;
            mouse.y = e.clientY - r.top;
        });
        faixa.addEventListener('pointerleave', function () {
            mouse.x = mouse.y = -1e4;
        });

        if (!reduzir.matches) ligar();
    }
})();
