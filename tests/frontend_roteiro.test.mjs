import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {nativeExecutionBlocked, ownedIntentMatchingCurrent, readOwnedStoryIntent, rejectedStoryDraft, standaloneLocation, storyLocation, storyPointer, storyUpdate, storyBlockState, storyContext, createStoryClient, HTTPError} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const id = '11111111-1111-4111-8111-111111111111', block = '22222222-2222-4222-8222-222222222222', intent = '33333333-3333-4333-8333-333333333333';
const fixture = () => ({id, revision: 2, name: '<img onerror=evil()>', idea: 'Macro', reference: {source_root: 'inputs', path: 'own/original.png'}, reference_sha256: 'a'.repeat(64), adopted: true, blocks: [{id: block, action: 'Dance', prompt: ' exact FINAL\n', duration_seconds: 8, seed: 42}], attempts: []});
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
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
  assert.match(packed, /resultado visual pode diferir/); assert.match(packed, /192 frames/); assert.match(packed, /exact FINAL/);
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
