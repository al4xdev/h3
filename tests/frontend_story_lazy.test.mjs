import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {createLazyStoryCards, createStoryElastic, createScreenTransitions, storyBlockState} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function fixture({observer = true} = {}) {
  const document = new EventTarget(), view = new EventTarget(), observed = new Set(), preference = new EventTarget();
  preference.matches = false;
  Object.assign(view, {innerHeight: 700, scrollY: 0, Event, matchMedia: () => preference});
  if (observer) view.IntersectionObserver = class {
    constructor(callback) { this.callback = callback; view.observer = this; }
    observe(node) { observed.add(node); }
    disconnect() { observed.clear(); }
  };
  class Element extends EventTarget {
    constructor(tag) { super(); this.tagName = tag; this.children = []; this.dataset = {}; this.className = ''; this.textContent = ''; this.parentNode = null; this.attributes = new Map(); const props = new Map(); this.style = {setProperty: (key, value) => props.set(key, value), getPropertyValue: key => props.get(key) || '', removeProperty: key => props.delete(key)}; }
    get childNodes() { return this.children; }
    get isConnected() { return this === list || Boolean(this.parentNode?.isConnected); }
    append(...nodes) { for (const node of nodes) { node.remove(); this.children.push(node); node.parentNode = this; } }
    insertBefore(node, before) { node.remove(); const index = before ? this.children.indexOf(before) : this.children.length; this.children.splice(index, 0, node); node.parentNode = this; }
    replaceChildren(...nodes) { for (const child of [...this.children]) child.remove(); this.append(...nodes); }
    remove() { if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    querySelectorAll(tag) { return this.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...child.querySelectorAll(tag)]); }
    querySelector(tag) { return this.querySelectorAll(tag)[0] || null; }
    setAttribute(key, value) { this.attributes.set(key, value); }
    removeAttribute(key) { this.attributes.delete(key); }
    getBoundingClientRect() { const top = this.parentNode === list ? list.children.indexOf(this) * 400 - view.scrollY : this.parentNode?.getBoundingClientRect().top || 0; return {top, bottom: top + 360}; }
    focus() { document.activeElement = this; }
    closest() { return null; }
  }
  const list = new Element('ol');
  Object.assign(document, {defaultView: view, hidden: false, activeElement: null, documentElement: {scrollHeight: 80000}, createElement: tag => new Element(tag), getElementById: () => list});
  const builds = [], items = Array.from({length: 200}, (_, index) => ({id: String(index), title: `Block ${index}`, action: `Action ${index}`, signature: 'first', build() { builds.push(index); const node = new Element('li'); node.className = 'story-block'; const input = new Element('textarea'), history = new Element('details'); history.append(new Element('summary')); node.append(input, history, ...Array.from({length: 8}, () => new Element('button'))); return node; }}));
  return {document, view, list, preference, builds, items, observed, Element};
}

test('large story materializes only nearby controls; seen nodes survive Back, scrolling and reconciliation', () => {
  const f = fixture(), cards = createLazyStoryCards(f.document, f.list);
  cards.reconcile('story', f.items); assert.equal(f.builds.length, 0);
  cards.setActive(true); assert.deepEqual(f.builds, [0, 1, 2]);
  assert.equal(f.list.querySelectorAll('textarea').length, 3);
  assert.equal(f.list.querySelectorAll('button').length, 221);
  const first = f.list.children[0], field = first.querySelector('textarea'); field.value = 'Unsaved text';
  const details = first.querySelector('details'); details.open = true;
  f.view.scrollY = 20000; f.view.observer.callback([{target: f.list.children[50], isIntersecting: true}]);
  const distant = f.list.children[50]; assert.equal(distant.dataset.lazyState, 'ready'); assert.equal(f.builds.length, 4);
  cards.setActive(false); cards.reconcile('story', f.items); cards.setActive(true);
  assert.equal(f.list.children[0], first); assert.equal(first.querySelector('textarea'), field); assert.equal(field.value, 'Unsaved text'); assert.equal(details.open, true); assert.equal(f.view.scrollY, 20000);
  assert.equal(f.list.children[50], distant);
  const secondStory = [{...f.items[0], id: 'other'}]; cards.reconcile('other-story', secondStory); cards.reconcile('story', f.items);
  assert.equal(f.list.children[0], first); assert.equal(field.value, 'Unsaved text'); cards.destroy(); assert.equal(f.observed.size, 0);
});

