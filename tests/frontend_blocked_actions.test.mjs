import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
const css = await readFile(new URL('../src/h3_backend/web/app.css', import.meta.url), 'utf8');
const {blockedActionReason, createBlockedActionFeedback} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function button(id, classes = []) {
  return {id, disabled: true, dataset: {}, title: 'Original label', attrs: {}, hidden: false,
    classList: {contains: value => classes.includes(value)},
    closest(selector) { return selector === 'button:disabled' && this.disabled || selector === 'button' ? this : null; },
    matches() { return this.disabled; },
    getBoundingClientRect() { return {left: 10, top: 10, right: 110, bottom: 60, width: 100, height: 50}; },
    setAttribute(key, value) { this.attrs[key] = value; }, removeAttribute(key) { delete this.attrs[key]; }};
}
test('blocked actions explain the actual Tail and batch prerequisite', () => {
  const state = {config: {}}, story = {doc: {blocks: Array(3)}};
  assert.match(blockedActionReason(button('tail-plan'), state, story), /aceite todos/);
  story.doc.blocks = Array(50); assert.match(blockedActionReason(button('tail-plan'), state, story), /50 blocos/);
  assert.match(blockedActionReason(button('story-batch'), state, story), /Salve o prompt/);
  assert.match(blockedActionReason(button('story-batch'), state, story, {savedBatchEditor: true, batchDraftsClean: false}), /edições/);
  assert.match(blockedActionReason(button('story-batch'), state, story, {savedBatchEditor: true, batchDraftsClean: true}), /Revise os vídeos/);
});
test('uncertainty gives same-ID recovery directions and never suggests replay', () => {
  for (const [state, story, phrase] of [[{}, {tailUncertain: true}, /Consultar mesma continuação/], [{batchUncertain: true}, {}, /mesmo pedido/], [{uncertain: true}, {}, /mesmo pedido/], [{stopUncertain: true}, {}, /mesmo pedido/], [{assemblyUncertain: true}, {}, /Reler montagem/]]) {
    assert.match(blockedActionReason(button('generate'), state, story), phrase);
  }
  assert.match(blockedActionReason(button('generate'), {config: {}}, {}, {submitted: true}), /já foi enviado/);
  assert.match(blockedActionReason(button('generate'), {config: {}}, {}, {promptStale: true}), /intenção do bloco mudou/);
});
test('disabled card actions and navigation retain specific explanations', () => {
  assert.match(blockedActionReason(button('back'), {}, {}), /primeira tela/);
  assert.match(blockedActionReason(button('favorite', ['favorite-toggle']), {}, {}, {favoriteBusy: true}), /favoritos/);
  const move = button(''); move.dataset.blockReason = 'Já está no fim da lista.';
  assert.equal(blockedActionReason(move, {config: {}}, {}), move.dataset.blockReason);
});
function fixture() {
  const document = new EventTarget(), action = button('generate'), panel = {hidden: true}, text = {textContent: ''}, close = new EventTarget();
  document.getElementById = id => ({'blocked-action-feedback': panel, 'blocked-action-text': text, 'blocked-action-close': close})[id];
  document.querySelectorAll = selector => selector === 'button:disabled' ? action.disabled ? [action] : [] : [action];
  const feedback = createBlockedActionFeedback(document, () => 'Consulte o mesmo pedido.');
  function click(target = {closest() { return null; }}, overrides = {}) {
    const event = new Event('click', {cancelable: true});
    Object.defineProperties(event, {clientX: {value: overrides.x ?? 50}, clientY: {value: overrides.y ?? 30}, detail: {value: 1}, target: {value: target}});
    document.dispatchEvent(event); return event;
  }
  return {document, action, panel, text, close, feedback, click};
}
test('touch location over a native disabled button shows feedback and stops ancestor actions', () => {
  const f = fixture(); let businessCalls = 0;
  f.document.addEventListener('click', () => businessCalls++);
  const event = f.click(); assert.equal(event.defaultPrevented, true); assert.equal(businessCalls, 0);
  assert.equal(f.action.disabled, true); assert.equal(f.panel.hidden, false); assert.equal(f.text.textContent, 'Consulte o mesmo pedido.');
  f.close.dispatchEvent(new Event('click')); assert.equal(f.panel.hidden, true);
  f.click(); const escape = new Event('keydown'); Object.defineProperty(escape, 'key', {value: 'Escape'}); f.document.dispatchEvent(escape); assert.equal(f.panel.hidden, true);
});
test('a blocked icon over a full-card button cannot open the card underneath', () => {
  const f = fixture(); let opened = 0; f.document.addEventListener('click', () => opened++);
  const card = button('card-open'); card.disabled = false; card.matches = selector => selector === '.clip-card,.card-open';
  const event = f.click(card); assert.equal(event.defaultPrevented, true); assert.equal(opened, 0); assert.equal(f.panel.hidden, false);
});
test('a disabled action behind the sticky header cannot swallow its enabled gear tap', () => {
  const f = fixture(), gear = button('settings-open'); gear.disabled = false; gear.matches = () => false;
  let calls = 0; f.document.addEventListener('click', () => calls++);
  assert.equal(f.click(gear).defaultPrevented, false); assert.equal(calls, 1); assert.equal(f.panel.hidden, true);
});
test('enabled, hidden and inert actions are never intercepted, nor controls on top of feedback', () => {
  for (const scenario of ['enabled', 'hidden', 'feedback', 'outside']) {
    const f = fixture(); let calls = 0; f.document.addEventListener('click', () => calls++);
    if (scenario === 'enabled') f.action.disabled = false;
    if (scenario === 'hidden') f.action.closest = selector => selector === '[hidden],[inert]' ? {} : null;
    const target = scenario === 'feedback' ? {closest: selector => selector === '#blocked-action-feedback' ? {} : null} : undefined;
    const event = f.click(target, scenario === 'outside' ? {x: 200} : {});
    assert.equal(event.defaultPrevented, false, scenario); assert.equal(calls, 1); assert.equal(f.panel.hidden, true);
  }
});
test('disabled titles and accessible descriptions are refreshed and restored on enable', () => {
  const f = fixture(); f.feedback.sync(); f.feedback.sync();
  assert.equal(f.action.title, 'Consulte o mesmo pedido.'); assert.equal(f.action.attrs['aria-description'], f.action.title);
  f.action.disabled = false; f.feedback.sync(); assert.equal(f.action.title, 'Original label'); assert.equal(f.action.attrs['aria-description'], undefined);
  assert.match(css, /button:disabled\s*\{\s*pointer-events: none/);
});
test('Tail follows the main actions; secondary actions live inside Other options', () => {
  const panel = html.slice(html.indexOf('<section id="panel-story"'), html.indexOf('<section id="panel-context"'));
  assert.ok(panel.indexOf('id="tail-controls"') > panel.indexOf('id="story-next"'));
  const options = panel.slice(panel.indexOf('<summary>Outras opções</summary>'));
  for (const id of ['story-delete', 'story-idea-copy', 'story-reference-copy']) assert.ok(options.includes(`id="${id}"`));
  assert.doesNotMatch(source, /Roteiro salvo no PC\.|'Salvo no PC'/);
});
