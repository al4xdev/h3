import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const worker = await readFile(new URL('../src/h3_backend/web/service-worker.js', import.meta.url), 'utf8');
const source = await readFile(new URL('../src/h3_backend/web/pwa.js', import.meta.url), 'utf8');
const {setupPwa} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

function fixture() {
  const handlers = new Map();
  const stored = new Map([['/ui/offline.html', new Response('Sem conexão com o PC')]]);
  const fetched = [];
  const cache = {
    match: async request => stored.get(typeof request === 'string' ? request : new URL(request.url).pathname)?.clone(),
    put: async (request, response) => stored.set(new URL(request.url).pathname, response),
    addAll: async paths => { assert.deepEqual(Array.from(paths), ['/ui/offline.html', '/ui/app.css']); },
  };
  let offline = false;
  vm.runInNewContext(worker, {
    URL, Response, Set, Promise,
    self: {location: {origin: 'https://h3.test'}, addEventListener: (name, handler) => handlers.set(name, handler)},
    caches: {open: async () => cache, keys: async () => [], delete: async () => true},
    fetch: async request => { fetched.push(request.url); if (offline) throw Error('disconnected'); return new Response('live'); },
  });
  return {stored, fetched, handlers, offline: () => { offline = true; },
    request(path, {method = 'GET', mode = 'cors', origin = 'https://h3.test'} = {}) {
      let result;
      handlers.get('fetch')({request: {url: origin + path, method, mode}, respondWith: promise => { result = promise; }});
      return result;
    }};
}

test('worker leaves mutations, APIs, media, static queries and app code entirely on the network', () => {
  const sw = fixture();
  for (const path of ['/runs?screen=generation', '/grok/editor?screen=context', '/app/config', '/events', '/.data/a.json', '/runs/id/chunk.mp4?screen=review', '/ui/app.js', '/ui/pwa.js', '/ui/app.css?v=1']) {
    assert.equal(sw.request(path, {mode: 'navigate'}), undefined, path);
  }
  assert.equal(sw.request('/', {method: 'POST', mode: 'navigate'}), undefined);
  assert.equal(sw.request('/?screen=generation&pending_run=id', {method: 'POST', mode: 'navigate'}), undefined);
  assert.equal(sw.request('/ui/app.css', {origin: 'https://other.test'}), undefined);
  assert.equal(sw.fetched.length, 0);
});

test('page query navigation falls back offline without caching or dropping pending IDs', async () => {
  const sw = fixture();
  const paths = [
    '/?screen=generation&pending_run=run-id',
    '/index?screen=story&batch=batch-id',
    '/roteiro?screen=assembly&assembly=assembly-id',
  ];
  for (const path of paths) {
    assert.equal(await (await sw.request(path, {mode: 'navigate'})).text(), 'live');
    assert.equal(sw.fetched.at(-1), 'https://h3.test' + path);
    assert.deepEqual([...sw.stored.keys()], ['/ui/offline.html']);
  }
  sw.offline();
  for (const path of paths) {
    const response = await sw.request(path, {mode: 'navigate'});
    assert.equal(response.status, 503);
    assert.equal(await response.text(), 'Sem conexão com o PC');
    assert.equal(sw.fetched.at(-1), 'https://h3.test' + path);
    assert.deepEqual([...sw.stored.keys()], ['/ui/offline.html']);
  }
  const offline = await readFile(new URL('../src/h3_backend/web/offline.html', import.meta.url), 'utf8');
  assert.match(offline, /<a href="">Reconectar ao estúdio<\/a>/);
  for (const path of paths) assert.equal(new URL('', 'https://h3.test' + path).href, 'https://h3.test' + path);
});

test('worker never caches live pages and disconnected navigation shows explicit 503', async () => {
  const sw = fixture();
  assert.equal(await (await sw.request('/', {mode: 'navigate'})).text(), 'live');
  assert.equal(sw.stored.has('/'), false);
  sw.offline();
  const response = await sw.request('/roteiro', {mode: 'navigate'});
  assert.equal(response.status, 503);
  assert.equal(await response.text(), 'Sem conexão com o PC');
});

test('allowlisted static asset is network first with cache fallback', async () => {
  const sw = fixture();
  assert.equal(await (await sw.request('/ui/app.css')).text(), 'live');
  assert.equal(sw.fetched.length, 1);
  sw.offline();
  assert.equal(await (await sw.request('/ui/app.css')).text(), 'live');
  assert.equal(sw.fetched.length, 2);
});

function uiFixture(secure) {
  const view = new EventTarget();
  const button = new EventTarget();
  button.hidden = true;
  const status = {};
  const registrations = [];
  view.isSecureContext = secure;
  view.matchMedia = () => ({matches: false});
  view.navigator = {serviceWorker: {register: async (...args) => registrations.push(args)}};
  const document = {getElementById: id => id === 'pwa-install' ? button : status};
  setupPwa(view, document);
  return {view, button, status, registrations};
}

test('insecure LAN shows HTTPS requirement and registers no worker', () => {
  const ui = uiFixture(false);
  assert.match(ui.status.textContent, /HTTPS/);
  assert.equal(ui.registrations.length, 0);
  assert.equal(ui.button.hidden, true);
});

test('installation requires browser invitation and an explicit click', async () => {
  const ui = uiFixture(true);
  assert.equal(ui.registrations.length, 1);
  assert.deepEqual(ui.registrations[0], ['/service-worker.js', {scope: '/', updateViaCache: 'none'}]);
  let prompts = 0;
  const event = new Event('beforeinstallprompt', {cancelable: true});
  event.prompt = async () => { prompts++; };
  event.userChoice = Promise.resolve({outcome: 'dismissed'});
  ui.view.dispatchEvent(event);
  assert.equal(event.defaultPrevented, true);
  assert.equal(prompts, 0);
  assert.equal(ui.button.hidden, false);
  ui.button.dispatchEvent(new Event('click'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(prompts, 1);
  assert.equal(ui.button.hidden, true);
  assert.match(ui.status.textContent, /cancelada/);
  ui.button.dispatchEvent(new Event('click'));
  assert.equal(prompts, 1);
});
