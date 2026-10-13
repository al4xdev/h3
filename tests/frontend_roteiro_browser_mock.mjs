// Plan41r1: isolated browser regression. No HTTP listener or product runtime imports.
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir, lstat} from 'node:fs/promises';
import {resolve, relative} from 'node:path';
import {createRequire} from 'node:module';
import {createHash, randomUUID} from 'node:crypto';
import {execFileSync} from 'node:child_process';

const root = resolve(new URL('..', import.meta.url).pathname);
const origin = 'http://h3.mock.invalid';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const copy = value => structuredClone(value);
const uuid = value => { assert.match(value, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/); return value; };
const IDs = {
  story: '41000000-0000-4000-8000-000000000001',
  blocks: [1, 2, 3].map(n => `41000000-0000-4000-8100-${String(n).padStart(12, '0')}`),
  candidate: '41000000-0000-4000-8200-000000000001',
  legacy: '41000000-0000-4000-8300-000000000001',
};
const pin = 'grok-4.20-0309-non-reasoning';
const reference = {source_root: 'assets', path: 'dance_reference.png'};
const idea = 'Começa dançando de preto. Salta, muda para vermelho, termina de costas e vira de frente.';
const actions = ['Dança mantendo o vestido preto.', 'Pequeno salto; vestido vermelho; termina de costas.', 'Vira de frente; mantém o vestido vermelho.'];
const finalPrompt = '  Ela dá um pequeno salto. O vestido fica vermelho.\nTermina de costas; preserve a identidade original.  ';
const caps = {default_requested_seconds: 8, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125};
// Independent numerical oracle, not an injected/imported product helper.
function frames(seconds) { const n = (seconds * 24 - 5) / 17, lower = Math.floor(n), fraction = n - lower; return 5 + 17 * Math.max(0, fraction === .5 ? lower + lower % 2 : Math.round(n)); }
const mediaPaths = {
  identity: 'assets/dance_reference.png',
  clip: 'runs/02cf408f-c985-47a2-887d-731569d7827a/chunk.mp4',
  frame: '.dumps/tests/ui-app-navigation/fixture-last-frame.png',
  assembly: '.dumps/benchmarks/baseline-three-chunks/benchmark.mp4',
};
const media = {}, protectedPaths = new Set(Object.values(mediaPaths));
for (const [key, name] of Object.entries(mediaPaths)) {
  const path = resolve(root, name), info = await lstat(path);
  assert.ok(info.isFile() && !info.isSymbolicLink() && info.size <= (key === 'clip' || key === 'assembly' ? 64 : 20) * 1024 * 1024, `bounded known fixture: ${name}`);
  media[key] = await readFile(path);
}
assert.notEqual(sha(media.identity), sha(media.frame), 'Real last frame must differ from identity');
assert.deepEqual(media.frame.subarray(0, 8), Buffer.from([137,80,78,71,13,10,26,10]));
// Only versioned resources and four explicit known media files; never walk legacy/.data trees.
for (const name of execFileSync('git', ['ls-files', '-z', '--', 'assets', 'workflows', 'prompts'], {cwd: root}).toString().split('\0').filter(Boolean)) protectedPaths.add(name);
async function protectedHashes() { return Object.fromEntries(await Promise.all([...protectedPaths].map(async name => [name, sha(await readFile(resolve(root, name)))]))); }
const before = await protectedHashes();
const knownMediaHashes = {identity: '668550fbe3973a423262dd2a3a4888127d7966eff5476353799ced1b1b032d98', clip: 'd30e715ee3ce84a8a453ad4db38e79ffb7ba6b6d141edf4a5ec959fa56b01d89', frame: '5156f9a695f13e33db12dd4c156cd9cf62da175f3154e53249e1d03f1408a4c6', assembly: '01741624b4b387797bbde3f352f35ab36f11fdd69fc47c782a6b29274147e38f'};
for (const [name, bytes] of Object.entries(media)) assert.equal(sha(bytes), knownMediaHashes[name], `Selected known media SHA: ${name}`);
const identityHash = sha(media.identity);
const block = (id, index) => ({id, action: actions[index], duration_seconds: 8, seed: 2026101205, prompt: actions[index]});
const baseDoc = () => ({id: IDs.story, revision: 1, name: 'Dança: do preto ao vermelho', idea, reference: copy(reference), reference_sha256: identityHash, adopted: false, blocks: [], attempts: []});
function nativeRun(id, state, parent_id = null, duration = 8, prompt = actions[0], seed = 2026101205) {
  return {id, state, parent_id, prompt, seed, duration_seconds: duration, decision: ['accepted', 'rejected'].includes(state) ? {accepted: state === 'accepted', at: '2026-10-13T18:00:02Z'} : null,
    created_at: '2026-10-13T18:00:00Z', updated_at: '2026-10-13T18:00:01Z', publication_mode: 'atomic_copy_from_comfy_output',
    references: [{type: 'image', role: 'identity', source_root: 'assets', source: 'dance_reference.png', sha256: identityHash}],
    input_info: {mode: parent_id ? 'continuation' : 'normal', operation: parent_id ? 'v2v' : 'i2v', continuation: parent_id ? {prompt, seed, duration_seconds: duration, reference_tail_seconds: 3, include_audio: true} : null},
    output: ['accepted', 'rejected', 'ready_for_review'].includes(state) ? {path: `.data/runs/${id}/chunk.mp4`, probe: {streams: [{codec_type: 'video', duration: String(frames(duration) / 24)}]}} : {}, error: state === 'interrupted' ? 'Interrupção histórica confirmada.' : null};
}
const slim = run => Object.fromEntries(['id', 'state', 'parent_id', 'prompt', 'seed', 'duration_seconds', 'created_at', 'updated_at', 'error'].map(key => [key, run[key]]).concat([['video_url', run.output.path ? `/runs/${run.id}/video` : null]]));
function deferred() { let release; const promise = new Promise(resolve => { release = resolve; }); return {promise, release}; }
function model({adopted = false} = {}) {
  const doc = baseDoc(); if (adopted) { doc.adopted = true; doc.blocks = IDs.blocks.map(block); }
  return {doc, exists: adopted, runs: [nativeRun(IDs.legacy, 'accepted')], assemblies: [],
    editor: {system_prompt: 'Preserve ação, roupa, pose e ordem. Responda só com a cena.', model: pin},
    macroEditor: {system_prompt: 'Divida a ideia em blocos claros, sem gerar vídeo.', model: pin},
    proposalMode: 'normal', grokMode: 'normal', admissionMode: 'normal', previewMode: 'normal', conflict: false,
    waitGate: null, grokGate: null, macroGate: null, requests: [], errors: [], violations: [], console: [], failed: []};
}
function reconcile(m) {
  for (const attempt of m.doc.attempts) { const run = m.runs.find(item => item.id === attempt.intent_id); if (run) { attempt.run = copy(run); attempt.state = run.state; } }
  return copy(m.doc);
}
function makeAttempt(m, key, id, body, state = 'queued', admission = 'admitted') {
  const attempt = {intent_id: id, run_id: id, roteiro_id: m.doc.id, block_id: key, source_revision: body.expected_revision, state, admission,
    snapshot: {...copy(body), reference: {...reference, sha256: identityHash}}, run: null};
  delete attempt.snapshot.expected_revision;
  if (admission === 'admitted') { const run = nativeRun(id, state, body.parent_id, body.duration_seconds, body.prompt, body.seed); m.runs.unshift(run); attempt.run = copy(run); }
  m.doc.attempts.push(attempt); return attempt;
}
function keys(body, expected) { assert.deepEqual(Object.keys(body).sort(), [...expected].sort(), 'Exact wire keys'); }
function frozenPrefix(m, body) {
  const end = Math.max(-1, ...m.doc.attempts.map(a => m.doc.blocks.findIndex(b => b.id === a.block_id)));
  assert.deepEqual(body.blocks.slice(0, end + 1), m.doc.blocks.slice(0, end + 1), 'Submitted prefix immutable');
  if (end >= 0) { assert.deepEqual(body.reference, m.doc.reference); assert.equal(body.idea, m.doc.idea); }
}
async function interceptor(m, route, assets) {
  const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
  if (url.origin !== origin) { m.violations.push(`external:${request.url()}`); return route.abort('blockedbyclient'); }
  const body = request.postData() ? request.postDataJSON() : null;
  m.requests.push({method, path: path + url.search, body: copy(body)});
  const json = (data, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(data)});
  if (method === 'GET' && ['/', '/roteiro'].includes(path)) return route.fulfill({contentType: 'text/html', body: assets['index.html']});
  if (method === 'GET' && ['/ui/app.js', '/ui/app.css'].includes(path)) return route.fulfill({contentType: path.endsWith('.js') ? 'text/javascript' : 'text/css', body: assets[path.slice(4)]});
  if (path === '/favicon.ico' && method === 'GET') return route.fulfill({status: 204});
  if (path === '/app/config' && method === 'GET') return json({default_prompt: actions[0], continuation_prompt: actions[1], reference_image: reference.path, duration_seconds: 8, duration_capabilities: caps, workflow_output_profile: 'final_only', filesystem_events: true, reference_library: true, assembly_enabled: true, roteiro_enabled: true});
  if (path === '/inputs' && method === 'GET') return json({items: [{...reference, name: 'Referência original', image_url: '/assets/image?path=dance_reference.png'}], total: 1});
  if (path === '/assets/image' && method === 'GET' && url.searchParams.get('path') === reference.path) return route.fulfill({contentType: 'image/png', body: media.identity});
  if (['/grok/editor', '/roteiros/editor'].includes(path)) {
    const target = path === '/grok/editor' ? 'editor' : 'macroEditor';
    if (method === 'PUT') { keys(body, target === 'editor' ? ['system_prompt', 'model'] : ['system_prompt']); if (target === 'editor') assert.equal(body.model, pin); m[target] = {...m[target], system_prompt: body.system_prompt}; }
    else assert.equal(method, 'GET');
    return json(m[target]);
  }
  if (path === '/grok' && method === 'POST') {
    keys(body, ['system_prompt', 'prompt', 'model', 'reference', ...(body.continuation_parent_id ? ['continuation_parent_id'] : [])]);
    assert.equal(body.system_prompt, m.editor.system_prompt); assert.equal(body.model, pin); assert.deepEqual(body.reference, reference);
    assert.ok(body.prompt.length <= 12000);
    if (body.continuation_parent_id) { assert.equal(m.runs.find(r => r.id === body.continuation_parent_id)?.state, 'accepted'); assert.equal(m.previewMode, 'normal'); }
    if (m.grokGate) await m.grokGate.promise;
    if (m.grokMode === 'network') return route.abort('connectionfailed');
    if (m.grokMode === 'provider') return json({detail: 'Detalhamento indisponível; instrução mantida.'}, 503);
    return json({text: finalPrompt, model: pin});
  }
  const preview = path.match(/^\/grok\/continuation\/([0-9a-f-]{36})\/last-frame$/);
  if (preview && method === 'GET') {
    assert.equal(m.runs.find(run => run.id === preview[1])?.state, 'accepted');
    if (m.previewMode === 'missing') return json({detail: 'Não foi possível mostrar o último frame.'}, 409);
    return route.fulfill({contentType: 'image/png', body: m.previewMode === 'invalid' ? Buffer.from('quadro inválido') : media.frame});
  }
  if (path === '/roteiros') {
    if (method === 'GET') return json({items: m.exists ? [reconcile(m)] : [], total: m.exists ? 1 : 0});
    assert.equal(method, 'POST'); keys(body, ['name', 'idea', 'reference', 'adopted', 'blocks']); assert.equal(body.adopted, false); assert.equal(m.exists, false); assert.deepEqual(body.reference, reference);
    Object.assign(m.doc, copy(body)); m.exists = true; return json(reconcile(m), 201);
  }
  const proposal = path.match(/^\/roteiros\/([0-9a-f-]{36})\/proposal$/);
  if (proposal) {
    assert.equal(method, 'POST'); assert.equal(proposal[1], m.doc.id); keys(body, ['expected_revision', 'count', 'duration_seconds', 'seed']); assert.equal(body.expected_revision, m.doc.revision);
    const revision = m.doc.revision; if (m.macroGate) await m.macroGate.promise;
    if (m.proposalMode === 'invalid') return json({error: 'invalid_proposal', raw_text: 'resposta benigna sem JSON', source_revision: revision, stale: revision !== m.doc.revision, id: IDs.candidate, roteiro_id: m.doc.id, detail: 'A resposta não pôde ser convertida em blocos válidos.'}, 422);
    const blocks = IDs.blocks.slice(0, body.count).map((id, i) => ({...block(id, i), duration_seconds: body.duration_seconds, seed: body.seed}));
    return json({id: IDs.candidate, roteiro_id: m.doc.id, source_revision: revision, name: 'Dança: do preto ao vermelho', blocks, raw_text: JSON.stringify({name: 'Dança: do preto ao vermelho', blocks: blocks.map(({action, duration_seconds, prompt}) => ({action, duration_seconds, prompt}))}), stale: revision !== m.doc.revision});
  }
  const intent = path.match(/^\/roteiros\/([0-9a-f-]{36})\/blocks\/([0-9a-f-]{36})\/attempts\/([0-9a-f-]{36})$/);
  if (intent) {
    const [, story, key, id] = intent; uuid(id); assert.equal(story, m.doc.id);
    const existing = m.doc.attempts.find(a => a.intent_id === id);
    if (method === 'GET') return existing ? json(reconcile(m).attempts.find(a => a.intent_id === id)) : json({detail: 'Vínculo não confirmado; não reenviar.'}, 404);
    assert.equal(method, 'POST'); keys(body, ['expected_revision', 'prompt', 'seed', 'duration_seconds', 'parent_id']);
    assert.equal(new URL(request.frame().page().url()).searchParams.get('intent'), id, 'Known address before admission');
    if (existing) return json({detail: 'Intenção já registrada.'}, 409);
    assert.equal(body.expected_revision, m.doc.revision);
    const position = m.doc.blocks.findIndex(b => b.id === key); assert.ok(position >= 0);
    const past = m.doc.attempts.filter(a => a.block_id === key);
    if (!past.length) { const saved = m.doc.blocks[position]; for (const field of ['prompt', 'seed', 'duration_seconds']) assert.equal(body[field], saved[field], 'Save must match admission draft'); }
    if (position === 0) assert.equal(body.parent_id, null);
    else { const parent = m.doc.attempts.findLast(a => a.block_id === m.doc.blocks[position - 1].id && m.runs.find(r => r.id === a.intent_id)?.state === 'accepted'); assert.ok(parent); assert.equal(body.parent_id, parent.intent_id); }
    if (m.admissionMode === 'uncertain') return json(makeAttempt(m, key, id, body, 'uncertain', 'uncertain'), 202);
    if (m.admissionMode === 'rejected') return json({...makeAttempt(m, key, id, body, 'not_admitted', 'rejected'), error: 'Slot ocupado.'}, 409);
    const record = makeAttempt(m, key, id, body);
    if (m.admissionMode === 'lost') return route.abort('connectionfailed');
    return json(record, 202);
  }
  if (path === `/roteiros/${m.doc.id}`) {
    if (method === 'GET') return json(reconcile(m));
    assert.equal(method, 'PUT'); keys(body, ['expected_revision', 'name', 'idea', 'reference', 'adopted', 'blocks']);
    if (m.conflict || body.expected_revision !== m.doc.revision) return json({detail: 'O roteiro mudou no PC.'}, 409);
    frozenPrefix(m, body); const {expected_revision, ...editable} = body; Object.assign(m.doc, copy(editable), {revision: expected_revision + 1}); return json(reconcile(m));
  }
  if (path === '/runs' && method === 'GET') return json({items: m.runs.map(slim), total: m.runs.length});
  if (method === 'POST' && (path === '/runs/i2v' || /^\/runs\/[^/]+\/v2v$/.test(path))) {
    const id = randomUUID(), parent = path === '/runs/i2v' ? null : path.split('/')[2]; const run = nativeRun(id, 'queued', parent, body.duration_seconds, body.prompt, body.seed); m.runs.unshift(run); return json(run, 202);
  }
  if (path === '/assemblies' && method === 'GET') { const items = m.assemblies.filter(a => a.end_run_id === url.searchParams.get('end_run_id')); return json({items, total: items.length}); }
  const assembly = path.match(/^\/assemblies\/([0-9a-f-]{36})(\/video)?$/);
  if (assembly) {
    const id = assembly[1];
    if (method === 'POST') {
      keys(body, ['end_run_id']); assert.equal(new URL(request.frame().page().url()).searchParams.get('assembly'), id);
      const end = m.runs.find(r => r.id === body.end_run_id); assert.equal(end?.state, 'accepted');
      const record = {id, end_run_id: end.id, state: 'completed', mode: 'accepted_sequence', request_sha256: 'a'.repeat(64), output_sha256: sha(media.assembly), frames: frames(8) * m.doc.blocks.length, fps: '24/1', video_url: `/assemblies/${id}/video`, output: {path: `.data/assemblies/${id}/video.mp4`}};
      m.assemblies.push(record); return json(record);
    }
    const record = m.assemblies.find(a => a.id === id); if (!record) return json({detail: 'Montagem não confirmada.'}, 404);
    return assembly[2] ? route.fulfill({contentType: 'video/mp4', body: media.assembly}) : json(record);
  }
  const native = path.match(/^\/runs\/([0-9a-f-]{36})(\/(video|sequence|accept|reject))?$/);
  if (native) {
    const run = m.runs.find(r => r.id === native[1]); if (!run) return json({detail: 'Run não encontrado.'}, 404);
    if (native[3] === 'video') return route.fulfill({contentType: 'video/mp4', body: media.clip});
    if (native[3] === 'sequence') {
      const chain = []; let cursor = run; while (cursor) { chain.unshift(cursor); cursor = m.runs.find(r => r.id === cursor.parent_id); }
      return json({root_id: chain[0].id, end_run_id: run.id, blocks: chain.map(r => ({id: r.id, parent_id: r.parent_id, state: r.state, duration_seconds: frames(r.duration_seconds) / 24, video_url: r.output.path ? `/runs/${r.id}/video` : null}))});
    }
    if (['accept', 'reject'].includes(native[3])) { assert.equal(method, 'POST'); assert.equal(run.state, 'ready_for_review'); run.state = native[3] === 'accept' ? 'accepted' : 'rejected'; run.decision = {accepted: run.state === 'accepted', at: '2026-10-13T18:00:02Z'}; return json(run); }
    assert.equal(method, 'GET');
    if (url.searchParams.get('wait') === 'true') { run.state = 'running'; if (m.waitGate) await m.waitGate.promise; Object.assign(run, nativeRun(run.id, 'ready_for_review', run.parent_id, run.duration_seconds, run.prompt, run.seed)); }
    return json(run);
  }
  m.violations.push(`unexpected:${method}:${path}`); return route.abort('blockedbyclient');
}

