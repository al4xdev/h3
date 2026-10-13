// Maintained E2E: every request is intercepted; no API listener, provider or GPU.
import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile, readdir, lstat} from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {resolve, relative} from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
const {chromium} = createRequire(import.meta.url)('playwright');
const root = resolve(new URL('..', import.meta.url).pathname);
const artifacts = resolve(root, '.dumps/tests/ui-progressive');
const motionArtifacts = resolve(root, '.dumps/tests/ui-motion');
await mkdir(artifacts, {recursive: true});
await mkdir(motionArtifacts, {recursive: true});
const motionEvidence = {};
const assets = Object.fromEntries(await Promise.all(['index.html', 'app.css', 'app.js'].map(async file => [file, await readFile(resolve(root, 'src/h3_backend/web', file))])));
const {alignedFrames} = await import(`data:text/javascript;base64,${Buffer.from(assets['app.js']).toString('base64')}`);
// No traversal into .data/grok, OAuth, or private credentials, even for hashes.
async function protectedHashes() {
  const result = {};
  async function visit(path) {
    const info = await lstat(path); if (info.isSymbolicLink()) return;
    if (info.isDirectory()) { for (const entry of await readdir(path)) await visit(resolve(path, entry)); }
    else if (info.isFile()) { const hash = createHash('sha256'); for await (const block of createReadStream(path)) hash.update(block); result[relative(root, path)] = hash.digest('hex'); }
  }
  for (const path of ['assets', 'workflows', 'prompts', 'runs', '.data/runs', '.data/inputs', '.data/assemblies']) await visit(resolve(root, path));
  return result;
}
const beforeHashes = await protectedHashes();
const image = await readFile(resolve(root, 'assets/dance_reference.png'));
let media = null, assemblyMedia = null;
if (process.env.H3_UI_TEST_CLIP) {
  const path = resolve(root, process.env.H3_UI_TEST_CLIP);
  assert.ok(['runs/', '.data/runs/'].some(prefix => relative(root, path).startsWith(prefix)) && path.endsWith('/chunk.mp4'));
  media = await readFile(path);
}
if (process.env.H3_UI_TEST_ASSEMBLY) {
  const path = resolve(root, process.env.H3_UI_TEST_ASSEMBLY);
  assert.equal(relative(root, path), '.dumps/benchmarks/baseline-three-chunks/benchmark.mp4');
  assemblyMedia = await readFile(path);
}
const assemblyHash = assemblyMedia && createHash('sha256').update(assemblyMedia).digest('hex');
const pin = 'grok-4.20-0309-non-reasoning';
const caps = {default_requested_seconds: 2.3, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125};
const rootID = '11111111-1111-4111-8111-111111111111', endID = '22222222-2222-4222-8222-222222222222', failedID = '44444444-4444-4444-8444-444444444444';
const malicious = '<img src=x onerror="window.hacked=true"> vestido preto & continuidade';
const scene = 'Ela dá um salto. O vestido fica vermelho. <img onerror="window.hacked=true">';
let providerScene = scene;
const original = {source_root: 'assets', path: 'dance_reference.png'};
const references = [{...original, name: 'Original', image_url: '/assets/image?path=dance_reference.png'}, {source_root: 'inputs', path: 'own/original.png', name: malicious, image_url: '/inputs/image?path=own%2Foriginal.png'}, {source_root: 'runs', path: `.data/runs/${rootID}/last_frame.png`, name: 'Último frame', image_url: `/runs/${rootID}/image?name=last_frame.png`}];
const config = {default_prompt: 'Dança com vestido preto.', continuation_prompt: 'Pequeno salto. Vestido vermelho. Termina de costas.', reference_image: 'dance_reference.png', duration_seconds: 2.3, duration_capabilities: caps, workflow_output_profile: 'final_only', filesystem_events: true, reference_library: true, assembly_enabled: true};
let editor = {system_prompt: 'Preserve ação, roupa, pose e ordem. Responda só com a cena.', model: pin};
const mkRun = (id, state, parent_id = null, duration = 2.3, prompt = malicious) => ({id, state, parent_id, prompt, seed: 2026101205, duration_seconds: duration, created_at: '2026-10-12T20:00:00Z', updated_at: '2026-10-12T20:00:01Z', references: [{type: 'image', role: 'identity', source_root: 'assets', source: 'dance_reference.png'}], output: {path: `.data/runs/${id}/chunk.mp4`, probe: {streams: [{codec_type: 'video', duration: String(alignedFrames(duration) / 24)}]}}, error: null});
let runs, assemblies = [], mode = 'normal', grokMode = 'normal', assemblyMode = 'normal', generated = 0;
let grokGate = null, releaseGrok, waitGate = null, releaseWait, detailGate = null, releaseDetail;
let admissionGate = null, releaseAdmission, decisionGate = null, releaseDecision;
const resetRuns = () => { runs = [mkRun(endID, 'ready_for_review', rootID), mkRun(rootID, 'accepted'), {...mkRun(failedID, 'failed'), error: 'Falha histórica preservada', output: {}}]; };
resetRuns();
const requests = [], exceptions = [], violations = [], consoleMessages = [], failedRequests = [], audits = [], captures = [];
const posts = () => requests.filter(item => item.method === 'POST');
const inference = () => posts().filter(item => item.path === '/runs/i2v' || item.path.endsWith('/v2v'));
const grokPosts = () => posts().filter(item => item.path === '/grok');
const assemblyPosts = () => posts().filter(item => item.path.startsWith('/assemblies/'));
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 393, height: 852}, deviceScaleFactor: 2, isMobile: true, hasTouch: true, reducedMotion: 'reduce', serviceWorkers: 'block'});
async function routeRequest(route) {
  const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
  if (url.origin !== 'http://h3.mock.invalid') { violations.push(request.url()); return route.abort(); }
  requests.push({method, path: path + url.search, body: path === '/inputs' && method === 'POST' ? {diskUploadFake: true, bytes: request.postDataBuffer()?.length} : request.postDataJSON()});
  const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
  if (path === '/') return route.fulfill({contentType: 'text/html', body: assets['index.html']});
  if (path.startsWith('/ui/') && assets[path.slice(4)]) return route.fulfill({contentType: path.endsWith('.js') ? 'text/javascript' : 'text/css', body: assets[path.slice(4)]});
  if (path === '/favicon.ico') return route.fulfill({status: 204});
  if (path === '/app/config') return mode === 'config-error' ? json({detail: 'Configuração indisponível'}, 503) : json(config);
  if (path === '/grok/editor') {
    if (grokMode === 'editor-error') return json({detail: 'Editor indisponível'}, 409);
    if (method === 'PUT') { const body = request.postDataJSON(); assert.equal(body.model, pin); editor = body; }
    return json(editor);
  }
  if (path === '/grok' && method === 'POST') {
    if (grokGate) await grokGate;
    if (grokMode === 'network') return route.abort('connectionfailed');
    if (grokMode === 'error') return json({detail: 'Imagem não suportada'}, 400);
    return json({text: grokMode === 'oversized' ? 'x'.repeat(12001) : providerScene, model: pin});
  }
  if (path.startsWith('/grok/auth/') || path === '/events') { violations.push(path); return route.abort(); }
  if (path === '/inputs') {
    if (method === 'POST') { const item = {source_root: 'inputs', path: 'uploaded/original.png', name: 'phone photo.png', image_url: '/inputs/image?path=uploaded%2Foriginal.png'}; references.push(item); return json(item, 201); }
    return json({items: references, total: references.length});
  }
  if (['/assets/image', '/inputs/image'].includes(path) || path.endsWith('/image')) return route.fulfill({contentType: 'image/png', body: image});
  if (path === '/runs') return mode === 'list-error' ? json({detail: 'Leitura indisponível <b>texto</b>'}, 503) : json({items: mode === 'empty' ? [] : runs.map(run => ({...run, video_url: ['ready_for_review', 'accepted', 'rejected'].includes(run.state) && run.output.path ? `/runs/${run.id}/video` : null})), total: mode === 'empty' ? 0 : runs.length});
  if (method === 'POST' && (path === '/runs/i2v' || path.endsWith('/v2v'))) {
    if (mode === 'ambiguous') return route.abort('connectionfailed');
    if (mode === 'conflict') return json({detail: 'Slot ocupado'}, 409);
    if (admissionGate) await admissionGate;
    const body = request.postDataJSON(), id = `00000000-0000-4000-8000-${String(++generated).padStart(12, '0')}`;
    const run = {...mkRun(id, 'queued', path.endsWith('/v2v') ? path.split('/')[2] : null, body.duration_seconds, body.prompt), seed: body.seed, output: {}};
    run.references = run.parent_id ? structuredClone(runs.find(item => item.id === run.parent_id).references) : (body.references || [original]).map(ref => ({type: 'image', role: 'identity', source_root: ref.source_root, source: ref.path}));
    runs.unshift(run); return json(run, 202);
  }
  if (path === '/assemblies') { const items = assemblies.filter(item => item.end_run_id === url.searchParams.get('end_run_id')); return json({items, total: items.length}); }
  if (path.startsWith('/assemblies/')) {
    const id = path.split('/')[2];
    if (method === 'POST') {
      const body = request.postDataJSON(); assert.deepEqual(Object.keys(body), ['end_run_id']);
      assert.equal(new URL(request.frame().page().url()).searchParams.get('assembly'), id);
      if (assemblyMode === 'busy' || assemblyMode === 'collision') return json({detail: assemblyMode}, 409);
      const end = runs.find(run => run.id === body.end_run_id);
      const record = {id, end_run_id: end.id, state: 'completed', mode: end.state === 'accepted' ? 'accepted_sequence' : 'preview', request_sha256: 'a'.repeat(64), output_sha256: 'b'.repeat(64), frames: 168, fps: '24/1', video_url: `/assemblies/${id}/video`, output: {path: `.data/assemblies/${id}/video.mp4`}};
      assemblies.unshift(record); if (assemblyMode === 'lost') return route.abort('connectionfailed'); return json(record);
    }
    const record = assemblies.find(item => item.id === id);
    if (!record) return json({detail: 'ID não publicado'}, 404);
    if (path.endsWith('/video')) return route.fulfill(assemblyMedia ? {contentType: 'video/mp4', body: assemblyMedia} : {status: 204});
    return json(record);
  }
  if (path.startsWith('/runs/')) {
    const run = runs.find(item => item.id === path.split('/')[2]); if (!run) return json({detail: 'Run not found'}, 404);
    if (path === `/runs/${rootID}` && detailGate) await detailGate;
    if (path.endsWith('/video')) return route.fulfill(media ? {contentType: 'video/mp4', body: media} : {status: 204});
    if (method === 'POST' && /\/(accept|reject)$/.test(path)) { assert.equal(run.state, 'ready_for_review'); if (mode === 'decision-error') return json({detail: 'Decisão recusada'}, 409); if (decisionGate) await decisionGate; run.state = path.endsWith('/accept') ? 'accepted' : 'rejected'; return json(run); }
    if (path.endsWith('/sequence')) {
      const chain = []; let current = run; while (current) { chain.unshift(current); current = runs.find(item => item.id === current.parent_id); }
      return json({root_id: chain[0].id, end_run_id: run.id, blocks: chain.map(item => ({id: item.id, parent_id: item.parent_id, state: item.state, duration_seconds: alignedFrames(item.duration_seconds) / 24, video_url: item.output.path && ['ready_for_review', 'accepted', 'rejected'].includes(item.state) ? `/runs/${item.id}/video` : null}))});
    }
    if (url.searchParams.get('wait') === 'true') { if (waitGate) await waitGate; run.state = 'ready_for_review'; run.output = mkRun(run.id, run.state, run.parent_id, run.duration_seconds).output; }
    return json(run);
  }
  violations.push(`unexpected:${method}:${path}`); return route.abort();
}
const mockStartup = () => {
  window.mockEvents = []; window.startupOrder = []; window.uuidDraws = 0; window.mediaLoads = 0;
  const load = HTMLMediaElement.prototype.load; HTMLMediaElement.prototype.load = function() { window.mediaLoads++; return load.call(this); };
  const random = crypto.getRandomValues.bind(crypto); Object.defineProperty(crypto, 'randomUUID', {value: undefined, configurable: true});
  crypto.getRandomValues = bytes => { window.uuidDraws++; return random(bytes); };
  const fetch = window.fetch.bind(window); window.fetch = (...args) => { window.startupOrder.push(String(args[0])); return fetch(...args); };
  window.EventSource = class extends EventTarget {
    constructor(path) { super(); this.url = path; this.closed = false; window.mockEvents.push(this); window.startupOrder.push('SSE registered'); queueMicrotask(() => { window.startupOrder.push('SSE open'); this.emit('open'); }); }
    close() { this.closed = true; }
    emit(type, data) { this.dispatchEvent(type === 'open' ? new Event(type) : new MessageEvent(type, {data: JSON.stringify(data)})); }
  };
};
await context.route('**/*', routeRequest); await context.addInitScript(mockStartup);
const page = await context.newPage();
function watch(page) { page.on('pageerror', error => exceptions.push(error.message)); page.on('console', message => { if (message.type() === 'error') consoleMessages.push(message.text()); }); page.on('requestfailed', request => failedRequests.push({url: request.url(), reason: request.failure()?.errorText})); }
watch(page);
async function ready(href = 'http://h3.mock.invalid/?other=keep#viewer') { await page.goto(href); await page.locator('#notice').filter({hasText: /Escolha um bloco|API indisponível/}).waitFor(); }
async function active(screen) { await page.locator(`[data-screen="${screen}"]`).waitFor({state: 'visible'}); assert.equal(await page.locator('[data-screen]:visible').count(), 1); }
async function audit(name, target = page) {
  const bounds = await target.evaluate(() => ({width: innerWidth, height: innerHeight, scrollX, scrollY, visualViewport: {x: visualViewport.offsetLeft, y: visualViewport.offsetTop, width: visualViewport.width, height: visualViewport.height, scale: visualViewport.scale}, heading: document.getElementById('screen-title').getBoundingClientRect().toJSON(), overflow: document.documentElement.scrollWidth > innerWidth, active: [...document.querySelectorAll('[data-screen]')].filter(node => !node.hidden).map(node => node.dataset.screen), hiddenInert: [...document.querySelectorAll('[data-screen][hidden]')].every(node => node.inert), hiddenFocus: Boolean(document.activeElement?.closest('[data-screen][hidden]')), controls: [...document.querySelectorAll('button')].filter(node => node.getClientRects().length).map(node => ({id: node.id, height: node.getBoundingClientRect().height, width: node.getBoundingClientRect().width})), panels: [...document.querySelectorAll('[data-screen]')].filter(node => !node.hidden).map(node => ({screen: node.dataset.screen, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight, overflow: getComputedStyle(node).overflow, bounds: node.getBoundingClientRect().toJSON()}))}));
  assert.equal(bounds.overflow, false, `${name}: horizontal overflow`); assert.equal(bounds.active.length, 1); assert.equal(bounds.hiddenInert, true); assert.equal(bounds.hiddenFocus, false); assert.ok(bounds.controls.every(control => control.height >= 44), `${name}: touch target`);
  const actions = await target.evaluate(() => {
    const footer = document.querySelector('.studio-footer').getBoundingClientRect(), view = visualViewport;
    return [...document.querySelectorAll('[data-screen]:not([hidden]) .screen-actions button')].filter(node => node.getClientRects().length).map(node => {
      const box = node.getBoundingClientRect(), center = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
      return {id: node.id, box: box.toJSON(), footer: footer.toJSON(), intersectsFooter: box.bottom > footer.top + 1 && box.top < footer.bottom && box.left < footer.right && box.right > footer.left, insideViewport: box.top >= view.offsetTop && box.bottom <= view.offsetTop + view.height && box.left >= view.offsetLeft && box.right <= view.offsetLeft + view.width, centerTarget: center?.closest('button')?.id};
    });
  });
  if (bounds.width <= 640) for (const action of actions) { assert.equal(action.intersectsFooter, false, `${name}: ${action.id} footer overlap`); assert.equal(action.insideViewport, true, `${name}: ${action.id} clipped`); assert.equal(action.centerTarget, action.id, `${name}: ${action.id} occluded`); }
  audits.push({name, ...bounds, actions}); return bounds;
}
async function focusedAudit(id) {
  await page.locator(`#${id}`).tap(); await page.locator(`#${id}`).evaluate(node => node.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'}));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const result = await page.evaluate(id => { const box = document.getElementById(id).getBoundingClientRect(); const blockers = [...document.querySelectorAll('.studio-footer,[data-screen]:not([hidden]) .screen-actions')].filter(node => node.getClientRects().length && ['fixed', 'sticky'].includes(getComputedStyle(node).position)).map(node => node.getBoundingClientRect().top); return {id, focused: document.activeElement.id, box: box.toJSON(), safeBottom: Math.min(visualViewport.offsetTop + visualViewport.height, ...blockers), viewportTop: visualViewport.offsetTop}; }, id);
  assert.equal(result.focused, id); assert.ok(result.box.top >= result.viewportTop && result.box.bottom <= result.safeBottom, `${id}: focused field covered by fixed controls`); audits.push({name: `focused-${id}`, ...result});
}
async function capture(name, target = page, {directory = artifacts, animations = 'disabled'} = {}) {
  await target.evaluate(async () => { await document.fonts.ready; for (const image of document.images) if (image.getClientRects().length && !image.complete) await new Promise(resolve => { image.addEventListener('load', resolve, {once: true}); image.addEventListener('error', resolve, {once: true}); }); document.getElementById('screen-title').focus({preventScroll: true}); document.activeElement?.blur(); window.scrollTo(0, 0); await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); window.scrollTo(0, 0); await new Promise(resolve => requestAnimationFrame(resolve)); });
  await target.mouse.move(2, 2);
  await target.waitForLoadState('networkidle');
  if (media || assemblyMedia) await target.waitForFunction(() => [...document.querySelectorAll('video')].filter(video => !video.hidden && video.getClientRects().length && video.getAttribute('src')).every(video => video.readyState >= 2 || video.error));
  await audit(name, target); assert.deepEqual(exceptions, []); assert.deepEqual(violations, []);
  const path = resolve(directory, `${name}.png`), size = target.viewportSize();
  // An explicit document-origin clip avoids mobile IME/compositor scroll races.
  await target.screenshot({path, animations, clip: {x: 0, y: 0, width: size.width, height: size.height}}); captures.push(path);
}
async function openRun(id) { await page.locator('#nav-library').click(); await page.getByRole('button', {name: new RegExp(id)}).click(); await active('review'); }
async function newIdea(text = 'Uma ideia simples') { await page.locator('#nav-new').click(); await active('context'); await page.locator('#idea').fill(text); }
async function prepare(text = 'Uma ideia simples', duration = '2.3') { await newIdea(text); await page.locator('#use-idea').click(); await active('generation'); await page.locator('#duration').fill(duration); }
async function emitHints() { await page.evaluate(() => { mockEvents[0]?.emit('open'); for (let i = 0; i < 12; i++) mockEvents[0]?.emit('change', {path: '.data/runs/own/manifest.json', invalidation: true}); }); await page.locator('#notice').filter({hasText: /Biblioteca atualizada|Resultado anterior incerto/}).waitFor(); }
try {
  await ready(); await active('library'); assert.equal(posts().length, 0); assert.equal(await page.locator('#player').getAttribute('src'), null);
  assert.ok(await page.evaluate(() => startupOrder.indexOf('SSE open') < startupOrder.indexOf('/inputs?limit=50&offset=0')));
  assert.equal(await page.evaluate(() => navigator.maxTouchPoints > 0 && devicePixelRatio === 2), true);
  await capture('phone-library');
  await newIdea('ela dá um salto e o vestido fica vermelho');
  assert.equal(await page.locator('#grok-model').inputValue(), pin); assert.equal(await page.locator('#grok-model').getAttribute('readonly'), '');
  await page.locator('.grok-settings summary').click(); await page.locator('#grok-system').fill('Detalhe sem inventar identidade.');
  const enterCount = posts().length; await page.locator('#grok-model').press('Enter'); assert.equal(posts().length, enterCount);
  await page.locator('#grok-save').click(); await page.locator('#grok-config-status').filter({hasText: 'Configuração salva'}).waitFor();
  await page.locator('.grok-settings summary').click();
  await page.locator('#reference').selectOption('1'); await focusedAudit('idea'); await capture('phone-context');
  const beforeGrok = inference().length;
  await page.locator('#grok-detail').evaluate(button => { button.click(); button.click(); }); await active('proposal');
  assert.equal(grokPosts().length, 1); assert.equal(inference().length, beforeGrok);
  assert.deepEqual(grokPosts().at(-1).body, {system_prompt: editor.system_prompt, prompt: 'ela dá um salto e o vestido fica vermelho', model: pin, reference: {source_root: 'inputs', path: 'own/original.png'}});
  assert.equal(await page.locator('#idea').inputValue(), 'ela dá um salto e o vestido fica vermelho'); assert.equal(await page.locator('#grok-result').inputValue(), scene);
  await page.locator('#grok-result').fill('   '); await page.locator('#grok-use').click(); await page.locator('#proposal-error').filter({hasText: 'não devolveu'}).waitFor(); assert.equal(inference().length, beforeGrok); await page.locator('#grok-result').fill(`${scene}\nEla termina de costas.`); await focusedAudit('grok-result'); await capture('phone-proposal');
  await page.locator('#grok-use').tap(); await active('generation'); assert.equal(inference().length, beforeGrok);
  await page.locator('#duration').tap(); await page.locator('#duration').fill('5'); await page.locator('#seed').fill('42'); await page.locator('#duration-preview').filter({hasText: '124 frames'}).waitFor();
  await page.locator('#duration').press('Enter'); assert.equal(inference().length, beforeGrok);
  await focusedAudit('duration'); await capture('phone-generation-5s');
  // Back and mode/selection changes retain idea, edited proposal, duration and seed.
  await page.locator('#back').click(); await active('proposal'); assert.match(await page.locator('#grok-result').inputValue(), /termina de costas/);
  await page.locator('#grok-use').click(); assert.equal(await page.locator('#duration').inputValue(), '5'); assert.equal(await page.locator('#seed').inputValue(), '42');
  waitGate = new Promise(resolve => { releaseWait = resolve; });
  await page.locator('#generate').evaluate(button => { button.click(); button.click(); }); await page.locator('#operation').filter({hasText: 'Admitido:'}).waitFor();
  assert.equal(inference().length, beforeGrok + 1); assert.equal(inference().at(-1).body.duration_seconds, 5);
  const admitted = runs[0].id; assert.equal(requests.filter(item => item.path === `/runs/${admitted}?wait=true`).length, 1);
  await capture('phone-status'); const countPending = posts().length; await page.locator('#nav-library').click(); await active('library');
  await page.evaluate(() => mockEvents[0].emit('change', {path: '.data/runs/own/manifest.json', invalidation: true})); assert.equal(posts().length, countPending);
  releaseWait(); waitGate = null; await page.locator('#nav-status').click(); await page.locator('#operation').filter({hasText: `Pronto para revisão · ${admitted}`}).waitFor(); await page.locator('#status-review').click(); await active('review');
  assert.match(await page.locator('#review-duration').textContent(), /Solicitada 5 s.*124 frames.*verificada 5,167 s/);
  if (media) { await page.waitForFunction(() => document.getElementById('player').videoWidth > 0); await page.locator('#player').evaluate(async video => { await video.play(); }); await page.waitForFunction(() => document.getElementById('player').currentTime > 0.05); await page.locator('#player').evaluate(video => video.pause()); }
  await capture('phone-review'); mode = 'decision-error'; await page.locator('#accept').click(); await page.locator('#review-status').filter({hasText: 'Decisão não confirmada'}).waitFor(); assert.equal(await page.locator('#accept').isEnabled(), true); await active('review'); mode = 'normal'; const beforeAccept = posts().length; await page.locator('#accept').click(); await page.locator('#run-state').filter({hasText: 'Aceito'}).waitFor(); await active('review'); assert.equal(posts().length, beforeAccept + 1);
  await page.locator('#continue-mode').click(); await active('continuation'); await capture('phone-continuation'); await page.locator('#continue-idea').click(); await active('context');
  assert.equal(await page.locator('#reference').isDisabled(), true); await page.locator('#idea').fill('Continua de costas e vira de frente.');
  await page.locator('#grok-detail').click(); await active('proposal'); assert.deepEqual(grokPosts().at(-1).body.reference, {source_root: 'inputs', path: 'own/original.png'});
  await page.locator('#grok-use').click(); await page.locator('#duration').fill('10'); await page.locator('#seed').fill('9007199254740991');
  await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'Pronto para revisão'}).waitFor();
  assert.deepEqual(inference().at(-1).body, {seed: Number.MAX_SAFE_INTEGER, prompt: scene, duration_seconds: 10, reference_tail_seconds: 3, include_audio: true}); assert.equal(inference().at(-1).path, `/runs/${admitted}/v2v`);
  await page.locator('#status-review').click(); await active('review'); await page.locator('#reject').click(); await page.locator('#run-state').filter({hasText: 'Rejeitado'}).waitFor(); assert.equal(await page.locator('#continue-mode').isDisabled(), true);
  // Parent-keyed continuation drafts survive visiting another parent and the new scene.
  await openRun(rootID); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); await page.locator('#idea').fill('Rascunho do pai original'); await page.locator('#use-idea').click(); await page.locator('#duration').fill('3');
  await openRun(admitted); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); assert.equal(await page.locator('#idea').inputValue(), 'Continua de costas e vira de frente.'); await page.locator('#use-idea').click(); assert.equal(await page.locator('#duration').inputValue(), '10');
  await openRun(rootID); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); assert.equal(await page.locator('#idea').inputValue(), 'Rascunho do pai original'); await page.locator('#use-idea').click(); assert.equal(await page.locator('#duration').inputValue(), '3');
  await newIdea(); assert.equal(await page.locator('#grok-result').inputValue(), `${scene}\nEla termina de costas.`); assert.equal(await page.locator('#duration').inputValue(), '5');
  // Explicit upload selects only; it never details, generates or accepts.
  await page.locator('#upload-details summary').click(); const uploadBefore = posts().length;
  await page.locator('#upload-file').setInputFiles({name: 'phone photo.png', mimeType: 'image/png', buffer: image}); await page.locator('#upload').evaluate(button => { button.click(); button.click(); }); await page.locator('#upload-status').filter({hasText: 'Imagem salva no PC'}).waitFor(); assert.equal(posts().length, uploadBefore + 1);
  await page.locator('#upload-details summary').click();
  grokGate = new Promise(resolve => { releaseGrok = resolve; }); await page.locator('#idea').fill('Ideia antiga'); await page.locator('#grok-detail').click(); await page.locator('#idea').fill('Ideia nova, não substituir'); await page.locator('#reference').selectOption('0');
  releaseGrok(); grokGate = null; await page.locator('#grok-status').filter({hasText: 'contexto mudou'}).waitFor(); await active('context'); assert.equal(await page.locator('#idea').inputValue(), 'Ideia nova, não substituir'); await page.locator('#show-proposal').click(); await active('proposal'); assert.match(await page.locator('#proposal-hint').textContent(), /contexto mudou/); assert.match(await page.locator('#proposal-context').textContent(), /uploaded/);
  await capture('phone-stale-proposal');
  // Changing originating parent during an in-flight Grok never replaces another draft.
  await newIdea('Pedido no rascunho novo'); grokGate = new Promise(resolve => { releaseGrok = resolve; }); await page.locator('#grok-detail').click(); await openRun(rootID); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click();
  releaseGrok(); grokGate = null; await page.locator('#grok-status').filter({hasText: 'contexto mudou'}).waitFor(); assert.equal(await page.locator('#idea').inputValue(), 'Rascunho do pai original');
  // A provider response must not clobber a manually edited original proposal,
  // including after leaving that draft. Its late candidate requires a separate choice.
  await newIdea('Pedido com uma proposta em edição'); const editedOrigin = {chosen: await page.locator('#prompt').inputValue(), duration: await page.locator('#duration').inputValue(), seed: await page.locator('#seed').inputValue(), reference: await page.locator('#reference').inputValue()}; grokGate = new Promise(resolve => { releaseGrok = resolve; }); await page.locator('#grok-detail').click(); await page.locator('#show-proposal').click();
  await page.locator('#grok-result').fill('Minha proposta editada deve sobreviver ao retorno atrasado.'); await openRun(rootID); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); releaseGrok(); grokGate = null;
  await page.locator('#grok-status').filter({hasText: 'contexto mudou'}).waitFor(); const lateBefore = inference().length; await page.locator('#nav-new').click(); await page.locator('#show-proposal').click();
  assert.equal(await page.locator('#grok-result').inputValue(), 'Minha proposta editada deve sobreviver ao retorno atrasado.'); assert.equal(await page.locator('#idea').inputValue(), 'Pedido com uma proposta em edição');
  await page.locator('#late-proposal-details summary').click(); assert.equal(await page.locator('#late-proposal').inputValue(), scene); assert.match(await page.locator('#late-proposal-context').textContent(), /assets.*dance_reference/); const beforeAdopt = posts().length; await page.locator('#use-late-proposal').click(); assert.equal(await page.locator('#grok-result').inputValue(), scene); assert.equal(inference().length, lateBefore); assert.equal(posts().length, beforeAdopt); await page.locator('#use-late-proposal').evaluate(button => button.click()); assert.equal(posts().length, beforeAdopt); assert.equal(await page.locator('#grok-result').inputValue(), scene); assert.deepEqual({chosen: await page.locator('#prompt').inputValue(), duration: await page.locator('#duration').inputValue(), seed: await page.locator('#seed').inputValue(), reference: await page.locator('#reference').inputValue()}, editedOrigin); await page.locator('#edit-idea').click();
  // No form submit from hidden screens, navigation, SSE, resize or browser history.
  const noPost = posts().length; await page.locator('#create-form').evaluate(form => form.dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}))); await emitHints(); await page.evaluate(() => window.dispatchEvent(new PopStateEvent('popstate'))); assert.equal(posts().length, noPost);
  await openRun(rootID); const source = await page.locator('#player').getAttribute('src'), loads = await page.evaluate(() => mediaLoads); await emitHints(); assert.equal(await page.locator('#player').getAttribute('src'), source); assert.equal(await page.evaluate(() => mediaLoads), loads);
  await openRun(failedID); assert.equal(await page.locator('#player').isHidden(), true); assert.equal(await page.locator('#accept').isDisabled(), true); await capture('phone-failed');
  // Stale library detail cannot open the wrong clip after a newer selection.
  await page.locator('#nav-library').click(); detailGate = new Promise(resolve => { releaseDetail = resolve; }); await page.locator('.clip-card').filter({hasText: rootID.slice(0, 8)}).click(); await page.locator('.clip-card').filter({hasText: endID.slice(0, 8)}).click(); await active('review'); releaseDetail(); detailGate = null; assert.match(await page.locator('#metadata').textContent(), new RegExp(endID));
  await page.locator('.metadata summary').click(); assert.equal(await page.locator('#run-prompt').textContent(), malicious); assert.equal(await page.locator('#run-prompt img').count(), 0); assert.equal(await page.evaluate(() => Boolean(window.hacked)), false);
  // Assembly is its own explicit action and read-only same-UUID recovery.
  await page.locator('#open-assembly').click(); await active('assembly'); const nativeBeforeAssembly = inference().length;
  await page.locator('#assemble').evaluate(button => { button.click(); button.click(); }); await page.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor(); const ownID = new URL(page.url()).searchParams.get('assembly');
  assert.equal(await page.evaluate(() => uuidDraws), 1); assert.equal(new URL(page.url()).searchParams.get('other'), 'keep'); assert.equal(new URL(page.url()).hash, '#viewer'); assert.equal(await page.locator('#run-state').textContent(), 'Pronto para revisão'); assert.equal(await page.locator('#assembly-label').textContent(), 'Montagem de prévia — revisão pendente'); assert.equal(inference().length, nativeBeforeAssembly);
  if (assemblyMedia) { await page.waitForFunction(() => document.getElementById('assembly-player').videoWidth > 0); await page.locator('#assembly-player').evaluate(async video => { await video.play(); }); await page.waitForFunction(() => document.getElementById('assembly-player').currentTime > 0.05); await page.locator('#assembly-player').evaluate(video => video.pause()); }
  await capture('phone-assembly-preview'); const assemblyBeforeReload = assemblyPosts().length; await page.reload(); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); await active('assembly'); assert.equal(assemblyPosts().length, assemblyBeforeReload); assert.equal(new URL(page.url()).searchParams.get('assembly'), ownID);
  await page.locator('#assembly-refresh').click(); await page.locator('#assembly-status').filter({hasText: 'Apenas metadados relidos'}).waitFor(); assert.equal(assemblyPosts().length, assemblyBeforeReload);
  await page.locator('#nav-library').click(); await openRun(endID); await page.locator('#accept').click(); await page.locator('#run-state').filter({hasText: 'Aceito'}).waitFor(); assert.equal(assemblyPosts().length, assemblyBeforeReload); await page.locator('#open-assembly').click(); await page.locator('#assemble').click(); await page.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor(); assert.notEqual(new URL(page.url()).searchParams.get('assembly'), ownID); assert.equal(await page.locator('#assembly-label').textContent(), 'Montagem da sequência aceita');
  await capture('phone-assembly-accepted');
  // Uncertain CPU publication never invents/reposts an ID on read, reload or navigation.
  resetRuns(); assemblies = []; assemblyMode = 'lost'; await ready(); await openRun(endID); await page.locator('#open-assembly').click(); await page.locator('#assemble').click(); await page.locator('#assembly-status').filter({hasText: 'Resultado incerto'}).waitFor(); const lostID = new URL(page.url()).searchParams.get('assembly'), lostCount = assemblyPosts().length; assert.equal(await page.locator('#assemble').isDisabled(), true);
  await page.locator('#assembly-refresh').click(); await page.locator('#assembly-status').filter({hasText: 'Apenas metadados relidos'}).waitFor(); await page.reload(); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); assert.equal(assemblyPosts().length, lostCount); assert.equal(new URL(page.url()).searchParams.get('assembly'), lostID);
  assemblyMode = 'normal'; const missing = '99999999-9999-4999-8999-999999999999'; await ready(`http://h3.mock.invalid/?assembly=${missing}`); await active('assembly'); assert.equal(await page.locator('#assemble').isDisabled(), true); await capture('phone-assembly-missing');
  // Explicit refuses are recoverable, uncertain inference is not, even after navigation/SSE.
  mode = 'conflict'; await ready(); await prepare('Recusa explícita', '3'); await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'HTTP 409'}).waitFor(); assert.equal(await page.locator('#generate').isEnabled(), true);
  mode = 'ambiguous'; await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'Resultado incerto'}).waitFor(); const uncertainCount = inference().length; await newIdea('Rascunho mantido após incerteza'); await page.locator('#use-idea').click(); assert.equal(await page.locator('#generate').isDisabled(), true); await emitHints(); assert.equal(inference().length, uncertainCount); await capture('phone-native-uncertain');
  mode = 'normal'; grokMode = 'network'; await ready(); await newIdea('Grok incerto'); await page.locator('#grok-detail').click(); await page.locator('#grok-status').filter({hasText: 'Resultado incerto'}).waitFor(); const uncertainGrok = grokPosts().length; await page.locator('#nav-library').click(); await newIdea('Outra navegação'); assert.equal(await page.locator('#grok-detail').isDisabled(), true); await emitHints(); assert.equal(grokPosts().length, uncertainGrok);
  grokMode = 'error'; await ready(); await newIdea('Imagem recusada'); await page.locator('#grok-detail').click(); await page.locator('#grok-status').filter({hasText: 'HTTP 400'}).waitFor(); assert.equal(await page.locator('#idea').inputValue(), 'Imagem recusada'); assert.equal(await page.locator('#grok-detail').isEnabled(), true);
  grokMode = 'oversized'; await page.locator('#grok-detail').click(); await page.locator('#grok-status').filter({hasText: 'sem truncar'}).waitFor(); assert.equal(await page.locator('#idea').inputValue(), 'Imagem recusada');
  grokMode = 'editor-error'; await ready(); await prepare('Sem editor', '2.8'); assert.equal(await page.locator('#generate').isEnabled(), true); grokMode = 'normal';
  delete config.duration_capabilities; await ready(); await newIdea(); await page.locator('#use-idea').click(); assert.equal(await page.locator('#duration').getAttribute('readonly'), ''); assert.match(await page.locator('#duration-policy').textContent(), /legado/);
  config.duration_capabilities = {...caps, max_frames: 240}; await ready(); assert.equal(await page.locator('#new-mode').isDisabled(), true); assert.equal(await page.locator('#generate').isDisabled(), true);
  config.duration_capabilities = caps; config.assembly_enabled = false; delete config.filesystem_events; delete config.reference_library; const disabledAssemblyReads = requests.filter(item => item.path.startsWith('/assemblies')).length; await ready(); assert.equal(await page.evaluate(() => mockEvents.length), 0); assert.equal(requests.filter(item => item.path.startsWith('/assemblies')).length, disabledAssemblyReads);
  config.assembly_enabled = true; config.filesystem_events = true; config.reference_library = true; mode = 'empty'; await ready(); await capture('phone-empty'); mode = 'list-error'; await ready(); assert.equal(await page.locator('#notice b').count(), 0); await capture('phone-api-error'); mode = 'normal';
  runs = Array.from({length: 12}, (_, index) => mkRun(`10000000-0000-4000-8000-${String(index).padStart(12, '0')}`, 'accepted', null, 2.3, malicious.repeat(30))); await ready();
  for (const width of [393, 320, 640, 1440]) {
    const count = posts().length; await page.setViewportSize({width, height: 852}); await audit(`library-${width}`); assert.equal(posts().length, count);
    const cards = await page.locator('.clip-card').evaluateAll(nodes => nodes.map(node => { const box = node.getBoundingClientRect(); return {shrink: getComputedStyle(node).flexShrink, children: [...node.children].map(child => { const rect = child.getBoundingClientRect(); return rect.top >= box.top - 1 && rect.bottom <= box.bottom + 1; })}; })); assert.equal(cards.length, 12); assert.ok(cards.every(card => card.shrink === '0' && card.children.every(Boolean))); await capture(`library-${width}`);
    await prepare('Mobile parâmetros', '10'); await audit(`generation-${width}`); await capture(`generation-${width}`); await page.locator('#nav-library').click();
  }
  const desktop = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce', serviceWorkers: 'block'}); await desktop.route('**/*', routeRequest); await desktop.addInitScript(mockStartup); const desktopPage = await desktop.newPage(); watch(desktopPage); await desktopPage.goto('http://h3.mock.invalid/'); await desktopPage.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); await audit('desktop-real-context', desktopPage); await desktop.close();
  // Owner-facing evidence is a separate benign fixture set, not XSS regression copy.
  resetRuns(); for (const run of runs) run.prompt = run.parent_id ? 'Ela dá um pequeno salto e termina de costas.' : 'Ela dança mantendo a referência original.';
  references[1].name = 'Foto publicada no PC'; providerScene = 'Ela dá um pequeno salto. Durante o movimento, o vestido fica vermelho. Ao final, ela fica de costas. Preserve a identidade da referência original.';
  await page.setViewportSize({width: 393, height: 852}); await ready(); await capture('owner-library');
  await newIdea('Ela dá um salto, muda o vestido para vermelho e termina de costas.'); await focusedAudit('idea'); await capture('owner-context');
  await page.locator('#grok-detail').click(); await active('proposal'); await focusedAudit('grok-result'); await capture('owner-proposal');
  await page.locator('#grok-use').click(); await page.locator('#duration').fill('5'); await focusedAudit('duration'); await capture('owner-generation-5s');
  await openRun(endID); await capture('owner-review');
  assert.equal(await page.evaluate(() => document.getAnimations().length), 0, 'reduce context has no CSS or WAAPI motion');
  // The regression context intentionally reduces motion. A separate normal-touch
  // context observes real keyframes, interruption and input while motion is running.
  resetRuns(); assemblies = []; mode = grokMode = assemblyMode = 'normal';
  const liveMotion = await browser.newContext({viewport: {width: 393, height: 852}, deviceScaleFactor: 2, isMobile: true, hasTouch: true, reducedMotion: 'no-preference', serviceWorkers: 'block', recordVideo: {dir: motionArtifacts, size: {width: 393, height: 852}}});
  await liveMotion.route('**/*', routeRequest); await liveMotion.addInitScript(mockStartup);
  await liveMotion.addInitScript(() => {
    window.motionLog = [];
    const animate = Element.prototype.animate;
    Element.prototype.animate = function(frames, options) {
      motionLog.push({id: this.id, tag: this.tagName, classes: this.className, frames, options, unsafe: this.matches('video,input,textarea,select,form,fieldset,.task-panel,.stage,.studio,body,.screen-actions') || Boolean(this.querySelector('video,.screen-actions'))});
      return animate.call(this, frames, options);
    };
  });
  const moving = await liveMotion.newPage(); watch(moving);
  await moving.goto('http://h3.mock.invalid/?other=keep#viewer'); await moving.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor();
  await moving.waitForFunction(() => motionLog.length > 0);
  await moving.getByRole('button', {name: new RegExp(endID)}).tap(); await moving.locator('[data-screen="review"]').waitFor({state: 'visible'});
  const beforeMotion = posts().length;
  const mid = await moving.locator('#nav-new').evaluate(button => {
    button.click(); const animations = document.getAnimations().filter(animation => animation.effect?.target?.matches('[data-motion="heading"]'));
    for (const animation of animations) { animation.pause(); animation.currentTime = 90; }
    const heading = document.querySelector('[data-motion="heading"]'), style = getComputedStyle(heading);
    return {running: animations.length, transform: style.transform, opacity: Number(style.opacity), panel: document.querySelector('[data-screen]:not([hidden])').dataset.screen, focus: document.activeElement.id};
  });
  assert.equal(mid.running, 1); assert.equal(mid.panel, 'context'); assert.equal(mid.focus, 'screen-title'); assert.ok(mid.opacity > .65 && mid.opacity < 1); assert.notEqual(mid.transform, 'none');
  await capture('context-mid', moving, {directory: motionArtifacts, animations: 'allow'}); assert.equal(posts().length, beforeMotion);
  await moving.locator('#idea').fill('Uma cena viva, sem mudar os parâmetros.');
  await moving.locator('#back').evaluate(button => button.click()); await moving.locator('#nav-new').evaluate(button => button.click());
  assert.equal(await moving.locator('#idea').inputValue(), 'Uma cena viva, sem mudar os parâmetros.'); assert.equal(posts().length, beforeMotion);
  grokGate = new Promise(resolve => { releaseGrok = resolve; }); const beforeBusy = grokPosts().length;
  await moving.locator('#grok-detail').evaluate(button => { button.click(); button.click(); }); await moving.waitForFunction(() => document.getElementById('grok-detail').dataset.busy === 'true');
  await moving.waitForFunction(() => !document.getAnimations().some(animation => animation.animationName === 'decision-busy'));
  assert.equal(grokPosts().length, beforeBusy + 1); assert.equal(await moving.locator('[role="progressbar"]').count(), 0); await audit('motion-busy-static', moving);
  await moving.evaluate(() => document.getElementById('grok-detail').dispatchEvent(new Event('animationend', {bubbles: true}))); assert.equal(grokPosts().length, beforeBusy + 1);
  await moving.emulateMedia({reducedMotion: 'reduce'}); await moving.waitForFunction(() => document.getAnimations().length === 0 && document.documentElement.classList.contains('motion-paused'));
  assert.equal(await moving.locator('#idea').inputValue(), 'Uma cena viva, sem mudar os parâmetros.');
  await moving.emulateMedia({reducedMotion: 'no-preference'}); releaseGrok(); grokGate = null;
  await moving.locator('[data-screen="proposal"]').waitFor({state: 'visible'}); await moving.locator('#grok-use').tap();
  await moving.locator('#duration').fill('5'); await audit('motion-generation-touch', moving);
  waitGate = new Promise(resolve => { releaseWait = resolve; }); admissionGate = new Promise(resolve => { releaseAdmission = resolve; }); const beforeNative = inference().length;
  await moving.locator('#generate').evaluate(button => { button.click(); button.click(); });
  for (let back = 0; back < 3; ++back) await moving.locator('#back').evaluate(button => button.click());
  await moving.locator('[data-screen="review"]').waitFor({state: 'visible'}); assert.equal(await moving.locator('#run-state').textContent(), 'Pronto para revisão');
  assert.equal(await moving.locator('#accept').getAttribute('aria-busy'), 'false'); assert.equal(await moving.locator('#reject').getAttribute('aria-busy'), 'false'); await audit('native-pending-not-review-busy', moving);
  releaseAdmission(); admissionGate = null; await moving.locator('#nav-status').waitFor({state: 'visible'}); await moving.locator('#nav-status').tap(); await moving.locator('#operation').filter({hasText: 'Admitido:'}).waitFor();
  const motionRun = runs[0].id; assert.equal(inference().length, beforeNative + 1); assert.equal(inference().at(-1).body.duration_seconds, 5); assert.equal(requests.filter(item => item.path === `/runs/${motionRun}?wait=true`).length, 1);
  await moving.evaluate(() => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); document.dispatchEvent(new Event('visibilitychange')); });
  assert.equal(await moving.evaluate(() => document.getAnimations().length), 0); assert.equal(inference().length, beforeNative + 1);
  await moving.evaluate(() => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => false}); document.dispatchEvent(new Event('visibilitychange')); mockEvents[0].emit('change', {path: '.data/runs/own/manifest.json', invalidation: true}); });
  releaseWait(); waitGate = null; await moving.locator('#operation').filter({hasText: 'Pronto para revisão'}).waitFor(); await moving.locator('#status-review').tap();
  decisionGate = new Promise(resolve => { releaseDecision = resolve; }); await moving.locator('#accept').tap();
  assert.equal(await moving.locator('#accept').getAttribute('aria-busy'), 'true'); assert.equal(await moving.locator('#reject').getAttribute('aria-busy'), 'false'); await audit('only-actual-review-action-busy', moving);
  releaseDecision(); decisionGate = null; await moving.locator('#run-state').filter({hasText: 'Aceito'}).waitFor(); assert.equal(inference().length, beforeNative + 1);
  await moving.locator('#open-assembly').tap(); await moving.locator('#assemble').tap(); await moving.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor();
  const assembledCount = assemblyPosts().length; await moving.evaluate(() => window.dispatchEvent(new Event('animationend'))); assert.equal(assemblyPosts().length, assembledCount);
  await moving.waitForFunction(() => document.getAnimations().every(animation => animation.playState !== 'running'));
  await capture('assembly-settled', moving, {directory: motionArtifacts, animations: 'allow'});
  const log = await moving.evaluate(() => motionLog); assert.ok(log.every(entry => !entry.unsafe)); assert.ok(log.some(entry => entry.options.duration === 240 && entry.id === 'run-state')); assert.ok(log.some(entry => entry.options.duration === 180)); assert.ok(log.every(entry => (entry.options.delay || 0) <= 80));
  const video = moving.video(); await moving.evaluate(() => window.dispatchEvent(new Event('pagehide'))); assert.equal(await moving.evaluate(() => document.getAnimations().length), 0);
  await liveMotion.close(); Object.assign(motionEvidence, {normal: true, reduced: true, dynamicPreference: true, hiddenCancellation: true, rapidBackDraftPreserved: true, compositorOnlyTargets: true, observed: log, mid, video: await video.path()});
  const fallback = await browser.newContext({viewport: {width: 393, height: 852}, deviceScaleFactor: 2, isMobile: true, hasTouch: true, serviceWorkers: 'block'});
  await fallback.route('**/*', routeRequest); await fallback.addInitScript(mockStartup); await fallback.addInitScript(() => { Element.prototype.animate = undefined; });
  const staticPage = await fallback.newPage(); watch(staticPage); await staticPage.goto('http://h3.mock.invalid/'); await staticPage.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); const fallbackCount = posts().length;
  await staticPage.locator('#nav-new').tap(); await staticPage.locator('#idea').fill('Fallback continua editável'); await staticPage.locator('#use-idea').tap(); assert.equal(await staticPage.locator('#prompt').inputValue(), 'Fallback continua editável'); assert.equal(posts().length, fallbackCount); await audit('motion-unsupported-fallback', staticPage); await fallback.close();
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide'))); assert.equal(await page.evaluate(() => mockEvents.every(event => event.closed)), true);
  assert.deepEqual(exceptions, []); assert.deepEqual(violations, []); assert.deepEqual(await protectedHashes(), beforeHashes);
  if (assemblyMedia) assert.equal(createHash('sha256').update(await readFile(resolve(root, process.env.H3_UI_TEST_ASSEMBLY))).digest('hex'), assemblyHash);
  console.log(`PASS progressive browser: ${requests.length} intercepted requests, ${posts().length} explicit fake POSTs, ${audits.length} bounds audits, zero API/provider/GPU`);
} finally {
  await writeFile(resolve(artifacts, 'report.json'), JSON.stringify({requests, exceptions, violations, consoleMessages, failedRequests, audits, captures, motionEvidence, phone: {width: 393, height: 852, touch: true, scale: 2}, originalFilesProtected: Object.keys(beforeHashes).length, mediaFixture: Boolean(media), assemblyFixture: Boolean(assemblyMedia), assemblyHash, liveAPI: 0, provider: 0, GPU: 0}, null, 2));
  await browser.close();
}
