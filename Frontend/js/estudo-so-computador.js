// ============================================================
//  KaIA — estudo-so-computador.js: sessão de estudo só no computador (beta)
// ============================================================
// SÓ materias.html. NUNCA no comum.js: o consentimento.html carrega o comum.js, e o
// responsável abre aquele link no celular — bloquear ali mata o aceite da LGPD.
// Carregado DEPOIS do comum.js (a rail já foi montada quando o DOMContentLoaded
// daqui roda) e ANTES do materias.js (que lê a flag e desiste do init).

// PONTEIRO, NÃO LARGURA. Não "simplifique" para max-width.
// O que a sessão mede (trajeto do mouse, teclado, ociosidade) depende de mouse e
// teclado; dedo na tela gera outra medida, que iria para o banco misturada. Largura
// erra para os dois lados: janela estreita de desktop tem mouse (não deve bloquear) e
// iPhone Pro Max deitado dá 932px (passaria). E largura muda ao girar o aparelho,
// o que obrigaria a ligar/desligar sensores ao vivo (listener dobrado em silêncio).
// Ponteiro não muda ao girar: decide UMA vez, no carregamento, antes de qualquer init.
// Consequência aceita: tablet com dedo também cai aqui. É intencional.
//
// NEM TUDO PARA: a guarda (materias.js:3465) só corta o init que importa (sensores,
// pomodoro, meta). Outros três DOMContentLoaded do materias.js seguem rodando —
// pintarFaixasDasMaterias (3850), ligarAlcaSplit (3955) e o do caderno (3417) —, e
// tudo bem: nenhum mede nem registra nada, são cosméticos sobre conteúdo inert e escondido.
window.KAIA_ESTUDO_BLOQUEADO = !!window.matchMedia?.('(pointer: coarse)').matches;

if (window.KAIA_ESTUDO_BLOQUEADO) {
    document.addEventListener('DOMContentLoaded', () => {
        document.body.classList.add('estudo-bloqueado');

        // Conteúdo de estudo inalcançável (clique, Tab e leitor de tela). A rail fica
        // viva: a pessoa não pode ficar presa, sai por ali para o perfil ou o coati.
        for (const el of document.body.children) {
            if (el.matches('.railnav, script')) continue;
            el.inert = true;
            el.setAttribute('aria-hidden', 'true');
        }

        const aviso = document.createElement('section');
        aviso.className = 'estudo-pc';
        aviso.tabIndex = -1;   // recebe o foco ao aparecer, sem entrar na ordem do Tab
        aviso.setAttribute('aria-labelledby', 'estudo-pc-titulo');
        // Texto da Bia. SEM listar o que é medido (tempo por questão, pausas, mouse,
        // teclado): enumerar sensores numa tela de bloqueio soa como vigilância — foi
        // o que tirou o "Ainda está Conosco?" da tela de ociosidade. Não devolva a lista.
        aviso.innerHTML = `
            <h1 id="estudo-pc-titulo" class="estudo-pc__titulo">A sessão de estudo chega ao celular em breve</h1>
            <p class="estudo-pc__texto">Por enquanto, as sessões de estudo da KaIA acontecem no computador:
                durante o estudo ela acompanha o seu ritmo pela tela, e isso depende
                de mouse e teclado. A versão para toque ainda está sendo feita.</p>
            <p class="estudo-pc__texto">Nada do que você já estudou se perde. É só abrir no computador com a
                mesma conta e continuar de onde parou.</p>
            <p class="estudo-pc__texto">Enquanto isso, aqui no celular você pode:</p>
            <div class="estudo-pc__acoes">
                <a class="e404-btn e404-btn-cheio" href="perfil.html">Ver meu perfil</a>
                <a class="e404-btn e404-btn-contorno" href="meu-coati.html">Visitar meu coati</a>
            </div>`;
        document.body.append(aviso);
        aviso.focus();
    });
}