const apiKeys = {document: Object.keys(baseDoc()), save: ['expected_revision', 'name', 'idea', 'reference', 'adopted', 'blocks'], macro: ['expected_revision', 'count', 'duration_seconds', 'seed'], intent: ['expected_revision', 'prompt', 'seed', 'duration_seconds', 'parent_id'], editor: ['system_prompt'], selectors: ['story-new', 'story-create', 'story-propose', 'story-manual', 'story-blocks', 'story-adopt', 'story-next', 'story-detail', 'story-block-candidate', 'story-block-use', 'story-return', 'story-intent-read', 'story-system', 'story-editor-save']};
if (process.argv.includes('--prepare')) { console.log(JSON.stringify({ready: 'fixtures and exact API model prepared; browser not launched', apiKeys, mediaHashes: Object.fromEntries(Object.entries(media).map(([key, bytes]) => [key, sha(bytes)])), protectedFiles: protectedPaths.size}, null, 2)); process.exit(0); }

// Selecting these exact existing fixtures is explicit, never a search of private trees.
for (const [variable, key] of [['H3_UI_TEST_CLIP','clip'],['H3_UI_TEST_ASSEMBLY','assembly'],['H3_UI_TEST_LAST_FRAME','frame']]) assert.equal(process.env[variable],mediaPaths[key],`Require explicit known fixture ${variable}`);
// The owner supplies exact hashes after ALL three frontend files are frozen.
const frozen = JSON.parse(process.env.H3_ROTEIRO_FROZEN_SHA256 || 'null');
assert.ok(frozen && Object.keys(frozen).length === 3, 'Require parent freeze: H3_ROTEIRO_FROZEN_SHA256 JSON for index.html/app.js/app.css');
const assets = Object.fromEntries(await Promise.all(['index.html', 'app.js', 'app.css'].map(async name => [name, await readFile(resolve(root, 'src/h3_backend/web', name))])));
const sourceHashes = Object.fromEntries(Object.entries(assets).map(([name, bytes]) => [name, sha(bytes)]));
assert.deepEqual(sourceHashes, frozen, 'All web3 source must match owner freeze before browser start');
const directory = resolve(root, '.dumps/tests/ui-roteiro', `run-${new Date().toISOString().replace(/[:.]/g, '-')}-${randomUUID()}`);
await mkdir(directory, {recursive: true});
const {chromium} = createRequire('/home/alex/package.json')('/home/alex/node_modules/playwright');
const browser = await chromium.launch({headless: true});
const report = {plan: '41r1', sourceHashes, mediaPaths, protectedBefore: before, cases: [], audits: [], captures: [], models: [], firstFailure: null, limits: {liveAPI: 0, provider: 0, GPU: 0, physicalIME: false, artisticContinuity: false, nativeVideoDurationFixture: 'prerecorded historical clip; mock metadata is intentional'}};
let currentCase = null, lastPage = null;
const posts = m => m.requests.filter(r => r.method === 'POST');
const intents = m => posts(m).filter(r => /\/attempts\//.test(r.path));
const groks = m => posts(m).filter(r => r.path === '/grok');
const assemblies = m => posts(m).filter(r => r.path.startsWith('/assemblies/'));
async function scenario(name, options = {}) {
  currentCase = name; const m = model(options); report.models.push(m);
  const context = await browser.newContext({viewport: options.desktop ? {width:1440,height:1000} : {width: 393, height: 852}, deviceScaleFactor: options.desktop ? 1 : 2, isMobile: !options.desktop, hasTouch: !options.desktop, reducedMotion: options.motion || 'reduce', serviceWorkers: 'block', ...(options.video ? {recordVideo: {dir: directory, size: {width: 393, height: 852}}} : {})});
  await context.route('**/*', route => interceptor(m, route, assets).catch(async error => { m.errors.push(`fixture:${error.stack}`); await route.abort('failed').catch(() => {}); }));
  // SSE is an in-memory inert event source, never a listener or native execution.
  await context.addInitScript(() => { window.mockEvents = []; window.EventSource = class extends EventTarget { constructor() { super(); window.mockEvents.push(this); queueMicrotask(() => this.dispatchEvent(new Event('open'))); } close() {} }; });
  const page = await context.newPage(); lastPage = page; page.setDefaultTimeout(8000);
  page.on('pageerror', error => m.errors.push(`app:${error.stack}`)); page.on('console', msg => { if (msg.type() === 'error') m.console.push(msg.text()); }); page.on('requestfailed', request => m.failed.push({url: request.url(), error: request.failure()?.errorText}));
  return {m, context, page};
}
async function ready(page, path = '/?other=keep#viewer') { await page.goto(origin + path); await page.locator('#notice').filter({hasText: /Escolha um bloco|API indisponível/}).waitFor(); }
async function active(page, screen) { await page.locator(`[data-screen="${screen}"]`).waitFor({state: 'visible'}); assert.equal(await page.locator('[data-screen]:visible').count(), 1); }
async function tapTop(page, id) { const box = await page.locator(`#${id}`).boundingBox(); assert.ok(box && box.y >= 0 && box.width >= 44 && box.height >= 44); await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2); }
async function audit(page, name) {
  const result = await page.evaluate(() => {
    const visible = node => node.getClientRects().length > 0;
    const scrolling = [...document.querySelectorAll('body *')].filter(visible).filter(node => !node.matches('input,textarea')).filter(node => { const css = getComputedStyle(node); return (/auto|scroll/.test(css.overflowY) && node.scrollHeight > node.clientHeight + 1) || (/auto|scroll/.test(css.overflowX) && node.scrollWidth > node.clientWidth + 1); }).map(node => ({id: node.id, classes: node.className}));
    const rootTransforms = [...document.querySelectorAll('video,#back,#settings-open,#visual-contexts')].filter(visible).flatMap(node => { const ancestors = []; for (let a = node.parentElement; a; a = a.parentElement) if (getComputedStyle(a).transform !== 'none') ancestors.push({id: a.id, classes: a.className}); return ancestors; });
    return {width: innerWidth, height: innerHeight, dpr: devicePixelRatio, touch: navigator.maxTouchPoints, scroll: scrollY, overflow: document.documentElement.scrollWidth > innerWidth, scrolling, rootTransforms,
      hiddenInert: [...document.querySelectorAll('[data-screen][hidden]')].every(node => node.inert), hiddenFocus: Boolean(document.activeElement?.closest('[data-screen][hidden]')),
      active: [...document.querySelectorAll('[data-screen]:not([hidden])')].map(node => node.dataset.screen),
      buttons: [...document.querySelectorAll('button,summary')].filter(visible).map(node => ({id: node.id, label: node.textContent.trim(), height: node.getBoundingClientRect().height, width: node.getBoundingClientRect().width})),
      ancestry: [...document.querySelectorAll('#sequence li')].filter(visible).map(node => node.getBoundingClientRect().toJSON())};
  });
  report.audits.push({case: currentCase, name, ...result});
  assert.equal(result.overflow, false, `${name}: horizontal overflow`); assert.deepEqual(result.scrolling, [], `${name}: one document scroll`); assert.deepEqual(result.rootTransforms, [], `${name}: no transformed media/header/context ancestors`); assert.equal(result.hiddenInert, true); assert.equal(result.hiddenFocus, false); assert.equal(result.active.length, 1); assert.ok(result.buttons.every(b => b.height >= 44 && b.width >= 44), `${name}: 44px touch targets`);
}
async function capture(page, name) {
  await page.evaluate(async () => { await document.fonts.ready; for (const image of document.images) if (image.getClientRects().length && !image.complete) await new Promise(resolve => { image.addEventListener('load', resolve, {once: true}); image.addEventListener('error', resolve, {once: true}); }); });
  await audit(page, name); const path = resolve(directory, `${report.captures.length}-${name}.png`); await page.screenshot({path, fullPage: true, animations: 'disabled'}); report.captures.push({name, path});
}
async function pass(name, fn) { currentCase = name; await fn(); report.cases.push({name, passed: true}); }
const card = (page, id) => page.locator(`#story-blocks [data-block-id="${id}"]`);
async function createAndAdopt(page, m) {
  await ready(page); await active(page, 'library'); assert.equal(posts(m).length, 0);
  await page.locator('#new-mode').tap(); await active(page, 'context'); assert.equal(await page.locator('#use-idea').isVisible(), true); await tapTop(page, 'back'); await active(page, 'library');
  await page.locator('#story-new').tap(); await active(page, 'context'); assert.equal(await page.locator('#screen-title').textContent(), 'Novo roteiro');
  await page.locator('#idea').fill(idea); await page.locator('#story-create summary').tap(); assert.equal(await page.locator('#story-duration').inputValue(), '8'); await page.locator('#story-create-name').fill('Dança planejada'); await page.locator('#story-count').fill('3');
  await page.locator('#story-propose').tap(); await active(page, 'story'); assert.equal(posts(m).filter(r => r.path.endsWith('/proposal')).length, 1); assert.equal(intents(m).length, 0); assert.deepEqual(m.doc.blocks, []); await capture(page, 'story-proposal');
  await card(page, IDs.blocks[0]).getByRole('button', {name: 'Editar', exact: true}).tap(); await card(page, IDs.blocks[0]).getByRole('textbox', {name: 'O que acontece'}).fill('Dança de preto, mantendo a identidade.'); await card(page, IDs.blocks[0]).getByRole('button', {name: 'Salvar alterações'}).tap();
  await page.locator('#story-adopt').tap(); await page.locator('#story-status').filter({hasText: 'Roteiro salvo'}).waitFor(); assert.equal(m.doc.adopted, true); assert.equal(m.doc.blocks.length, 3); assert.ok(m.doc.blocks.every(b => b.prompt && b.duration_seconds === 8 && b.seed === 2026101205)); assert.equal(intents(m).length, 0); await capture(page, 'story-adopted');
}
async function generate(page, m, {reject = false} = {}) {
  const beforeCount = intents(m).length; m.waitGate = deferred();
  await page.locator('#generate').tap(); await page.locator('#operation').filter({hasText: 'Admitido:'}).waitFor();
  const item = intents(m).at(-1), id = item.path.split('/').at(-1); assert.equal(intents(m).length, beforeCount + 1); assert.equal(new URL(page.url()).searchParams.get('intent'), id);
  assert.equal(m.requests.filter(r => r.path === `/runs/${id}?wait=true`).length, 1); assert.equal(await page.locator('#generate').isDisabled(), true);
  m.waitGate.release(); m.waitGate = null; await page.locator('#operation').filter({hasText: 'Pronto para revisão'}).waitFor(); await page.locator('#status-review').tap(); await active(page, 'review'); assert.equal(m.runs.find(r => r.id === id).state, 'ready_for_review'); await capture(page, reject ? 'review-before-reject' : 'review');
  const count = posts(m).length; await page.locator(reject ? '#reject' : '#accept').tap(); await page.locator('#run-state').filter({hasText: reject ? 'Rejeitado' : 'Aceito'}).waitFor(); assert.equal(posts(m).length, count + 1); await active(page, 'review'); assert.equal(intents(m).length, beforeCount + 1); assert.equal(assemblies(m).length, 0); return id;
}

