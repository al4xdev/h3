import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {GROK_WAIT_MESSAGES, createGrokWaiting} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function fixture() {
  const document = new EventTarget(), preference = new EventTarget(), nodes = [], callbacks = new Map(); let timerID = 0;
  preference.matches = false; document.hidden = false;
  const host = {textContent: 'Status real do pedido', matches: () => false, after(node) { nodes.push(node); }};
  document.getElementById = () => host;
  document.defaultView = {matchMedia: () => preference};
  document.createElement = () => {
    const classes = new Set();
    return {textContent: '', attrs: {}, children: [], hiddenParent: false, visible: true, removed: false,
      classList: {toggle(key, value) { if (value) classes.add(key); else classes.delete(key); }, contains: key => classes.has(key)},
      setAttribute(key, value) { this.attrs[key] = value; }, append(...children) { this.children.push(...children); },
      closest() { return this.hiddenParent ? {} : null; }, checkVisibility() { return this.visible; }, remove() { this.removed = true; }};
  };
  const timers = {setTimeout(callback, delay) { assert.equal(delay, 4800); callbacks.set(++timerID, callback); return timerID; }, clearTimeout(id) { callbacks.delete(id); }};
  const waiting = createGrokWaiting(document, timers);
  function tick() { const current = [...callbacks.values()]; callbacks.clear(); for (const callback of current) callback(); }
  return {document, preference, host, nodes, callbacks, waiting, tick};
}
test('twenty different waiting messages never claim completion', () => {
  assert.equal(GROK_WAIT_MESSAGES.length, 20); assert.equal(new Set(GROK_WAIT_MESSAGES).size, 20);
  assert.ok(GROK_WAIT_MESSAGES.every(value => value.split(' ').length <= 8));
  assert.ok(GROK_WAIT_MESSAGES.every(value => !/quase pronto|concluído|\d+%|gerando vídeo/i.test(value)));
});
test('waiting rotates decoration without touching real status or submitting work again', async () => {
  const f = fixture(); let release, calls = 0;
  const task = f.waiting.track('grok-status', () => { calls++; return new Promise(resolve => { release = resolve; }); });
  const node = f.nodes[0], copy = node.children[1], original = copy.textContent;
  assert.equal(node.attrs['aria-hidden'], 'true'); assert.equal(f.callbacks.size, 1);
  f.tick(); assert.notEqual(copy.textContent, original); assert.equal(f.host.textContent, 'Status real do pedido'); assert.equal(calls, 1);
  release('Proposta real'); assert.equal(await task, 'Proposta real'); assert.equal(node.removed, true); assert.equal(f.callbacks.size, 0);
});
test('failed or uncertain provider response ends decoration and retains the original error', async () => {
  const f = fixture(), error = new Error('Lost response'); let calls = 0;
  await assert.rejects(f.waiting.track('tail-status', async () => { calls++; throw error; }), value => value === error);
  assert.equal(calls, 1); assert.equal(f.nodes[0].removed, true); assert.equal(f.callbacks.size, 0);
});
test('an old response cannot remove a newer waiting indicator in the same panel', async () => {
  const f = fixture(); let first, second;
  const old = f.waiting.track('grok-status', () => new Promise(resolve => { first = resolve; }));
  const current = f.waiting.track('grok-status', () => new Promise(resolve => { second = resolve; }));
  assert.equal(f.nodes[0].removed, true); first('old'); await old; assert.equal(f.nodes[1].removed, false);
  second('current'); await current; assert.equal(f.nodes[1].removed, true); assert.equal(f.callbacks.size, 0);
});
test('hidden tab, hidden panel and closed details pause the timer and resume safely', () => {
  for (const kind of ['tab', 'panel', 'details']) {
    const f = fixture(); f.waiting.set('batch-status', true, 'known-id'); const node = f.nodes[0];
    if (kind === 'tab') f.document.hidden = true;
    if (kind === 'panel') node.hiddenParent = true;
    if (kind === 'details') node.visible = false;
    f.waiting.sync(); assert.equal(f.callbacks.size, 0); assert.equal(node.classList.contains('grok-wait-paused'), true);
    f.document.hidden = false; node.hiddenParent = false; node.visible = true; f.document.dispatchEvent(new Event('visibilitychange'));
    assert.equal(f.callbacks.size, 1); f.waiting.set('batch-status', false); assert.equal(f.callbacks.size, 0);
  }
});
test('reduced motion dynamically freezes both movement and message changes', () => {
  const f = fixture(); f.preference.matches = true; f.waiting.set('batch-status', true, 'known-id');
  assert.equal(f.callbacks.size, 0); assert.equal(f.nodes[0].classList.contains('grok-wait-paused'), true);
  f.preference.matches = false; f.preference.dispatchEvent(new Event('change')); assert.equal(f.callbacks.size, 1);
  f.preference.matches = true; f.preference.dispatchEvent(new Event('change')); assert.equal(f.callbacks.size, 0);
  f.waiting.set('batch-status', false);
});
test('repeated confirmed batch observations retain the same presentation identity', () => {
  const f = fixture(); f.waiting.set('batch-status', true, 'known-id'); f.waiting.set('batch-status', true, 'known-id');
  assert.equal(f.nodes.length, 1); assert.equal(f.callbacks.size, 1); f.waiting.set('batch-status', false); assert.equal(f.callbacks.size, 0);
  const controller = source.slice(source.indexOf('export function createGrokWaiting('), source.indexOf('export function blockedActionReason('));
  assert.doesNotMatch(controller, /fetch\(|client\.|stories\.|POST|UUID|\.value\s*=/);
  assert.match(source, /!state.batchUncertain && state.batchRecord\?\.state === 'active' && state.batchRecord.phase === 'improving'/);
});
