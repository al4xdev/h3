import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {createLibraryClient, appendLibraryPage} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const id = '11111111-1111-4111-8111-111111111111', other = '22222222-2222-4222-8222-222222222222';
test('explicit favorites use bounded local PUT for either item kind without generation', async () => {
  const calls = [], client = createLibraryClient(async (path, options) => { calls.push([path, options.method, JSON.parse(options.body)]); return {ok: true, json: async () => ({items: []})}; });
  await client.favorite('roteiro', id, true); await client.favorite('freestyle', other, false);
  assert.deepEqual(calls, [[`/favorites/roteiro/${id}`, 'PUT', {favorite: true}], [`/favorites/freestyle/${other}`, 'PUT', {favorite: false}]]);
  await assert.rejects(client.favorite('freestyle', '../private', true));
  await assert.rejects(client.favorite('run', id, true)); assert.equal(calls.length, 2);
});
test('load more deduplicates drifting catalog pages and refresh replaces stale items', () => {
  const result = appendLibraryPage([{id, state: 'running'}], {items: [{id, state: 'accepted'}, {id: other}], total: 2}, true);
  assert.deepEqual(result, [{id, state: 'accepted'}, {id: other}]);
  assert.deepEqual(appendLibraryPage(result, {items: [{id: other}], total: 1}), [{id: other}]);
  assert.throws(() => appendLibraryPage([], {items: [], total: -1}));
});
test('actual load-more handler requires an expanded group and never invokes generation', async () => {
  const line = source.split('\n').find(line => line.includes("$('load-more').addEventListener"));
  let handler, reads = 0;
  const nodes = {'load-more': {addEventListener: (_, fn) => { handler = fn; }}, 'freestyle-group': {open: false}};
  new Function('$', 'state', 'loadLibrary', 'message', line)(id => nodes[id], {items: [], offset: 0, total: 20}, async append => { assert.equal(append, true); reads++; }, () => {});
  handler(); assert.equal(reads, 0); nodes['freestyle-group'].open = true; handler(); await Promise.resolve(); assert.equal(reads, 1);
  assert.equal(source.match(/limit: 12,/g).length, 1);
});
test('groups retain native summary keyboard semantics and reduced motion', async () => {
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
  const css = await readFile(new URL('../src/h3_backend/web/app.css', import.meta.url), 'utf8');
  for (const group of ['favorites', 'stories', 'freestyle']) assert.match(html, new RegExp(`<details id="${group}-group"[^>]*><summary>`));
  assert.match(css, /content-visibility 400ms allow-discrete/);
  assert.match(css, /prefers-reduced-motion:reduce\)\{\.library-chevron/);
});
test('actual loader fetches twelve then appends only the requested next page', async () => {
  const handler = source.slice(source.indexOf('  async function loadLibrary('), source.indexOf('  async function select('));
  const reads = [], state = {items: [], offset: 0, limit: 12};
  const deps = {$: () => ({setAttribute() {}}), client: {get: async path => { reads.push(path); if (path === '/favorites') return {items: []}; return {items: [{id: reads.length === 1 ? id : other}], total: 2}; }}, state, appendLibraryPage, renderLibrary() {}, message() {}, drainChanges() {}};
  const load = new Function(...Object.keys(deps), `let freestyleLoading = false, libraryEpoch = 0, stopped = false, favoriteItems, favoritesReady, dirty = false; ${handler}; return loadLibrary;`)(...Object.values(deps));
  await load(); await load(true);
  assert.deepEqual(reads, ['/library/freestyle?limit=12&offset=0', '/favorites', '/library/freestyle?limit=12&offset=1']);
  assert.equal(state.items.length, 2); assert.equal(state.offset, 2);
});
test('refresh during an in-flight append waits and queues exactly one authoritative reread', async () => {
  const handler = source.slice(source.indexOf('  async function loadLibrary('), source.indexOf('  async function select('));
  const state = {items: [{id, state: 'running'}], offset: 1, limit: 12}, reads = [];
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const deps = {$: () => ({setAttribute() {}}), client: {get: async path => { reads.push(path); if (reads.length === 1) { await pending; return {items: [{id: other}], total: 2}; } if (path === '/favorites') return {items: []}; return {items: [{id, state: 'accepted'}, {id: other}], total: 2}; }}, state, appendLibraryPage, renderLibrary() {}, message() {}};
  const subject = new Function(...Object.keys(deps), `let freestyleLoading = false, libraryEpoch = 0, stopped = false, favoriteItems, favoritesReady, dirty = false, refreshActive = false, refreshes = 0; let reread; function drainChanges() { if (!dirty || refreshActive) return; dirty = false; refreshActive = true; refreshes++; reread = loadLibrary().finally(() => { refreshActive = false; drainChanges(); }); } ${handler}; return {loadLibrary, setRefreshing: value => {refreshActive = value;}, drainChanges, get dirty() {return dirty;}, get reread() {return reread;}, get refreshes() {return refreshes;}};`)(...Object.values(deps));
  const append = subject.loadLibrary(true); subject.setRefreshing(true);
  let finished = false; const eventRead = subject.loadLibrary().then(() => { finished = true; });
  await Promise.resolve(); assert.equal(finished, false); assert.equal(subject.dirty, true); assert.equal(reads.length, 1);
  release(); await append; await eventRead; assert.equal(subject.refreshes, 0);
  subject.setRefreshing(false); subject.drainChanges(); await subject.reread;
  assert.equal(subject.refreshes, 1); assert.equal(subject.dirty, false);
  assert.equal(state.items[0].state, 'accepted');
  assert.deepEqual(reads, ['/library/freestyle?limit=12&offset=1', '/library/freestyle?limit=12&offset=0', '/favorites']);
});
test('authoritative refresh preserves all previously loaded pages in twelve-item slices', async () => {
  const handler = source.slice(source.indexOf('  async function loadLibrary('), source.indexOf('  async function select('));
  const items = Array.from({length: 24}, (_, index) => ({id: `10000000-0000-4000-8000-${String(index).padStart(12, '0')}`}));
  const state = {items, offset: 24, limit: 12}, reads = [];
  const deps = {$: () => ({setAttribute() {}}), client: {get: async path => { reads.push(path); if (path === '/favorites') return {items: []}; const offset = Number(new URL(path, 'http://local').searchParams.get('offset')); return {items: items.slice(offset, offset + 12), total: 24}; }}, state, appendLibraryPage, renderLibrary() {}, message() {}, drainChanges() {}};
  const load = new Function(...Object.keys(deps), `let freestyleLoading = false, libraryEpoch = 0, stopped = false, favoriteItems, favoritesReady, dirty = false; ${handler}; return loadLibrary;`)(...Object.values(deps));
  await load(); assert.equal(state.items.length, 24); assert.equal(state.offset, 24);
  assert.deepEqual(reads, ['/library/freestyle?limit=12&offset=0', '/library/freestyle?limit=12&offset=12', '/favorites']);
});
