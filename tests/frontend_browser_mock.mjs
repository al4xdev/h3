// All browser requests are intercepted; no listener or real H3 API is used.
import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {resolve, relative} from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const root = resolve(new URL('..', import.meta.url).pathname);
const artifacts = resolve(root, '.dumps/tests/ui-assembly');
await mkdir(artifacts, {recursive: true});
const assets = Object.fromEntries(await Promise.all(['index.html', 'app.css', 'app.js'].map(async file => [file, await readFile(resolve(root, 'src/h3_backend/web', file))])));
let media = null;
if (process.env.H3_UI_TEST_CLIP) {
  const path = resolve(root, process.env.H3_UI_TEST_CLIP);
  assert.ok(['runs/', '.data/'].some(prefix => relative(root, path).startsWith(prefix)), 'Media must be an explicitly supplied existing local H3 clip');
  media = await readFile(path);
}
let assemblyMedia = null, assemblyFixture = null, assemblyFixtureSHA = null;
if (process.env.H3_UI_TEST_ASSEMBLY) {
  assemblyFixture = resolve(root, process.env.H3_UI_TEST_ASSEMBLY);
  assert.equal(relative(root, assemblyFixture), '.dumps/benchmarks/baseline-three-chunks/benchmark.mp4', 'Only the existing frozen baseline movie is an assembly fixture');
  assemblyMedia = await readFile(assemblyFixture); assemblyFixtureSHA = createHash('sha256').update(assemblyMedia).digest('hex');
}
const malicious = '<img src=x onerror="window.hacked=true"> vestido preto & continuidade';
const config = {default_prompt: 'Dança com vestido preto.', continuation_prompt: 'Pequeno salto. Vestido vermelho. Termina de costas.', reference_image: 'dance_reference.png', duration_seconds: 2.3, workflow_output_profile: 'final_only', filesystem_events: true, reference_library: true, assembly_enabled: false};
const image = await readFile(resolve(root, 'assets/dance_reference.png'));
const references = [{id: 'original', source_root: 'assets', path: 'dance_reference.png', name: 'Original', image_url: '/assets/image?path=dance_reference.png'}, {id: 'manual', source_root: 'inputs', path: 'my_photo.png', name: malicious, image_url: '/inputs/image?path=my_photo.png'}, {id: 'frame', source_root: 'runs', path: '.data/runs/z-root/last_frame.png', name: 'Último frame', image_url: '/runs/z-root/image?name=last_frame.png'}];
const mkRun = (id, state, parent_id = null, prompt = malicious) => ({id, state, parent_id, prompt, seed: 2026101205, duration_seconds: 2.3, created_at: '2026-10-12T20:00:00Z', updated_at: '2026-10-12T20:00:01Z', output: {path: `runs/${id}/chunk.mp4`}, error: null});
let runs = [mkRun('a-child', 'ready_for_review', 'z-root'), mkRun('z-root', 'accepted'), {...mkRun('failed-root', 'failed'), error: 'Falha histórica preservada', output: {}}];
const requests = []; const exceptions = []; const violations = [];
let editor = {system_prompt: 'Preserve ação, roupa, pose e ordem. Responda só com a cena.', model: ''};
let grokMode = 'normal'; let grokGate = null; let releaseGrok;
const detailedScene = 'Ela dá um salto. Durante o movimento, o vestido fica vermelho. Preserve a identidade original. <img onerror="window.hacked=true">';
const chainRoot = '11111111-1111-4111-8111-111111111111', chainMid = '22222222-2222-4222-8222-222222222222', chainEnd = '33333333-3333-4333-8333-333333333333';
let assemblyMode = 'normal', assemblies = [], assemblyGate = null, releaseAssembly;
const mkAssembly = (id, end, state = 'completed') => ({id, end_run_id: end, state, mode: runs.find(run => run.id === end)?.state === 'accepted' ? 'accepted_sequence' : 'preview', created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:01Z', request_sha256: 'a'.repeat(64), output_sha256: state === 'completed' ? 'b'.repeat(64) : null, label: 'Server text is untrusted <img onerror=evil>', input_ids: [chainRoot, chainMid, chainEnd], frames: 168, fps: '24/1', video_url: state === 'completed' ? `/assemblies/${id}/video` : null, output: state === 'completed' ? {path: `.data/assemblies/${id}/video.mp4`} : null, error: null});
let mode = 'normal'; let generated = 0; let releaseWait; let waitGate = null; let releaseDetail; let detailGate = null;
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce', serviceWorkers: 'block'});
const routeRequest = async route => {
  const request = route.request(); const url = new URL(request.url());
  if (url.origin !== 'http://h3.mock.invalid') { violations.push(request.url()); await route.abort(); return; }
  const path = url.pathname; const method = request.method();
  requests.push({method, path: path + url.search, body: path === '/inputs' && method === 'POST' ? {diskUploadFake: true, bytes: request.postDataBuffer()?.length, contentType: request.headers()['content-type']} : request.postDataJSON()});
  const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
  if (path === '/') return route.fulfill({contentType: 'text/html', body: assets['index.html']});
  if (path === '/ui/app.css') return route.fulfill({contentType: 'text/css', body: assets['app.css']});
  if (path === '/ui/app.js') return route.fulfill({contentType: 'text/javascript', body: assets['app.js']});
  if (path === '/assemblies' && method === 'GET') {
    const end = url.searchParams.get('end_run_id');
    const items = assemblies.filter(item => item.end_run_id === end);
    return json({items, total: items.length, limit: 50, offset: 0});
  }
  if (path.startsWith('/assemblies/')) {
    const match = path.match(/^\/assemblies\/([0-9a-f-]{36})(\/video)?$/); assert.ok(match, 'Only canonical own assembly routes allowed');
    const id = match[1];
    if (method === 'POST') {
      const body = request.postDataJSON(); assert.deepEqual(Object.keys(body), ['end_run_id']);
      assert.equal(new URL(request.frame().page().url()).searchParams.get('assembly'), id, 'UUID pointer must be recorded before POST');
      if (assemblyMode === 'busy' || assemblyMode === 'collision') return json({detail: assemblyMode === 'busy' ? 'CPU ocupado' : 'UUID já existente'}, 409);
      const record = mkAssembly(id, body.end_run_id); assemblies.unshift(record);
      if (assemblyGate) await assemblyGate;
      if (assemblyMode === 'lost') return route.abort('connectionfailed');
      return json(record);
    }
    const record = assemblies.find(item => item.id === id);
    if (!record) return json({detail: 'Montagem ainda não publicada'}, 404);
    if (match[2]) return record.state === 'completed' && assemblyMedia ? route.fulfill({status: 200, contentType: 'video/mp4', body: assemblyMedia}) : route.fulfill({status: 404});
    return json(record);
  }
  if (path === '/grok/editor' && method === 'GET') return grokMode === 'editor-error' ? json({detail: 'Configuração local indisponível'}, 409) : json(editor);
  if (path === '/grok/editor' && method === 'PUT') { editor = request.postDataJSON(); return json(editor); }
  if (path === '/grok' && method === 'POST') {
    if (grokGate) await grokGate;
    if (grokMode === 'network') return route.abort('connectionfailed');
    if (grokMode === 'error') return json({detail: 'Modelo ou conexão precisa ser configurado'}, 400);
    if (grokMode === 'oversized') return json({text: 'x'.repeat(12001), model: 'fake'});
    return json({text: detailedScene, model: 'fake'});
  }
  if (path.startsWith('/grok/auth/')) { violations.push('Authentication/model catalog must never start automatically'); return json({detail: 'Forbidden test call'}, 409); }
  if (path === '/inputs' && method === 'GET') return json({items: references, total: references.length, limit: 50, offset: 0});
  if (path === '/inputs' && method === 'POST') {
    assert.equal(url.searchParams.get('name'), 'phone photo.png');
    const item = {id: 'uploaded', source_root: 'inputs', path: 'mock-upload/original.png', name: 'phone photo.png', image_url: '/inputs/image?path=mock-upload%2Foriginal.png'};
    references.push(item); return json(item, 201);
  }
  if (['/assets/image', '/inputs/image'].includes(path) || path.endsWith('/image')) return route.fulfill({contentType: 'image/png', body: image});
  if (path === '/events') { violations.push('Native SSE unexpectedly reached network'); return route.abort(); }
  if (path === '/favicon.ico') return route.fulfill({status: 204});
  if (path === '/app/config') return mode === 'config-error' ? json({detail: 'Configuração temporariamente indisponível'}, 503) : json(config);
  if (path === '/runs') {
    if (mode === 'list-error') return json({detail: 'Leitura indisponível <b>não é HTML</b>'}, 503);
    const items = mode === 'empty' ? [] : runs.map(run => ({...run, video_url: ['ready_for_review', 'accepted', 'rejected'].includes(run.state) && run.output.path ? `/runs/${run.id}/video` : null}));
    return json({items, total: items.length, limit: 50, offset: 0});
  }
  if (method === 'POST' && (path === '/runs/i2v' || path.endsWith('/v2v'))) {
    if (mode === 'ambiguous') { await route.abort('connectionfailed'); return; }
    if (mode === 'conflict') return json({detail: 'Slot ocupado'}, 409);
    const body = request.postDataJSON();
    const id = `generated-${++generated}`;
    const parent = path.endsWith('/v2v') ? path.split('/')[2] : null;
    const run = {...mkRun(id, 'queued', parent, body.prompt), seed: body.seed, output: {}};
    runs.unshift(run); return json(run, 202);
  }
  const id = path.split('/')[2]; const run = runs.find(item => item.id === id);
  if (!run) return json({detail: 'Run not found'}, 404);
  if (path.endsWith('/video')) {
    if (!media) return route.fulfill({status: 204});
    return route.fulfill({status: 200, contentType: 'video/mp4', body: media});
  }
  if (method === 'POST' && /\/(accept|reject)$/.test(path)) {
    assert.equal(run.state, 'ready_for_review');
    run.state = path.endsWith('/accept') ? 'accepted' : 'rejected'; return json(run);
  }
  if (path.endsWith('/sequence')) {
    const chain = []; let current = run;
    while (current) { chain.unshift(current); current = runs.find(item => item.id === current.parent_id); }
    return json({schema_version: 1, root_id: chain[0].id, end_run_id: run.id, blocks: chain.map((item, index) => ({index, id: item.id, parent_id: item.parent_id, state: item.state, accepted: item.state === 'accepted', duration_seconds: 2.333333, duration_source: 'verified_video', video_url: item.output.path && ['ready_for_review', 'accepted', 'rejected'].includes(item.state) ? `/runs/${item.id}/video` : null}))});
  }
  if (path === '/runs/z-root' && detailGate) await detailGate;
  if (url.searchParams.get('wait') === 'true') { if (waitGate) await waitGate; run.state = 'ready_for_review'; run.output = {path: `runs/${id}/chunk.mp4`}; }
  return json(run);
};
await context.route('**/*', routeRequest);
const mockStartup = () => {
  window.mockEvents = []; window.startupOrder = []; window.uuidDraws = 0;
  const random = crypto.getRandomValues.bind(crypto);
  Object.defineProperty(crypto, 'randomUUID', {value: undefined, configurable: true});
  crypto.getRandomValues = bytes => { window.uuidDraws++; return random(bytes); };
  const fetch = window.fetch.bind(window);
  window.fetch = (...args) => { window.startupOrder.push(String(args[0])); return fetch(...args); };
  window.EventSource = class extends EventTarget {
    constructor(path) { super(); this.url = path; this.closed = false; window.mockEvents.push(this); window.startupOrder.push('SSE registered'); queueMicrotask(() => { window.startupOrder.push('SSE open'); this.emit('open'); }); }
    close() { this.closed = true; }
    emit(type, data) { this.dispatchEvent(type === 'open' ? new Event(type) : new MessageEvent(type, {data: JSON.stringify(data)})); }
  };
};
await context.addInitScript(mockStartup);
const page = await context.newPage(); page.on('pageerror', error => exceptions.push(error.message));
const ready = async () => { await page.goto('http://h3.mock.invalid/'); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); };
const posts = () => requests.filter(item => item.method === 'POST');
const capture = async options => { await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); }); await page.screenshot(options); };
try {
  await ready();
  assert.equal(posts().length, 0, 'initial reads cannot generate');
  assert.ok(await page.evaluate(() => startupOrder.indexOf('SSE open') < startupOrder.indexOf('/inputs?limit=50&offset=0')), 'Subscribe before catalog snapshot');
  assert.deepEqual(requests.filter(item => item.path.startsWith('/runs') && !item.path.endsWith('/video')).map(item => [item.method, item.path]), [['GET', '/runs?limit=50&offset=0'], ['GET', '/runs/a-child'], ['GET', '/runs/a-child/sequence']]);
  assert.equal(await page.locator('#player').getAttribute('autoplay'), null);
  assert.equal(await page.locator('#player').evaluate(node => getComputedStyle(node).objectFit), 'contain');
  assert.equal(await page.locator('#player').evaluate(node => node.paused), true);
  assert.deepEqual(await page.locator('.shot-id').allTextContents(), ['z-root', 'a-child']);
  await page.locator('.metadata summary').click();
  assert.equal(await page.locator('#run-prompt').textContent(), malicious);
  assert.equal(await page.locator('#run-prompt img').count(), 0);
  assert.equal(await page.evaluate(() => Boolean(window.hacked)), false);
  if (media) {
    await page.waitForFunction(() => document.getElementById('player').videoWidth > 0);
    assert.deepEqual(await page.locator('#player').evaluate(node => [node.videoWidth, node.videoHeight]), [480, 864]);
    // Deliberate test playback of the supplied prerecorded clip, never autoplay.
    await page.locator('#player').evaluate(async node => { await node.play(); });
    await page.waitForFunction(() => document.getElementById('player').currentTime > 0);
    await page.locator('#player').evaluate(node => { node.pause(); });
  }
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
  assert.equal(await page.locator('.skip').evaluate(node => getComputedStyle(node).top), '-100px');
  await capture({path: resolve(artifacts, 'desktop-1440.png'), fullPage: true});
  for (const width of [390, 320]) {
    await page.setViewportSize({width, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px horizontal overflow`);
    await capture({path: resolve(artifacts, `mobile-${width}.png`), fullPage: true});
  }
  await page.setViewportSize({width: 1440, height: 1000});
  detailGate = new Promise(resolve => { releaseDetail = resolve; });
  await page.locator('.clip-card').filter({hasText: 'z-root'}).click();
  await page.locator('.clip-card').filter({hasText: 'a-child'}).click();
  await page.waitForFunction(() => document.getElementById('metadata').textContent.includes('a-child'));
  releaseDetail(); detailGate = null;
  await page.locator('#accept').waitFor({state: 'visible'});
  assert.equal(await page.locator('#run-state').textContent(), 'Pronto para revisão', 'Late old selection cannot overwrite current child');
  // Keyboard activation of the gallery is read-only and failed evidence stays failed.
  await page.locator('.clip-card').filter({hasText: 'failed-r'}).focus(); await page.keyboard.press('Enter');
  await page.locator('#run-state').filter({hasText: 'Falhou'}).waitFor();
  assert.equal(await page.locator('#player').isHidden(), true);
  assert.equal(await page.locator('#accept').isDisabled(), true);
  assert.equal(await page.locator('#continue-mode').isDisabled(), true);
  assert.equal(posts().length, 0);
  await capture({path: resolve(artifacts, 'failed-evidence.png'), fullPage: true});
  await page.locator('.clip-card').filter({hasText: 'a-child'}).click();
  await page.locator('#accept').waitFor({state: 'visible'});
  await page.waitForFunction(() => !document.getElementById('accept').disabled);
  await page.locator('#accept').click();
  await page.locator('#run-state').filter({hasText: 'Aceito'}).waitFor();
  assert.equal(posts().filter(item => item.path === '/runs/a-child/accept').length, 1);
  await page.locator('#continue-mode').click();
  await page.locator('#seed').fill('9007199254740991');
  await page.locator('#prompt').fill('Continuação <script>não executar</script>');
  await page.locator('#create-form').evaluate(form => { form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); });
  await page.locator('#operation').filter({hasText: 'Pronto para revisão'}).waitFor();
  await page.waitForFunction(() => !document.getElementById('accept').disabled);
  const continuations = posts().filter(item => item.path.endsWith('/v2v'));
  assert.deepEqual(continuations, [{method: 'POST', path: '/runs/a-child/v2v', body: {seed: Number.MAX_SAFE_INTEGER, prompt: 'Continuação <script>não executar</script>', duration_seconds: 2.3, reference_tail_seconds: 3, include_audio: true}}]);
  assert.equal(requests.filter(item => item.path === '/runs/generated-1?wait=true').length, 1);
  await page.locator('#reject').click(); await page.locator('#run-state').filter({hasText: 'Rejeitado'}).waitFor();
  assert.equal(posts().filter(item => item.path === '/runs/generated-1/reject').length, 1);
  assert.equal(await page.locator('#continue-mode').isDisabled(), true);
  await page.locator('#new-mode').click();
  await page.locator('#seed').fill('0'); await page.locator('#prompt').fill('Nova cena');
  await page.locator('#create-form').evaluate(form => { form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); });
  await page.locator('#operation').filter({hasText: 'generated-2'}).waitFor();
  await page.waitForFunction(() => !document.getElementById('generate').disabled);
  assert.deepEqual(posts().filter(item => item.path === '/runs/i2v'), [{method: 'POST', path: '/runs/i2v', body: {seed: 0, prompt: 'Nova cena', duration_seconds: 2.3, image: 'dance_reference.png'}}]);
  assert.equal(requests.filter(item => item.path === '/runs/generated-2?wait=true').length, 1);
  mode = 'conflict'; await page.locator('#generate').click();
  await page.locator('#operation').filter({hasText: 'HTTP 409'}).waitFor();
  assert.equal(await page.locator('#generate').isEnabled(), true);
  mode = 'ambiguous'; await page.locator('#generate').click();
  await page.locator('#operation').filter({hasText: 'Resultado incerto'}).waitFor();
  assert.equal(await page.locator('#generate').isDisabled(), true);
  const count = posts().length; await page.locator('#refresh').click();
  await page.locator('#notice').filter({hasText: 'Resultado anterior incerto'}).waitFor();
  assert.equal(posts().length, count); assert.equal(await page.locator('#generate').isDisabled(), true);
  await page.evaluate(() => mockEvents[0].emit('open'));
  await page.locator('#notice').filter({hasText: 'Resultado anterior incerto'}).waitFor();
  assert.equal(await page.locator('#generate').isDisabled(), true, 'SSE cannot clear uncertainty');
  await capture({path: resolve(artifacts, 'admission-uncertain.png'), fullPage: true});
  mode = 'empty'; await ready(); assert.equal(await page.locator('.clip-card').count(), 0);
  await capture({path: resolve(artifacts, 'empty.png'), fullPage: true});
  // False-ready files and all nonplayable states must not attach a media URL.
  for (const state of ['ready_for_review', 'accepted', 'rejected', 'queued', 'running', 'interrupted']) {
    mode = 'normal'; runs = [{...mkRun(`no-file-${state}`, state), output: {}}];
    await ready();
    assert.equal(await page.locator('#player').isHidden(), true, `${state} without publication`);
    assert.equal(await page.locator('#player').getAttribute('src'), null);
    assert.equal(await page.locator('#accept').isEnabled(), state === 'ready_for_review');
    assert.equal(await page.locator('#continue-mode').isEnabled(), state === 'accepted');
  }
  mode = 'config-error'; await page.goto('http://h3.mock.invalid/');
  await page.locator('#notice').filter({hasText: 'API indisponível'}).waitFor();
  assert.equal(await page.locator('#generate').isDisabled(), true);
  mode = 'normal'; await page.locator('#refresh').click();
  await page.locator('#notice').filter({hasText: 'Biblioteca atualizada'}).waitFor();
  assert.equal(await page.locator('#generate').isEnabled(), true);
  // Client-side seed validation also guards synthetic form submits.
  const beforeInvalid = posts().length;
  for (const seed of ['1e3', '-1', '9007199254740992']) {
    await page.locator('#seed').fill(seed);
    await page.locator('#create-form').evaluate(form => form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})));
    await page.locator('#operation').filter({hasText: 'Seed'}).waitFor();
  }
  assert.equal(posts().length, beforeInvalid);
  await page.locator('#reference').selectOption('1');
  assert.equal(await page.locator('#reference-path').textContent(), 'inputs / my_photo.png');
  assert.equal(await page.locator('#reference-library img').count(), 1);
  assert.equal(await page.evaluate(() => Boolean(window.hacked)), false);
  await capture({path: resolve(artifacts, 'reference-gallery.png'), fullPage: true});
  await page.locator('#seed').fill('42'); await page.locator('#prompt').fill('Imagem do PC');
  await page.locator('#generate').click();
  await page.locator('#operation').filter({hasText: 'generated-3'}).waitFor();
  await page.waitForFunction(() => !document.getElementById('generate').disabled);
  assert.deepEqual(posts().filter(item => item.path === '/runs/i2v').at(-1).body, {seed: 42, prompt: 'Imagem do PC', duration_seconds: 2.3, references: [{source_root: 'inputs', path: 'my_photo.png'}]});
  const beforeUpload = posts().length;
  await page.locator('#upload-file').setInputFiles({name: 'phone photo.png', mimeType: 'image/png', buffer: image});
  await page.locator('#upload').evaluate(button => { button.click(); button.click(); });
  await page.locator('#upload-status').filter({hasText: 'Imagem salva no PC'}).waitFor();
  assert.equal(posts().length, beforeUpload + 1, 'Upload alone cannot infer');
  const uploaded = posts().at(-1); assert.equal(uploaded.body.diskUploadFake, true); assert.equal(uploaded.body.bytes, image.length);
  assert.equal(await page.locator('#reference-path').textContent(), 'inputs / mock-upload/original.png');
  await capture({path: resolve(artifacts, 'upload-selected.png'), fullPage: true});
  await page.locator('#reference').selectOption('2');
  waitGate = new Promise(resolve => { releaseWait = resolve; });
  await page.locator('#generate').click();
  await page.locator('#operation').filter({hasText: 'Admitido: generated-4'}).waitFor();
  const busyReads = requests.filter(item => item.path.startsWith('/inputs?limit')).length;
  await page.evaluate(() => { for (let i = 0; i < 8; i++) mockEvents[0].emit('change', {path: '.data/runs/generated-4/manifest.json', invalidation: true}); });
  assert.equal(requests.filter(item => item.path.startsWith('/inputs?limit')).length, busyReads, 'Hints stay dirty during own wait');
  assert.equal(await page.locator('#generate').isDisabled(), true);
  releaseWait(); waitGate = null;
  await page.locator('#operation').filter({hasText: 'Pronto para revisão · generated-4'}).waitFor();
  await page.locator('#notice').filter({hasText: 'Biblioteca atualizada'}).waitFor();
  assert.equal(requests.filter(item => item.path === '/runs/generated-4?wait=true').length, 1);
  assert.deepEqual(posts().filter(item => item.path === '/runs/i2v').at(-1).body.references, [{source_root: 'runs', path: '.data/runs/z-root/last_frame.png'}]);
  const beforeSSE = posts().length; const beforeReads = requests.filter(item => item.path.startsWith('/inputs?limit')).length;
  const playerSrc = await page.locator('#player').getAttribute('src');
  await page.evaluate(() => { const events = mockEvents[0]; events.emit('open'); for (let i = 0; i < 12; i++) events.emit('change', {path: '.data/runs/generated-3/manifest.json', invalidation: true}); events.emit('message', {path: '.data/inputs/new/metadata.json', invalidation: true}); });
  await page.locator('#notice').filter({hasText: 'Biblioteca atualizada'}).waitFor();
  await page.waitForFunction(() => !document.getElementById('library').getAttribute('aria-busy') || document.getElementById('library').getAttribute('aria-busy') === 'false');
  assert.equal(posts().length, beforeSSE, 'Reconnect and hints are read-only');
  assert.ok(requests.filter(item => item.path.startsWith('/inputs?limit')).length - beforeReads <= 2, 'Burst coalesces to bounded reads');
  assert.equal(await page.locator('#player').getAttribute('src'), playerSrc);
  await capture({path: resolve(artifacts, 'sse-refreshed.png'), fullPage: true});
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
  assert.equal(await page.evaluate(() => mockEvents.every(event => event.closed)), true);
  mode = 'list-error'; await page.goto('http://h3.mock.invalid/');
  await page.locator('#notice').filter({hasText: 'API indisponível'}).waitFor();
  assert.equal(await page.locator('#notice b').count(), 0);
  await capture({path: resolve(artifacts, 'api-error.png'), fullPage: true});
  delete config.filesystem_events; delete config.reference_library; mode = 'normal'; await ready();
  assert.equal(await page.evaluate(() => mockEvents.length), 0, 'Legacy config does not open SSE');
  assert.equal(await page.locator('#reference-library').isHidden(), true);
  const nativePosts = () => posts().filter(item => item.path.startsWith('/runs')).length;
  const grokPosts = () => posts().filter(item => item.path === '/grok');
  assert.equal(grokPosts().length, 0, 'Grok must not run on load or SSE');
  await page.locator('.grok-settings summary').click();
  await page.locator('#grok-system').fill('Detalhe a ideia sem inventar ações ou parâmetros.');
  await page.locator('#grok-model').fill('explicit-fake-model');
  const beforeConfigEnter = posts().length;
  await page.locator('#grok-model').press('Enter');
  assert.equal(posts().length, beforeConfigEnter, 'Model ID Enter must not submit the native generation form');
  await page.locator('#grok-save').click();
  await page.locator('#grok-config-status').filter({hasText: 'Configuração salva'}).waitFor();
  assert.deepEqual(requests.filter(item => item.method === 'PUT').at(-1).body, {system_prompt: 'Detalhe a ideia sem inventar ações ou parâmetros.', model: 'explicit-fake-model'});
  const beforeGrokNative = nativePosts();
  await page.locator('#prompt').fill('ela dá um salto e o vestido fica vermelho');
  await page.locator('#grok-detail').evaluate(button => { button.click(); button.click(); });
  await page.locator('#grok-status').filter({hasText: 'Texto detalhado'}).waitFor();
  assert.equal(grokPosts().length, 1); assert.equal(nativePosts(), beforeGrokNative);
  assert.equal(await page.locator('#prompt').inputValue(), detailedScene);
  assert.deepEqual(grokPosts().at(-1).body, {prompt: 'ela dá um salto e o vestido fica vermelho', system_prompt: editor.system_prompt, model: 'explicit-fake-model'});
  assert.equal(await page.evaluate(() => Boolean(window.hacked)), false);
  await capture({path: resolve(artifacts, 'grok-detailed-desktop.png'), fullPage: true});
  grokGate = new Promise(resolve => { releaseGrok = resolve; });
  await page.locator('#prompt').fill('Outra ideia simples'); await page.locator('#grok-model').fill('');
  await page.locator('#grok-detail').click();
  await page.locator('#prompt').fill('Rascunho mais novo, não substituir');
  releaseGrok(); grokGate = null;
  await page.locator('#grok-status').filter({hasText: 'proposta ficou separada'}).waitFor();
  assert.equal(await page.locator('#prompt').inputValue(), 'Rascunho mais novo, não substituir');
  assert.equal(grokPosts().at(-1).body.model, undefined, 'Empty model defers to configured environment');
  assert.equal(nativePosts(), beforeGrokNative);
  await capture({path: resolve(artifacts, 'grok-stale-proposal.png'), fullPage: true});
  await page.locator('#grok-use').click();
  assert.equal(await page.locator('#prompt').inputValue(), detailedScene);
  assert.equal(nativePosts(), beforeGrokNative, 'Use proposal does not generate');
  await page.locator('#seed').fill('42'); await page.locator('#generate').click();
  await page.locator('#operation').filter({hasText: 'generated-5'}).waitFor();
  await page.waitForFunction(() => !document.getElementById('generate').disabled);
  assert.equal(nativePosts(), beforeGrokNative + 1, 'Only explicit Generate can submit native work');
  grokMode = 'error'; const preserved = await page.locator('#prompt').inputValue();
  await page.locator('#grok-detail').click();
  await page.locator('#grok-status').filter({hasText: 'HTTP 400'}).waitFor();
  assert.equal(await page.locator('#prompt').inputValue(), preserved);
  assert.equal(await page.locator('#grok-detail').isEnabled(), true);
  grokMode = 'oversized'; await page.locator('#grok-detail').click();
  await page.locator('#grok-status').filter({hasText: 'sem truncar'}).waitFor();
  assert.equal(await page.locator('#prompt').inputValue(), preserved);
  await capture({path: resolve(artifacts, 'grok-oversized-error.png'), fullPage: true});
  grokMode = 'normal'; await ready();
  grokGate = new Promise(resolve => { releaseGrok = resolve; });
  await page.locator('#prompt').fill('salto vermelho'); await page.locator('#grok-detail').click();
  mode = 'ambiguous'; await page.locator('#generate').click();
  await page.locator('#operation').filter({hasText: 'Resultado incerto'}).waitFor();
  releaseGrok(); grokGate = null;
  await page.locator('#grok-status').filter({hasText: 'proposta ficou separada'}).waitFor();
  assert.equal(await page.locator('#generate').isDisabled(), true, 'Grok completion cannot reset native uncertainty');
  assert.equal(await page.locator('#prompt').inputValue(), 'salto vermelho');
  mode = 'normal'; grokMode = 'network'; await ready();
  await page.locator('#grok-detail').click();
  await page.locator('#grok-status').filter({hasText: 'Resultado incerto'}).waitFor();
  const uncertainGrokCount = grokPosts().length;
  await page.locator('#refresh').click();
  await page.locator('#notice').filter({hasText: 'Biblioteca atualizada'}).waitFor();
  assert.equal(grokPosts().length, uncertainGrokCount); assert.equal(await page.locator('#grok-detail').isDisabled(), true);
  await capture({path: resolve(artifacts, 'grok-uncertain.png'), fullPage: true});
  grokMode = 'editor-error'; await ready();
  assert.equal(await page.locator('#grok-detail').isDisabled(), true); assert.equal(await page.locator('#generate').isEnabled(), true, 'Editor failure must not block native generation');
  grokMode = 'normal';
  runs = Array.from({length: 12}, (_, index) => mkRun(`many-${index}`, index === 0 ? 'ready_for_review' : 'accepted', null, ('# Cena longa\nEla dá um salto e o vestido fica vermelho. Preserve a ordem, a pose e a identidade original.\n').repeat(12)));
  await ready();
  const bounds = [];
  for (const width of [1440, 393, 320]) {
    await page.setViewportSize({width, height: 844});
    const cards = await page.locator('.clip-card').evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect();
      return {height: box.height, shrink: getComputedStyle(node).flexShrink, top: box.top, bottom: box.bottom, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight, overflow: getComputedStyle(node).overflow, children: [...node.children].map(child => { const rect = child.getBoundingClientRect(); return {className: child.className, inside: rect.top >= box.top && rect.bottom <= box.bottom, height: rect.height, top: rect.top, bottom: rect.bottom, scrollHeight: child.scrollHeight, clientHeight: child.clientHeight, overflow: getComputedStyle(child).overflow}; })};
    }));
    assert.equal(cards.length, 12);
    assert.ok(cards.every(card => card.shrink === '0' && card.children.every(child => child.inside)), `${width}px library children must remain inside each card`);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px long-library horizontal overflow`);
    const ancestors = await page.locator('#library').evaluate(node => [node, node.parentElement].map(item => { const box = item.getBoundingClientRect(); return {className: item.className, height: box.height, top: box.top, bottom: box.bottom, scrollHeight: item.scrollHeight, clientHeight: item.clientHeight, overflow: getComputedStyle(item).overflow}; }));
    if (width < 640) assert.ok(ancestors[0].clientHeight <= 430 && ancestors[0].scrollHeight > ancestors[0].clientHeight, 'Phone library remains bounded and scrollable');
    bounds.push({width, cards, ancestors});
    if (media) await page.waitForFunction(() => document.getElementById('player').readyState >= 2);
    await capture({path: resolve(artifacts, `library-many-${width}.png`), fullPage: true});
  }
  await writeFile(resolve(root, '.dumps/tests/reports/assembly_library_bounds.json'), JSON.stringify(bounds, null, 2));
  const phone = await browser.newContext({viewport: {width: 393, height: 852}, deviceScaleFactor: 2, isMobile: true, hasTouch: true, reducedMotion: 'reduce', serviceWorkers: 'block'});
  await phone.route('**/*', routeRequest); await phone.addInitScript(mockStartup);
  const phonePage = await phone.newPage(); phonePage.on('pageerror', error => exceptions.push(error.message));
  await phonePage.goto('http://h3.mock.invalid/');
  await phonePage.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor();
  assert.equal(await phonePage.evaluate(() => navigator.maxTouchPoints > 0 && devicePixelRatio === 2), true);
  await phonePage.locator('#prompt').fill('ela dá um salto e o vestido fica vermelho');
  const phoneNativeBefore = nativePosts(); await phonePage.locator('#grok-detail').tap();
  await phonePage.locator('#grok-status').filter({hasText: 'Texto detalhado'}).waitFor();
  assert.equal(nativePosts(), phoneNativeBefore);
  assert.ok(await phonePage.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  if (media) {
    // Explicit prerecorded fixture playback settles the decoder, never autoplay.
    await phonePage.locator('#player').evaluate(async player => { await player.play(); });
    await phonePage.waitForFunction(() => document.getElementById('player').currentTime > 0.05);
    await phonePage.locator('#player').evaluate(player => player.pause());
  }
  await phonePage.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
  await phonePage.screenshot({path: resolve(artifacts, 'grok-phone-393-touch-2x.png'), fullPage: true});
  await phone.close();
  assert.equal(await page.locator('#assembly-panel').isHidden(), true, 'Feature disabled in legacy config');
  assert.equal(requests.filter(item => item.path.startsWith('/assemblies')).length, 0, 'Disabled config makes no assembly reads or submissions');
  config.assembly_enabled = true; config.filesystem_events = true; config.reference_library = true;
  runs = [mkRun(chainEnd, 'ready_for_review', chainMid), mkRun(chainMid, 'accepted', chainRoot), mkRun(chainRoot, 'accepted')];
  const assemblyPosts = () => posts().filter(item => item.path.startsWith('/assemblies/'));
  const assemblyReady = async (href = 'http://h3.mock.invalid/?other=keep#viewer') => { if (page.url() === href) await page.reload(); else await page.goto(href); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); };
  await page.setViewportSize({width: 1440, height: 1000}); await assemblyReady();
  await page.waitForFunction(() => !document.getElementById('assemble').disabled);
  const nativeBeforeAssembly = nativePosts(), grokBeforeAssembly = grokPosts().length;
  const generationBeforeAssembly = posts().filter(item => item.path === '/runs/i2v' || item.path.endsWith('/v2v')).length;
  const waitsBeforeAssembly = requests.filter(item => item.path.endsWith('?wait=true')).length;
  const originalPlayer = await page.locator('#player').getAttribute('src');
  await page.locator('#assemble').evaluate(button => { button.click(); button.click(); });
  await page.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor();
  const ownID = new URL(page.url()).searchParams.get('assembly');
  assert.match(ownID, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(await page.evaluate(() => uuidDraws), 1, 'HTTP LAN fallback uses one WebCrypto UUID draw');
  assert.equal(new URL(page.url()).hash, '#viewer'); assert.equal(new URL(page.url()).searchParams.get('other'), 'keep');
  assert.equal(assemblyPosts().length, 1); assert.deepEqual(assemblyPosts()[0].body, {end_run_id: chainEnd});
  assert.equal(nativePosts(), nativeBeforeAssembly); assert.equal(grokPosts().length, grokBeforeAssembly);
  assert.equal(await page.locator('#player').getAttribute('src'), originalPlayer);
  assert.equal(await page.locator('#run-state').textContent(), 'Pronto para revisão');
  assert.equal(await page.locator('#assembly-label').textContent(), 'Montagem de prévia — revisão pendente');
  assert.equal(await page.locator('#assembly-download').getAttribute('href'), `/assemblies/${ownID}/video`);
  assert.equal(await page.locator('#assemble').isDisabled(), true, 'A committed own intent is not blindly reassembled');
  if (assemblyMedia) {
    await page.waitForFunction(() => { const video = document.getElementById('assembly-player'); return video.videoWidth === 480 && video.videoHeight === 864 && Math.abs(video.duration - 7) < .01; });
    await page.locator('#assembly-player').evaluate(async video => { await video.play(); });
    await page.waitForFunction(() => document.getElementById('assembly-player').currentTime > .1);
    await page.locator('#assembly-player').evaluate(video => video.pause());
  }
  await capture({path: resolve(artifacts, 'assembly-preview-1440.png'), fullPage: true});
  const assembledSrc = await page.locator('#assembly-player').getAttribute('src');
  await page.evaluate(id => { for (let i = 0; i < 10; i++) mockEvents[0].emit('change', {path: `.data/assemblies/${id}/metadata.json`, invalidation: true}); mockEvents[0].emit('open'); }, ownID);
  await page.locator('#notice').filter({hasText: 'Biblioteca atualizada'}).waitFor();
  assert.equal(assemblyPosts().length, 1); assert.equal(await page.locator('#player').getAttribute('src'), originalPlayer); assert.equal(await page.locator('#assembly-player').getAttribute('src'), assembledSrc);
  await page.reload(); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('assembly'), ownID); assert.equal(assemblyPosts().length, 1);
  assert.ok(requests.some(item => item.method === 'GET' && item.path === `/assemblies/${ownID}`), 'Reload recovers the known ID read-only');
  await assemblyReady(); assemblyGate = new Promise(resolve => { releaseAssembly = resolve; });
  await page.locator('#assemble').click();
  await page.locator('#assembly-status').filter({hasText: 'Montando no PC'}).waitFor();
  const staleID = new URL(page.url()).searchParams.get('assembly');
  await page.locator('.clip-card').filter({hasText: chainRoot.slice(0, 8)}).click();
  await page.waitForFunction(id => document.getElementById('metadata').textContent.includes(id), chainRoot);
  const newerSrc = await page.locator('#player').getAttribute('src'); releaseAssembly(); assemblyGate = null;
  await page.locator('#assembly-status').filter({hasText: 'seleção mudou'}).waitFor();
  assert.equal(await page.locator('#player').getAttribute('src'), newerSrc); assert.equal(await page.locator('#assembly-result').isHidden(), true);
  assert.equal(assemblies.find(item => item.id === staleID).end_run_id, chainEnd);
  await capture({path: resolve(artifacts, 'assembly-stale-selection.png'), fullPage: true});
  assemblyMode = 'busy'; await assemblyReady(); await page.locator('#assemble').click();
  await page.locator('#assembly-status').filter({hasText: 'CPU ocupado'}).waitFor();
  const busyCount = assemblyPosts().length;
  await capture({path: resolve(artifacts, 'assembly-busy.png'), fullPage: true});
  assemblyMode = 'collision'; await page.locator('#assemble').click();
  await page.locator('#assembly-status').filter({hasText: 'UUID já existente'}).waitFor(); assert.equal(assemblyPosts().length, busyCount + 1, 'Collision is not auto retried');
  assemblyMode = 'lost'; await assemblyReady(); await page.locator('#assemble').click();
  await page.locator('#assembly-status').filter({hasText: 'Resultado incerto'}).waitFor();
  const lostID = new URL(page.url()).searchParams.get('assembly'), lostPosts = assemblyPosts().length;
  assert.equal(await page.locator('#assemble').isDisabled(), true);
  await capture({path: resolve(artifacts, 'assembly-uncertain.png'), fullPage: true});
  await page.locator('#assembly-refresh').click();
  await page.locator('#assembly-status').filter({hasText: 'Apenas metadados relidos'}).waitFor();
  assert.equal(assemblyPosts().length, lostPosts); assert.equal(new URL(page.url()).searchParams.get('assembly'), lostID);
  await page.reload(); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor();
  assert.equal(assemblyPosts().length, lostPosts); assert.equal(new URL(page.url()).searchParams.get('assembly'), lostID);
  const missingID = '99999999-9999-4999-8999-999999999999'; assemblyMode = 'normal';
  await assemblyReady(`http://h3.mock.invalid/?other=keep&assembly=${missingID}#viewer`);
  assert.equal(await page.locator('#assemble').isDisabled(), true); assert.equal(assemblyPosts().length, lostPosts);
  await page.locator('#assembly-refresh').click(); await page.locator('#assembly-status').filter({hasText: 'não confirmada'}).waitFor();
  assert.equal(assemblyPosts().length, lostPosts); assert.equal(new URL(page.url()).searchParams.get('assembly'), missingID);
  await capture({path: resolve(artifacts, 'assembly-missing-id.png'), fullPage: true});
  runs[1].state = 'rejected'; await assemblyReady(); assert.equal(await page.locator('#assemble').isDisabled(), true);
  runs[1].state = 'accepted'; runs[0].state = 'failed'; await assemblyReady(); assert.equal(await page.locator('#assemble').isDisabled(), true);
  assert.equal(await page.locator('#player').isHidden(), true); assert.equal(assemblyPosts().length, lostPosts);
  runs[0].state = 'ready_for_review'; await assemblyReady(`http://h3.mock.invalid/?other=keep&assembly=${lostID}#viewer`);
  assert.equal(await page.locator('#assemble').isDisabled(), true);
  const oldPreview = JSON.stringify(assemblies.find(item => item.id === lostID));
  const cpuBeforeReview = assemblyPosts().length;
  await page.locator('#accept').click();
  await page.waitForFunction(() => document.getElementById('run-state').textContent === 'Aceito' && !document.getElementById('assemble').disabled);
  assert.equal(assemblyPosts().length, cpuBeforeReview, 'Accept changes review only, not assembly intent');
  assert.equal(new URL(page.url()).searchParams.get('assembly'), lostID);
  assert.equal(JSON.stringify(assemblies.find(item => item.id === lostID)), oldPreview, 'Previous preview remains immutable');
  assert.equal(await page.locator('#assembly-label').textContent(), 'Montagem de prévia — revisão pendente');
  await page.locator('#assemble').click();
  await page.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor();
  assert.notEqual(new URL(page.url()).searchParams.get('assembly'), lostID, 'Accepted revision has a new UUID only on explicit Montar');
  assert.equal(await page.locator('#assembly-label').textContent(), 'Montagem da sequência aceita');
  assert.equal(runs[0].state, 'accepted'); await capture({path: resolve(artifacts, 'assembly-accepted.png'), fullPage: true});
  runs[0].state = 'ready_for_review'; const safeURL = assemblies[0].video_url; assemblies[0].video_url = 'https://outside.invalid/movie';
  await assemblyReady(); assert.equal(await page.locator('#assembly-result').isHidden(), true);
  await page.locator('#assembly-status').filter({hasText: 'publicação própria'}).waitFor(); assemblies[0].video_url = safeURL;
  const assemblyPhone = await browser.newContext({viewport: {width: 393, height: 852}, deviceScaleFactor: 2, isMobile: true, hasTouch: true, reducedMotion: 'reduce', serviceWorkers: 'block'});
  await assemblyPhone.route('**/*', routeRequest); await assemblyPhone.addInitScript(mockStartup);
  const ap = await assemblyPhone.newPage(); ap.on('pageerror', error => exceptions.push(error.message));
  await ap.goto('http://h3.mock.invalid/?other=keep#viewer'); await ap.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor();
  await ap.locator('#assemble').tap(); await ap.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor();
  assert.equal(await ap.evaluate(() => uuidDraws), 1); assert.ok(await ap.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  if (assemblyMedia) { await ap.locator('#assembly-player').evaluate(async video => { await video.play(); }); await ap.waitForFunction(() => document.getElementById('assembly-player').currentTime > .1); await ap.locator('#assembly-player').evaluate(video => video.pause()); }
  await ap.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
  await ap.screenshot({path: resolve(artifacts, 'assembly-phone-393-touch-2x.png'), fullPage: true});
  await ap.locator('#assembly-panel').screenshot({path: resolve(artifacts, 'assembly-phone-panel-393.png')});
  await ap.setViewportSize({width: 320, height: 852}); assert.ok(await ap.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await ap.screenshot({path: resolve(artifacts, 'assembly-phone-320.png'), fullPage: true});
  await assemblyPhone.close();
  assert.equal(nativePosts(), nativeBeforeAssembly + 1, 'Only the explicit extra review was native; no inference'); assert.equal(grokPosts().length, grokBeforeAssembly);
  assert.equal(posts().filter(item => item.path === '/runs/i2v' || item.path.endsWith('/v2v')).length, generationBeforeAssembly);
  assert.equal(requests.filter(item => item.path.endsWith('?wait=true')).length, waitsBeforeAssembly);
  assert.equal(runs[0].state, 'ready_for_review');
  if (assemblyFixture) assert.equal(createHash('sha256').update(await readFile(assemblyFixture)).digest('hex'), assemblyFixtureSHA, 'Frozen assembly movie unchanged');
  assert.deepEqual(exceptions, []); assert.deepEqual(violations, []);
  assert.equal(await page.evaluate(() => localStorage.length), 0);
  console.log(`PASS mock browser: ${requests.length} intercepted requests, ${posts().length} fake POSTs, zero live API/GPU requests`);
} finally {
  await writeFile(resolve(root, '.dumps/tests/reports/assembly_ui.json'), JSON.stringify({requests, exceptions, violations, media: Boolean(media), fakeInferencePosts: posts().filter(item => item.path === '/runs/i2v' || item.path.endsWith('/v2v')).length, fakeDiskUploads: posts().filter(item => item.body?.diskUploadFake).length, fakeGrokPosts: posts().filter(item => item.path === '/grok').length, fakeEditorSaves: requests.filter(item => item.path === '/grok/editor' && item.method === 'PUT').length, phone: {width: 393, height: 852, touch: true, scale: 2}, protectedProof: '.dumps/tests/reports/assembly_ui_hashcheck.json', assemblyFixtureSHA, fakeAssemblyPosts: posts().filter(item => item.path.startsWith('/assemblies/')).length, uuidFallback: 'WebCrypto.getRandomValues; one16-byte draw/version4/variantRFC4122; HTTP mock, not physical phone', cloudRequests: 0, gpuRequests: 0}, null, 2));
  await browser.close();
}
