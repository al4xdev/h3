import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {createLoadingScreen} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const settle = () => new Promise(resolve => setImmediate(resolve));

function fixture() {
  const document = new EventTarget(), preference = new EventTarget(), animations = [];
  preference.matches = false;
  class Element extends EventTarget {
    constructor() { super(); this.hidden = false; this.inert = false; this.isConnected = true; this.attrs = {}; this.classes = new Set(); this.classList = {add: value => this.classes.add(value), remove: value => this.classes.delete(value)}; }
    setAttribute(key, value) { this.attrs[key] = value; }
    focus() { document.activeElement = this; }
    closest() { return null; }
    animate(frames, options) {
      let resolve, reject;
      const animation = {frames, options, finished: new Promise((yes, no) => { resolve = yes; reject = no; }), cancelled: false, cancel() { this.cancelled = true; reject(new Error('cancelled')); }, finish: () => resolve()};
      animations.push(animation); return animation;
    }
  }
  const nodes = new Map(['loading-screen', 'loading-content', 'loading-title', 'loading-detail', 'loading-back', 'screen-title', 'main', '.topbar', '.skip'].map(key => [key, new Element()]));
  nodes.get('loading-screen').hidden = true;
  document.getElementById = key => nodes.get(key);
  document.querySelector = key => nodes.get(key);
  document.defaultView = {matchMedia: () => preference};
  const controller = createLoadingScreen(document);
  return {document, preference, animations, nodes, controller};
}

test('generic loading shows immediately and unblocks the real screen before exit motion finishes', async () => {
  const f = fixture(), panel = f.nodes.get('loading-screen');
  const ticket = f.controller.begin('Carregando roteiro…', 'Lendo blocos e histórico.');
  assert.equal(panel.hidden, false); assert.equal(f.nodes.get('main').inert, true);
  assert.equal(f.nodes.get('loading-title').textContent, 'Carregando roteiro…');
  assert.equal(f.nodes.get('loading-back').hidden, true);
  assert.equal(f.animations[0].options.duration, 400);
  f.controller.end(ticket);
  assert.equal(f.controller.key, null); assert.equal(f.nodes.get('main').inert, false);
  assert.equal(panel.inert, true); assert.equal(panel.attrs['aria-busy'], 'false');
  assert.equal(panel.classes.has('loading-leaving'), true);
  assert.equal(f.animations[0].cancelled, true);
  f.animations.at(-1).finish(); await settle(); assert.equal(panel.hidden, true);
  f.controller.destroy();
});

test('new owner supersedes loading and stale completion cannot dismiss a newer screen', async () => {
  const f = fixture(); let cancelled = 0;
  const old = f.controller.begin('Old', 'Read', {key: 'old', onCancel: () => cancelled++});
  const current = f.controller.begin('New', 'Read', {key: 'new'});
  assert.equal(cancelled, 1); f.controller.end(old); assert.equal(f.controller.key, 'new');
  f.controller.end(current); const exit = f.animations.at(-1);
  const next = f.controller.begin('Next', 'Read', {key: 'next'});
  exit.finish(); await settle();
  assert.equal(f.controller.key, 'next'); assert.equal(f.nodes.get('loading-screen').hidden, false);
  f.controller.end(next); f.controller.destroy();
});

test('Voltar and Escape only abandon the read view, preserving original inert and focus', () => {
  const f = fixture(); let cancelled = 0;
  f.nodes.get('.skip').inert = true;
  const origin = f.nodes.get('screen-title'); origin.focus();
  f.controller.begin('Read', 'Metadata', {onCancel: () => cancelled++});
  f.nodes.get('loading-back').dispatchEvent(new Event('click'));
  assert.equal(cancelled, 1); assert.equal(f.nodes.get('.skip').inert, true);
  assert.equal(f.document.activeElement, origin);
  f.controller.begin('Another', 'Metadata', {onCancel: () => cancelled++});
  const escape = new Event('keydown', {cancelable: true}); Object.defineProperty(escape, 'key', {value: 'Escape'});
  f.nodes.get('loading-screen').dispatchEvent(escape);
  assert.equal(escape.defaultPrevented, true); assert.equal(cancelled, 2);
  f.controller.destroy();
});

test('reduced motion, hidden page and failed animation preserve real loading lifecycle', async () => {
  const f = fixture(); let cancelled = 0;
  const ticket = f.controller.begin('Read', 'Metadata', {onCancel: () => cancelled++});
  f.preference.matches = true; f.preference.dispatchEvent(new Event('change'));
  assert.equal(f.animations[0].cancelled, true); assert.equal(f.nodes.get('loading-screen').hidden, false);
  assert.equal(cancelled, 0); f.controller.end(ticket);
  assert.equal(f.nodes.get('loading-screen').hidden, true);
  f.preference.matches = false;
  f.nodes.get('loading-screen').animate = () => { throw new Error('unsupported'); };
  const unsupported = f.controller.begin('Read', 'Metadata'); f.controller.end(unsupported);
  assert.equal(f.nodes.get('main').inert, false); assert.equal(f.nodes.get('loading-screen').hidden, true);
  f.document.hidden = true; f.controller.begin('Hidden', 'Read'); f.controller.destroy(); await settle();
  assert.equal(f.nodes.get('main').inert, false); assert.equal(cancelled, 0);
  assert.equal(f.controller.begin('Disposed', 'Read'), null);
});

function openingFixture() {
  const state = {navigationEpoch: 0, screen: 'library'}, story = {doc: null}, reads = [], navigations = [], messages = [];
  let release, active = null;
  const loadingScreen = {get key() { return active?.key; }, begin(label, detail, options) { active = {...options, label, detail}; return active; }, end(ticket) { if (active === ticket) active = null; }, cancel() { active.onCancel(); active = null; }};
  const handler = source.slice(source.indexOf('  async function openStory('), source.indexOf('  function storyBlocks('));
  const deps = {state, story, loadingScreen, stopped: false, stories: {read: async id => { reads.push(id); return new Promise(resolve => { release = resolve; }); }}, renderStory() {}, storyURL() {}, navigate: screen => { state.screen = screen; state.navigationEpoch++; navigations.push(screen); }, message: (...args) => messages.push(args)};
  const open = new Function(...Object.keys(deps), `${handler}; return openStory;`)(...Object.values(deps));
  return {state, story, loadingScreen, reads, navigations, messages, open, reply: doc => release(doc)};
}

test('actual story opening displays loading before GET finishes, dedupes and keeps one navigation', async () => {
  const f = openingFixture(), read = f.open('own-id');
  assert.equal(f.loadingScreen.key, 'story:own-id'); assert.equal(f.state.screen, 'library');
  assert.equal(await f.open('own-id'), false); assert.equal(f.reads.length, 1);
  f.reply({id: 'own-id'}); assert.equal(await read, true);
  assert.deepEqual(f.navigations, ['story']); assert.equal(f.loadingScreen.key, undefined);
});

test('abandoned story response cannot navigate, replace current document or execute a job', async () => {
  const f = openingFixture(), read = f.open('own-id');
  const original = {id: 'previous'}; f.story.doc = original;
  f.loadingScreen.cancel(); f.reply({id: 'own-id'});
  assert.equal(await read, false); assert.equal(f.story.doc, original);
  assert.deepEqual(f.navigations, []); assert.deepEqual(f.reads, ['own-id']);
});