try {
  const {page, m, context} = await scenario('T00–T06 complete story');
  await pass('T00/T01/T02 proposal inline adoption', () => createAndAdopt(page, m));
  await pass('T03 root prefill and explicit Grok adoption', async () => {
    await page.locator('#story-next').tap(); await active(page, 'generation'); assert.equal(await page.locator('#prompt').inputValue(), actions[0]); assert.equal(groks(m).length, 0);
    await page.locator('#story-detail').tap(); await page.locator('#story-block-candidate').waitFor({state: 'visible'}); assert.equal(await page.locator('#prompt').inputValue(), actions[0]); assert.equal(await page.locator('#generate').isDisabled(), true); assert.equal(groks(m).length, 1); assert.ok(groks(m)[0].body.prompt.includes('Próximo bloco planejado: ' + actions[1])); assert.equal(groks(m)[0].body.continuation_parent_id, undefined);
    await page.locator('#story-block-proposal').fill(finalPrompt); await page.locator('#story-block-use').tap(); assert.equal(intents(m).length, 0); assert.equal((await page.locator('#prompt').inputValue()).trim(), finalPrompt.trim());
  });
  let rootID, rejectedID, retryID, finalID;
  await pass('T04/T05 root one native intent/wait and explicit acceptance', async () => { rootID = await generate(page, m); assert.equal(intents(m)[0].body.parent_id, null); });
  await pass('T03 accepted parent paired real frame and packed context', async () => {
    await page.locator('#continue-mode').tap(); await active(page, 'generation'); assert.equal(await page.locator('#prompt').inputValue(), actions[1]); await page.locator('#last-frame-preview').waitFor({state: 'visible'}); await page.waitForFunction(() => document.getElementById('last-frame-preview').naturalWidth > 0); assert.equal(await page.locator('#last-frame-preview').getAttribute('src'), `/grok/continuation/${rootID}/last-frame`); assert.equal(await page.locator('#reference-preview').isVisible(), true); await capture(page, 'workbench-paired');
    await page.locator('#story-detail').tap(); await page.locator('#story-block-candidate').waitFor({state: 'visible'}); const body = groks(m).at(-1).body; assert.equal(body.continuation_parent_id, rootID); assert.ok(body.prompt.includes('Instrução enviada: ' + m.runs.find(r => r.id === rootID).prompt)); assert.ok(body.prompt.includes('Este bloco: ' + actions[1])); assert.ok(body.prompt.includes('Próximo bloco planejado: ' + actions[2])); await page.locator('#story-block-use').tap();
  });
  await pass('Rejected retry final snapshot original parent immutable', async () => {
    rejectedID = await generate(page, m, {reject: true}); const old = copy(m.runs.find(r => r.id === rejectedID)), count = posts(m).length;
    await page.locator('#retry-mode').tap(); await active(page, 'generation'); assert.equal(await page.locator('#prompt').inputValue(), old.prompt); assert.equal(posts(m).length, count); await capture(page, 'retry-workbench');
    retryID = await generate(page, m); assert.notEqual(retryID, rejectedID); assert.equal(intents(m).at(-1).body.parent_id, rootID); assert.deepEqual(m.runs.find(r => r.id === rejectedID), old); assert.equal(m.runs.find(r => r.id === retryID).state, 'accepted');
  });
  await pass('Accepted chain explicit assembly and readonly UUID reload', async () => {
    await page.locator('#continue-mode').tap(); await active(page, 'generation'); finalID = await generate(page, m); assert.equal(intents(m).at(-1).body.parent_id, retryID);
    await page.locator('#open-assembly').tap(); await active(page, 'assembly'); assert.equal(assemblies(m).length, 0); await page.locator('#assemble').tap(); await page.locator('#assembly-status').filter({hasText: 'Montagem publicada'}).waitFor(); const own = new URL(page.url()).searchParams.get('assembly'); assert.ok(own); assert.equal(assemblies(m).length, 1); await capture(page, 'assembly'); const count = posts(m).length;
    await page.reload(); await page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); assert.equal(new URL(page.url()).searchParams.get('roteiro'), IDs.story); assert.equal(new URL(page.url()).searchParams.get('intent'), finalID); assert.equal(new URL(page.url()).searchParams.get('assembly'), own); assert.equal(new URL(page.url()).searchParams.get('other'), 'keep'); assert.equal(new URL(page.url()).hash, '#viewer'); assert.equal(posts(m).length, count); assert.ok(m.requests.some(r => r.method === 'GET' && r.path.includes(`/attempts/${finalID}`)));
  });
  assert.deepEqual(m.errors, []); assert.deepEqual(m.violations, []); await context.close();

  await pass('Future stable keys reorder/remove and frozen prefix', async () => {
    const s = await scenario(currentCase, {adopted: true}); const acceptedID = '41000000-0000-4000-8700-000000000001'; makeAttempt(s.m, IDs.blocks[0], acceptedID, {expected_revision:1,prompt:actions[0],seed:2026101205,duration_seconds:8,parent_id:null}, 'accepted'); const frozenBlock = copy(s.m.doc.blocks[0]); await ready(s.page, `/roteiro?roteiro=${IDs.story}`); await active(s.page, 'story'); const ids = s.m.doc.blocks.map(b => b.id); assert.equal(await card(s.page,ids[0]).getByRole('button',{name:'Assistir bloco'}).isVisible(),true); assert.equal(await card(s.page,ids[0]).getByText('Organizar bloco',{exact:true}).count(),0); await card(s.page,ids[1]).getByText('Organizar bloco',{exact:true}).tap(); assert.equal(await card(s.page,ids[1]).getByRole('button',{name:'Mover para cima'}).isDisabled(),true);
    await card(s.page, ids[2]).getByText('Organizar bloco', {exact: true}).tap(); await card(s.page, ids[2]).getByRole('button', {name: 'Mover para cima'}).tap(); await s.page.locator('#story-status').filter({hasText: 'Roteiro salvo'}).waitFor(); assert.deepEqual(s.m.doc.blocks.map(b => b.id), [ids[0], ids[2], ids[1]]);
    await card(s.page, ids[1]).getByText('Organizar bloco', {exact: true}).tap(); s.page.once('dialog', dialog => dialog.accept()); await card(s.page, ids[1]).getByRole('button', {name: 'Remover bloco'}).tap(); await s.page.waitForFunction(() => document.querySelectorAll('#story-blocks > li').length === 2); assert.deepEqual(s.m.doc.blocks.map(b => b.id), [ids[0], ids[2]]); assert.deepEqual(s.m.doc.blocks[0],frozenBlock); assert.equal(intents(s.m).length, 0); await s.context.close();
  });
  await pass('Dirty inline editor choices and revision conflict no POST', async () => {
    const s = await scenario(currentCase, {adopted: true}); await ready(s.page, `/roteiro?roteiro=${IDs.story}`);
    await card(s.page, IDs.blocks[0]).getByRole('button', {name: 'Editar', exact: true}).tap(); await card(s.page, IDs.blocks[0]).getByRole('textbox', {name: 'O que acontece'}).fill('Minha edição não salva.'); await card(s.page, IDs.blocks[1]).getByRole('button', {name: 'Editar', exact: true}).tap(); await s.page.locator('#story-unsaved').waitFor({state: 'visible'}); for (const id of ['story-save-continue', 'story-discard', 'story-keep-editing']) assert.equal(await s.page.locator('#' + id).isVisible(), true); await s.page.locator('#story-keep-editing').tap(); assert.equal(await card(s.page, IDs.blocks[0]).getByRole('textbox', {name: 'O que acontece'}).inputValue(), 'Minha edição não salva.'); s.m.conflict = true; await card(s.page, IDs.blocks[0]).getByRole('button', {name: 'Salvar alterações'}).tap(); await s.page.locator('#story-status').filter({hasText: 'O roteiro mudou no PC'}).waitFor(); assert.equal(intents(s.m).length, 0); assert.equal(await card(s.page, IDs.blocks[0]).getByRole('textbox', {name: 'O que acontece'}).inputValue(), 'Minha edição não salva.'); await s.context.close();
  });
  for (const admissionMode of ['lost', 'uncertain', 'rejected']) await pass(`Native ${admissionMode} same known intent recovery no replay`, async () => {
    const s = await scenario(currentCase, {adopted: true}); s.m.admissionMode = admissionMode; await ready(s.page, `/roteiro?roteiro=${IDs.story}&other=keep`); await s.page.locator('#story-next').tap(); await s.page.locator('#generate').tap(); await s.page.locator('#operation').filter({hasText: /incerto|recusado/i}).waitFor(); const id = new URL(s.page.url()).searchParams.get('intent'); assert.ok(id); assert.equal(intents(s.m).length, 1); const count = posts(s.m).length;
    await s.page.locator('#story-intent-read').tap(); await s.page.locator('#operation').filter({hasText: /Nenhum pedido repetido|não reenvie/}).waitFor(); await s.page.reload(); await s.page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); assert.equal(posts(s.m).length, count); assert.ok(s.m.requests.some(r => r.method === 'GET' && r.path.endsWith(`/attempts/${id}`))); assert.equal(new URL(s.page.url()).searchParams.get('intent'), id); assert.equal(new URL(s.page.url()).searchParams.get('other'), 'keep'); await capture(s.page, `native-${admissionMode}`); await s.context.close();
  });
  await pass('First Gerar revision conflict preserves draft no native intent', async () => {
    const s = await scenario(currentCase, {adopted: true}); await ready(s.page, `/roteiro?roteiro=${IDs.story}`); await s.page.locator('#story-next').tap(); await s.page.locator('#prompt').fill('Minha instrução escolhida antes do conflito.'); s.m.conflict = true; await s.page.locator('#generate').tap(); await s.page.locator('#story-status').filter({hasText: 'O roteiro mudou no PC'}).waitFor(); assert.equal(intents(s.m).length, 0); assert.equal(await s.page.locator('#prompt').inputValue(), 'Minha instrução escolhida antes do conflito.'); assert.equal(new URL(s.page.url()).searchParams.get('intent'), null); await s.context.close();
  });
  await pass('Lost association cannot imply not submitted or replay', async () => {
    const s = await scenario(currentCase, {adopted: true}); s.m.admissionMode = 'lost'; await ready(s.page, `/roteiro?roteiro=${IDs.story}`); await s.page.locator('#story-next').tap(); await s.page.locator('#generate').tap(); await s.page.locator('#operation').filter({hasText: 'Resultado incerto'}).waitFor(); const id = new URL(s.page.url()).searchParams.get('intent'); assert.ok(s.m.runs.some(r => r.id === id)); s.m.doc.attempts = []; const count = posts(s.m).length;
    await s.page.locator('#story-intent-read').tap(); await s.page.locator('#operation').filter({hasText: 'não reenvie'}).waitFor(); assert.equal(await s.page.locator('#generate').isDisabled(), true); await s.page.reload(); await s.page.locator('#notice').filter({hasText: 'Escolha um bloco'}).waitFor(); assert.equal(posts(s.m).length, count); assert.equal(new URL(s.page.url()).searchParams.get('intent'), id); assert.equal(await s.page.locator('#generate').isDisabled(), true); await s.context.close();
  });
  for (const continuation of [false, true]) await pass(`Interrupted ${continuation ? 'child' : 'root'} literal FINAL retry snapshot`, async () => {
    const s = await scenario(currentCase, {adopted: true}); const parent = '41000000-0000-4000-8600-000000000001', interrupted = '41000000-0000-4000-8600-000000000002';
    if (continuation) makeAttempt(s.m, IDs.blocks[0], parent, {expected_revision:1,prompt:actions[0],seed:2026101205,duration_seconds:8,parent_id:null}, 'accepted');
    const literal = '  Prompt FINAL enviado pelo Grok.\nPreserve a pose e o vestido vermelho.  ';
    makeAttempt(s.m, IDs.blocks[continuation ? 1 : 0], interrupted, {expected_revision:1,prompt:literal,seed:77,duration_seconds:5,parent_id:continuation ? parent : null}, 'interrupted'); const old = copy(s.m.runs.find(r => r.id === interrupted));
    await ready(s.page, `/roteiro?roteiro=${IDs.story}`); const count = posts(s.m).length; await s.page.locator('#story-next').tap(); await active(s.page,'generation'); assert.equal(await s.page.locator('#prompt').inputValue(),literal); assert.equal(await s.page.locator('#duration').inputValue(),'5'); assert.equal(await s.page.locator('#seed').inputValue(),'77'); assert.equal(posts(s.m).length,count); assert.equal(groks(s.m).length,0);
    const newID = await generate(s.page,s.m); assert.notEqual(newID,interrupted); assert.equal(intents(s.m).at(-1).body.parent_id,continuation ? parent : null); assert.deepEqual(s.m.runs.find(r => r.id === interrupted),old); assert.equal(s.m.requests.filter(r => r.method === 'PUT' && r.path === `/roteiros/${IDs.story}`).length,0,'Retry never rewrites frozen plan'); await s.context.close();
  });
  await pass('Late macro does not overwrite edited idea or adopted blocks', async () => {
    const s = await scenario(currentCase); s.m.macroGate = deferred(); await ready(s.page); await s.page.locator('#story-new').tap(); await s.page.locator('#idea').fill(idea); await s.page.locator('#story-propose').tap(); await s.page.waitForFunction(() => document.getElementById('grok-status').textContent.includes('Dividindo')); await s.page.locator('#idea').fill('Minha ideia editada durante a proposta.'); s.m.macroGate.release(); await active(s.page,'story'); assert.equal(await s.page.locator('#idea').inputValue(),'Minha ideia editada durante a proposta.'); assert.deepEqual(s.m.doc.blocks,[]); assert.equal(s.m.doc.adopted,false); assert.equal(intents(s.m).length,0); await s.context.close();
  });
  await pass('Macro invalid response preserves idea/manual path', async () => {
    const s = await scenario(currentCase); s.m.proposalMode = 'invalid'; await ready(s.page); await s.page.locator('#story-new').tap(); await s.page.locator('#idea').fill(idea); await s.page.locator('#story-propose').tap(); await s.page.locator('#grok-status').filter({hasText: 'Não foi possível obter a proposta'}).waitFor(); assert.equal(await s.page.locator('#idea').inputValue(), idea); await s.page.locator('#story-manual').tap(); await active(s.page, 'story'); assert.equal(intents(s.m).length, 0); await s.context.close();
  });
  for (const previewMode of ['missing', 'invalid']) await pass(`Continuation ${previewMode} frame blocks Grok not manual`, async () => {
    const s = await scenario(currentCase, {adopted: true}); const id = '41000000-0000-4000-8400-000000000001'; makeAttempt(s.m, IDs.blocks[0], id, {expected_revision: 1, prompt: actions[0], seed: 2026101205, duration_seconds: 8, parent_id: null}, 'accepted'); s.m.previewMode = previewMode;
    await ready(s.page, `/roteiro?roteiro=${IDs.story}`); await s.page.locator('#story-next').tap(); await active(s.page, 'generation'); await s.page.locator('#last-frame-status').filter({hasText: /não|indisponível|falh/i}).waitFor(); assert.equal(await s.page.locator('#story-detail').isDisabled(), true); assert.equal(await s.page.locator('#generate').isEnabled(), true); assert.equal(groks(s.m).length, 0); assert.equal(intents(s.m).length, 0); await s.context.close();
  });
  for (const grokMode of ['provider', 'network']) await pass(`Grok ${grokMode} keeps manual prompt no replay`, async () => {
    const s = await scenario(currentCase, {adopted: true}); s.m.grokMode = grokMode; await ready(s.page, `/roteiro?roteiro=${IDs.story}`); await s.page.locator('#story-next').tap(); await s.page.locator('#story-detail').tap(); await s.page.locator('#story-detail-status').filter({hasText: 'Sua instrução foi mantida'}).waitFor(); assert.equal(await s.page.locator('#prompt').inputValue(), actions[0]); assert.equal(await s.page.locator('#generate').isEnabled(), true); assert.equal(groks(s.m).length, 1); await s.context.close();
  });
  await pass('Late block Grok preserves edited chosen prompt', async () => {
    const s = await scenario(currentCase, {adopted: true}); await ready(s.page, `/roteiro?roteiro=${IDs.story}`); await s.page.locator('#story-next').tap(); s.m.grokGate = deferred(); await s.page.locator('#story-detail').tap(); await s.page.locator('#prompt').fill('Minha instrução editada durante a consulta.'); s.m.grokGate.release(); await s.page.locator('#story-block-candidate').waitFor({state: 'visible'}); assert.equal(await s.page.locator('#prompt').inputValue(), 'Minha instrução editada durante a consulta.'); assert.match(await s.page.locator('#story-block-candidate-context').textContent(), /anterior/i); await s.page.locator('#story-block-keep').tap(); assert.equal(await s.page.locator('#generate').isEnabled(), true); await s.context.close();
  });
  await pass('Settings own explicit PUTs readonly pins return focus/scroll', async () => {
    const s = await scenario(currentCase, {adopted: true}); await ready(s.page, `/roteiro?roteiro=${IDs.story}`); await s.page.locator('#story-next').tap(); await s.page.locator('#prompt').fill('Rascunho local preservado.'); await s.page.locator('#screen-title').focus(); const original = await s.page.evaluate(() => ({y: scrollY, focus: document.activeElement.id})); const postCount = posts(s.m).length; await tapTop(s.page, 'settings-open'); await active(s.page, 'settings'); assert.equal(await s.page.locator('#duration').inputValue(), '8');
    await s.page.getByText('Instruções do roteirista', {exact: true}).tap(); await s.page.locator('#story-system').fill('Divida a ideia sem inventar ação.'); await s.page.locator('#story-editor-save').tap(); await s.page.locator('#story-editor-status').filter({hasText: 'salvas'}).waitFor(); assert.equal(s.m.editor.system_prompt, 'Preserve ação, roupa, pose e ordem. Responda só com a cena.'); assert.equal(await s.page.locator('#story-model').inputValue(), pin); assert.equal(await s.page.locator('#story-model').getAttribute('readonly'), '');
    await s.page.getByText('Instruções do detalhamento', {exact: true}).tap(); await s.page.locator('#grok-system').fill('Detalhe somente a ação atual.'); await s.page.locator('#grok-save').tap(); await s.page.locator('#grok-config-status').filter({hasText: 'Configuração salva'}).waitFor(); assert.equal(s.m.macroEditor.system_prompt, 'Divida a ideia sem inventar ação.'); await capture(s.page, 'settings'); await tapTop(s.page, 'back'); await active(s.page, 'generation'); const restored = await s.page.evaluate(() => ({y: scrollY, focus: document.activeElement.id})); assert.equal(restored.focus, original.focus); assert.ok(Math.abs(restored.y - original.y) <= 2); assert.equal(await s.page.locator('#prompt').inputValue(), 'Rascunho local preservado.'); assert.equal(posts(s.m).length, postCount); await s.context.close();
  });
  for (const motion of ['reduce', 'no-preference']) await pass(`${motion} responsive document/touch/motion evidence`, async () => {
    const s = await scenario(currentCase, {adopted: true, motion, video: motion === 'no-preference'});
    s.m.runs = Array.from({length: 12}, (_, index) => nativeRun(`41000000-0000-4000-8500-${String(index + 1).padStart(12, '0')}`, 'accepted', null, 8, actions[0].repeat(12)));
    await ready(s.page); const count = posts(s.m).length;
    for (const [width, height] of [[393,852], [320,852], [640,852], [852,393], [1440,1000]]) { await s.page.setViewportSize({width, height}); await audit(s.page, `${motion}-library-${width}`); await s.page.locator('#story-library button').tap(); await active(s.page, 'story'); await audit(s.page, `${motion}-story-${width}`); await s.page.locator('#story-next').tap(); await active(s.page, 'generation'); await audit(s.page, `${motion}-workbench-${width}`); await ready(s.page); }
    await s.page.setViewportSize({width:393,height:852}); await ready(s.page); const clip = s.page.locator('.clip-card').first(); const box = await clip.boundingBox(); assert.ok(box); const pre = await s.page.evaluate(() => ({y:scrollY, list:document.getElementById('library').scrollTop, selection:getSelection().toString()})); const cdp = await s.context.newCDPSession(s.page); const x = Math.round(box.x + box.width / 2), y = Math.min(700, Math.round(box.y + 80));
    await s.page.waitForTimeout(400); await cdp.send('Input.dispatchTouchEvent', {type:'touchStart',touchPoints:[{x,y,id:1}]}); for(let i=1;i<=8;i++){ await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y-i*35,id:1}]}); await s.page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve))); } await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]}); await s.page.waitForTimeout(800); await cdp.detach();
    const post = await s.page.evaluate(() => ({y:scrollY, list:document.getElementById('library').scrollTop, selection:getSelection().toString()})); assert.ok(post.y > pre.y + 30, 'Real touch card drag scrolls document'); assert.equal(post.list, pre.list); assert.equal(post.selection, pre.selection); assert.equal(posts(s.m).length,count); report.audits.push({name:'actual-touch-drag',motion,pre,post,start:{x,y},end:{x,y:y-280}}); await capture(s.page, `${motion}-gesture-result`);
    await tapTop(s.page,'settings-open'); await active(s.page,'settings'); await tapTop(s.page,'back'); await active(s.page,'library'); await s.page.locator('#story-new').tap(); await active(s.page,'context'); assert.equal(posts(s.m).length,count); await s.page.emulateMedia({reducedMotion:'reduce'}); await s.page.waitForFunction(() => document.getAnimations().length === 0); await s.page.emulateMedia({reducedMotion:motion});
    const video = s.page.video(); await s.context.close(); if(video) report.video = await video.path();
  });
  await pass('Actual desktop non-touch context', async () => { const s = await scenario(currentCase,{adopted:true,desktop:true}); await ready(s.page); await audit(s.page,'desktop-library'); assert.equal(await s.page.evaluate(() => navigator.maxTouchPoints),0); await s.page.locator('#story-library button').click(); await active(s.page,'story'); await audit(s.page,'desktop-story'); await s.page.locator('#story-next').click(); await active(s.page,'generation'); await audit(s.page,'desktop-workbench'); assert.equal(posts(s.m).length,0); await s.context.close(); });
  for(const m of report.models){ assert.deepEqual(m.errors,[]); assert.deepEqual(m.violations,[]); const unique = intents(m).map(r => r.path); assert.equal(unique.length,new Set(unique).size,'One POST per known intent'); }
} catch(error) {
  report.firstFailure = {case: currentCase, message:error.message, stack:error.stack, classification:report.models.some(m=>m.errors.some(e=>e.startsWith('fixture:'))) ? 'fixture-contract failure' : 'app assertion or selector/state failure; inspect frozen source'};
  if (lastPage && !lastPage.isClosed()) { report.firstFailure.url = lastPage.url(); report.firstFailure.visibleState = await lastPage.locator('[data-screen]:visible').getAttribute('data-screen').catch(() => null); report.firstFailure.screenshot = resolve(directory,'first-failure.png'); await lastPage.screenshot({path:report.firstFailure.screenshot,fullPage:true}).catch(() => {}); }
  console.error(JSON.stringify(report.firstFailure,null,2)); process.exitCode = 1;
} finally {
  await browser.close(); report.protectedAfter = await protectedHashes(); report.sourceHashesAfter = Object.fromEntries(await Promise.all(Object.keys(assets).map(async name => [name,sha(await readFile(resolve(root,'src/h3_backend/web',name)))])));
  try { assert.deepEqual(report.protectedAfter,before); assert.deepEqual(report.sourceHashesAfter,sourceHashes); } catch(error) { report.integrityFailure = error.message; process.exitCode = 1; }
  report.counts = {passed:report.cases.length, requests:report.models.reduce((n,m)=>n+m.requests.length,0), nativeIntents:report.models.reduce((n,m)=>n+intents(m).length,0), fakeGrok:report.models.reduce((n,m)=>n+groks(m).length,0), fakeAssembly:report.models.reduce((n,m)=>n+assemblies(m).length,0), audits:report.audits.length, captures:report.captures.length};
  await writeFile(resolve(directory,'report.json'),JSON.stringify(report,null,2),{flag:'wx'});
  console.log(JSON.stringify({directory,counts:report.counts,firstFailure:report.firstFailure,sourceHashes,protectedUnchanged:JSON.stringify(report.protectedAfter)===JSON.stringify(before)},null,2));
}