test('hidden state and reduced motion preserve progressive loading, with a scroll fallback', () => {
  const f = fixture({observer: false}), cards = createLazyStoryCards(f.document, f.list); f.preference.matches = true;
  cards.reconcile('story', f.items); cards.setActive(true); assert.equal(f.builds.length, 3);
  f.document.hidden = true; f.view.scrollY = 20000; f.view.dispatchEvent(new Event('scroll')); assert.equal(f.builds.length, 3);
  f.document.hidden = false; f.document.dispatchEvent(new Event('visibilitychange')); assert.deepEqual(f.builds.slice(3), [49, 50, 51, 52]);
  cards.destroy(); f.view.scrollY = 40000; f.view.dispatchEvent(new Event('scroll')); assert.equal(f.builds.length, 7);
});

test('focused dirty card waits for focusout; rebuilding preserves expanded histories', async () => {
  const f = fixture(), cards = createLazyStoryCards(f.document, f.list); cards.reconcile('story', f.items); cards.setActive(true);
  const node = f.list.children[0], field = node.querySelector('textarea'); field.focus(); node.querySelector('details').open = true;
  const next = f.items.map(item => item.id === '0' ? {...item, signature: 'changed'} : item);
  cards.reconcile('story', next); assert.equal(node.querySelector('textarea'), field); assert.equal(f.builds.length, 3);
  f.document.activeElement = null; node.dispatchEvent(new Event('focusout')); await Promise.resolve();
  assert.equal(f.builds.length, 4); assert.equal(node.querySelector('details').open, true);
  cards.destroy();
});

test('real block histories build version rows only on opening and once per cached card', () => {
  const f = fixture(), block = {id: 'block', action: 'Dance', prompt: 'dance', duration_seconds: 8}, attempts = Array.from({length: 80}, (_, index) => ({block_id: block.id, intent_id: `intent-${index}`, run_id: `run-${index}`, run: {state: 'accepted', output: {path: 'chunk.mp4'}}}));
  const story = {doc: {id: 'story', blocks: [block], attempts}}, opened = [];
  const deps = {story, element: (tag, classes, text) => { const node = new f.Element(tag); node.className = classes; node.textContent = text; return node; }, storyBlockState, alignedFrames: () => 192, batchBlocked: () => false, editFence: () => false, edit: {lists: new Map()}, openStoryAttempt: attempt => opened.push(attempt), STATE_LABELS: {accepted: 'Accepted'}};
  const text = source.slice(source.indexOf('  function renderStoryBlock('), source.indexOf('  function renderStory()'));
  const render = new Function(...Object.keys(deps), `${text}; return renderStoryBlock;`)(...Object.values(deps));
  const node = render(block, 0, [block]), history = node.querySelector('details');
  assert.equal(history.querySelectorAll('button').length, 0); history.open = true; history.dispatchEvent(new Event('toggle'));
  assert.equal(history.querySelectorAll('button').length, 160); history.dispatchEvent(new Event('toggle')); assert.equal(history.querySelectorAll('button').length, 160);
  history.querySelector('button').dispatchEvent(new Event('click')); assert.deepEqual(opened, [attempts[0]]);
});

