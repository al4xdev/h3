export function setupPwa(view = window, document = view.document) {
  const button = document.getElementById('pwa-install');
  const status = document.getElementById('pwa-status');
  const say = message => { if (status) status.textContent = message; };
  if (!view.isSecureContext) {
    say('Instalação como app requer HTTPS confiável. HTTP pelo IP do PC abre o site, mas não habilita o PWA no celular.');
    return;
  }
  const installed = view.matchMedia('(display-mode: fullscreen)').matches
    || view.matchMedia('(display-mode: standalone)').matches || view.navigator.standalone;
  say(installed ? 'H3 aberto como app. A conexão com o PC continua necessária.'
    : 'Use “Instalar app” no navegador ou “Adicionar à Tela de Início” no Safari. A conexão com o PC continua necessária.');
  if ('serviceWorker' in view.navigator) {
    view.navigator.serviceWorker.register('/service-worker.js', {scope: '/', updateViaCache: 'none'})
      .catch(() => say('Não foi possível preparar a tela de desconexão. O estúdio continua disponível enquanto conectado.'));
  }
  let invitation = null;
  view.addEventListener('beforeinstallprompt', event => {
    if (!button || installed) return;
    event.preventDefault();
    invitation = event;
    button.hidden = false;
    say('Instale o H3 para abrir em uma janela própria. A conexão com o PC continua necessária.');
  });
  button?.addEventListener('click', async () => {
    const pending = invitation;
    if (!pending) return;
    invitation = null;
    button.hidden = true;
    try {
      await pending.prompt();
      const choice = await pending.userChoice;
      say(choice.outcome === 'accepted' ? 'Instalação solicitada ao navegador.'
        : 'Instalação cancelada. Você pode continuar pelo navegador.');
    } catch {
      say('Use a opção de instalação no menu do navegador.');
    }
  });
  view.addEventListener('appinstalled', () => {
    invitation = null;
    if (button) button.hidden = true;
    say('H3 instalado. Abra pelo ícone; a conexão com o PC continua necessária.');
  });
}

if (typeof window !== 'undefined') setupPwa();
