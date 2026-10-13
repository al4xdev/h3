export function createStopConfirmation({document, card, onConfirm, onCancel, label = 'Parar', signal}) {
  const view = document.defaultView;
  const preference = view?.matchMedia?.('(prefers-reduced-motion: reduce)');
  let destroyed = false;
  let opened = false;
  let busy = false;
  let submitted = false;
  let statusRevision = 0;
  let animation;
  const listeners = [];
  const make = (tag, className, text) => {
    const element = document.createElement(tag);
    element.className = className;
    if (text) element.textContent = text;
    return element;
  };
  const listen = (target, type, callback) => {
    target?.addEventListener(type, callback);
    listeners.push(() => target?.removeEventListener(type, callback));
  };
  const stopButton = make('button', 'stop-confirmation-trigger', label);
  const overlay = make('div', 'stop-confirmation');
  const fill = make('div', 'stop-confirmation-fill');
  const choices = make('div', 'stop-confirmation-choices');
  const cancelButton = make('button', 'stop-confirmation-cancel', 'Cancelar');
  const confirmButton = make('button', 'stop-confirmation-confirm', 'Confirmar parada');
  const status = make('p', 'stop-confirmation-status');
  for (const button of [stopButton, cancelButton, confirmButton]) {
    button.type = 'button';
    button.setAttribute('data-no-swipe', '');
  }
  stopButton.setAttribute('aria-expanded', 'false');
  overlay.setAttribute('role', 'group');
  overlay.setAttribute('aria-label', 'Confirmar parada desta operação');
  overlay.setAttribute('data-no-swipe', '');
  fill.setAttribute('aria-hidden', 'true');
  status.setAttribute('role', 'status');
  overlay.hidden = true;
  choices.append(cancelButton, confirmButton);
  overlay.append(fill, choices, status);
  card.classList.add('has-stop-confirmation');
  card.append(stopButton, overlay);
  const stopMotion = () => { animation?.cancel(); animation = undefined; };
  const render = () => {
    stopButton.disabled = busy || submitted;
    cancelButton.disabled = busy || submitted;
    confirmButton.disabled = busy || submitted;
    overlay.setAttribute('aria-busy', String(busy));
  };
  const setStatus = text => {
    if (!destroyed) { status.textContent = text; statusRevision++; }
  };
  const open = () => {
    if (destroyed || opened || busy || submitted) return;
    opened = true;
    overlay.hidden = false;
    stopButton.setAttribute('aria-expanded', 'true');
    cancelButton.focus();
    if (!preference?.matches && !document.hidden && fill.animate) {
      animation = fill.animate([{transform: 'scaleX(0)'}, {transform: 'scaleX(1)'}], {duration: 200, easing: 'ease-out'});
    }
  };
  const cancel = () => {
    if (destroyed || !opened || busy || submitted) return;
    stopMotion();
    opened = false;
    overlay.hidden = true;
    stopButton.setAttribute('aria-expanded', 'false');
    stopButton.focus();
    onCancel?.();
  };
  const updateBusy = value => { if (!destroyed) { busy = Boolean(value); render(); } };
  const confirm = () => {
    if (destroyed || !opened || busy || submitted) return;
    submitted = true;
    busy = true;
    stopMotion();
    setStatus('Solicitando parada…');
    const pendingStatusRevision = statusRevision;
    render();
    let result;
    try { result = onConfirm(); }
    catch { result = Promise.reject(); }
    Promise.resolve(result).then(outcome => {
      if (destroyed) return;
      busy = false;
      if (outcome?.requested === false) {
        submitted = false;
        if (statusRevision === pendingStatusRevision) {
          setStatus(typeof outcome.status === 'string' ? outcome.status : 'Nenhum pedido de parada foi enviado.');
        }
      } else if (statusRevision === pendingStatusRevision) {
        setStatus(typeof outcome?.status === 'string' ? outcome.status :
          'Parada solicitada. Aguardando confirmação.');
      }
      render();
    }, () => {
      if (destroyed) return;
      busy = false;
      if (statusRevision === pendingStatusRevision) {
        setStatus('Não foi possível confirmar a parada. Consulte o estado da operação.');
      }
      render();
    });
  };
  const destroy = () => {
    if (destroyed) return;
    destroyed = true;
    stopMotion();
    for (const remove of listeners) remove();
    stopButton.remove();
    overlay.remove();
    card.classList.remove('has-stop-confirmation');
  };
  listen(stopButton, 'click', event => { event.stopPropagation(); open(); });
  listen(cancelButton, 'click', event => { event.stopPropagation(); cancel(); });
  listen(confirmButton, 'click', event => { event.stopPropagation(); confirm(); });
  listen(overlay, 'keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancel(); }
  });
  listen(preference, 'change', stopMotion);
  listen(document, 'visibilitychange', () => { if (document.hidden) stopMotion(); });
  listen(view, 'pagehide', destroy);
  listen(signal, 'abort', destroy);
  if (signal?.aborted) destroy();
  render();
  return {stopButton, open, cancel, destroy, updateBusy, setStatus};
}
