import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/h3_backend/web/stop-confirmation.js', import.meta.url), 'utf8');
const {createStopConfirmation} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

class Element extends EventTarget {
  constructor(document) {
    super();
    this.document = document;
    this.children = [];
    this.attributes = new Map();
    this.classes = new Set();
    this.classList = {add: value => this.classes.add(value), remove: value => this.classes.delete(value)};
  }
  append(...elements) { for (const element of elements) { element.parent = this; this.children.push(element); } }
  remove() { this.parent.children = this.parent.children.filter(element => element !== this); }
  setAttribute(key, value) { this.attributes.set(key, value); }
  focus() { this.document.activeElement = this; }
  animate(frames, options) {
    assert.equal(frames[0].transform, 'scaleX(0)');
    assert.ok(options.duration <= 440);
    this.motion = {cancelled: false, cancel() { this.cancelled = true; }};
    return this.motion;
  }
  click() { if (!this.disabled) this.dispatchEvent(new Event('click')); }
}
function fixture(onConfirm = () => undefined, options = {}) {
  const preference = new EventTarget();
  preference.matches = Boolean(options.reduced);
  const document = new EventTarget();
  const view = new EventTarget();
  view.matchMedia = () => preference;
  document.defaultView = view;
  document.createElement = () => new Element(document);
  const card = new Element(document);
  let cancellations = 0;
  const api = createStopConfirmation({document, card, onConfirm, onCancel: () => cancellations++, ...options});
  const overlay = card.children[1];
  const [fill, choices, status] = overlay.children;
  const [cancel, confirm] = choices.children;
  return {api, document, view, preference, card, overlay, fill, status, cancel, confirm, cancellations: () => cancellations};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('requested stop displays the returned terminal or uncertain domain status', async () => {
  for (const status of ['Parada confirmada no PC.', 'Resultado incerto. Consulte este mesmo pedido.']) {
    const f = fixture(() => ({requested: true, status}));
    f.api.open();
    f.confirm.click();
    await settle();
    assert.equal(f.status.textContent, status);
    assert.equal(f.confirm.disabled, true);
  }
});

test('first tap only reveals; cancel and Escape restore focus without business callback', () => {
  let calls = 0;
  const f = fixture(() => calls++);
  f.api.stopButton.click();
  f.api.stopButton.click();
  assert.equal(calls, 0);
  assert.equal(f.overlay.hidden, false);
  assert.equal(f.document.activeElement, f.cancel);
  f.cancel.click();
  assert.equal(f.overlay.hidden, true);
  assert.equal(f.cancellations(), 1);
  f.api.open();
  const escape = new Event('keydown', {cancelable: true});
  Object.defineProperty(escape, 'key', {value: 'Escape'});
  f.overlay.dispatchEvent(escape);
  assert.equal(escape.defaultPrevented, true);
  assert.equal(f.document.activeElement, f.api.stopButton);
  assert.equal(f.cancellations(), 2);
  assert.equal(calls, 0);
});

test('explicit confirmation deduplicates rapid clicks and retains uncertain failure fence', async () => {
  let reject;
  let calls = 0;
  const f = fixture(() => { calls++; return new Promise((_, no) => { reject = no; }); });
  f.api.open();
  f.confirm.click();
  f.confirm.click();
  f.api.cancel();
  assert.equal(calls, 1);
  assert.equal(f.cancel.disabled, true);
  assert.equal(f.overlay.hidden, false);
  reject(new Error('unknown'));
  await settle();
  assert.match(f.status.textContent, /Não foi possível confirmar/);
  f.api.updateBusy(false);
  f.confirm.click();
  assert.equal(calls, 1);
  assert.equal(f.confirm.disabled, true);
});

test('motion stops on dynamic preference and hidden without changing confirmation', () => {
  const f = fixture();
  f.api.open();
  const initial = f.fill.motion;
  f.preference.matches = true;
  f.preference.dispatchEvent(new Event('change'));
  assert.equal(initial.cancelled, true);
  assert.equal(f.overlay.hidden, false);
  f.api.cancel();
  f.api.open();
  assert.equal(f.fill.motion, initial);
  f.api.cancel();
  f.preference.matches = false;
  f.api.open();
  const next = f.fill.motion;
  f.document.hidden = true;
  f.document.dispatchEvent(new Event('visibilitychange'));
  assert.equal(next.cancelled, true);
  assert.equal(f.overlay.hidden, false);
});

test('busy admission, abort, pagehide and destroyed async completion are inert', async () => {
  let resolve;
  const signal = new AbortController();
  const f = fixture(() => new Promise(yes => { resolve = yes; }), {signal: signal.signal, reduced: true});
  f.api.updateBusy(true);
  f.api.open();
  assert.equal(f.overlay.hidden, true);
  f.api.updateBusy(false);
  f.api.open();
  assert.equal(f.fill.motion, undefined);
  f.confirm.click();
  signal.abort();
  assert.equal(f.card.children.length, 0);
  const text = f.status.textContent;
  resolve();
  await settle();
  assert.equal(f.status.textContent, text);
  f.api.destroy();
  f.api.open();
  const other = fixture();
  other.view.dispatchEvent(new Event('pagehide'));
  assert.equal(other.card.children.length, 0);
});

test('synchronous business errors are fenced; successful request does not claim completion', async () => {
  const failure = fixture(() => { throw new Error('uncertain'); });
  failure.api.open();
  failure.confirm.click();
  await settle();
  assert.match(failure.status.textContent, /Consulte o estado/);
  const success = fixture();
  success.api.open();
  success.confirm.click();
  await settle();
  assert.match(success.status.textContent, /Aguardando confirmação/);
  assert.equal(success.confirm.disabled, true);
});

test('confirmed and uncertain domain statuses remain authoritative after settlement', async () => {
  let success;
  success = fixture(() => { success.api.setStatus('Parada confirmada no PC.'); });
  success.api.open();
  success.confirm.click();
  await settle();
  assert.equal(success.status.textContent, 'Parada confirmada no PC.');
  let failure;
  failure = fixture(() => {
    failure.api.setStatus('Resultado incerto. Consulte este mesmo pedido.');
    return Promise.reject(new Error('unknown'));
  });
  failure.api.open();
  failure.confirm.click();
  await settle();
  assert.equal(failure.status.textContent, 'Resultado incerto. Consulte este mesmo pedido.');
  assert.equal(failure.confirm.disabled, true);
});

test('explicit no-op guard releases confirmation without claiming a request', async () => {
  let calls = 0;
  const f = fixture(() => {
    calls++;
    return {requested: false, status: 'Estado atualizado. Nenhum pedido enviado.'};
  });
  f.api.open();
  f.confirm.click();
  f.confirm.click();
  assert.equal(calls, 1);
  await settle();
  assert.equal(f.status.textContent, 'Estado atualizado. Nenhum pedido enviado.');
  assert.equal(f.confirm.disabled, false);
  f.confirm.click();
  assert.equal(calls, 2);
  await settle();
  f.api.cancel();
  assert.equal(f.overlay.hidden, true);
});
