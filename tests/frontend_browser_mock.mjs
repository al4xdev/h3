// All browser requests are intercepted; no listener or real H3 API is used.
import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {resolve, relative} from 'node:path';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const root = resolve(new URL('..', import.meta.url).pathname);
const artifacts = resolve(root, '.dumps/tests/ui-paths');
await mkdir(artifacts, {recursive: true});
const assets = Object.fromEntries(await Promise.all(['index.html', 'app.css', 'app.js'].map(async file => [file, await readFile(resolve(root, 'src/h3_backend/web', file))])));
let media = null;
if (process.env.H3_UI_TEST_CLIP) {
  const path = resolve(root, process.env.H3_UI_TEST_CLIP);
  assert.ok(['runs/', '.data/'].some(prefix => relative(root, path).startsWith(prefix)), 'Media must be an explicitly supplied existing local H3 clip');
  media = await readFile(path);
}
const malicious = '<img src=x onerror="window.hacked=true"> vestido preto & continuidade';
const config = {default_prompt: 'Dança com vestido preto.', continuation_prompt: 'Pequeno salto. Vestido vermelho. Termina de costas.', reference_image: 'dance_reference.png', duration_seconds: 2.3, workflow_output_profile: 'final_only', filesystem_events: true, reference_library: true, assembly_enabled: false};
const image = await readFile(resolve(root, 'assets/dance_reference.png'));
const references = [{id: 'original', source_root: 'assets', path: 'dance_reference.png', name: 'Original', image_url: '/assets/image?path=dance_reference.png'}, {id: 'manual', source_root: 'inputs', path: 'my_photo.png', name: malicious, image_url: '/inputs/image?path=my_photo.png'}, {id: 'frame', source_root: 'runs', path: '.data/runs/z-root/last_frame.png', name: 'Último frame', image_url: '/runs/z-root/image?name=last_frame.png'}];
const mkRun = (id, state, parent_id = null, prompt = malicious) => ({id, state, parent_id, prompt, seed: 2026101205, duration_seconds: 2.3, created_at: '2026-10-12T20:00:00Z', updated_at: '2026-10-12T20:00:01Z', output: {path: `runs/${id}/chunk.mp4`}, error: null});
let runs = [mkRun('a-child', 'ready_for_review', 'z-root'), mkRun('z-root', 'accepted'), {...mkRun('failed-root', 'failed'), error: 'Falha histórica preservada', output: {}}];
const requests = []; const exceptions = []; const violations = [];
let mode = 'normal'; let generated = 0; let releaseWait; let waitGate = null; let releaseDetail; let detailGate = null;
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce', serviceWorkers: 'block'});
await context.route('**/*', async route => {
  const request = route.request(); const url = new URL(request.url());
  if (url.origin !== 'http://h3.mock.invalid') { violations.push(request.url()); await route.abort(); return; }
  const path = url.pathname; const method = request.method();
  requests.push({method, path: path + url.search, body: path === '/inputs' && method === 'POST' ? {diskUploadFake: true, bytes: request.postDataBuffer()?.length, contentType: request.headers()['content-type']} : request.postDataJSON()});
  const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
  if (path === '/') return route.fulfill({contentType: 'text/html', body: assets['index.html']});
  if (path === '/ui/app.css') return route.fulfill({contentType: 'text/css', body: assets['app.css']});
  if (path === '/ui/app.js') return route.fulfill({contentType: 'text/javascript', body: assets['app.js']});
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
});
await context.addInitScript(() => {
  window.mockEvents = []; window.startupOrder = [];
  const fetch = window.fetch.bind(window);
  window.fetch = (...args) => { window.startupOrder.push(String(args[0])); return fetch(...args); };
  window.EventSource = class extends EventTarget {
    constructor(path) { super(); this.url = path; this.closed = false; window.mockEvents.push(this); window.startupOrder.push('SSE registered'); queueMicrotask(() => { window.startupOrder.push('SSE open'); this.emit('open'); }); }
    close() { this.closed = true; }
    emit(type, data) { this.dispatchEvent(type === 'open' ? new Event(type) : new MessageEvent(type, {data: JSON.stringify(data)})); }
  };
});
const page = await context.newPage(); page.on('pageerror', error => exceptions.push(error.message));
const ready = async () => { await page.goto('http://h3.mock.invalid/'); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); };
const posts = () => requests.filter(item => item.method === 'POST');
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
  await page.screenshot({path: resolve(artifacts, 'desktop-1440.png'), fullPage: true});
  for (const width of [390, 320]) {
    await page.setViewportSize({width, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px horizontal overflow`);
    await page.screenshot({path: resolve(artifacts, `mobile-${width}.png`), fullPage: true});
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
  await page.screenshot({path: resolve(artifacts, 'failed-evidence.png'), fullPage: true});
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
  await page.screenshot({path: resolve(artifacts, 'admission-uncertain.png'), fullPage: true});
  mode = 'empty'; await ready(); assert.equal(await page.locator('.clip-card').count(), 0);
  await page.screenshot({path: resolve(artifacts, 'empty.png'), fullPage: true});
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
  await page.screenshot({path: resolve(artifacts, 'reference-gallery.png'), fullPage: true});
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
  await page.screenshot({path: resolve(artifacts, 'upload-selected.png'), fullPage: true});
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
  await page.screenshot({path: resolve(artifacts, 'sse-refreshed.png'), fullPage: true});
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
  assert.equal(await page.evaluate(() => mockEvents.every(event => event.closed)), true);
  mode = 'list-error'; await page.goto('http://h3.mock.invalid/');
  await page.locator('#notice').filter({hasText: 'API indisponível'}).waitFor();
  assert.equal(await page.locator('#notice b').count(), 0);
  await page.screenshot({path: resolve(artifacts, 'api-error.png'), fullPage: true});
  delete config.filesystem_events; delete config.reference_library; mode = 'normal'; await ready();
  assert.equal(await page.evaluate(() => mockEvents.length), 0, 'Legacy config does not open SSE');
  assert.equal(await page.locator('#reference-library').isHidden(), true);
  assert.deepEqual(exceptions, []); assert.deepEqual(violations, []);
  assert.equal(await page.evaluate(() => localStorage.length), 0);
  console.log(`PASS mock browser: ${requests.length} intercepted requests, ${posts().length} fake POSTs, zero live API/GPU requests`);
} finally {
  await writeFile(resolve(root, '.dumps/tests/reports/frontend_paths.json'), JSON.stringify({requests, exceptions, violations, media: Boolean(media), fakeInferencePosts: posts().filter(item => item.path === '/runs/i2v' || item.path.endsWith('/v2v')).length, fakeDiskUploads: posts().filter(item => item.body?.diskUploadFake).length}, null, 2));
  await browser.close();
}
