import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {captureView, createSwipePresentation, disclosureState, restoreDisclosures, selectionState, restoreSelections, mediaState, restoreMediaState} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function fixture() {
  const document = new EventTarget(), preference = new EventTarget(), animations = [], created = [];
  preference.matches = false; document.hidden = false;
  class Node {
    constructor() { this.style = {}; this.attrs = {}; this.children = []; this.removed = false; this.classes = new Set(); this.classList = {add: name => this.classes.add(name)}; created.push(this); }
    setAttribute(key, value) { this.attrs[key] = value; }
    append(...children) { this.children.push(...children); }
    attachShadow() { this.shadowRoot = {adoptedStyleSheets: [], children: [], append(...children) { this.children.push(...children); }}; return this.shadowRoot; }
    cloneNode() { return new Node(); }
    querySelectorAll() { return []; }
    getBoundingClientRect() { return {top: -120, left: 0, width: 393}; }
    remove() { this.removed = true; }
    animate(frames, options) { let resolve, reject; const animation = {frames, options, finished: new Promise((yes, no) => { resolve = yes; reject = no; }), finish: () => resolve(), cancel: () => reject(new Error('cancelled'))}; animations.push(animation); return animation; }
  }
  document.createElement = () => new Node(); document.body = new Node();
  const main = new Node(), topbar = new Node(); document.querySelector = selector => selector === 'main' ? main : topbar;
  document.querySelectorAll = () => []; document.styleSheets = [{cssRules: [{cssText: 'button { color: red; }'}]}];
  class Sheet { replaceSync(value) { this.text = value; } }
  const view = new EventTarget(); Object.assign(view, {innerWidth: 393, CSSStyleSheet: Sheet, matchMedia: () => preference}); document.defaultView = view;
  return {document, preference, created, animations, main, topbar};
}
test('frozen view isolates IDs and styling from application queries and leaves native media untouched', () => {
  const f = fixture(), copy = captureView(f.document);
  assert.equal(copy.inert, true); assert.equal(copy.attrs['aria-hidden'], 'true'); assert.equal(copy.shadowRoot.children.length, 2);
  assert.notEqual(copy.shadowRoot.children[0], f.topbar); assert.notEqual(copy.shadowRoot.children[1], f.main);
  assert.equal(copy.shadowRoot.children[1].style.top, '-120px'); assert.match(copy.shadowRoot.adoptedStyleSheets[0].text, /animation:none!important/);
  const implementation = source.slice(source.indexOf('export function captureView('), source.indexOf('export function createSwipePresentation('));
  assert.doesNotMatch(implementation, /fetch\(|client\.|stories\.|\.play\(|innerHTML/);
  assert.match(implementation, /drawImage\(media/); assert.match(implementation, /replica.replaceWith\(canvas\)/);
});
test('freezing a view never assigns a selected filename to a cloned file input', () => {
  const f = fixture(), originalClone = f.main.cloneNode;
  const cloned = {type: 'file', disabled: false, set value(value) { throw new Error(`Forbidden filename assignment: ${value}`); }};
  f.main.querySelectorAll = selector => selector === 'input,textarea,select' ? [{type: 'file', value: 'C:\\fakepath\\phone.png'}] : [];
  f.main.cloneNode = () => { const copy = originalClone(); copy.querySelectorAll = selector => selector === 'input,textarea,select' ? [cloned] : []; return copy; };
  assert.ok(captureView(f.document)); assert.equal(cloned.disabled, true);
});
test('drag moves only the inert foreground and exposes the frozen previous view', async () => {
  const f = fixture(), presentation = createSwipePresentation(f.document), previous = {screen: 'library', draftKey: 'new'};
  presentation.remember(previous); presentation.begin(previous); const layer = f.document.body.children.at(-1), [backing, front] = layer.children;
  assert.equal(layer.inert, true); assert.equal(backing.className, 'view-snapshot swipe-backing'); presentation.move(87);
  assert.equal(front.style.transform, 'translateX(87px)'); assert.equal(f.main.style.transform, undefined); assert.equal(f.topbar.style.transform, undefined);
  presentation.cancel(); assert.equal(f.animations.at(-1).frames.at(-1).transform, 'translateX(0px)'); f.animations.at(-1).finish(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  assert.equal(layer.removed, true); presentation.destroy();
});
test('accepted Back paints its destination before the frozen foreground finishes sliding', async () => {
  const f = fixture(), presentation = createSwipePresentation(f.document), previous = {screen: 'story', storyDoc: {id: 'owned'}, draftKey: 'new'};
  presentation.remember(previous); presentation.begin(previous); const layer = f.document.body.children.at(-1);
  presentation.move(130); presentation.commit(); assert.equal(presentation.committing, true); presentation.painted();
  assert.equal(layer.removed, false); assert.equal(f.animations.at(-1).frames.at(-1).transform, 'translateX(393px)');
  f.animations.at(-1).finish(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); assert.equal(layer.removed, true); presentation.destroy();
});
test('reduced motion, hidden tabs and resizing cancel presentation independently of business state', () => {
  const f = fixture(), presentation = createSwipePresentation(f.document), previous = {screen: 'library'};
  presentation.remember(previous); f.preference.matches = true; presentation.begin(previous); assert.equal(f.document.body.children.length, 0);
  f.preference.matches = false; presentation.begin(previous); const layer = f.document.body.children.at(-1);
  f.document.hidden = true; f.document.dispatchEvent(new Event('visibilitychange')); assert.equal(layer.removed, true); presentation.destroy();
});
test('returning restores expanded sections even when cards have been recreated', () => {
  let nodes = [{id: 'tail-controls', open: true, closest: () => null}, {id: '', open: true, closest: () => ({dataset: {blockId: 'owned-block'}})}];
  const document = {querySelector: () => ({querySelectorAll: () => nodes})}, saved = disclosureState(document, 'story');
  nodes = [{...nodes[0], open: false}, {...nodes[1], open: false}]; restoreDisclosures(document, 'story', saved);
  assert.equal(nodes[0].open, true); assert.equal(nodes[1].open, true);
});
test('text selection survives Back without reopening the keyboard or changing the draft', () => {
  const node = {id: 'idea', value: 'Keep this draft exactly', selectionStart: 3, selectionEnd: 8, selectionDirection: 'forward', setSelectionRange(start, end, direction) { this.selectionStart = start; this.selectionEnd = end; this.selectionDirection = direction; }, focus() { throw new Error('Back must not focus editable controls'); }};
  const panel = {querySelectorAll: () => [node], contains: target => target === node}, document = {querySelector: () => panel, getElementById: () => node};
  const saved = selectionState(document, 'context'); node.selectionStart = node.selectionEnd = 0;
  restoreSelections(document, 'context', saved); assert.equal(node.selectionStart, 3); assert.equal(node.selectionEnd, 8); assert.equal(node.value, 'Keep this draft exactly');
});
test('paused native video returns to its saved position without autoplay', () => {
  const video = {id: 'player', src: 'http://local/runs/owned/video', currentTime: 4.25, readyState: 1, play() { throw new Error('No autoplay on Back'); }};
  const panel = {querySelectorAll: () => [video], contains: node => node === video}, document = {querySelector: () => panel, getElementById: () => video};
  const saved = mediaState(document, 'review'); video.currentTime = 0; restoreMediaState(document, 'review', saved); assert.equal(video.currentTime, 4.25);
  video.src = 'http://local/runs/other/video'; video.currentTime = 0; restoreMediaState(document, 'review', saved); assert.equal(video.currentTime, 0);
});
test('late media metadata cannot seek another navigation or another video', () => {
  const video = new EventTarget(); Object.assign(video, {id: 'player', src: 'http://local/runs/owned/video', currentTime: 0, readyState: 0});
  const panel = {contains: node => node === video}, document = {querySelector: () => panel, getElementById: () => video}; let current = true;
  restoreMediaState(document, 'review', [{id: 'player', src: video.src, time: 5}], () => current); current = false; video.dispatchEvent(new Event('loadedmetadata')); assert.equal(video.currentTime, 0);
});
