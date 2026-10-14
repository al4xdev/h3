import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {HTTPError, tailNotSubmitted, tailPointer, tailEnd, verifiedTail, tailMatches, tailAdoption, createStoryClient, storyBlockState, sceneText, parseSeed, parseDuration} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const id = '11111111-1111-4111-8111-111111111111', block = '22222222-2222-4222-8222-222222222222', tail = '33333333-3333-4333-8333-333333333333', child = '44444444-4444-4444-8444-444444444444';
const owner = {id: tail, roteiro: id};
function fixture() {
  const reference = {source_root: 'inputs', path: 'own/original.png'}, sha = 'a'.repeat(64), prefix = {id: block, action: 'Dance', prompt: 'Dance', seed: 42, duration_seconds: 8};
  const run = {id: block, parent_id: null, state: 'accepted', output: {path: `.data/runs/${block}/chunk.mp4`}, references: [{type: 'image', role: 'identity', source_root: reference.source_root, source: reference.path, sha256: sha}]};
  const doc = {id, revision: 2, adopted: true, name: 'Film', idea: 'Original macro', reference, reference_sha256: sha, blocks: [prefix], attempts: [{block_id: block, run_id: block, run}]};
  const candidate = {id: tail, roteiro_id: id, source_revision: 2, parent_id: block, prefix_block_ids: [block], source: {name: doc.name, idea: doc.idea, reference, reference_sha256: sha}, name: doc.name, blocks: [{...prefix, id: child, action: 'Turn', prompt: 'Turn'}], raw_text: '', state: 'proposed', stale: false};
  return {doc, candidate, wrapper: {kind: 'tail', name: doc.name, blocks: [...doc.blocks, ...candidate.blocks], tail: candidate}};
}
test('Tail points at the latest fully accepted own video and original identity', () => {
  const f = fixture(); assert.equal(tailEnd(f.doc), block); assert.equal(tailMatches(f.doc, f.candidate), true);
  for (const mutate of [f => f.doc.attempts.push({...f.doc.attempts[0], run: {...f.doc.attempts[0].run, state: 'ready_for_review'}}), f => f.doc.attempts[0].run.output.path = '/private.mp4', f => f.doc.blocks.push({...f.doc.blocks[0], id: child}), f => f.doc.attempts[0].run.references[0].sha256 = 'b'.repeat(64), f => f.doc.attempts[0].run.parent_id = child]) { const f = fixture(); mutate(f); assert.equal(tailEnd(f.doc), null); }
});
test('Tail adoption sends suffix only and preserves source macro, prefix and history', () => {
  const f = fixture(), before = JSON.stringify(f.doc), body = tailAdoption(f.doc, f.wrapper); assert.deepEqual(body, {expected_revision: 2, blocks: f.candidate.blocks}); assert.equal(JSON.stringify(f.doc), before);
  f.wrapper.blocks[0] = {...f.wrapper.blocks[0], action: 'Changed'}; assert.throws(() => tailAdoption(f.doc, f.wrapper));
});
test('Tail adoption rejects stale revision, changed identity, name, source and empty suffix', () => {
  for (const mutate of [f => f.doc.revision++, f => f.candidate.stale = true, f => f.doc.idea = 'Changed', f => f.doc.reference_sha256 = 'b'.repeat(64), f => f.wrapper.name = 'Changed', f => f.wrapper.blocks = f.doc.blocks, f => f.candidate.state = 'uncertain']) { const f = fixture(); mutate(f); assert.throws(() => tailAdoption(f.doc, f.wrapper)); }
});
test('Tail durable pointer is independent of selected roteiro and rejects duplicates or missing owner', () => {
  assert.deepEqual(tailPointer(`http://local/?roteiro=${child}&tail=${tail}&tail_roteiro=${id}`), owner); assert.equal(tailPointer('http://local/'), null);
  for (const query of [`tail=${tail}`, `tail=${tail}&tail=${tail}&tail_roteiro=${id}`, `tail=${tail}&tail_roteiro=bad`]) assert.throws(() => tailPointer(`http://local/?${query}`));
  for (const state of ['uncertain', 'proposed', 'invalid', 'adopting', 'adopted']) { const f = fixture(); f.candidate.state = state; assert.equal(verifiedTail(f.candidate, owner), f.candidate); }
});
test('Tail client prevents duplicate planning after lost response; recovery is GET, adoption is PUT', async () => {
  const calls = [], client = createStoryClient(async (path, request) => { calls.push([path, request]); if (request.method === 'POST') throw new Error('lost'); return {ok: true, status: 200, json: async () => ({})}; });
  await assert.rejects(client.planTail(id, tail, {idea: 'Turn'})); await assert.rejects(client.planTail(id, tail, {idea: 'Turn'})); await client.readTail(id, tail); await client.adoptTail(id, tail, {expected_revision: 2, blocks: []}); assert.deepEqual(calls.map(([, request]) => request.method), ['POST', 'GET', 'PUT']); assert.ok(calls.every(([path]) => path === `/roteiros/${id}/tail/${tail}`));
});
test('actual lost planning response fences new intentions and manual recovery uses known ID only', async () => {
  const functions = source.slice(source.indexOf('  async function readTail()'), source.indexOf('  async function adoptTail()'));
  const {doc, candidate} = fixture(), story = {doc, tailOwner: null, tailReading: false, busy: false}, calls = [], nodes = new Map();
  const $ = key => { if (!nodes.has(key)) nodes.set(key, {value: ({'tail-idea': 'Turn', 'tail-count': '3', 'tail-duration': '8', 'tail-seed': '42', 'story-name': doc.name})[key]}); return nodes.get(key); };
  const deps = {grokWaiting: {track: (_id, operation) => operation()}, story, state: {capabilities: {default_requested_seconds: 8, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125}}, $, tailClean: () => !story.busy && !story.tailUncertain, tailEnd, sceneText, parseSeed, parseDuration, verifiedTail, tailNotSubmitted, newAssemblyUUID: () => tail, document: {defaultView: {crypto: {}}}, tailURL() {}, controls() {}, message() {}, applyTail: record => { story.tailRecord = record; story.tailUncertain = ['uncertain', 'adopting'].includes(record.state); }, stories: {planTail: async (...args) => { calls.push(['POST', ...args]); throw new Error('lost'); }, readTail: async (...args) => { calls.push(['GET', ...args]); return candidate; }}};
  const runtime = new Function(...Object.keys(deps), `${functions}; return {readTail, planTail};`)(...Object.values(deps)); await runtime.planTail(); assert.equal(story.tailUncertain, true); assert.deepEqual(story.tailOwner, owner); await runtime.planTail(); assert.equal(calls.length, 1); await runtime.readTail(); assert.equal(story.tailUncertain, false); assert.deepEqual(calls.map(call => call[0]), ['POST', 'GET']); assert.equal($('tail-idea').value, 'Turn');
});
test('Tail stays inside story screen, has safe raw text and separate adoption/generation', async () => {
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8'); assert.match(html.slice(html.indexOf('<section id="panel-story"'), html.indexOf('<section id="panel-context"')), /tail-controls/);
  const recovery = source.slice(source.indexOf('  async function readTail()'), source.indexOf('  async function planTail()')); assert.doesNotMatch(recovery, /planTail\(|POST|startBatch/);
  const adopt = source.slice(source.indexOf('  async function adoptTail()'), source.indexOf('  function renderTail()')); assert.doesNotMatch(adopt, /startBatch|generate\(/); assert.match(source, /text\('tail-invalid-text', record.raw_text\)/);
});

test('Tail capacity and unique suffix IDs stay fenced after proposal editing', () => {
  const f = fixture(); f.wrapper.blocks.push({...f.candidate.blocks[0]}); assert.throws(() => tailAdoption(f.doc, f.wrapper));
  const full = fixture(); full.doc.blocks = Array.from({length: 50}, () => full.doc.blocks[0]); assert.equal(tailEnd(full.doc), null);
});
test('actual adopted recovery proves edited suffix and clears only its own candidate through GET', async () => {
  const handler = source.slice(source.indexOf('  async function readTail()'), source.indexOf('  async function planTail()'));
  const f = fixture(), adopted = [{...f.candidate.blocks[0], action: 'Edited turn'}], record = {...f.candidate, state: 'adopted', adopted_blocks: adopted}, published = {...f.doc, revision: 3, blocks: [...f.doc.blocks, ...adopted]};
  const story = {doc: f.doc, candidate: f.wrapper, tailOwner: owner, tailWrappers: new Map([[id, f.wrapper]])}, calls = [];
  const deps = {story, $: () => ({value: f.doc.name}), controls() {}, message() {}, verifiedTail, applyTail: value => { story.tailRecord = value; story.tailUncertain = false; }, stories: {readTail: async (doc, candidate) => { calls.push(['candidate', doc, candidate]); return record; }, read: async doc => { calls.push(['doc', doc]); return published; }}};
  const read = new Function(...Object.keys(deps), `${handler}; return readTail;`)(...Object.values(deps)); await read(); assert.equal(story.doc, published); assert.equal(story.candidate, null); assert.equal(story.tailWrappers.size, 0); assert.deepEqual(calls, [['candidate', id, tail], ['doc', id]]);
});
test('actual late proposal retains unsaved name and block edit without repainting drafts', () => {
  const handler = source.slice(source.indexOf('  function applyTail('), source.indexOf('  async function readTail()'));
  for (const editing of [null, child]) {
    const f = fixture(), story = {doc: f.doc, editing, tailDrafts: new Map(), tailWrappers: new Map()}, calls = [];
    const deps = {story, $: () => ({value: editing ? f.doc.name : 'Unsaved film name'}), tailMatches, renderStory: () => calls.push('render'), text: () => calls.push('text')};
    const apply = new Function(...Object.keys(deps), `${handler}; return applyTail;`)(...Object.values(deps)); apply(f.candidate); assert.equal(story.tailRecord, f.candidate); assert.equal(story.candidate, undefined); assert.deepEqual(calls, []);
  }
});
test('delayed adopted document read preserves changed owner, current document and editing state', async () => {
  const handler = source.slice(source.indexOf('  async function readTail()'), source.indexOf('  async function planTail()'));
  for (const change of ['owner', 'document', 'editing', 'candidate', 'name']) {
    const f = fixture(), record = {...f.candidate, state: 'adopted'}, published = {...f.doc, revision: 3, blocks: f.wrapper.blocks}, story = {doc: f.doc, candidate: f.wrapper, tailOwner: owner, tailWrappers: new Map([[id, f.wrapper]])};
    let release, name = f.doc.name;
    const deps = {story, $: () => ({value: name}), controls() {}, message() {}, verifiedTail, applyTail: value => { story.tailRecord = value; }, stories: {readTail: async () => record, read: async () => new Promise(resolve => { release = resolve; })}};
    const read = new Function(...Object.keys(deps), `${handler}; return readTail;`)(...Object.values(deps)), pending = read(); await Promise.resolve(); await Promise.resolve();
    if (change === 'owner') story.tailOwner = {...owner, id: child};
    if (change === 'document') story.doc = {...f.doc, id: child};
    if (change === 'editing') story.editing = child;
    if (change === 'candidate') story.candidate = {...f.wrapper};
    if (change === 'name') name = 'Unsaved name';
    const expectedDoc = story.doc, expectedCandidate = story.candidate; release(published); await pending; assert.equal(story.doc, expectedDoc, change); assert.equal(story.candidate, expectedCandidate, change); assert.equal(story.tailWrappers.size, 1);
  }
});
test('actual planning releases only own explicit pre-provider rejection and never auto retries', async () => {
  const handler = source.slice(source.indexOf('  async function planTail()'), source.indexOf('  async function adoptTail()'));
  for (const proof of ['own', 'absent', 'wrong-id', 'server-error']) {
    const {doc} = fixture(), story = {doc, tailOwner: null, tailReading: false, busy: false}, calls = [], error = new HTTPError(proof === 'server-error' ? 500 : 409, 'preflight');
    if (proof !== 'absent') error.data = {tail_not_submitted: true, id: proof === 'wrong-id' ? child : tail, roteiro_id: id};
    const nodes = {'tail-idea': {value: 'Turn'}, 'tail-count': {value: '3'}, 'tail-duration': {value: '8'}, 'tail-seed': {value: '42'}};
    const deps = {grokWaiting: {track: (_id, operation) => operation()}, story, state: {capabilities: {}}, $: key => nodes[key], tailClean: () => !story.busy && !story.tailUncertain, tailEnd, sceneText, parseSeed, parseDuration: () => 8, verifiedTail, tailNotSubmitted, newAssemblyUUID: () => tail, document: {defaultView: {crypto: {}}}, tailURL() {}, controls() {}, message() {}, applyTail() {}, stories: {planTail: async (...args) => { calls.push(args); throw error; }}};
    const plan = new Function(...Object.keys(deps), `${handler}; return planTail;`)(...Object.values(deps)); await plan(); assert.equal(calls.length, 1); assert.equal(story.tailUncertain, proof !== 'own'); assert.equal(story.tailOwner === null, proof === 'own'); assert.equal(nodes['tail-idea'].value, 'Turn');
    if (proof !== 'own') { await plan(); assert.equal(calls.length, 1); }
  }
});
test('metadata refresh refuses stale document reads after navigation or local edits', async () => {
  const handler = source.slice(source.indexOf('  async function refreshCurrentStory()'), source.indexOf('  async function refresh(fromEvent'));
  for (const change of ['none', 'navigation', 'document', 'editing', 'candidate', 'name']) {
    const {doc} = fixture(), story = {doc}, state = {navigationEpoch: 1, screen: 'story'}; let release, name = doc.name, renders = 0;
    const deps = {story, state, $: () => ({value: name}), stories: {read: async () => new Promise(resolve => { release = resolve; })}, renderStory: () => renders++};
    const refresh = new Function(...Object.keys(deps), `${handler}; return refreshCurrentStory;`)(...Object.values(deps)), pending = refresh();
    if (change === 'navigation') state.navigationEpoch++;
    if (change === 'document') story.doc = {...doc, id: child};
    if (change === 'editing') story.editing = child;
    if (change === 'candidate') story.candidate = {};
    if (change === 'name') name = 'Unsaved';
    const expected = story.doc, fresh = {...doc, revision: 3}; release(fresh); await pending; assert.equal(story.doc, change === 'none' ? fresh : expected, change); assert.equal(renders, change === 'none' ? 1 : 0);
  }
});
