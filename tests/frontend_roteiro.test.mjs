import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {savedEditorMatches, editorPayload, relevantChange, batchDraftsClean, batchPointer, remainingStoryBlocks, verifiedBatch, freestyleConversionEnd, createBackSwipe, canonicalUUID, branchEndForSelection, validateBranchSequence, storyReviewOrigin, nativeExecutionBlocked, ownedIntentMatchingCurrent, readOwnedStoryIntent, rejectedStoryDraft, standaloneLocation, storyLocation, storyPointer, storyUpdate, storyBlockState, storyContext, createStoryClient, HTTPError} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const id = '11111111-1111-4111-8111-111111111111', block = '22222222-2222-4222-8222-222222222222', intent = '33333333-3333-4333-8333-333333333333';
const fixture = () => ({id, revision: 2, name: '<img onerror=evil()>', idea: 'Macro', reference: {source_root: 'inputs', path: 'own/original.png'}, reference_sha256: 'a'.repeat(64), adopted: true, blocks: [{id: block, action: 'Dance', prompt: ' exact FINAL\n', duration_seconds: 8, seed: 42}], attempts: []});
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
test('actual story renderer opens pending blocks and attaches organization actions', async () => {
  const handler = source.slice(source.indexOf('  function renderStory()'), source.indexOf('  async function saveStoryBlocks'));
  const nodes = new Map(), saved = [];
  const element = (tag, classes, value) => ({tag, textContent: value, children: [], dataset: {}, listeners: {}, append(...items) { this.children.push(...items); }, replaceChildren(...items) { this.children = items; }, addEventListener(event, callback) { this.listeners[event] = callback; }});
  const $ = key => { if (!nodes.has(key)) nodes.set(key, element('div')); return nodes.get(key); };
  const doc = fixture();
  doc.blocks.push({...doc.blocks[0], id: intent});
  const story = {doc};
  const deps = {story, $, element, storyBlocks: () => doc.blocks, storyBlockState, alignedFrames: () => 192, text: (key, value) => { $(key).textContent = value; }, batchBlocked: () => false, saveStoryBlocks: async blocks => { saved.push(blocks); }, STATE_LABELS: {}, document: {defaultView: {confirm: () => true}}};
  const render = new Function(...Object.keys(deps), `${handler}; return renderStory;`)(...Object.values(deps));
  render();
  assert.equal($('story-blocks').children.length, 2);
  const organize = $('story-blocks').children[0].children.find(node => node.tag === 'details');
  const moveDown = organize.children.at(-1);
  assert.equal(moveDown.disabled, false);
  await moveDown.listeners.click();
  assert.deepEqual(saved[0].map(item => item.id), [intent, block]);
});
test('story pointers preserve assembly, extras and hash before submission', () => {
  const result = storyLocation(`http://local/?assembly=${intent}&extra=x#viewer`, {id, block, intent});
  assert.equal(result, `/roteiro?assembly=${intent}&extra=x&roteiro=${id}&block=${block}&intent=${intent}#viewer`);
  assert.deepEqual(storyPointer(`http://local${result}`), {roteiro: id, block, intent});
  assert.throws(() => storyPointer(`http://local/?intent=${intent}`));
  assert.throws(() => storyPointer(`http://local/?roteiro=${id}&roteiro=${id}`));
});
test('standalone mode removes story context but retains assembly and pending recovery', () => {
  const href = `http://local/roteiro?roteiro=${id}&block=${block}&intent=${intent}&assembly=${intent}&pending_intent=${intent}&extra=x#viewer`;
  assert.equal(standaloneLocation(href), `/?assembly=${intent}&pending_intent=${intent}&extra=x#viewer`);
  const mode = source.slice(source.indexOf('function setMode(mode)'), source.indexOf('function storyURL'));
  assert.match(mode, /standaloneLocation/); assert.doesNotMatch(mode, /state\.(?:uncertain|busy|assemblyUncertain|pendingRun|uploadUncertain)\s*=/);
});
test('PUT emits all editable fields but never server revision/id/attempt authority', () => {
  const doc = fixture(), body = storyUpdate(doc);
  assert.deepEqual(Object.keys(body), ['expected_revision', 'name', 'idea', 'reference', 'adopted', 'blocks']);
  assert.equal(body.expected_revision, 2); assert.equal(body.blocks[0].id, block); assert.equal(body.blocks[0].prompt, ' exact FINAL\n');
  assert.equal(Object.hasOwn(body, 'reference_sha256'), false);
});
test('accepted positions require observed native publication and decision', () => {
  const doc = fixture(), item = doc.blocks[0];
  doc.attempts.push({block_id: block, state: 'accepted', run: null});
  assert.equal(storyBlockState(doc, item).accepted, undefined); assert.equal(storyBlockState(doc, item).frozen, true);
  doc.attempts.push({block_id: block, run: {state: 'accepted', output: {path: `.data/runs/${intent}/chunk.mp4`}}});
  assert.equal(storyBlockState(doc, item).accepted, doc.attempts[1]);
});
test('packed enhancer context is literal intention not invented visual proof', () => {
  const doc = fixture(), packed = storyContext(doc, block, '8');
  assert.match(packed, /visual result may differ/); assert.match(packed, /192 frames/); assert.match(packed, /exact FINAL/); assert.doesNotMatch(packed, /Roteiro:|Ideia geral:|Instrução escolhida:|Duração solicitada:|Contexto visual:/);
  doc.idea = 'Ideia original em português'; assert.match(storyContext(doc, block, '8'), /Ideia original em português/);
  assert.match(source, /action: 'Descreva a próxima ação\.', prompt: 'Describe the next action\.'/);
  doc.idea = 'x'.repeat(12000); assert.throws(() => storyContext(doc, block, '8'));
});
test('new intent is known and serialized once; duplicate POST never replays', async () => {
  const calls = [], client = createStoryClient(async (path, options) => { calls.push([path, options.method, JSON.parse(options.body)]); throw new Error('lost response'); });
  const body = {expected_revision: 2, prompt: 'FINAL', duration_seconds: 8, seed: 42, parent_id: null};
  await assert.rejects(client.generate(id, block, intent, body), /lost/);
  await assert.rejects(client.generate(id, block, intent, body), /consulte/);
  assert.deepEqual(calls, [[`/roteiros/${id}/blocks/${block}/attempts/${intent}`, 'POST', body]]);
});
test('recovery is GET same intent only, never native inference', async () => {
  const calls = [], client = createStoryClient(async (path, options) => { calls.push([path, options.method]); return response({intent_id: intent, admission: 'uncertain', run: null}); });
  await client.readIntent(id, block, intent); assert.deepEqual(calls, [[`/roteiros/${id}/blocks/${block}/attempts/${intent}`, 'GET']]);
});
test('macro proposal and configuration keep separate exact contracts', async () => {
  const calls = [], client = createStoryClient(async (path, options) => { calls.push([path, options.method, JSON.parse(options.body)]); return response({}); });
  await client.proposal(id, {expected_revision: 2, count: 3, duration_seconds: 8, seed: 42}); await client.saveEditor(' custom macro ');
  assert.deepEqual(calls, [[`/roteiros/${id}/proposal`, 'POST', {expected_revision: 2, count: 3, duration_seconds: 8, seed: 42}], ['/roteiros/editor', 'PUT', {system_prompt: ' custom macro '}]]);
});
test('revision conflict remains actionable and no automatic retry', async () => {
  let calls = 0; const client = createStoryClient(async () => { calls++; return response({detail: 'changed'}, 409); });
  await assert.rejects(client.save(id, storyUpdate(fixture())), error => error instanceof HTTPError && error.status === 409); assert.equal(calls, 1);
});
test('workspace IDs unique and proposal is inside same block preparation view', async () => {
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]); assert.equal(ids.length, new Set(ids).size);
  for (const key of ['story-new', 'story-create', 'story-blocks', 'story-block-candidate', 'story-intent-read', 'story-system', 'grok-system']) assert.ok(ids.includes(key));
  assert.doesNotMatch(source + html, /innerHTML|localStorage|sessionStorage|autoplay/);
  const generation = html.match(/<section id="panel-generation"[^]*?<\/section>/)[0]; assert.match(generation, /story-block-candidate/);
});
const caps = {default_requested_seconds: 8, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125};
function refused() {
  const doc = fixture(), owner = {id, block, intent};
  const attempt = {intent_id: intent, run_id: intent, roteiro_id: id, block_id: block, source_revision: 2, admission: 'rejected', state: 'not_admitted', run: null, snapshot: {prompt: '  FINAL rejected submission\n', seed: 17, duration_seconds: 2.3, parent_id: null, reference: {...doc.reference, sha256: doc.reference_sha256}}};
  doc.attempts = [structuredClone(attempt)]; return {doc, owner, attempt};
}
test('confirmed preflight refusal copies its literal snapshot, never invents a native Run', () => {
  const {doc, owner, attempt} = refused(), before = JSON.stringify(doc), copied = rejectedStoryDraft(doc, attempt, owner, caps);
  assert.equal(copied.key, `not-admitted:${intent}`); assert.equal(copied.chosenPrompt, attempt.snapshot.prompt); assert.equal(copied.duration, '2.3'); assert.equal(copied.seed, '17'); assert.equal(copied.parentId, null); assert.equal(copied.submitted, false); assert.equal(copied.sourceId, undefined); assert.equal(JSON.stringify(doc), before);
});
test('confirmed refusal preserves zero seed and older source revision after future plan edits', () => {
  const {doc, owner, attempt} = refused(); doc.revision = 3; attempt.snapshot.seed = 0; doc.attempts[0].snapshot.seed = 0;
  const copied = rejectedStoryDraft(doc, attempt, owner, caps); assert.equal(copied.seed, '0'); assert.equal(copied.duration, '2.3'); assert.equal(copied.chosenPrompt, attempt.snapshot.prompt);
});
for (const [name, mutate] of [
  ['wrong story owner', value => { value.owner.id = intent; }],
  ['wrong block owner', value => { value.owner.block = intent; }],
  ['wrong intent owner', value => { value.owner.intent = id; }],
  ['missing attempt', value => { value.attempt = null; }],
  ['uncertain admission', value => { value.attempt.admission = 'uncertain'; }],
  ['uncertain state', value => { value.attempt.state = 'uncertain'; }],
  ['missing native-null proof', value => { delete value.attempt.run; }],
  ['existing native run', value => { value.attempt.run = {id: intent}; }],
  ['missing snapshot', value => { value.attempt.snapshot = null; }],
  ['missing history', value => { value.doc.attempts = []; }],
  ['newer attempt exists', value => { value.doc.attempts.push({...value.attempt, intent_id: id}); }],
  ['different historical snapshot', value => { value.doc.attempts[0].snapshot.prompt = 'not this snapshot'; }],
  ['bad revision', value => { value.attempt.source_revision = 999; }],
  ['traversal reference', value => { value.attempt.snapshot.reference.path = '../private.png'; }],
  ['different identity SHA', value => { value.attempt.snapshot.reference.sha256 = 'b'.repeat(64); }],
  ['missing identity SHA', value => { delete value.doc.reference_sha256; }],
  ['blank prompt', value => { value.attempt.snapshot.prompt = ' '; }],
  ['coerced seed', value => { value.attempt.snapshot.seed = '17'; }],
  ['excess duration', value => { value.attempt.snapshot.duration_seconds = 10.01; }],
  ['coerced duration', value => { value.attempt.snapshot.duration_seconds = '2.3'; }],
  ['unexpected root parent', value => { value.attempt.snapshot.parent_id = id; }],
]) test(`preflight refusal recovery rejects ${name}`, () => { const value = refused(); mutate(value); if (value.attempt && value.doc.attempts.length === 1 && name !== 'different historical snapshot') value.doc.attempts[0].snapshot = structuredClone(value.attempt.snapshot); assert.throws(() => rejectedStoryDraft(value.doc, value.attempt, value.owner, caps)); });
function refusedContinuation() {
  const value = refused(), previousBlock = '44444444-4444-4444-8444-444444444444', parentID = '55555555-5555-4555-8555-555555555555';
  const parent = {id: parentID, state: 'accepted', output: {path: `.data/runs/${parentID}/chunk.mp4`}, references: [{type: 'image', role: 'identity', source_root: value.doc.reference.source_root, source: value.doc.reference.path, sha256: value.doc.reference_sha256}]};
  value.doc.blocks.unshift({...value.doc.blocks[0], id: previousBlock}); value.attempt.snapshot.parent_id = parentID;
  value.doc.attempts = [{block_id: previousBlock, run: parent}, structuredClone(value.attempt)]; return {...value, parent};
}
test('preflight-refused continuation keeps actual accepted original parent and identity', () => {
  const value = refusedContinuation(), copied = rejectedStoryDraft(value.doc, value.attempt, value.owner, caps);
  assert.equal(copied.parentId, value.parent.id); assert.equal(copied.mode, 'continue'); assert.equal(copied.chosenPrompt, value.attempt.snapshot.prompt);
});
for (const [name, mutate] of [
  ['parent rejected', value => { value.parent.state = 'rejected'; }],
  ['wrong original parent', value => { value.attempt.snapshot.parent_id = id; value.doc.attempts[1].snapshot.parent_id = id; }],
  ['parent publication absent', value => { value.parent.output = {}; }],
  ['parent identity mismatch', value => { value.parent.references[0].sha256 = 'b'.repeat(64); }],
]) test(`preflight refusal continuation blocks ${name}`, () => { const value = refusedContinuation(); mutate(value); assert.throws(() => rejectedStoryDraft(value.doc, value.attempt, value.owner, caps)); });
test('compact dual context is roteiro-only and solo identity spans its row', async () => {
  const css = await readFile(new URL('../src/h3_backend/web/app.css', import.meta.url), 'utf8');
  const compact = [...css.matchAll(/([^{}]+)\{([^{}]*height:170px[^{}]*)\}/g)].filter(rule => rule[1].includes('.visual-card')); assert.equal(compact.length, 1); assert.match(compact[0][1], /\.task-panel\.story-presentation/); assert.match(compact[0][1], /:not\(\.expanded\)/);
  assert.match(css, /\.task-panel\.story-presentation \.visual-contexts\{grid-template-columns:repeat\(2/);
  assert.match(css, /\.task-panel\.story-presentation \.visual-contexts\.single-context>\.visual-card:first-child\{grid-column:1\/-1\}/);
  assert.match(css, /@media\(max-width:340px\)\{\.task-panel\.story-presentation/);
  assert.match(source, /classList\.toggle\('story-presentation', Boolean\(story\.doc \|\| story\.creating\)\)/);
  const paint = source.slice(source.indexOf('function paintScreen('), source.indexOf('function viewSnapshot('));
  assert.match(paint, /classList\.toggle\('single-context', state\.mode !== 'continue' \|\| state\.parent\?\.state !== 'accepted'\)/);
  assert.doesNotMatch(paint, /stories\.(?:save|generate)|client\.(?:generate|detail)|newAssemblyUUID/);
});
test('fresh preflight-refused draft remains an explicit preparation with all native fences', () => {
  const handler = source.slice(source.indexOf('function prepareRejectedStory()'), source.indexOf('async function detailStoryBlock()'));
  assert.doesNotMatch(handler, /stories\.(?:save|generate)|client\.(?:generate|detail)|newAssemblyUUID/);
  for (const field of ['uncertain', 'uploadUncertain', 'assemblyUncertain', 'busy', 'uploadBusy', 'assemblyBusy']) assert.match(handler, new RegExp(`state\\.${field}`));
  assert.doesNotMatch(handler, /state\.(?:uncertain|assemblyUncertain|uploadUncertain|busy)\s*=/);
});
test('current intent consultation requires its exact canonical story/block/intent owner', () => {
  const doc = fixture(), owner = {id, block, intent};
  assert.equal(ownedIntentMatchingCurrent(doc, block, intent, owner), true);
  for (const [currentDoc, currentBlock, currentIntent, currentOwner] of [[doc, intent, intent, owner], [{...doc, id: intent}, block, intent, owner], [doc, block, id, owner], [null, block, intent, owner], [doc, block, intent, null], [doc, block, '../invalid', owner], [doc, block, intent, {...owner, block: null}], [{...doc, blocks: []}, block, intent, owner]]) assert.equal(ownedIntentMatchingCurrent(currentDoc, currentBlock, currentIntent, currentOwner), false);
});
test('old root intent on a new child performs no HTTP; exact uncertain owner is readable by GET', async () => {
  const doc = fixture(), child = '66666666-6666-4666-8666-666666666666', owner = {id, block, intent}, calls = [];
  doc.blocks.push({...doc.blocks[0], id: child});
  const client = createStoryClient(async (path, options) => { calls.push([path, options.method]); return response({intent_id: intent, admission: 'uncertain', run: null}); });
  assert.equal(await readOwnedStoryIntent(client, doc, child, intent, owner), null); assert.deepEqual(calls, []);
  const result = await readOwnedStoryIntent(client, doc, block, intent, owner); assert.equal(result.admission, 'uncertain');
  assert.deepEqual(calls, [[`/roteiros/${id}/blocks/${block}/attempts/${intent}`, 'GET']]);
});
test('intent UI rejects owner mismatch before reads or any uncertainty mutation', () => {
  const handler = source.slice(source.indexOf('async function readStoryIntent()'), source.indexOf('function prepareRejectedStory()'));
  assert.match(handler, /if \(!ownedIntentMatchingCurrent\(story\.doc, story\.block, story\.intent, story\.intentOwner\) \|\| state\.busy\) return;/);
  assert.match(source, /\$\('story-intent-read'\)\.hidden = !ownIntent/); assert.match(source, /\$\('story-intent-read'\)\.disabled = !ownIntent \|\| state\.busy/);
  const routing = source.slice(source.indexOf('function setMode(mode)'), source.indexOf('function storyURL'));
  assert.doesNotMatch(routing, /state\.(?:uncertain|busy|assemblyUncertain|uploadUncertain)\s*=/);
  assert.match(source, /text\('continue-mode', story\.doc && story\.block \? nextStoryBlock/); assert.match(source, /'Preparar montagem' : 'Preparar continuação'/);
});
test('every story admission 4xx remains submitted/status-only until own intent GET proof', () => {
  const handler = source.slice(source.indexOf('async function generate(event)'), source.indexOf("for (const id of ['idea', 'prompt'"));
  const expression = handler.match(/state\.uncertain = ([^;]+);/)[1];
  assert.equal(expression, 'Boolean(storyIntent) || admittedID !== null || !(error instanceof HTTPError) || error.status >= 500');
  // Execute the actual handler condition in isolation; no network or UI startup.
  const uncertain = Function('storyIntent', 'admittedID', 'error', 'HTTPError', `return (${expression});`);
  assert.match(handler, /submittedDraft\.submitted = state\.uncertain \|\| admittedID !== null/);
  assert.match(handler, /state\.statusOnly = state\.uncertain \|\| admittedID !== null/);
  for (const status of [400, 401, 403, 404, 409, 422, 429]) {
    const error = new HTTPError(status, 'No admission conclusion from response detail');
    const fenced = uncertain(intent, null, error, HTTPError); assert.equal(fenced, true);
    assert.equal(nativeExecutionBlocked({config: {}, mode: 'new', uncertain: fenced, submitted: fenced, statusOnly: fenced}), true);
    assert.equal(uncertain(null, null, error, HTTPError), false, `standalone HTTP ${status} preserves prior semantics`);
  }
});
test('library deletion uses explicit DELETE contracts without inference', async () => {
  const calls = [];
  const api = createStoryClient(async (url, options = {}) => { calls.push({url, options}); return response({removed: true}); });
  await api.remove(id, 2);
  assert.equal(calls[0].url, `/roteiros/${id}`);
  assert.equal(calls[0].options.method, 'DELETE');
  assert.deepEqual(JSON.parse(calls[0].options.body), {expected_revision: 2});
  const handler = source.slice(source.indexOf('async function removeLibraryItem'), source.indexOf('async function storyLibrary'));
  assert.match(handler, /navigation === state.navigationEpoch/);
  assert.match(handler, /deletedRunIDs.has\(state.selected\?\.id\)/);
  assert.match(handler, /button.disabled = false/);
  assert.doesNotMatch(handler, /client\.(detail|generate|accept)|stories\.(proposal|create)/);
  assert.match(source, /card.append\(button, cardTools\(favoriteButton\('freestyle', run.id\), deleteButton\('Apagar bloco'/);
});
function deletionFixture() {
  const handler = source.slice(source.indexOf('  async function removeLibraryItem'), source.indexOf('  async function storyLibrary'));
  const state = {navigationEpoch: 1, screen: 'review', epoch: 0, selected: {id}, sequence: {blocks: []}};
  const story = {doc: fixture(), block, candidate: {}, editing: block};
  const calls = [], messages = [], buttons = [{disabled: true}];
  let confirm = true, gate = Promise.resolve();
  const remove = async (...args) => { calls.push(args); await gate; };
  const deps = {state, story, batchBlocked: () => false, document: {defaultView: {confirm: () => confirm}, querySelectorAll: () => buttons}, stories: {remove}, client: {remove}, renderLibrary() {}, storyURL() {}, renderRun() {}, storyLibrary: async () => {}, loadLibrary: async () => {}, navigate: screen => { state.screen = screen; }, message: (...args) => messages.push(args)};
  const invoke = new Function(...Object.keys(deps), `let deleting = false, libraryEpoch = 0; const removedStories = new Set(), removedRuns = new Set(); ${handler}; return removeLibraryItem;`)(...Object.values(deps));
  return {state, story, calls, buttons, messages, invoke, cancel: () => { confirm = false; }, wait: promise => { gate = promise; }};
}
test('actual deletion handler cancels and fences busy without requests', async () => {
  const cancelled = deletionFixture(); cancelled.cancel(); await cancelled.invoke('run', {id}); assert.equal(cancelled.calls.length, 0);
  const busy = deletionFixture(); busy.state.uncertain = true; await busy.invoke('run', {id}); assert.equal(busy.calls.length, 0);
});
test('actual deletion handler clears selected media and reenables buttons', async () => {
  const f = deletionFixture(); await f.invoke('run', {id}); assert.deepEqual(f.calls, [[id]]); assert.equal(f.state.selected, null); assert.equal(f.state.screen, 'library'); assert.equal(f.buttons[0].disabled, false);
  const s = deletionFixture(); const doc = {...fixture(), attempts: [{run_id: id}]}; await s.invoke('story', doc); assert.deepEqual(s.calls, [[id, 2]]); assert.equal(s.state.selected, null); assert.equal(s.story.doc, null);
});
test('actual deletion handler keeps newer scene and draft on late response', async () => {
  const f = deletionFixture(); let resolve; f.wait(new Promise(done => { resolve = done; })); const pending = f.invoke('run', {id});
  f.state.navigationEpoch++; f.state.screen = 'context'; f.state.selected = {id: block}; f.state.parent = {id: block}; f.state.pendingRun = {id: intent}; f.state.uncertain = true;
  resolve(); await pending;
  assert.equal(f.state.screen, 'context'); assert.equal(f.state.selected.id, block); assert.equal(f.state.parent.id, block); assert.equal(f.state.pendingRun.id, intent); assert.equal(f.state.uncertain, true);
});

const branchIds = Array.from({length: 12}, (_, i) => `${String(i + 1).padStart(8, '0')}-1111-4111-8111-111111111111`);
const branchFixture = (count = 12) => ({end_run_id: branchIds[count - 1], root_id: branchIds[0], blocks: branchIds.slice(0, count).map((id, i) => ({id, parent_id: i ? branchIds[i - 1] : null}))});
test('filmstrip keeps explicit block12 branch while selected block7 ancestry remains separate', () => {
  const full = branchFixture(), ancestor = branchIds[6];
  assert.equal(branchEndForSelection(ancestor, full, true), branchIds[11]);
  assert.equal(branchEndForSelection(ancestor, full), ancestor);
  assert.equal(branchEndForSelection(id, full, true), id);
  assert.equal(branchEndForSelection(ancestor, null, false, branchIds[11]), branchIds[11]);
  assert.equal(validateBranchSequence(full, branchIds[11], ancestor), full);
  assert.throws(() => validateBranchSequence({...full, end_run_id: ancestor}, branchIds[11], ancestor));
  assert.throws(() => validateBranchSequence({...full, blocks: [...full.blocks.slice(0, 6), {...full.blocks[6], parent_id: id}, ...full.blocks.slice(7)]}, branchIds[11], ancestor));
  assert.throws(() => validateBranchSequence(full, branchIds[11], id));
});
test('roteiro review origin returns all planned blocks while settings keeps review origin', () => {
  const doc = {...fixture(), attempts: [{run_id: id}]}, previous = {screen: 'generation', draftKey: 'active', storyDoc: doc, storyCandidate: {blocks: []}};
  const remembered = {screen: 'story', storyDoc: doc, scroll: 120, draftKey: 'earlier'};
  const result = storyReviewOrigin(previous, doc, id, block, intent, [remembered]);
  assert.equal(result.screen, 'story'); assert.equal(result.scroll, 120); assert.equal(result.storyCandidate, previous.storyCandidate);
  assert.equal(storyReviewOrigin(previous, doc, intent, block, intent).screen, 'story');
  assert.equal(storyReviewOrigin(previous, doc, block, null, null), previous);
  const navigation = source.slice(source.indexOf('  function navigate('), source.indexOf('  async function restoreView('));
  assert.match(navigation, /screen === 'review' \? storyReviewOrigin/);
  assert.match(source, /branchEnd: state.openedBranchEnd/);
  assert.match(source, /snapshot.branchEnd !== state.openedBranchEnd/);
});
function selectionFixture() {
  const handler = source.slice(source.indexOf('  async function select('), source.indexOf('  async function loadConfig('));
  const state = {epoch: 0, navigationEpoch: 0, draftRevision: 0, branchSequence: branchFixture(), openedBranchEnd: branchIds[11], selected: {id: branchIds[11]}};
  const calls = [], story = {doc: null}; let gate = Promise.resolve();
  const client = {get: async path => { calls.push(path); await gate; const selected = path.split('/')[2]; const count = branchIds.indexOf(selected) + 1; return path.endsWith('/sequence') ? branchFixture(count) : {id: selected}; }};
  const deps = {state, story, client, stopped: false, loadingScreen: {begin() {}, end() {}}, canonicalUUID: value => value, branchEndForSelection, validateBranchSequence, text() {}, message() {}, renderRun() {}, renderSequence() {}, loadAssemblies: async () => {}};
  return {state, calls, client, select: new Function(...Object.keys(deps), `${handler}; return select;`)(...Object.values(deps)), wait: value => { gate = value; }};
}
test('actual ancestor selection and refresh GET exact opened end without truncating display', async () => {
  const f = selectionFixture(); await f.select(branchIds[6], undefined, {preserveBranch: true});
  assert.equal(f.state.sequence.end_run_id, branchIds[6]); assert.equal(f.state.sequence.blocks.length, 7);
  assert.equal(f.state.branchSequence.end_run_id, branchIds[11]); assert.equal(f.state.branchSequence.blocks.length, 12);
  assert.ok(f.calls.includes(`/runs/${branchIds[11]}/sequence`));
  await f.select(branchIds[6], undefined, {preserveBranch: true}); assert.equal(f.state.branchSequence.blocks.length, 12);
  await f.select(branchIds[3]); assert.equal(f.state.branchSequence.blocks.length, 4);
});
test('actual selection discards stale run response after home navigation', async () => {
  const f = selectionFixture(); let resolve; f.wait(new Promise(done => { resolve = done; })); const pending = f.select(branchIds[6], undefined, {preserveBranch: true});
  f.state.navigationEpoch++; resolve(); await pending; assert.equal(f.state.selected.id, branchIds[11]); assert.equal(f.calls.length, 1);
});

test('home uses navigation only and keeps unsaved roteiro edits behind the explicit save guard', async () => {
  const handler = source.slice(source.indexOf('  function goHome()'), source.indexOf('  function openSettings('));
  const state = {screen: 'story', uncertain: true, pendingRun: {id}, drafts: new Map([['own', {submitted: true}]])}, story = {editing: block, candidate: {blocks: []}}, unsaved = {hidden: true}, calls = [];
  const goHome = new Function('state', 'story', '$', 'navigate', `${handler}; return goHome;`)(state, story, () => unsaved, screen => calls.push(screen));
  goHome(); assert.deepEqual(calls, []); assert.equal(story.pendingEdit, 'home'); assert.equal(unsaved.hidden, false); assert.equal(story.editing, block);
  story.editing = null; goHome(); assert.deepEqual(calls, ['library']); assert.equal(state.uncertain, true); assert.equal(state.pendingRun.id, id); assert.equal(state.drafts.get('own').submitted, true); assert.ok(story.candidate);
  assert.doesNotMatch(handler, /client|stories|POST|uuid|uncertain\s*=/i);
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
  assert.match(html, /<button id="screen-eyebrow"[^>]+type="button"[^>]+aria-label="Estúdio local: abrir biblioteca"/);
  assert.match(source, /stop\(\); play\(heading, 'cue'\)/);
});

test('known display anchor survives unavailable frames and refresh never anchors selected ancestor', () => {
  assert.equal(branchEndForSelection(branchIds[6], null, true, null, branchIds[11]), branchIds[11]);
  const selectSource = source.slice(source.indexOf('  async function select('), source.indexOf('  async function loadConfig('));
  assert.ok(selectSource.indexOf('if (run.id !== id)') < selectSource.indexOf('state.selected = run'));
  assert.doesNotMatch(selectSource.slice(selectSource.indexOf('catch (error)')), /openedBranchEnd\s*=/);
  const restore = source.slice(source.indexOf('  async function restoreView('), source.indexOf('  function back('));
  assert.match(restore, /removedStories.has\(snapshot.storyDoc\?\.id\)/);
  assert.match(restore, /state.selected\?\.id !== snapshot.selectedId/);
  assert.match(source, /state.trail = state.trail.slice\(0, prior\)/);
});

test('actual navigation replaces generation entry after roteiro so Back reaches story once', () => {
  const handler = source.slice(source.indexOf('  function navigate('), source.indexOf('  async function restoreView('));
  const doc = {...fixture(), attempts: [{run_id: id}]}, storyView = {screen: 'story', storyDoc: doc, selectedId: null};
  const state = {screen: 'generation', navigationEpoch: 0, retryEpoch: 0, selected: {id}, trail: [{screen: 'library'}, storyView]};
  const story = {doc, block, intent}, historyViews = new Map(), recorded = [];
  const snapshot = () => ({screen: state.screen, storyDoc: doc, selectedId: id});
  const deps = {state, story, TITLES: {review: 'Review', settings: 'Settings'}, saveDraft() {}, storyReviewOrigin, viewSnapshot: snapshot, historyViews, historyToken: 2, paintScreen() {}, controls() {}, recordView: (value, push) => recorded.push({value, push})};
  const navigate = new Function(...Object.keys(deps), `${handler}; return navigate;`)(...Object.values(deps));
  navigate('review'); assert.equal(recorded[0].push, false); assert.deepEqual(state.trail.map(view => view.screen), ['library', 'story']); assert.equal(state.screen, 'review');
  navigate('settings'); assert.equal(recorded[1].push, true); assert.deepEqual(state.trail.map(view => view.screen), ['library', 'story', 'review']);
});

test('actual selection rejects mismatched run and retains end12 through transient anchor failure', async () => {
  const bad = selectionFixture(); bad.client.get = async () => ({id}); await bad.select(branchIds[6]); assert.equal(bad.state.selected.id, branchIds[11]);
  const f = selectionFixture(), read = f.client.get; let unavailable = true;
  f.client.get = async path => { if (unavailable && path === `/runs/${branchIds[11]}/sequence`) throw new Error('temporarily unavailable'); return read(path); };
  await f.select(branchIds[6], undefined, {preserveBranch: true}); assert.equal(f.state.openedBranchEnd, branchIds[11]); assert.equal(f.state.branchSequence, null);
  unavailable = false; await f.select(branchIds[6], undefined, {preserveBranch: true}); assert.equal(f.state.branchSequence.blocks.length, 12); assert.equal(f.state.sequence.blocks.length, 7);
});
test('actual restore of an own deleted item returns library before using deleted metadata', async () => {
  const handler = source.slice(source.indexOf('  async function restoreView('), source.indexOf('  function back('));
  const calls = [], deps = {removedStories: new Set([id]), removedRuns: new Set([intent]), navigate: (...args) => calls.push(args), message() {}};
  const restore = new Function(...Object.keys(deps), `${handler}; return restoreView;`)(...Object.values(deps));
  await restore({screen: 'story', storyDoc: {id}}, []); await restore({screen: 'review', selectedId: intent}, []);
  assert.deepEqual(calls.map(call => call[0]), ['library', 'library']);
});
test('actual restore preserves unrelated draft when deleted selection was incidental', async () => {
  const handler = source.slice(source.indexOf('  async function restoreView('), source.indexOf('  function back('));
  const state = {navigationEpoch: 0, retryEpoch: 0, selected: null, uncertain: true, pendingRun: {id: block}}, story = {}, calls = [];
  const node = {disabled: false, closest: () => null, matches: () => false, focus() {}};
  const deps = {state, story, removedStories: new Set(), removedRuns: new Set([id]), navigate: screen => calls.push(screen), message() {}, stopped: false, saveDraft() {}, restoreDraft() {}, draft: () => ({submitted: false}), paintScreen() {}, controls() {}, $: () => node, document: {defaultView: {scrollTo() {}}}, recordView() {}};
  const restore = new Function(...Object.keys(deps), `${handler}; return restoreView;`)(...Object.values(deps));
  await restore({screen: 'context', mode: 'new', draftKey: 'isolated-own-draft', parent: null, selectedId: id, statusOnly: false, scroll: 0}, []);
  assert.deepEqual(calls, []); assert.equal(state.screen, 'context'); assert.equal(state.draftKey, 'isolated-own-draft'); assert.equal(state.uncertain, true); assert.equal(state.pendingRun.id, block);
});
test('batch eligibility requires adopted accepted prefix and a never-attempted suffix', () => {
  const doc = fixture(); assert.equal(remainingStoryBlocks(doc).length, 1);
  doc.adopted = false; assert.deepEqual(remainingStoryBlocks(doc), []); doc.adopted = true;
  doc.attempts.push({block_id: block, run: {state: 'ready_for_review'}}); assert.deepEqual(remainingStoryBlocks(doc), []);
  doc.attempts[0].run.state = 'interrupted'; assert.deepEqual(remainingStoryBlocks(doc), []);
  doc.attempts[0].run = {state: 'accepted', output: {path: 'own'}}; doc.blocks.push({...doc.blocks[0], id: intent}); assert.deepEqual(remainingStoryBlocks(doc).map(item => item.id), [intent]);
  doc.attempts.push({block_id: intent, state: 'uncertain'}); assert.deepEqual(remainingStoryBlocks(doc), []);
});
test('own batch pointer/client submit once and recover by GET only', async () => {
  assert.deepEqual(batchPointer(`http://local/?batch=${intent}&batch_roteiro=${id}`), {id: intent, roteiro: id});
  assert.throws(() => batchPointer(`http://local/?batch=${intent}`));
  const calls = [], api = createStoryClient(async (url, options) => { calls.push({url, options}); return response({id: intent}, options.method === 'POST' ? 202 : 200); });
  await api.startBatch(id, intent, 2); await assert.rejects(api.startBatch(id, intent, 2)); await api.readBatch(id, intent);
  assert.deepEqual(calls.map(call => call.options.method), ['POST', 'GET']); assert.deepEqual(JSON.parse(calls[0].options.body), {expected_revision: 2, auto_accept_intermediate: true, enhance_with_grok: true});
  const value = {id: intent, roteiro_id: id, source_revision: 2, enhance_with_grok: true, expected_current_revision: 2, enhancement_ids: [], phase: null, stop_requested: false, state: 'active', blocks: [block], completed_block_ids: []}; assert.equal(verifiedBatch(value, {id: intent, roteiro: id}), value); assert.throws(() => verifiedBatch({...value, id: block}, {id: intent, roteiro: id}));
});
test('conversion chooses full explicit block12 even selected block7 and POSTs own known roteiro once', async () => {
  assert.equal(freestyleConversionEnd(branchIds[11], branchFixture(), branchIds[6]), branchIds[11]); assert.throws(() => freestyleConversionEnd(null, branchFixture(), branchIds[6])); assert.throws(() => freestyleConversionEnd(branchIds[11], null, branchIds[6]));
  const calls = [], api = createStoryClient(async (url, options) => { calls.push({url, options}); return response({id}, 201); });
  await api.convertFreestyle(branchIds[11], id); await assert.rejects(api.convertFreestyle(branchIds[11], id));
  assert.equal(calls[0].url, `/roteiros/from-freestyle/${branchIds[11]}`); assert.deepEqual(JSON.parse(calls[0].options.body), {roteiro_id: id});
});
test('Freestyle labels and batch option below planned blocks, conversion inside Operações', async () => {
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /Blocos avulsos|Ficha do bloco|>Novo bloco</);
  assert.match(html, /<summary><span>Freestyle<\/span>/); assert.ok(html.indexOf('id="story-batch"') > html.indexOf('id="story-blocks"'));
  const operations = html.slice(html.indexOf('<summary>Operações</summary>'), html.indexOf('</details>', html.indexOf('<summary>Operações</summary>')));
  assert.match(operations, /id="open-assembly"/); assert.match(operations, /id="convert-story"/);
});
function swipeFixture() {
  const handlers = new Map(), options = [], calls = []; let epoch = 0, enabled = true;
  const document = {addEventListener: (name, fn, opts) => { handlers.set(name, fn); options.push(opts); }, removeEventListener: name => handlers.delete(name)};
  const swipe = createBackSwipe(document, {back: () => calls.push('back'), canGoBack: () => enabled, navigationEpoch: () => epoch});
  const event = (x, y, extra = {}) => ({pointerType: 'touch', pointerId: 1, isPrimary: true, clientX: x, clientY: y, target: {closest: () => false}, preventDefault() { throw new Error('Native gesture must not be blocked'); }, ...extra});
  return {handlers, calls, options, swipe, event, advance: () => epoch++, root: () => { enabled = false; }};
}
test('edge swipe triggers same Back only for intentional horizontal touch and passive native events', () => {
  const f = swipeFixture(); f.handlers.get('pointerdown')(f.event(12, 100)); f.handlers.get('pointermove')(f.event(70, 102)); f.handlers.get('pointerup')(f.event(110, 106)); assert.deepEqual(f.calls, ['back']); assert.ok(f.options.every(option => option.passive));
  for (const scenario of ['vertical', 'cancel', 'navigation', 'two-fingers', 'native', 'root', 'middle']) {
    const s = swipeFixture(); if (scenario === 'root') s.root(); s.handlers.get('pointerdown')(s.event(scenario === 'middle' ? 80 : 12, 100, scenario === 'native' ? {target: {closest: () => true}} : {}));
    if (scenario === 'vertical') s.handlers.get('pointermove')(s.event(18, 140));
    if (scenario === 'cancel') s.handlers.get('pointercancel')();
    if (scenario === 'navigation') s.advance();
    if (scenario === 'two-fingers') s.handlers.get('pointerdown')(s.event(12, 100, {pointerId: 2, isPrimary: false}));
    s.handlers.get('pointerup')(s.event(115, 102)); assert.equal(s.calls.length, 0, scenario);
    s.swipe.destroy(); assert.equal(s.handlers.size, 0);
  }
});
function navigationHistoryFixture() {
  const record = source.slice(source.indexOf('  function recordView('), source.indexOf('  function navigate('));
  const navigate = source.slice(source.indexOf('  function navigate('), source.indexOf('  async function restoreView('));
  const restore = source.slice(source.indexOf('  async function restoreView('), source.indexOf('  function back('));
  const back = source.slice(source.indexOf('  function back('), source.indexOf('  function goHome('));
  const pop = source.slice(source.indexOf("addEventListener('popstate', event => {") + "addEventListener('popstate', ".length, source.indexOf("  if (document.defaultView?.history) document.defaultView.history.scrollRestoration"));
  const popFunction = pop.slice(0, pop.lastIndexOf(');')).trim();
  const state = {screen: 'library', trail: [], mode: 'new', draftKey: 'own', selected: null, navigationEpoch: 0, retryEpoch: 0, config: {}, uncertain: true, pendingRun: {id: intent}, openedBranchEnd: null}, story = {doc: null, block: null, intent: null, editing: null};
  const entries = []; let cursor = -1, popstate;
  const location = {href: 'http://local/'};
  const history = {state: null, pushState(value, unused, url) { entries.splice(cursor + 1); entries.push({value, url}); cursor++; this.state = value; location.href = new URL(url, location.href).href; }, replaceState(value, unused, url) { if (cursor < 0) { entries.push({value, url}); cursor = 0; } else entries[cursor] = {value, url}; this.state = value; location.href = new URL(url, location.href).href; }, back() { if (cursor > 0) { cursor--; this.state = entries[cursor].value; location.href = new URL(entries[cursor].url, location.href).href; popstate({state: this.state}); } }, forward() { if (cursor + 1 < entries.length) { cursor++; this.state = entries[cursor].value; popstate({state: this.state}); } }};
  const node = {disabled: false, closest: () => null, matches: () => false, focus() {}};
  const deps = {state, story, document: {defaultView: {history, location, scrollTo() {}}}, removedStories: new Set(), removedRuns: new Set(), TITLES: {library: 'Library', story: 'Story', generation: 'Generation', review: 'Review', settings: 'Settings'}, storyReviewOrigin, saveDraft() {}, restoreDraft() {}, draft: () => ({submitted: true}), paintScreen() {}, controls() {}, $: () => node, message() {}, stopped: false, select: async selectedId => { state.selected = {id: selectedId}; }, viewSnapshot: () => ({screen: state.screen, mode: state.mode, draftKey: state.draftKey, parent: null, statusOnly: false, storyDoc: story.doc, storyBlock: story.block, selectedId: state.selected?.id || null, branchEnd: null, scroll: 0})};
  const runtime = new Function(...Object.keys(deps), `const historyViews = new Map(); let historyToken = 0, historySerial = 0; ${record}${navigate}${restore}${back} const popstate = ${popFunction}; recordView(); return {navigate, back, popstate};`)(...Object.values(deps));
  popstate = runtime.popstate;
  return {state, story, history, entries, ...runtime};
}
test('real navigation record/popstate preserves library→roteiro→block→Back→roteiro→Back→library', async () => {
  const f = navigationHistoryFixture(); f.story.doc = {...fixture(), attempts: [{run_id: id}]}; f.navigate('story'); const origin = {screen: 'story', storyDoc: f.story.doc, selectedId: null, mode: 'new', draftKey: 'own'}; f.story.block = block; f.state.selected = {id}; f.navigate('review', {origin});
  f.back(); await Promise.resolve(); assert.equal(f.state.screen, 'story'); assert.equal(f.story.doc.id, id); assert.equal(f.state.uncertain, true); assert.equal(f.state.pendingRun.id, intent);
  f.back(); await Promise.resolve(); assert.equal(f.state.screen, 'library'); f.history.forward(); await Promise.resolve(); assert.equal(f.state.screen, 'story'); f.history.forward(); await Promise.resolve(); assert.equal(f.state.screen, 'review');
});
test('real history generated review and settings Back each restore exactly one intended screen', async () => {
  const f = navigationHistoryFixture(); f.story.doc = {...fixture(), attempts: [{run_id: id}]}; f.navigate('story'); f.navigate('generation'); f.story.block = block; f.state.selected = {id}; f.navigate('review'); assert.equal(f.entries.length, 3);
  f.navigate('settings'); f.back(); await Promise.resolve(); assert.equal(f.state.screen, 'review'); f.back(); await Promise.resolve(); assert.equal(f.state.screen, 'story'); f.back(); await Promise.resolve(); assert.equal(f.state.screen, 'library');
});
test('actual batch submission retains own uncertain ID and recovery never repeats POST', async () => {
  const start = source.slice(source.indexOf('  async function startBatch()'), source.indexOf('  function retryBlocked('));
  const read = source.slice(source.indexOf('  async function readBatch()'), source.indexOf('  async function startBatch()'));
  const state = {editorReady: true, editorSnapshot: {system_prompt: 'editor', model: 'fixed'}, drafts: new Map(), batchEpoch: 0, batchOwner: null, batchUncertain: false, batchReading: false, batchRecord: null}, story = {doc: fixture(), editing: null, candidate: null}, calls = [], counts = {uuid: 0};
  const record = {id: intent, roteiro_id: id, source_revision: 2, enhance_with_grok: true, expected_current_revision: 2, enhancement_ids: [], phase: null, stop_requested: false, state: 'active', blocks: [story.doc.blocks[0]], completed_block_ids: [], current_block_id: block, current_run_id: intent};
  const deps = {state, story, $: node => ({disabled: false, value: node === 'story-name' ? story.doc.name : node === 'grok-system' ? 'editor' : node === 'grok-model' ? 'fixed' : ''}), savedEditorMatches, batchDraftsClean, retryBlocked: () => state.batchUncertain || state.batchRecord?.state === 'active', remainingStoryBlocks, verifiedBatch, document: {defaultView: {confirm: () => true, crypto: {}}}, newAssemblyUUID: () => { counts.uuid++; return intent; }, batchURL() {}, saveDraft() {}, controls() {}, message() {}, stopped: false, renderStory() {}, stories: {startBatch: async (...args) => { calls.push(['POST', ...args]); throw new Error('connection lost'); }, readBatch: async (...args) => { calls.push(['GET', ...args]); return record; }, read: async () => story.doc}};
  const runtime = new Function(...Object.keys(deps), `${start}${read}; return {startBatch, readBatch};`)(...Object.values(deps));
  await runtime.startBatch(); assert.equal(state.batchOwner.id, intent); assert.equal(state.batchUncertain, true); await runtime.startBatch(); assert.equal(counts.uuid, 1); assert.equal(calls.length, 1);
  await runtime.readBatch(); assert.deepEqual(calls.map(call => call[0]), ['POST', 'GET']); assert.equal(state.batchRecord.state, 'active'); assert.equal(state.batchUncertain, false); await runtime.startBatch(); assert.equal(calls.length, 2);
});
test('actual conversion submission uses opened end and uncertain recovery reads known UUID only', async () => {
  const convert = source.slice(source.indexOf('  async function convertFreestyle()'), source.indexOf('  function batchBlocked()'));
  const read = source.slice(source.indexOf('  async function readConversion()'), source.indexOf('  async function convertFreestyle()'));
  const state = {selected: {id: branchIds[6]}, openedBranchEnd: branchIds[11], branchSequence: branchFixture(), conversionBusy: false, conversionUncertain: false, navigationEpoch: 0}, calls = [], counts = {uuid: 0};
  const deps = {state, $: () => ({disabled: false}), batchBlocked: () => false, freestyleConversionEnd, document: {defaultView: {confirm: () => true, crypto: {}}}, newAssemblyUUID: () => { counts.uuid++; return id; }, conversionURL() {}, saveDraft() {}, controls() {}, message() {}, useConvertedStory: async (doc, expected) => { assert.equal(doc.id, expected); state.conversionUncertain = false; }, stories: {convertFreestyle: async (...args) => { calls.push(['POST', ...args]); throw new Error('response lost'); }, read: async known => { calls.push(['GET', known]); return fixture(); }}};
  const runtime = new Function(...Object.keys(deps), `${convert}${read}; return {convertFreestyle, readConversion};`)(...Object.values(deps));
  await runtime.convertFreestyle(); assert.deepEqual(calls, [['POST', branchIds[11], id]]); assert.equal(state.conversionUncertain, true); await runtime.convertFreestyle(); assert.equal(counts.uuid, 1); await runtime.readConversion(); assert.deepEqual(calls[1], ['GET', id]); assert.equal(state.selected.id, branchIds[6]);
});
test('batch never ignores unsaved per-block prompts and ignores unrelated Freestyle drafts', () => {
  const doc = fixture(), drafts = new Map([['new', {chosenPrompt: 'unrelated'}]]); assert.equal(batchDraftsClean(doc, drafts), true);
  drafts.set(`story:${id}:${block}`, {submitted: false, chosenPrompt: doc.blocks[0].prompt, idea: doc.blocks[0].action, seed: '42', duration: '8'}); assert.equal(batchDraftsClean(doc, drafts), true);
  drafts.get(`story:${id}:${block}`).chosenPrompt = 'custom English prompt pending'; assert.equal(batchDraftsClean(doc, drafts), false);
});
function stopFixture(batch = null) {
  const handler = source.slice(source.indexOf('  async function stopOwned('), source.indexOf('  async function loadStopViews('));
  const run = {id, state: 'running'}, state = {pendingRun: run, items: [run], selected: {id: block}, globalBatchRecord: batch, batchRecord: batch, batchOwner: batch ? {id: batch.id, roteiro: batch.roteiro_id} : null, uncertain: false, stopBusy: false, stopUncertain: false}, calls = [];
  const deps = {state, canonicalUUID, verifiedBatch, submittedStops: new Set(), stopURL() {}, controls() {}, renderRun() {}, message() {}, stopViews: {}, client: {stopRun: async ident => { calls.push(['run', ident]); return {id: ident, state: 'interrupted'}; }}, stories: {stopBatch: async (doc, ident) => { calls.push(['batch', doc, ident]); return {...batch, state: 'stopped'}; }}};
  const stop = new Function(...Object.keys(deps), `${handler}; return stopOwned;`)(...Object.values(deps));
  return {state, calls, stop, client: deps.client};
}
test('actual card STOP targets own confirmed run once without touching newer selection', async () => {
  const f = stopFixture(); await f.stop('run'); await f.stop('run'); assert.deepEqual(f.calls, [['run', id]]); assert.equal(f.state.pendingRun.state, 'interrupted'); assert.equal(f.state.selected.id, block); assert.equal(f.state.stopUncertain, false);
  const uncertain = stopFixture(); uncertain.state.uncertain = true; await uncertain.stop('run'); assert.equal(uncertain.calls.length, 0);
  const failed = stopFixture(); failed.client.stopRun = async ident => { failed.calls.push(['run', ident]); throw new Error('response lost'); }; await failed.stop('run'); await failed.stop('run'); assert.equal(failed.calls.length, 1); assert.equal(failed.state.stopUncertain, true); assert.equal(failed.state.pendingRun.state, 'running'); assert.equal(failed.state.stopOwner.id, id);
});
test('STOP on current batch child routes to exact whole batch, never native child endpoint', async () => {
  const batch = {id: intent, roteiro_id: block, source_revision: 2, enhance_with_grok: true, expected_current_revision: 3, enhancement_ids: [], phase: 'generating', stop_requested: false, state: 'active', blocks: [], completed_block_ids: [], current_run_id: id};
  const f = stopFixture(batch); await f.stop('run'); assert.deepEqual(f.calls, [['batch', block, intent]]); assert.equal(f.state.batchRecord.state, 'stopped'); assert.equal(f.state.globalBatchRecord.state, 'stopped'); assert.equal(f.state.pendingRun.state, 'running');
});
test('actual discovery gates unknown global execution then binds confirmed external batch without POST', async () => {
  const handler = source.slice(source.indexOf('  async function discoverBatch()'), source.indexOf('  function batchURL()'));
  const record = {id: intent, roteiro_id: id, source_revision: 2, enhance_with_grok: true, expected_current_revision: 2, enhancement_ids: [], phase: 'improving', stop_requested: false, state: 'active', blocks: [], completed_block_ids: []};
  const state = {batchDiscoveryEpoch: 0, batchDiscoveryUncertain: true, batchOwner: null}, calls = [];
  const deps = {state, client: {get: async path => { calls.push(path); return {batch: record}; }}, verifiedBatch, canonicalUUID, stopped: false, batchURL() {}, controls() {}, message() {}};
  const discover = new Function(...Object.keys(deps), `${handler}; return discoverBatch;`)(...Object.values(deps));
  await discover(); assert.deepEqual(calls, ['/roteiro-batches/current']); assert.equal(state.batchDiscoveryUncertain, false); assert.equal(state.globalBatchRecord.state, 'active'); assert.equal(state.batchOwner.id, intent);
  assert.equal(nativeExecutionBlocked({config: {}, globalBatchRecord: record}), true); assert.equal(nativeExecutionBlocked({config: {}, batchDiscoveryUncertain: true}), true);
});

test('new public roteiro and batch container hints trigger only metadata invalidation', () => {
  for (const path of ['.data/roteiros', `.data/roteiros/${id}`, '.data/roteiro-batches', `.data/roteiro-batches/${intent}.json`, '.data/roteiro-batches/active.json']) assert.equal(relevantChange({invalidation: true, path}), true, path);
  for (const path of ['.data/roteiros/.locks', '.data/roteiros/private', '.data/roteiro-batches/private/.part', '.data/roteiro-batches/active.json.part']) assert.equal(relevantChange({invalidation: true, path}), false, path);
  const listener = source.slice(source.indexOf('const change = event =>'), source.indexOf("events.addEventListener('change'"));
  assert.match(listener, /queueRefresh\(\)/); assert.doesNotMatch(listener, /startBatch|generate|proposal|POST/);
});

test('actual STOP callback reports no request for blocked or changed sources and returns domain status for attempts', async () => {
  const inactive = stopFixture(); inactive.state.pendingRun.state = 'ready_for_review'; const noOp = await inactive.stop('run'); assert.equal(noOp.requested, false); assert.match(noOp.status, /ativa confirmada/); assert.equal(inactive.calls.length, 0);
  const busy = stopFixture(); busy.state.stopUncertain = true; const blocked = await busy.stop('run'); assert.equal(blocked.requested, false); assert.match(blocked.status, /anterior/); assert.equal(busy.calls.length, 0);
  const unknown = stopFixture(); assert.equal((await unknown.stop('unknown')).requested, false); assert.equal(unknown.calls.length, 0);
  const success = stopFixture(); assert.deepEqual(await success.stop('run'), {requested: true, status: 'Parada confirmada no PC.'});
  const lost = stopFixture(); lost.client.stopRun = async () => { throw new Error('response lost'); }; const result = await lost.stop('run'); assert.equal(result.requested, true); assert.match(result.status, /não confirmada/); assert.equal(lost.state.stopUncertain, true);
});

test('batch requires exact saved Grok instructions while explicit Save updates snapshot without changing manual draft text', async () => {
  const saved = {system_prompt: 'Exact English system\n', model: 'fixed'}, current = {...saved}; assert.equal(savedEditorMatches(saved, current), true);
  current.system_prompt = 'Unsaved custom English instructions'; assert.equal(savedEditorMatches(saved, current), false); assert.equal(savedEditorMatches(saved, saved, true), false);
  const handler = source.slice(source.indexOf('  async function saveEditor()'), source.indexOf('  async function detailScene()'));
  const state = {editorReady: true, editorSaving: false, editorSnapshot: saved}, calls = [];
  const deps = {state, editorPayload, editorDraft: () => current, client: {saveEditor: async payload => { calls.push(payload); return {...payload}; }}, controls() {}, message() {}};
  const save = new Function(...Object.keys(deps), `${handler}; return saveEditor;`)(...Object.values(deps));
  assert.equal(calls.length, 0); await save(); assert.equal(calls.length, 1); assert.deepEqual(state.editorSnapshot, current); assert.equal(savedEditorMatches(state.editorSnapshot, current, state.editorSaving), true); assert.equal(current.system_prompt, 'Unsaved custom English instructions');
  const nativeDrafts = new Map([['new', {chosenPrompt: 'unrelated Freestyle draft'}]]); assert.equal(batchDraftsClean(fixture(), nativeDrafts), true);
});