test('elastic presentation stays passive and settles on motion preference, hidden state and navigation', () => {
  const f = fixture(), leaf = new f.Element('h3'); f.list.append(leaf); f.list.querySelectorAll = () => [leaf]; let epoch = 0, enabled = true, cancelled = 0;
  leaf.animate = () => ({cancel() { cancelled++; }, finished: new Promise(() => {})});
  const elastic = createStoryElastic(f.document, {enabled: () => enabled, navigationEpoch: () => epoch});
  const touch = (name, y, x = 10) => { const event = new Event(name, {cancelable: true}); Object.defineProperty(event, 'touches', {value: [{clientX: x, clientY: y}]}); f.list.dispatchEvent(event); assert.equal(event.defaultPrevented, false); };
  touch('touchstart', 100); touch('touchmove', 110); touch('touchmove', 180); assert.ok(parseFloat(leaf.style.getPropertyValue('--story-edge-offset')) <= 24);
  touch('touchend', 180); f.preference.matches = true; f.preference.dispatchEvent(new Event('change')); assert.equal(cancelled, 1);
  touch('touchstart', 100); touch('touchmove', 200); assert.equal(leaf.style.getPropertyValue('--story-edge-offset'), '');
  f.preference.matches = false; touch('touchstart', 100); touch('touchmove', 110); epoch++; touch('touchmove', 180); assert.equal(leaf.style.getPropertyValue('--story-edge-offset'), '');
  enabled = false; touch('touchstart', 100); touch('touchmove', 180); elastic.destroy();
});

test('Back restores long story scroll only after the deferred ViewTransition paints, and stale navigation cannot restore it', async () => {
  const f = fixture(), pending = [], calls = [], state = {screen: 'settings', navigationEpoch: 0, retryEpoch: 0}, story = {}, edit = {};
  f.document.documentElement.dataset = {};
  f.document.getElementById = () => null;
  f.document.startViewTransition = update => { pending.push(update); return {skipTransition() {}, ready: new Promise(() => {}), finished: new Promise(() => {}), updateCallbackDone: new Promise(() => {})}; };
  f.view.scrollY = 300;
  let paintedScreen = 'settings';
  f.view.scrollTo = ({top}) => { f.view.scrollY = Math.min(top, paintedScreen === 'story' ? 25000 : 413); calls.push(['scroll', f.view.scrollY]); };
  const screenTransitions = createScreenTransitions(f.document); screenTransitions.paint('settings', () => {});
  const node = {disabled: false, closest: () => null, matches: () => false, focus: () => calls.push(['focus', paintedScreen])};
  const deps = {state, story, edit, screenTransitions, swipePresentation: {committing: false, painted() {}}, paintScreenNow() { paintedScreen = state.screen; calls.push(['paint', paintedScreen]); }, removedStories: new Set(), removedRuns: new Set(), stopped: false, saveDraft() {}, restoreDraft() {}, draft: () => ({submitted: false}), controls() {}, $: () => node, document: f.document, recordView: () => calls.push(['record', f.view.scrollY]), restoreDisclosures: () => calls.push(['disclosures', paintedScreen]), restoreSelections: () => calls.push(['selection', paintedScreen]), restoreMediaState: () => calls.push(['media', paintedScreen])};
  const paint = source.slice(source.indexOf('  function paintScreen('), source.indexOf('  function paintScreenNow('));
  const restore = source.slice(source.indexOf('  async function restoreView('), source.indexOf('  function back('));
  const restoreView = new Function(...Object.keys(deps), `${paint}\n${restore}; return restoreView;`)(...Object.values(deps));
  const snapshot = {screen: 'story', scroll: 18000, focus: 'story-title', disclosures: [], selections: [], media: []};
  await restoreView(snapshot, []);
  assert.equal(pending.length, 1); assert.equal(paintedScreen, 'settings'); assert.equal(f.view.scrollY, 300); assert.deepEqual(calls, []);
  pending.shift()();
  assert.equal(paintedScreen, 'story'); assert.equal(f.view.scrollY, 18000);
  assert.deepEqual(calls, [['paint', 'story'], ['disclosures', 'story'], ['selection', 'story'], ['media', 'story'], ['focus', 'story'], ['scroll', 18000], ['record', 18000]]);
  screenTransitions.paint('settings', () => { paintedScreen = 'settings'; }); pending.shift()(); calls.length = 0;
  await restoreView(snapshot, []); ++state.navigationEpoch; state.screen = 'library'; pending.shift()();
  assert.equal(paintedScreen, 'settings'); assert.deepEqual(calls, []);
  screenTransitions.destroy();
});
