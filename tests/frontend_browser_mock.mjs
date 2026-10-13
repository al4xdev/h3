// Maintained E2E: every request is intercepted; no API listener, provider or GPU.
import assert from 'node:assert/strict';
import {readFile, mkdir, writeFile, readdir, lstat} from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {resolve, relative} from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
const {chromium} = createRequire(import.meta.url)('playwright');
const root = resolve(new URL('..', import.meta.url).pathname);
const artifacts = resolve(root, '.dumps/tests/ui-app-navigation');
const motionArtifacts = resolve(root, '.dumps/tests/ui-app-motion');
await mkdir(artifacts, {recursive: true});
await mkdir(motionArtifacts, {recursive: true});
const motionEvidence = {};
const assets = Object.fromEntries(await Promise.all(['index.html', 'app.css', 'app.js'].map(async file => [file, await readFile(resolve(root, 'src/h3_backend/web', file))])));
const {alignedFrames} = await import(`data:text/javascript;base64,${Buffer.from(assets['app.js']).toString('base64')}`);
const sourceHashes = Object.fromEntries(Object.entries(assets).map(([file, bytes]) => [file, createHash('sha256').update(bytes).digest('hex')]));
async function currentSourceHashes() { return Object.fromEntries(await Promise.all(Object.keys(assets).map(async file => [file, createHash('sha256').update(await readFile(resolve(root, 'src/h3_backend/web', file))).digest('hex')]))); }
// No traversal into .data/grok, OAuth, or private credentials, even for hashes.
async function protectedHashes() {
  const result = {};
  async function visit(path) {
    const info = await lstat(path); if (info.isSymbolicLink()) return;
    if (info.isDirectory()) { for (const entry of await readdir(path)) await visit(resolve(path, entry)); }
    else if (info.isFile()) { const hash = createHash('sha256'); for await (const block of createReadStream(path)) hash.update(block); result[relative(root, path)] = hash.digest('hex'); }
  }
  // Production trees are opt-in anchors, never an incidental UI-test traversal.
  const paths = ['assets', 'workflows', 'prompts'];
  if (process.env.H3_UI_PROTECT_EXISTING === '1') paths.push('runs', '.data/runs', '.data/inputs', '.data/assemblies');
  for (const path of paths) await visit(resolve(root, path));
  for (const selected of [process.env.H3_UI_TEST_CLIP, process.env.H3_UI_TEST_ASSEMBLY, process.env.H3_UI_TEST_LAST_FRAME].filter(Boolean)) {
    const path = resolve(root, selected), name = relative(root, path);
    assert.ok((['runs/', '.data/runs/'].some(prefix => name.startsWith(prefix)) && name.endsWith('/chunk.mp4')) || name === '.dumps/benchmarks/baseline-three-chunks/benchmark.mp4' || name === '.dumps/tests/ui-app-navigation/fixture-last-frame.png');
    await visit(path);
  }
  return result;
}
const beforeHashes = await protectedHashes();
const image = await readFile(resolve(root, 'assets/dance_reference.png'));
let lastFrame = image;
if (process.env.H3_UI_TEST_LAST_FRAME) {
  const path = resolve(root, process.env.H3_UI_TEST_LAST_FRAME);
  assert.equal(relative(root, path), '.dumps/tests/ui-app-navigation/fixture-last-frame.png');
  const info = await lstat(path); assert.ok(info.isFile() && !info.isSymbolicLink() && info.size <= 20 * 1024 * 1024, 'Selected last frame must be a bounded regular PNG');
  lastFrame = await readFile(path); assert.deepEqual(lastFrame.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  assert.notEqual(createHash('sha256').update(lastFrame).digest('hex'), createHash('sha256').update(image).digest('hex'), 'Capture frame must be distinct from identity');
}
const lastFrameHash = createHash('sha256').update(lastFrame).digest('hex');
let media = null, assemblyMedia = null;
if (process.env.H3_UI_TEST_CLIP) {
  const path = resolve(root, process.env.H3_UI_TEST_CLIP);
  assert.ok(['runs/', '.data/runs/'].some(prefix => relative(root, path).startsWith(prefix)) && path.endsWith('/chunk.mp4'));
  assert.ok((await lstat(path)).size <= 64 * 1024 * 1024, 'UI fixture must remain modest prerecorded encoded bytes');
  media = await readFile(path);
}
if (process.env.H3_UI_TEST_ASSEMBLY) {
  const path = resolve(root, process.env.H3_UI_TEST_ASSEMBLY);
  assert.equal(relative(root, path), '.dumps/benchmarks/baseline-three-chunks/benchmark.mp4');
  assert.ok((await lstat(path)).size <= 64 * 1024 * 1024, 'Assembly fixture must remain modest prerecorded encoded bytes');
  assemblyMedia = await readFile(path);
}
const assemblyHash = assemblyMedia && createHash('sha256').update(assemblyMedia).digest('hex');
const pin = 'grok-4.20-0309-non-reasoning';
const caps = {default_requested_seconds: 8, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125};
const rootID = '11111111-1111-4111-8111-111111111111', endID = '22222222-2222-4222-8222-222222222222', failedID = '44444444-4444-4444-8444-444444444444';
const malicious = '<img src=x onerror="window.hacked=true"> vestido preto & continuidade';
const scene = 'Ela dá um salto. O vestido fica vermelho. <img onerror="window.hacked=true">';
let providerScene = scene;
const original = {source_root: 'assets', path: 'dance_reference.png'};
const references = [{...original, name: 'Original', image_url: '/assets/image?path=dance_reference.png'}, {source_root: 'inputs', path: 'own/original.png', name: malicious, image_url: '/inputs/image?path=own%2Foriginal.png'}, {source_root: 'runs', path: `.data/runs/${rootID}/last_frame.png`, name: 'Último frame', image_url: `/runs/${rootID}/image?name=last_frame.png`}];
const config = {default_prompt: 'Dança com vestido preto.', continuation_prompt: 'Pequeno salto. Vestido vermelho. Termina de costas.', reference_image: 'dance_reference.png', duration_seconds: 8, duration_capabilities: caps, workflow_output_profile: 'final_only', filesystem_events: true, reference_library: true, assembly_enabled: true};
let editor = {system_prompt: 'Preserve ação, roupa, pose e ordem. Responda só com a cena.', model: pin};
const identityHash = createHash('sha256').update(image).digest('hex');
const mkRun = (id, state, parent_id = null, duration = 2.3, prompt = malicious) => ({id, state, parent_id, prompt, decision: ['accepted', 'rejected'].includes(state) ? {accepted: state === 'accepted', at: '2026-10-12T20:00:02Z'} : null, publication_mode: 'atomic_copy_from_comfy_output', seed: 2026101205, duration_seconds: duration, created_at: '2026-10-12T20:00:00Z', updated_at: '2026-10-12T20:00:01Z', references: [{type: 'image', role: 'identity', source_root: 'assets', source: 'dance_reference.png', sha256: identityHash}], input_info: {mode: parent_id ? 'continuation' : 'normal', operation: parent_id ? 'v2v' : 'i2v', continuation: parent_id ? {seed: 2026101205, prompt, duration_seconds: duration, reference_tail_seconds: 3, include_audio: true} : null}, output: {path: `.data/runs/${id}/chunk.mp4`, probe: {streams: [{codec_type: 'video', duration: String(alignedFrames(duration) / 24)}]}}, error: null});
// /runs really is a summary: retry must fetch full detail, not rely on list refs.
const slimRun = run => Object.fromEntries(['id', 'state', 'parent_id', 'prompt', 'seed', 'duration_seconds', 'created_at', 'updated_at', 'error'].map(key => [key, run[key]]).concat([['video_url', ['ready_for_review', 'accepted', 'rejected'].includes(run.state) && run.output.path ? `/runs/${run.id}/video` : null]]));
let runs, assemblies = [], mode = 'normal', grokMode = 'normal', assemblyMode = 'normal', previewMode = 'normal', generated = 0;
let grokGate = null, releaseGrok, waitGate = null, releaseWait, detailGate = null, releaseDetail;
let admissionGate = null, releaseAdmission, decisionGate = null, releaseDecision;
const resetRuns = () => { runs = [mkRun(endID, 'ready_for_review', rootID), mkRun(rootID, 'accepted'), {...mkRun(failedID, 'failed'), error: 'Falha histórica preservada', output: {}}]; };
resetRuns();
const requests = [], exceptions = [], violations = [], consoleMessages = [], failedRequests = [], audits = [], captures = [];
let benignEvidence = false;
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
    const body = request.postDataJSON();
    if (body.continuation_parent_id) { assert.equal(runs.find(run => run.id === body.continuation_parent_id)?.state, 'accepted'); assert.ok(body.reference); assert.equal(previewMode, 'normal'); }
    if (grokGate) await grokGate;
    if (grokMode === 'network') return route.abort('connectionfailed');
    if (grokMode === 'error') return json({detail: 'Imagem não suportada'}, 400);
    return json({text: grokMode === 'oversized' ? 'x'.repeat(12001) : providerScene, model: pin});
  }
  if (path.startsWith('/grok/auth/') || path === '/events') { violations.push(path); return route.abort(); }
  if (/^\/grok\/continuation\/[0-9a-f-]{36}\/last-frame$/.test(path)) {
    assert.equal(method, 'GET'); const parent = runs.find(run => run.id === path.split('/')[3]);
    if (!parent || parent.state !== 'accepted') return json({detail: 'Pai não aceito'}, 409);
    if (previewMode === 'error') return json({detail: 'Prévia do último frame indisponível'}, 409);
    return route.fulfill({contentType: 'image/png', body: lastFrame});
  }
  if (path === '/inputs') {
    if (method === 'POST') { const item = {source_root: 'inputs', path: 'uploaded/original.png', name: 'phone photo.png', image_url: '/inputs/image?path=uploaded%2Foriginal.png'}; references.push(item); return json(item, 201); }
    return json({items: references, total: references.length});
  }
  if (['/assets/image', '/inputs/image'].includes(path) || path.endsWith('/image')) return route.fulfill({contentType: 'image/png', body: image});
  if (path === '/runs') return mode === 'list-error' ? json({detail: 'Leitura indisponível <b>texto</b>'}, 503) : json({items: mode === 'empty' ? [] : runs.map(slimRun), total: mode === 'empty' ? 0 : runs.length});
  if (method === 'POST' && (path === '/runs/i2v' || path.endsWith('/v2v'))) {
    if (mode === 'ambiguous') return route.abort('connectionfailed');
    if (mode === 'conflict') return json({detail: 'Slot ocupado'}, 409);
    if (admissionGate) await admissionGate;
    const body = request.postDataJSON(), id = `00000000-0000-4000-8000-${String(++generated).padStart(12, '0')}`;
    const run = {...mkRun(id, 'queued', path.endsWith('/v2v') ? path.split('/')[2] : null, body.duration_seconds, body.prompt), seed: body.seed, output: {}};
    run.references = run.parent_id ? structuredClone(runs.find(item => item.id === run.parent_id).references) : (body.references || [original]).map(ref => ({type: 'image', role: 'identity', source_root: ref.source_root, source: ref.path, sha256: identityHash}));
    if (run.parent_id) run.input_info.continuation = {...body};
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
    if (assemblyMode === 'read-error') return json({detail: 'Leitura do próprio UUID indisponível'}, 503);
    if (!record) return json({detail: 'ID não publicado'}, 404);
    if (path.endsWith('/video')) return route.fulfill(assemblyMedia ? {contentType: 'video/mp4', body: assemblyMedia} : {status: 204});
    if (assemblyMode === 'read-missing-proof') return json({...record, video_url: null, output: {}});
    return json(record);
  }
  if (path.startsWith('/runs/')) {
    const run = runs.find(item => item.id === path.split('/')[2]); if (!run) return json({detail: 'Run not found'}, 404);
    if (path === `/runs/${rootID}` && detailGate) await detailGate;
    if (path.endsWith('/video')) return route.fulfill(media ? {contentType: 'video/mp4', body: media} : {status: 204});
    if (method === 'POST' && /\/(accept|reject)$/.test(path)) { assert.equal(run.state, 'ready_for_review'); if (mode === 'decision-error') return json({detail: 'Decisão recusada'}, 409); if (decisionGate) await decisionGate; run.state = path.endsWith('/accept') ? 'accepted' : 'rejected'; run.decision = {accepted: run.state === 'accepted', at: '2026-10-12T20:00:02Z'}; return json(run); }
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
  const actions = await target.evaluate(() => [...document.querySelectorAll('[data-screen]:not([hidden]) .screen-actions')].filter(node => node.getClientRects().length).map(node => ({position: getComputedStyle(node).position, bounds: node.getBoundingClientRect().toJSON()})));
  assert.ok(actions.every(action => !['fixed', 'sticky'].includes(action.position)), `${name}: actions must stay in document flow`);
  const overflowAudit = await target.evaluate(() => {
    const editable = node => node.matches('textarea,input,[contenteditable="true"]');
    return [...document.querySelectorAll('body *')].filter(node => node.getClientRects().length && !editable(node)).flatMap(node => {
      const css = getComputedStyle(node), vertical = /auto|scroll/.test(css.overflowY) && node.scrollHeight > node.clientHeight + 1, horizontal = /auto|scroll/.test(css.overflowX) && node.scrollWidth > node.clientWidth + 1;
      return vertical || horizontal ? [{id: node.id, classes: node.className, vertical, horizontal}] : [];
    });
  });
  assert.deepEqual(overflowAudit, [], `${name}: document must be the only scroll owner (native editable excepted)`);
  const header = await target.evaluate(() => ['back', 'settings-open'].map(id => { const node = document.getElementById(id), box = node.getBoundingClientRect(); let ancestor = node.parentElement, transformed = false; while (ancestor) { transformed ||= getComputedStyle(ancestor).transform !== 'none'; ancestor = ancestor.parentElement; } return {id, width: box.width, height: box.height, top: box.top, bottom: box.bottom, transformed, header: Boolean(node.closest('header'))}; }));
  for (const control of header) { assert.ok(control.header && control.width >= 44 && control.height >= 44 && !control.transformed, `${name}: top header touch/transform contract`); assert.ok(control.top >= 0 && control.bottom <= bounds.height, `${name}: sticky header invisible`); }
  bounds.overflowAudit = overflowAudit; bounds.header = header;
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
  // Keep raw XSS assertions out of owner-facing evidence.
  if (!benignEvidence) return;
  const path = resolve(directory, `${name}.png`), size = target.viewportSize();
  // An explicit document-origin clip avoids mobile IME/compositor scroll races.
  await target.screenshot({path, animations, clip: {x: 0, y: 0, width: size.width, height: size.height}}); captures.push(path);
}
async function rootLibrary(target = page) {
  for (let i = 0; i < 80 && !await target.locator('[data-screen="library"]').isVisible(); i++) {
    const token = await target.evaluate(() => history.state?.h3View);
    await target.locator('#back').click();
    await target.waitForFunction(previous => history.state?.h3View !== previous, token);
    await target.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  }
  await target.locator('[data-screen="library"]').waitFor({state: 'visible'});
}
async function beginIdea(target = page) { await rootLibrary(target); await target.locator('#new-mode').click(); await target.locator('[data-screen="context"]').waitFor({state: 'visible'}); }
async function openRun(id) { await rootLibrary(); await page.getByRole('button', {name: new RegExp(id)}).click(); await active('review'); }
async function newIdea(text = 'Uma ideia simples') { await beginIdea(); await active('context'); await page.locator('#idea').fill(text); }
async function settings(target = page) {
  // Locator.click pre-scrolls sticky controls in Chromium; a native visible-header
  // tap preserves the user's document origin instead of testing that automation quirk.
  const gear = await target.locator('#settings-open').boundingBox(), before = await target.evaluate(() => ({scroll: scrollY, focus: document.activeElement.id, touch: navigator.maxTouchPoints > 0}));
  assert.ok(gear && gear.width >= 44 && gear.height >= 44 && gear.y >= 0 && gear.y + gear.height <= target.viewportSize().height);
  if (before.touch) await target.touchscreen.tap(gear.x + gear.width / 2, gear.y + gear.height / 2);
  else await target.mouse.click(gear.x + gear.width / 2, gear.y + gear.height / 2);
  await target.locator('[data-screen="settings"]').waitFor({state: 'visible'}); audits.push({name: 'native-header-gear', before, gear});
}
async function setBlock(duration, seed = null, target = page) {
  const before = posts().length, puts = requests.filter(item => item.method === 'PUT').length;
  await settings(target); assert.equal(await target.locator('#duration').isEnabled(), true);
  if (duration !== null) await target.locator('#duration').fill(duration);
  if (seed !== null) await target.locator('#seed').fill(seed);
  await target.locator('#settings-done').click();
  assert.equal(posts().length, before); assert.equal(requests.filter(item => item.method === 'PUT').length, puts);
}
async function prepare(text = 'Uma ideia simples', duration = '2.3') { await newIdea(text); await page.locator('#use-idea').click(); await active('generation'); await setBlock(duration); }
async function reachable(id, target = page) {
  await target.locator(`#${id}`).evaluate(node => node.scrollIntoView({block: 'center', behavior: 'instant'}));
  const hit = await target.locator(`#${id}`).evaluate(node => { const box = node.getBoundingClientRect(), view = visualViewport; return {inside: box.top >= view.offsetTop && box.bottom <= view.offsetTop + view.height, hit: document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)?.closest('button')?.id}; });
  assert.ok(hit.inside); assert.equal(hit.hit, id);
}
async function emitHints() { await page.evaluate(() => { mockEvents[0]?.emit('open'); for (let i = 0; i < 12; i++) mockEvents[0]?.emit('change', {path: '.data/runs/own/manifest.json', invalidation: true}); }); await page.locator('#notice').filter({hasText: /Biblioteca atualizada|Resultado anterior incerto/}).waitFor(); }
async function settingsRoundTrip(origin, target = page) {
  // Test prior non-editable origin focus without requiring a software keyboard.
  const focusID = {library: 'new-mode', context: 'use-idea', proposal: 'edit-idea', generation: 'screen-title', review: 'open-assembly', continuation: 'continue-idea', assembly: 'assembly-refresh'}[origin];
  await target.locator(`#${focusID}`).evaluate(node => node.focus({preventScroll: true}));
  const snapshot = await target.evaluate(() => ({scroll: scrollY, focus: document.activeElement.id, draft: ['idea', 'prompt', 'seed', 'duration', 'reference', 'grok-result'].map(id => [id, document.getElementById(id).value])}));
  const before = posts().length, puts = requests.filter(item => item.method === 'PUT').length;
  const nextDraft = origin === 'continuation' && await target.locator('#continue-idea').isEnabled() && /Pai aceito: [0-9a-f-]{36}/.test(await target.locator('#continuation-parent').textContent());
  const editable = (['context', 'proposal', 'generation'].includes(origin) || nextDraft) && await target.locator('#generate').isEnabled();
  await settings(target);
  if (await target.locator('#duration').isEnabled()) await target.locator('#duration').press('Enter');
  if (!editable) { assert.ok(await target.locator('#duration').isDisabled() || await target.locator('#duration').getAttribute('readonly') !== null); assert.ok(await target.locator('#seed').isDisabled() || await target.locator('#seed').getAttribute('readonly') !== null); }
  await target.locator('#settings-done').click(); await target.locator(`[data-screen="${origin}"]`).waitFor({state: 'visible'});
  await target.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const restored = await target.evaluate(() => ({scroll: scrollY, focus: document.activeElement.id, draft: ['idea', 'prompt', 'seed', 'duration', 'reference', 'grok-result'].map(id => [id, document.getElementById(id).value])}));
  audits.push({name: `settings-roundtrip-${origin}`, snapshot, restored});
  assert.deepEqual(restored.draft, snapshot.draft); assert.equal(restored.focus, snapshot.focus); assert.ok(Math.abs(restored.scroll - snapshot.scroll) <= 2, `${origin}: prior scroll ${snapshot.scroll}, restored ${restored.scroll}`);
  assert.equal(posts().length, before); assert.equal(requests.filter(item => item.method === 'PUT').length, puts);
}
async function cardGesture(target, name) {
  await target.evaluate(() => scrollTo(0, 0));
  const card = target.locator('.clip-card').first(); await card.scrollIntoViewIfNeeded();
  const box = await card.boundingBox(), before = await target.evaluate(() => ({y: scrollY, list: document.getElementById('library').scrollTop, screen: document.querySelector('[data-screen]:not([hidden])').dataset.screen})), count = posts().length;
  const cdp = await target.context().newCDPSession(target), x = Math.round(box.x + box.width / 2), y = Math.round(Math.min(box.y + box.height / 2, target.viewportSize().height - 100));
  const point = currentY => ({x, y: currentY, id: 1, radiusX: 3, radiusY: 3, force: 1});
  await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [point(y)]});
  for (let step = 1; step <= 8; step++) { await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [point(y - step * 35)]}); await target.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve))); }
  await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
  await target.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); await cdp.detach();
  const after = await target.evaluate(() => ({y: scrollY, list: document.getElementById('library').scrollTop, screen: document.querySelector('[data-screen]:not([hidden])').dataset.screen, owner: document.scrollingElement === document.documentElement, max: document.scrollingElement.scrollHeight - innerHeight}));
  audits.push({name, touchGesture: 'CDP real touch drag', before, after, card: box, start: {x, y}, end: {x, y: y - 280}});
  assert.ok(after.y > before.y + 30, `${name}: touch on a card scrolls document (${before.y}→${after.y}, max ${after.max})`); assert.equal(after.list, before.list); assert.equal(after.screen, 'library'); assert.equal(posts().length, count); assert.equal(after.owner, true);
  await audit(`${name}-sticky`, target); await reachable('new-mode', target);
}
try {
  await ready(); await active('library'); assert.equal(posts().length, 0); assert.equal(await page.locator('#player').getAttribute('src'), null);
  assert.equal(await page.locator('#nav-library,#nav-new').count(), 0);
  for (const id of ['new-mode', 'refresh', 'nav-status']) assert.equal(await page.locator(`#${id}`).evaluate(node => Boolean(node.closest('[data-screen="library"]'))), true);
  assert.ok(await page.evaluate(() => startupOrder.indexOf('SSE open') < startupOrder.indexOf('/inputs?limit=50&offset=0')));
  assert.equal(await page.evaluate(() => navigator.maxTouchPoints > 0 && devicePixelRatio === 2), true);
  await capture('phone-library');
  await newIdea('ela dá um salto e o vestido fica vermelho');
  assert.equal(await page.locator('#grok-model').inputValue(), pin); assert.equal(await page.locator('#grok-model').getAttribute('readonly'), '');
  await settings(); await page.locator('#grok-system').fill('Detalhe sem inventar identidade.');
  const enterCount = posts().length; await page.locator('#grok-model').press('Enter'); assert.equal(posts().length, enterCount);
  await page.locator('#grok-save').click(); await page.locator('#grok-config-status').filter({hasText: 'Configuração salva'}).waitFor();
  await page.locator('#settings-done').click();
  await page.locator('#reference').selectOption('1'); await focusedAudit('idea'); await capture('phone-context');
  const beforeGrok = inference().length;
  await page.locator('#grok-detail').evaluate(button => { button.click(); button.click(); }); await active('proposal');
  assert.equal(grokPosts().length, 1); assert.equal(inference().length, beforeGrok); assert.equal(requests.filter(item => item.path.startsWith('/grok/continuation/')).length, 0, 'root editor must not request a parent frame');
  assert.deepEqual(grokPosts().at(-1).body, {system_prompt: editor.system_prompt, prompt: 'ela dá um salto e o vestido fica vermelho', model: pin, reference: {source_root: 'inputs', path: 'own/original.png'}});
  assert.equal(await page.locator('#idea').inputValue(), 'ela dá um salto e o vestido fica vermelho'); assert.equal(await page.locator('#grok-result').inputValue(), scene);
  await page.locator('#grok-result').fill('   '); await page.locator('#grok-use').click(); await page.locator('#proposal-error').filter({hasText: 'não devolveu'}).waitFor(); assert.equal(inference().length, beforeGrok); await page.locator('#grok-result').fill(`${scene}\nEla termina de costas.`); await focusedAudit('grok-result'); await capture('phone-proposal');
  await page.locator('#grok-use').tap(); await active('generation'); assert.equal(inference().length, beforeGrok);
  await settings(); await page.locator('#duration').tap(); await page.locator('#duration').fill('5'); await page.locator('#seed').fill('42'); await page.locator('#duration-preview').filter({hasText: '124 frames'}).waitFor();
  await page.locator('#duration').press('Enter'); assert.equal(inference().length, beforeGrok);
  await focusedAudit('duration'); await capture('phone-settings-block'); await page.locator('#settings-done').click(); await capture('phone-generation-5s');
  // Back and mode/selection changes retain idea, edited proposal, duration and seed.
  await page.locator('#back').click(); await active('proposal'); assert.match(await page.locator('#grok-result').inputValue(), /termina de costas/);
  await page.locator('#grok-use').click(); assert.equal(await page.locator('#duration').inputValue(), '5'); assert.equal(await page.locator('#seed').inputValue(), '42');
  waitGate = new Promise(resolve => { releaseWait = resolve; });
  await page.locator('#generate').evaluate(button => { button.click(); button.click(); }); await page.locator('#operation').filter({hasText: 'Admitido:'}).waitFor();
  assert.equal(inference().length, beforeGrok + 1); assert.equal(inference().at(-1).body.duration_seconds, 5);
  const admitted = runs[0].id; assert.equal(requests.filter(item => item.path === `/runs/${admitted}?wait=true`).length, 1);
  await capture('phone-status'); await settingsRoundTrip('generation'); const countPending = posts().length; await rootLibrary(); await active('library');
  await page.evaluate(() => mockEvents[0].emit('change', {path: '.data/runs/own/manifest.json', invalidation: true})); assert.equal(posts().length, countPending);
  await page.locator('#nav-status').click(); await active('generation'); assert.equal(posts().length, countPending); releaseWait(); waitGate = null; await page.locator('#operation').filter({hasText: `Pronto para revisão · ${admitted}`}).waitFor(); await page.locator('#status-review').click(); await active('review');
  assert.match(await page.locator('#review-duration').textContent(), /Solicitada 5 s.*124 frames.*verificada 5,167 s/);
  if (media) { await page.waitForFunction(() => document.getElementById('player').videoWidth > 0); await page.locator('#player').evaluate(async video => { await video.play(); }); await page.waitForFunction(() => document.getElementById('player').currentTime > 0.05); await page.locator('#player').evaluate(video => video.pause()); }
  await capture('phone-review'); mode = 'decision-error'; await page.locator('#accept').click(); await page.locator('#review-status').filter({hasText: 'Decisão não confirmada'}).waitFor(); assert.equal(await page.locator('#accept').isEnabled(), true); await active('review'); mode = 'normal'; const beforeAccept = posts().length; await page.locator('#accept').click(); await page.locator('#run-state').filter({hasText: 'Aceito'}).waitFor(); await active('review'); assert.equal(posts().length, beforeAccept + 1);
  await page.waitForFunction(() => document.getElementById('accept').getAttribute('aria-busy') === 'false');
  const acceptedParentBeforeSettings = structuredClone(runs.find(run => run.id === admitted)); await settingsRoundTrip('review');
  await page.locator('#continue-mode').click(); await active('continuation'); await setBlock('4', '77'); assert.deepEqual(runs.find(run => run.id === admitted), acceptedParentBeforeSettings); await settings(); assert.match(await page.locator('#settings-draft-note').textContent(), /rascunho.*não alteram o pai publicado/i); await page.locator('#settings-done').click(); await settingsRoundTrip('continuation'); await capture('phone-continuation'); await page.locator('#continue-idea').click(); await active('context');
  assert.equal(await page.locator('#reference').isDisabled(), true); await page.locator('#idea').fill('Continua de costas e vira de frente.');
  await page.locator('#last-frame-preview').waitFor({state: 'visible'}); await page.waitForFunction(() => document.getElementById('last-frame-preview').naturalWidth > 0); assert.equal(await page.locator('#last-frame-preview').getAttribute('src'), `/grok/continuation/${admitted}/last-frame`); assert.equal(await page.locator('#reference-preview').isVisible(), true);
  await page.locator('#grok-detail').click(); await active('proposal'); assert.deepEqual(grokPosts().at(-1).body, {system_prompt: editor.system_prompt, prompt: 'Continua de costas e vira de frente.', model: pin, reference: {source_root: 'inputs', path: 'own/original.png'}, continuation_parent_id: admitted});
  await page.locator('#grok-use').click(); await setBlock('10', '9007199254740991');
  await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'Pronto para revisão'}).waitFor();
  assert.deepEqual(inference().at(-1).body, {seed: Number.MAX_SAFE_INTEGER, prompt: scene, duration_seconds: 10, reference_tail_seconds: 3, include_audio: true}); assert.equal(inference().at(-1).path, `/runs/${admitted}/v2v`);
  await page.locator('#status-review').click(); await active('review'); await page.locator('#reject').click(); await page.locator('#run-state').filter({hasText: 'Rejeitado'}).waitFor(); assert.equal(await page.locator('#continue-mode').isDisabled(), true);
  const rejectedChild = structuredClone(runs[0]), retryCount = posts().length;
  await page.locator('#retry-mode').click(); await active('generation');
  assert.equal(posts().length, retryCount); assert.equal(await page.locator('#prompt').inputValue(), rejectedChild.prompt); assert.equal(await page.locator('#duration').inputValue(), '10'); assert.equal(await page.locator('#seed').inputValue(), String(Number.MAX_SAFE_INTEGER));
  await page.locator('#retry-context').filter({hasText: rejectedChild.id}).waitFor();
  await page.locator('#prompt').fill('Rascunho retry filho editado'); await rootLibrary(); await openRun(rejectedChild.id); await page.locator('#retry-mode').click(); await active('generation'); assert.equal(await page.locator('#prompt').inputValue(), 'Rascunho retry filho editado'); assert.equal(posts().length, retryCount);
  await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'Pronto para revisão'}).waitFor();
  assert.equal(inference().at(-1).path, `/runs/${admitted}/v2v`); assert.deepEqual(inference().at(-1).body, {seed: Number.MAX_SAFE_INTEGER, prompt: 'Rascunho retry filho editado', duration_seconds: 10, reference_tail_seconds: 3, include_audio: true});
  assert.deepEqual(runs.find(run => run.id === rejectedChild.id), rejectedChild); assert.notEqual(runs[0].id, rejectedChild.id); assert.equal(runs[0].state, 'ready_for_review');
  await page.locator('#status-review').click(); await page.locator('#accept').click(); await page.locator('#run-state').filter({hasText: 'Aceito'}).waitFor(); assert.deepEqual(runs.find(run => run.id === rejectedChild.id), rejectedChild);
  // Parent-keyed continuation drafts survive visiting another parent and the new scene.
  await openRun(rootID); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); await page.locator('#idea').fill('Rascunho do pai original'); await page.locator('#use-idea').click(); await setBlock('3');
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
  await page.locator('#grok-status').filter({hasText: 'contexto mudou'}).waitFor(); const lateBefore = inference().length; await beginIdea(); await page.locator('#show-proposal').click();
  assert.equal(await page.locator('#grok-result').inputValue(), 'Minha proposta editada deve sobreviver ao retorno atrasado.'); assert.equal(await page.locator('#idea').inputValue(), 'Pedido com uma proposta em edição');
  await page.locator('#late-proposal-details summary').click(); assert.equal(await page.locator('#late-proposal').inputValue(), scene); assert.match(await page.locator('#late-proposal-context').textContent(), /assets.*dance_reference/); const beforeAdopt = posts().length; await page.locator('#use-late-proposal').click(); assert.equal(await page.locator('#grok-result').inputValue(), scene); assert.equal(inference().length, lateBefore); assert.equal(posts().length, beforeAdopt); await page.locator('#use-late-proposal').evaluate(button => button.click()); assert.equal(posts().length, beforeAdopt); assert.equal(await page.locator('#grok-result').inputValue(), scene); assert.deepEqual({chosen: await page.locator('#prompt').inputValue(), duration: await page.locator('#duration').inputValue(), seed: await page.locator('#seed').inputValue(), reference: await page.locator('#reference').inputValue()}, editedOrigin); await page.locator('#edit-idea').click();
  // No form submit from hidden screens, navigation, SSE, resize or browser history.
  const noPost = posts().length; await page.locator('#create-form').evaluate(form => form.dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}))); await emitHints(); await page.evaluate(() => window.dispatchEvent(new PopStateEvent('popstate'))); assert.equal(posts().length, noPost);
  await openRun(rootID); const source = await page.locator('#player').getAttribute('src'), loads = await page.evaluate(() => mediaLoads); await emitHints(); assert.equal(await page.locator('#player').getAttribute('src'), source); assert.equal(await page.evaluate(() => mediaLoads), loads);
  await openRun(failedID); assert.equal(await page.locator('#player').isHidden(), true); assert.equal(await page.locator('#accept').isDisabled(), true); await capture('phone-failed');
  // Stale library detail cannot open the wrong clip after a newer selection.
  await rootLibrary(); detailGate = new Promise(resolve => { releaseDetail = resolve; }); await page.locator('.clip-card').filter({hasText: rootID.slice(0, 8)}).click(); await page.locator('.clip-card').filter({hasText: endID.slice(0, 8)}).click(); await active('review'); releaseDetail(); detailGate = null; assert.match(await page.locator('#metadata').textContent(), new RegExp(endID));
  await page.locator('.metadata summary').click(); assert.equal(await page.locator('#run-prompt').textContent(), malicious); assert.equal(await page.locator('#run-prompt img').count(), 0); assert.equal(await page.evaluate(() => Boolean(window.hacked)), false);
  // Assembly is its own explicit action and read-only same-UUID recovery.
  await page.locator('#open-assembly').click(); await active('assembly'); const nativeBeforeAssembly = inference().length;
  await page.locator('#assemble').evaluate(button => { button.click(); button.click(); }); await page.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor(); const ownID = new URL(page.url()).searchParams.get('assembly');
  assert.equal(await page.evaluate(() => uuidDraws), 1); assert.equal(new URL(page.url()).searchParams.get('other'), 'keep'); assert.equal(new URL(page.url()).hash, '#viewer'); assert.equal(await page.locator('#run-state').textContent(), 'Pronto para revisão'); assert.equal(await page.locator('#assembly-label').textContent(), 'Montagem de prévia — revisão pendente'); assert.equal(inference().length, nativeBeforeAssembly);
  if (assemblyMedia) { await page.waitForFunction(() => document.getElementById('assembly-player').videoWidth > 0); await page.locator('#assembly-player').evaluate(async video => { await video.play(); }); await page.waitForFunction(() => document.getElementById('assembly-player').currentTime > 0.05); await page.locator('#assembly-player').evaluate(video => video.pause()); }
  await capture('phone-assembly-preview'); const assemblyBeforeReload = assemblyPosts().length; await page.reload(); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); await active('assembly'); assert.equal(assemblyPosts().length, assemblyBeforeReload); assert.equal(new URL(page.url()).searchParams.get('assembly'), ownID);
  await page.locator('#assembly-refresh').click(); await page.locator('#assembly-status').filter({hasText: 'Apenas metadados relidos'}).waitFor(); assert.equal(assemblyPosts().length, assemblyBeforeReload);
  await rootLibrary(); await openRun(endID); await page.locator('#accept').click(); await page.locator('#run-state').filter({hasText: 'Aceito'}).waitFor(); assert.equal(assemblyPosts().length, assemblyBeforeReload); await page.locator('#open-assembly').click(); await page.locator('#assemble').click(); await page.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor(); assert.notEqual(new URL(page.url()).searchParams.get('assembly'), ownID); assert.equal(await page.locator('#assembly-label').textContent(), 'Montagem da sequência aceita');
  await capture('phone-assembly-accepted');
  // Uncertain CPU publication never invents/reposts an ID on read, reload or navigation.
  resetRuns(); assemblies = []; assemblyMode = 'lost'; await ready(); await openRun(endID); await page.locator('#open-assembly').click(); await page.locator('#assemble').click(); await page.locator('#assembly-status').filter({hasText: 'Resultado incerto'}).waitFor(); const lostID = new URL(page.url()).searchParams.get('assembly'), lostCount = assemblyPosts().length; assert.equal(await page.locator('#assemble').isDisabled(), true);
  await page.locator('#assembly-refresh').click(); await page.locator('#assembly-status').filter({hasText: 'Apenas metadados relidos'}).waitFor(); await page.reload(); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); assert.equal(assemblyPosts().length, lostCount); assert.equal(new URL(page.url()).searchParams.get('assembly'), lostID);
  assemblyMode = 'normal'; const missing = '99999999-9999-4999-8999-999999999999'; await ready(`http://h3.mock.invalid/?assembly=${missing}`); await active('assembly'); assert.equal(await page.locator('#assemble').isDisabled(), true); await capture('phone-assembly-missing');
  const missingBefore = posts().length; await page.locator('#assembly-refresh').click(); await rootLibrary(); assert.equal(new URL(page.url()).searchParams.get('assembly'), missing); assert.equal(posts().length, missingBefore); await newIdea('Rascunho preservado durante montagem incerta'); await page.locator('#use-idea').click(); await active('generation'); assert.equal(await page.locator('#generate').isDisabled(), true, 'missing assembly proof fences native generation, not draft viewing'); assert.equal(posts().length, missingBefore); assert.equal(new URL(page.url()).searchParams.get('assembly'), missing); await rootLibrary();
  for (const brokenRead of ['read-error', 'read-missing-proof']) {
    resetRuns(); const lockedRetryID = '33333333-3333-4333-8333-333333333333'; runs.unshift({...mkRun(lockedRetryID, 'interrupted'), output: {}}); const id = '88888888-8888-4888-8888-888888888888'; assemblies = [{id, end_run_id: endID, state: 'completed', mode: 'preview', request_sha256: 'a'.repeat(64), output_sha256: 'b'.repeat(64), frames: 168, fps: '24/1', video_url: `/assemblies/${id}/video`, output: {path: `.data/assemblies/${id}/video.mp4`}}]; assemblyMode = brokenRead; const count = posts().length;
    await ready(`http://h3.mock.invalid/?assembly=${id}&other=keep#viewer`); await active('assembly'); await page.locator('#assembly-status').filter({hasText: /incert|não|indisponível|Erro|erro/i}).waitFor(); assert.equal(await page.locator('#assemble').isDisabled(), true); assert.equal(posts().length, count); await page.locator('#assembly-refresh').click(); await rootLibrary(); assert.equal(new URL(page.url()).searchParams.get('assembly'), id); assert.equal(new URL(page.url()).searchParams.get('other'), 'keep'); assert.equal(new URL(page.url()).hash, '#viewer'); assert.equal(posts().length, count); await newIdea('Rascunho consultável sem replay da montagem'); await page.locator('#use-idea').click(); await active('generation'); assert.equal(await page.locator('#generate').isDisabled(), true, `${brokenRead}: uncertainty still fences native admission`); await settingsRoundTrip('generation'); assert.equal(posts().length, count); assert.equal(new URL(page.url()).searchParams.get('assembly'), id); assert.equal(new URL(page.url()).searchParams.get('other'), 'keep'); assert.equal(new URL(page.url()).hash, '#viewer'); await rootLibrary(); await openRun(lockedRetryID); assert.equal(await page.locator('#retry-mode').isDisabled(), true, `${brokenRead}: no distinct retry while an intent remains unresolved`); assert.equal(posts().length, count); await rootLibrary();
  }
  assemblyMode = 'normal';
  // Explicit refuses are recoverable, uncertain inference is not, even after navigation/SSE.
  mode = 'conflict'; await ready(); await prepare('Recusa explícita', '3'); await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'HTTP 409'}).waitFor(); assert.equal(await page.locator('#generate').isEnabled(), true);
  mode = 'ambiguous'; await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'Resultado incerto'}).waitFor(); const uncertainCount = inference().length; await newIdea('Rascunho mantido após incerteza'); await page.locator('#use-idea').click(); assert.equal(await page.locator('#generate').isDisabled(), true); await emitHints(); assert.equal(inference().length, uncertainCount); await capture('phone-native-uncertain');
  mode = 'normal'; grokMode = 'network'; await ready(); await newIdea('Grok incerto'); await page.locator('#grok-detail').click(); await page.locator('#grok-status').filter({hasText: 'Resultado incerto'}).waitFor(); const uncertainGrok = grokPosts().length; await rootLibrary(); await newIdea('Outra navegação'); assert.equal(await page.locator('#grok-detail').isDisabled(), true); await emitHints(); assert.equal(grokPosts().length, uncertainGrok);
  grokMode = 'error'; await ready(); await newIdea('Imagem recusada'); await page.locator('#grok-detail').click(); await page.locator('#grok-status').filter({hasText: 'HTTP 400'}).waitFor(); assert.equal(await page.locator('#idea').inputValue(), 'Imagem recusada'); assert.equal(await page.locator('#grok-detail').isEnabled(), true);
  grokMode = 'oversized'; await page.locator('#grok-detail').click(); await page.locator('#grok-status').filter({hasText: 'sem truncar'}).waitFor(); assert.equal(await page.locator('#idea').inputValue(), 'Imagem recusada');
  grokMode = 'editor-error'; await ready(); await prepare('Sem editor', '2.8'); assert.equal(await page.locator('#generate').isEnabled(), true); grokMode = 'normal';
  delete config.duration_capabilities; config.duration_seconds = 2.3; await ready(); await newIdea(); await page.locator('#use-idea').click(); assert.equal(await page.locator('#duration').getAttribute('readonly'), ''); assert.match(await page.locator('#duration-policy').textContent(), /legado/);
  config.duration_capabilities = {...caps, max_frames: 240}; await ready(); assert.equal(await page.locator('#new-mode').isDisabled(), true); assert.equal(await page.locator('#generate').isDisabled(), true);
  config.duration_capabilities = caps; config.duration_seconds = 8; config.assembly_enabled = false; delete config.filesystem_events; delete config.reference_library; const disabledAssemblyReads = requests.filter(item => item.path.startsWith('/assemblies')).length; await ready(); assert.equal(await page.evaluate(() => mockEvents.length), 0); assert.equal(requests.filter(item => item.path.startsWith('/assemblies')).length, disabledAssemblyReads);
  config.assembly_enabled = true; config.filesystem_events = true; config.reference_library = true; mode = 'empty'; await ready(); await capture('phone-empty'); mode = 'list-error'; await ready(); assert.equal(await page.locator('#notice b').count(), 0); await capture('phone-api-error'); mode = 'normal';
  runs = Array.from({length: 12}, (_, index) => mkRun(`10000000-0000-4000-8000-${String(index).padStart(12, '0')}`, 'accepted', null, 2.3, malicious.repeat(30))); await ready();
  for (const [width, height] of [[393, 852], [320, 852], [640, 852], [852, 393], [1440, 1000]]) {
    const count = posts().length; await page.setViewportSize({width, height}); await audit(`library-${width}`); assert.equal(posts().length, count); if (height === 852 && width <= 640) await cardGesture(page, `reduced-card-scroll-${width}`);
    const cards = await page.locator('.clip-card').evaluateAll(nodes => nodes.map(node => { const box = node.getBoundingClientRect(); return {shrink: getComputedStyle(node).flexShrink, children: [...node.children].map(child => { const rect = child.getBoundingClientRect(); return rect.top >= box.top - 1 && rect.bottom <= box.bottom + 1; })}; })); assert.equal(cards.length, 12); assert.ok(cards.every(card => card.shrink === '0' && card.children.every(Boolean))); await capture(`library-${width}`);
    await prepare('Mobile parâmetros', '10'); await audit(`generation-${width}`); await reachable('generate'); await capture(`generation-${width}`); await rootLibrary();
  }
  const desktop = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce', serviceWorkers: 'block'}); await desktop.route('**/*', routeRequest); await desktop.addInitScript(mockStartup); const desktopPage = await desktop.newPage(); watch(desktopPage); await desktopPage.goto('http://h3.mock.invalid/'); await desktopPage.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); await audit('desktop-real-context', desktopPage); await desktop.close();
  // Owner-facing evidence is a separate benign fixture set, not XSS regression copy.
  // Root retry must isolate a dirty new draft and preserve the original decision.
  resetRuns(); runs.unshift(mkRun('33333333-3333-4333-8333-333333333333', 'ready_for_review', null, 5, 'Cena root registrada para nova tentativa.'));
  await ready(); await newIdea('Meu rascunho novo independente'); await setBlock('3', '87');
  const rejectedRootID = runs[0].id; await openRun(rejectedRootID); await page.locator('#reject').click(); await page.locator('#run-state').filter({hasText: 'Rejeitado'}).waitFor(); const rootRecord = structuredClone(runs.find(run => run.id === rejectedRootID)), rootBefore = posts().length;
  await page.locator('#retry-mode').click(); await active('generation'); assert.equal(posts().length, rootBefore); assert.equal(await page.locator('#prompt').inputValue(), rootRecord.prompt); assert.equal(await page.locator('#duration').inputValue(), '5');
  await settingsRoundTrip('generation'); await page.locator('#prompt').fill('Retry root editado'); await newIdea('Meu rascunho novo independente'); assert.equal(await page.locator('#duration').inputValue(), '3'); assert.equal(await page.locator('#seed').inputValue(), '87');
  await openRun(rejectedRootID); await page.locator('#retry-mode').click(); await active('generation'); assert.equal(await page.locator('#prompt').inputValue(), 'Retry root editado'); assert.equal(posts().length, rootBefore);
  await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'Pronto para revisão'}).waitFor(); assert.equal(inference().at(-1).path, '/runs/i2v'); assert.deepEqual(inference().at(-1).body, {seed: rootRecord.seed, prompt: 'Retry root editado', duration_seconds: 5, references: [original]}); assert.deepEqual(runs.find(run => run.id === rejectedRootID), rootRecord); assert.notEqual(runs[0].id, rejectedRootID); assert.equal(runs[0].state, 'ready_for_review');
  // Interrupted sources can lack output, but their final admitted prompt is authoritative.
  for (const parent_id of [null, rootID]) {
    resetRuns(); const literal = '  Prompt FINAL melhorado pelo Grok.\nPreserve roupa e pose. <img src=x onerror="window.hacked=true">  ', interrupted = {...mkRun('33333333-3333-4333-8333-333333333333', 'interrupted', parent_id, parent_id ? 10 : 5, literal), output: {}, error: 'Interrupção histórica confirmada'}; runs.unshift(interrupted); const old = structuredClone(interrupted); await ready(); await newIdea('Ideia crua independente — não usar no retry'); await openRun(old.id);
    assert.equal(await page.locator('#run-prompt').isVisible(), true); assert.equal(await page.locator('#run-prompt').textContent(), literal); assert.equal(await page.locator('#run-prompt img').count(), 0); const before = posts().length, editorBefore = grokPosts().length;
    await page.locator('#retry-mode').evaluate(button => { button.click(); button.click(); }); await active('generation'); assert.equal(await page.locator('#prompt').inputValue(), literal); assert.equal(posts().length, before); assert.equal(grokPosts().length, editorBefore); assert.deepEqual(runs.find(run => run.id === old.id), old);
    await page.locator('#prompt').fill(`${literal}\nMinha edição preservada.`); await page.locator('#back').click(); await active('review'); assert.equal(await page.locator('#run-prompt').isVisible(), true); assert.equal(await page.locator('#run-prompt').textContent(), literal); await page.locator('#retry-mode').click(); await active('generation'); assert.equal(await page.locator('#prompt').inputValue(), `${literal}\nMinha edição preservada.`); await settingsRoundTrip('generation'); assert.equal(posts().length, before);
    await page.locator('#generate').click(); await page.locator('#operation').filter({hasText: 'Pronto para revisão'}).waitFor(); assert.equal(inference().at(-1).path, parent_id ? `/runs/${parent_id}/v2v` : '/runs/i2v'); assert.deepEqual(inference().at(-1).body, {seed: old.seed, prompt: `${literal}\nMinha edição preservada.`, duration_seconds: old.duration_seconds, ...(parent_id ? {reference_tail_seconds: 3, include_audio: true} : {references: [original]})}); assert.notEqual(runs[0].id, old.id); assert.equal(runs[0].state, 'ready_for_review'); assert.deepEqual(runs.find(run => run.id === old.id), old); assert.equal(grokPosts().length, editorBefore);
  }
  // Missing CPU preview blocks only the two-image editor, not explicit manual v2v preparation.
  resetRuns(); previewMode = 'error'; await ready(); await openRun(rootID); const missingPreviewPosts = posts().length, missingPreview = page.waitForResponse(response => new URL(response.url()).pathname === `/grok/continuation/${rootID}/last-frame`);
  await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); await missingPreview; await page.waitForFunction(() => document.getElementById('grok-detail').disabled); assert.equal(await page.locator('#use-idea').isEnabled(), true); await page.locator('#idea').fill('Instrução manual sem prévia'); await page.locator('#use-idea').click(); await active('generation'); assert.equal(await page.locator('#generate').isEnabled(), true); assert.equal(posts().length, missingPreviewPosts); previewMode = 'normal';
  // Same identity across two parents still cannot make a late editor response current.
  resetRuns(); Object.assign(runs.find(run => run.id === endID), {state: 'accepted', decision: {accepted: true, at: '2026-10-12T20:00:02Z'}}); await ready(); await openRun(rootID); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); await page.waitForFunction(() => document.getElementById('last-frame-preview').naturalWidth > 0); await page.locator('#idea').fill('Pedido visual do pai A'); grokGate = new Promise(resolve => { releaseGrok = resolve; }); const parentGrokBefore = grokPosts().length, parentNativeBefore = inference().length;
  await page.locator('#grok-detail').click(); await openRun(endID); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); await page.locator('#idea').fill('Rascunho visual do pai B'); releaseGrok(); grokGate = null; await page.locator('#grok-status').filter({hasText: 'contexto mudou'}).waitFor(); await active('context'); assert.equal(await page.locator('#idea').inputValue(), 'Rascunho visual do pai B'); assert.equal(grokPosts().length, parentGrokBefore + 1); assert.equal(grokPosts().at(-1).body.continuation_parent_id, rootID); assert.deepEqual(grokPosts().at(-1).body.reference, original); assert.equal(inference().length, parentNativeBefore);
  // Unsupported historical records may never silently substitute defaults.
  const cases = [
    ['missing refs', run => { run.references = []; }],
    ['unsafe ref', run => { run.references[0].source = '../private.png'; }],
    ['multiple refs', run => { run.references.push({...run.references[0]}); }],
    ['missing hash', run => { delete run.references[0].sha256; }],
    ['missing operation', run => { delete run.input_info; }],
    ['duration precision', run => { run.duration_seconds = 2.345; run.input_info.continuation.duration_seconds = 2.345; }],
    ['tail two', run => { run.input_info.continuation.reference_tail_seconds = 2; }],
    ['audio false', run => { run.input_info.continuation.include_audio = false; }],
    ['missing continuation', run => { delete run.input_info.continuation; }],
    ['parent rejected', (run, parent) => { parent.state = 'rejected'; }],
  ];
  for (const [name, corrupt] of cases) {
    resetRuns(); const bad = mkRun('33333333-3333-4333-8333-333333333333', 'rejected', rootID); corrupt(bad, runs.find(run => run.id === rootID)); runs.unshift(bad); await ready(); await openRun(bad.id); const count = posts().length; await page.locator('#retry-mode').click(); await page.locator('#retry-status').filter({hasText: /\S/}).waitFor(); await active('review'); assert.equal(posts().length, count, `${name}: no POST`); assert.ok((await page.locator('#retry-status').textContent()).trim().length > 10, `${name}: explicit reason`);
  }
  resetRuns(); const delayedRetry = mkRun('33333333-3333-4333-8333-333333333333', 'rejected', rootID); runs.unshift(delayedRetry); await ready(); await openRun(delayedRetry.id); detailGate = new Promise(resolve => { releaseDetail = resolve; }); const delayedBefore = posts().length;
  const parentRequest = page.waitForRequest(request => new URL(request.url()).pathname === `/runs/${rootID}`); await page.locator('#retry-mode').click(); await parentRequest; await rootLibrary(); await page.getByRole('button', {name: new RegExp(endID)}).click(); await active('review'); const parentResponse = page.waitForResponse(response => new URL(response.url()).pathname === `/runs/${rootID}`); releaseDetail(); detailGate = null; await parentResponse; await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); await active('review'); assert.match(await page.locator('#metadata').textContent(), new RegExp(endID)); assert.equal(posts().length, delayedBefore);
  benignEvidence = true;
  runs = Array.from({length: 12}, (_, index) => mkRun(`10000000-0000-4000-8000-${String(index).padStart(12, '0')}`, 'accepted', index ? `10000000-0000-4000-8000-${String(index - 1).padStart(12, '0')}` : null, 2.3, 'Ela dança com a referência original.'));
  await ready(); await openRun(runs.at(-1).id); for (const [width, height] of [[393, 852], [320, 852], [640, 852], [852, 393], [1440, 1000]]) { await page.setViewportSize({width, height}); await audit(`reduced-long-chain-${width}`); await reachable('open-assembly'); }
  resetRuns(); for (const run of runs) { run.prompt = run.parent_id ? 'Ela dá um pequeno salto e termina de costas.' : 'Ela dança mantendo a referência original.'; if (run.input_info.continuation) run.input_info.continuation.prompt = run.prompt; }
  references[1].name = 'Foto publicada no PC'; providerScene = 'Ela dá um pequeno salto. Durante o movimento, o vestido fica vermelho. Ao final, ela fica de costas. Preserve a identidade da referência original.';
  await page.setViewportSize({width: 393, height: 852}); await ready(); await capture('owner-library');
  await settingsRoundTrip('library');
  await newIdea('Ela dá um salto, muda o vestido para vermelho e termina de costas.'); await focusedAudit('idea'); await capture('owner-context');
  await settings(); await capture('owner-settings-grok'); await page.locator('#back').click(); await active('context');
  const historyBefore = posts().length; await settings(); await page.goBack(); await active('context'); assert.equal(posts().length, historyBefore); assert.equal(await page.locator('#idea').inputValue(), 'Ela dá um salto, muda o vestido para vermelho e termina de costas.');
  const settingsGrokCount = posts().length; grokGate = new Promise(resolve => { releaseGrok = resolve; }); await page.locator('#grok-detail').click(); await settings(); releaseGrok(); grokGate = null; await page.waitForFunction(() => document.getElementById('grok-result').value.length > 0); await active('settings'); assert.equal(posts().length, settingsGrokCount + 1); await page.locator('#settings-done').click(); await active('context'); assert.equal(await page.locator('#idea').inputValue(), 'Ela dá um salto, muda o vestido para vermelho e termina de costas.'); await page.locator('#show-proposal').click(); await active('proposal');
  await focusedAudit('grok-result'); await capture('owner-proposal');
  await page.locator('#grok-use').click(); await settings(); await page.locator('#duration').fill('5'); await focusedAudit('duration'); await capture('owner-settings-block'); await page.locator('#settings-done').click(); await capture('owner-generation-5s');
  // Reduced emulated viewport bounds cannot certify a physical IME.
  await settings(); await page.setViewportSize({width: 393, height: 480}); await focusedAudit('duration'); await audit('fake-ime-visualViewport-bounds'); await page.setViewportSize({width: 393, height: 852}); await page.locator('#settings-done').click();
  await openRun(endID); await capture('owner-review'); await page.locator('#reject').click(); await page.locator('#run-state').filter({hasText: 'Rejeitado'}).waitFor(); await capture('owner-rejected-review'); await page.locator('#retry-mode').click(); await active('generation'); await capture('owner-retry'); await openRun(rootID); await page.locator('#open-assembly').click(); await page.locator('#assemble').click(); await page.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor(); await capture('owner-assembly'); await settingsRoundTrip('assembly');
  await openRun(rootID); await page.locator('#continue-mode').click(); await page.locator('#continue-idea').click(); await page.waitForFunction(() => document.getElementById('last-frame-preview').naturalWidth > 0); assert.equal(await page.locator('#reference-preview').isVisible(), true); await capture('owner-continuation-paired');
  assert.equal(await page.evaluate(() => document.getAnimations().length), 0, 'reduce context has no CSS or WAAPI motion');
  // The regression context intentionally reduces motion. A separate normal-touch
  // context observes real keyframes, interruption and input while motion is running.
  resetRuns(); for (const run of runs) { run.prompt = run.parent_id ? 'Ela dá um pequeno salto e termina de costas.' : 'Ela dança mantendo a referência original.'; if (run.input_info.continuation) run.input_info.continuation.prompt = run.prompt; } assemblies = []; mode = grokMode = assemblyMode = 'normal';
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
  runs = Array.from({length: 12}, (_, index) => mkRun(`10000000-0000-4000-8000-${String(index).padStart(12, '0')}`, 'accepted', index ? `10000000-0000-4000-8000-${String(index - 1).padStart(12, '0')}` : null, 2.3, 'Ela dança com a referência original.'));
  await moving.goto('http://h3.mock.invalid/?other=keep#viewer'); await moving.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor();
  for (const [width, height] of [[393, 852], [320, 852], [640, 852], [852, 393], [1440, 1000]]) {
    await moving.setViewportSize({width, height}); await audit(`normal-library-${width}`, moving); if (height === 852 && width <= 640) await cardGesture(moving, `normal-card-scroll-${width}`);
    await moving.getByRole('button', {name: new RegExp(runs.at(-1).id)}).click(); await moving.locator('[data-screen="review"]').waitFor({state: 'visible'}); await audit(`normal-long-chain-${width}`, moving); await reachable('open-assembly', moving); await rootLibrary(moving);
  }
  resetRuns(); for (const run of runs) { run.prompt = run.parent_id ? 'Ela dá um pequeno salto e termina de costas.' : 'Ela dança mantendo a referência original.'; if (run.input_info.continuation) run.input_info.continuation.prompt = run.prompt; }
  await moving.setViewportSize({width: 393, height: 852}); await moving.reload(); await moving.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor();
  await moving.waitForFunction(() => motionLog.length > 0);
  await moving.getByRole('button', {name: new RegExp(rootID)}).tap(); await moving.locator('[data-screen="review"]').waitFor({state: 'visible'}); await moving.locator('#continue-mode').click(); await moving.locator('#continue-idea').click(); await moving.waitForFunction(() => document.getElementById('last-frame-preview').naturalWidth > 0); await capture('normal-continuation-paired', moving, {directory: motionArtifacts}); await rootLibrary(moving);
  await moving.getByRole('button', {name: new RegExp(endID)}).tap(); await moving.locator('[data-screen="review"]').waitFor({state: 'visible'});
  const beforeMotion = posts().length;
  await rootLibrary(moving);
  const mid = await moving.locator('#new-mode').evaluate(button => {
    button.click(); const animations = document.getAnimations().filter(animation => animation.effect?.target?.matches('[data-motion="heading"]'));
    for (const animation of animations) { animation.pause(); animation.currentTime = 90; }
    const heading = document.querySelector('[data-motion="heading"]'), style = getComputedStyle(heading);
    return {running: animations.length, transform: style.transform, opacity: Number(style.opacity), panel: document.querySelector('[data-screen]:not([hidden])').dataset.screen, focus: document.activeElement.id};
  });
  assert.equal(mid.running, 1); assert.equal(mid.panel, 'context'); assert.equal(mid.focus, 'screen-title'); assert.ok(mid.opacity > .65 && mid.opacity < 1); assert.notEqual(mid.transform, 'none');
  await capture('context-mid', moving, {directory: motionArtifacts, animations: 'allow'}); assert.equal(posts().length, beforeMotion);
  await moving.locator('#idea').fill('Uma cena viva, sem mudar os parâmetros.');
  await moving.locator('#back').click(); await beginIdea(moving);
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
  await setBlock('5', null, moving); await audit('motion-generation-touch', moving);
  waitGate = new Promise(resolve => { releaseWait = resolve; }); admissionGate = new Promise(resolve => { releaseAdmission = resolve; }); const beforeNative = inference().length;
  await moving.locator('#generate').evaluate(button => { button.click(); button.click(); });
  // Return to the already-open review through real history. A fresh library
  // detail selection is intentionally fenced while native admission is pending.
  for (let step = 0; step < 12 && !await moving.locator('[data-screen="review"]').isVisible(); step++) {
    const token = await moving.evaluate(() => history.state?.h3View);
    await moving.locator('#back').click(); await moving.waitForFunction(previous => history.state?.h3View !== previous, token);
    await moving.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  }
  await moving.locator('[data-screen="review"]').waitFor({state: 'visible'}); assert.match(await moving.locator('#metadata').textContent(), new RegExp(endID)); assert.equal(await moving.locator('#run-state').textContent(), 'Pronto para revisão');
  assert.equal(await moving.locator('#accept').getAttribute('aria-busy'), 'false'); assert.equal(await moving.locator('#reject').getAttribute('aria-busy'), 'false'); await audit('native-pending-not-review-busy', moving);
  releaseAdmission(); admissionGate = null; await rootLibrary(moving); await moving.locator('#nav-status').waitFor({state: 'visible'}); assert.equal(await moving.locator('#nav-status').evaluate(node => Boolean(node.closest('[data-screen="library"]'))), true); await moving.locator('#nav-status').tap(); await moving.locator('#operation').filter({hasText: 'Admitido:'}).waitFor();
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
  await beginIdea(staticPage); await staticPage.locator('#idea').fill('Fallback continua editável'); await staticPage.locator('#use-idea').tap(); assert.equal(await staticPage.locator('#prompt').inputValue(), 'Fallback continua editável'); assert.equal(posts().length, fallbackCount); await audit('motion-unsupported-fallback', staticPage); await fallback.close();
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide'))); assert.equal(await page.evaluate(() => mockEvents.every(event => event.closed)), true);
  assert.deepEqual(exceptions, []); assert.deepEqual(violations, []); assert.deepEqual(await protectedHashes(), beforeHashes);
  assert.deepEqual(await currentSourceHashes(), sourceHashes, 'Frontend must remain frozen throughout the evidence run');
  if (assemblyMedia) assert.equal(createHash('sha256').update(await readFile(resolve(root, process.env.H3_UI_TEST_ASSEMBLY))).digest('hex'), assemblyHash);
  console.log(`PASS progressive browser: ${requests.length} intercepted requests, ${posts().length} explicit fake POSTs, ${audits.length} bounds audits, zero API/provider/GPU`);
} finally {
  await writeFile(resolve(artifacts, 'report.json'), JSON.stringify({requests, exceptions, violations, consoleMessages, failedRequests, audits, captures, motionEvidence, sourceHashes, sourceHashesAfter: await currentSourceHashes(), phone: {width: 393, height: 852, touch: true, scale: 2}, originalFilesProtected: Object.keys(beforeHashes).length, mediaFixture: Boolean(media), assemblyFixture: Boolean(assemblyMedia), assemblyHash, lastFrameFixture: Boolean(process.env.H3_UI_TEST_LAST_FRAME), lastFrameHash, physicalIMEVerified: false, liveAPI: 0, provider: 0, GPU: 0}, null, 2));
  await browser.close();
}
