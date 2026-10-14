import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const api = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const {storyBlockState, storyEditContext, storyEditPointer, verifiedStoryEdit, selectedStoryRuns, createStoryClient, tailEnd, sceneText, parseSeed, parseDuration, newAssemblyUUID} = api;
const id = '11111111-1111-4111-8111-111111111111', editId = '22222222-2222-4222-8222-222222222222';
const ids = [1, 2, 3, 4].map(n => `33333333-3333-4333-8333-${String(n).padStart(12, '0')}`);
const reference = {source_root: 'assets', path: 'dance_reference.png'}, sha = 'a'.repeat(64);
const caps = {default_requested_seconds: 8, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125};
function fixture() {
  const runs = ids.slice(0, 3).map((runId, index) => ({id: runId, state: 'accepted', parent_id: index ? ids[index - 1] : null, prompt: `  Enhanced actual instruction ${index}\n`, seed: 9, duration_seconds: 8, output: {path: `.data/runs/${runId}/chunk.mp4`}, references: [{type: 'image', role: 'identity', source_root: reference.source_root, source: reference.path, sha256: sha}]}));
  return {id, revision: 7, name: 'Film', adopted: true, reference, reference_sha256: sha, blocks: runs.map((run, index) => ({id: run.id, action: `Raw idea ${index}`, prompt: `Planned prompt ${index}`, seed: 9, duration_seconds: 8})), attempts: runs.map(run => ({intent_id: run.id, run_id: run.id, block_id: run.id, run}))};
}
const record = (state = 'proposed') => ({id: editId, roteiro_id: id, source_revision: 7, mode: 'replace', block_id: ids[1], previous_run_id: ids[0], next_run_id: ids[2], idea: 'Change dress', seed: 9, duration_seconds: 8, prompt: 'Literal proposed prompt', run_id: null, state, error: null, run: null});
test('editing chooses two real accepted neighbors and literal enhanced prompts for each mode', () => {
  const doc = fixture(), before = JSON.stringify(doc);
  for (const [block, mode, previous, next] of [[ids[1], 'replace', ids[0], ids[2]], [ids[1], 'insert_before', ids[0], ids[1]], [ids[1], 'insert_after', ids[1], ids[2]]]) {
    const context = storyEditContext(doc, block, mode); assert.equal(context.previous.id, previous); assert.equal(context.next.id, next); assert.equal(context.previous.prompt, doc.attempts.find(a => a.run_id === previous).run.prompt); assert.deepEqual(context.reference, reference);
  }
  assert.equal(JSON.stringify(doc), before);
  assert.throws(() => storyEditContext(doc, ids[0], 'replace'), /anterior/);
  assert.throws(() => storyEditContext(doc, ids[2], 'insert_after'), /Tail/);
  assert.throws(() => storyEditContext(doc, ids[1], 'arbitrary'), /Escolha/);
});
test('accepted selected versions determine edit anchors and assembly order without changing ancestry', () => {
  const doc = fixture(), original = doc.attempts[0].run, replacement = {...original, id: ids[3], parent_id: ids[2], prompt: 'Historical replacement prompt', output: {path: `.data/runs/${ids[3]}/chunk.mp4`}};
  doc.attempts.push({intent_id: ids[3], run_id: ids[3], block_id: ids[0], run: replacement}); doc.selected_runs = {[ids[0]]: ids[0], [ids[1]]: ids[1], [ids[2]]: ids[2]};
  assert.equal(storyBlockState(doc, doc.blocks[0]).selected.run.id, ids[0]); assert.equal(storyBlockState(doc, doc.blocks[0]).latest.run.id, ids[3]);
  doc.selected_runs[ids[0]] = ids[3]; assert.equal(storyEditContext(doc, ids[1], 'replace').previous.id, ids[3]); assert.deepEqual(selectedStoryRuns(doc), [ids[3], ids[1], ids[2]]); assert.equal(tailEnd(doc), ids[2]); assert.equal(doc.attempts[1].run.parent_id, ids[0]);
  doc.selected_runs[ids[0]] = editId; assert.equal(selectedStoryRuns(doc), null); assert.equal(storyBlockState(doc, doc.blocks[0]).accepted, undefined); assert.throws(() => storyEditContext(doc, ids[1], 'replace'), /Aceite/);
});
test('context rejects incomplete, rejected, wrong identity and missing literal historical prompt', () => {
  for (const mutate of [d => d.attempts[0].run.state = 'rejected', d => d.attempts[0].run.output.path = '/private.mp4', d => d.attempts[0].run.references[0].sha256 = 'b'.repeat(64), d => d.attempts[0].run.prompt = '', d => d.attempts[0].run.id = editId]) { const doc = fixture(); mutate(doc); assert.throws(() => storyEditContext(doc, ids[1], 'replace')); }
});
test('edit recovery validates UUID owner and performs no mutation', () => {
  assert.deepEqual(storyEditPointer(`http://local/roteiro?roteiro=${id}&edit=${editId}&screen=story-edit`), {id: editId, roteiro: id});
  assert.throws(() => storyEditPointer(`http://local/?roteiro=${id}&edit=${editId}&edit=${editId}`)); assert.equal(storyEditPointer('http://local/'), null);
  assert.equal(verifiedStoryEdit(record(), {id: editId, roteiro: id}).prompt, 'Literal proposed prompt'); assert.throws(() => verifiedStoryEdit({...record(), run: {id: ids[0]}}, {id: editId, roteiro: id}));
});
test('edit API makes each provider and generation request once and reads only the same UUID after uncertainty', async () => {
  const requests = []; let lost = false;
  const client = createStoryClient(async (path, options) => { requests.push({path, ...options}); if (lost && options.method === 'POST') throw new Error('Lost response'); return {ok: true, status: 200, json: async () => record()}; });
  await client.editEditor(); await client.saveEditEditor('Dedicated edits'); await client.edits(id); await client.readEdit(id, editId); assert.equal(requests.filter(r => r.method === 'POST').length, 0);
  const body = {expected_revision: 7, mode: 'replace', block_id: ids[1], idea: 'Change dress', seed: 9, duration_seconds: 8};
  await client.proposeEdit(id, editId, body); await assert.rejects(async () => client.proposeEdit(id, editId, body));
  lost = true; await assert.rejects(client.generateEdit(id, editId, 'literal edited proposal')); await assert.rejects(async () => client.generateEdit(id, editId, 'again')); await client.readEdit(id, editId);
  assert.equal(requests.filter(r => r.method === 'POST').length, 2); assert.deepEqual(JSON.parse(requests.find(r => r.path.endsWith('/generate')).body), {prompt: 'literal edited proposal'});
  assert.equal(requests.at(-1).path, `/roteiros/${id}/edits/${editId}`); assert.equal(requests.at(-1).method, 'GET');
});
function handler(name, end, deps) { const text = source.slice(source.indexOf(`  async function ${name}(`), source.indexOf(end, source.indexOf(`  async function ${name}(`))); return new Function(...Object.keys(deps), `${text}; return ${name};`)(...Object.values(deps)); }
function actionFixture() {
  const draft = {block: ids[1], mode: 'replace', idea: 'Change dress', duration: '8', seed: '9', prompt: '  Editable Grok proposal\n', owner: null, uncertain: false, generated: false, record: null}, edit = {busy: false}, nodes = new Map(), calls = [], story = {doc: fixture()}, state = {capabilities: caps, screen: 'story-edit'};
  const $ = id => { if (!nodes.has(id)) nodes.set(id, {disabled: false}); return nodes.get(id); };
  const deps = {$, edit, editDraft: () => draft, state, story, storyEditContext, sceneText, parseSeed, parseDuration, newAssemblyUUID, verifiedStoryEdit, document: {defaultView: {crypto: {randomUUID: () => { calls.push('uuid'); return editId; }}}}, recordView() {}, renderStoryEdit() {}, editControls() {}, controls() {}, grokWaiting: {track: (id, f) => f()}, stories: {proposeEdit: async (...args) => { calls.push(['propose', ...args]); return record(); }, generateEdit: async (...args) => { calls.push(['generate', ...args]); return {...record('generating'), run_id: ids[3]}; }}};
  return {draft, edit, state, story, calls, deps};
}
test('actual explicit proposal creates one UUID and later generation uses edited text without changing roteiro', async () => {
  const f = actionFixture(), before = JSON.stringify(f.story.doc), propose = handler('proposeStoryEdit', '  async function generateStoryEdit', f.deps);
  assert.deepEqual(f.calls, []); await propose(); await propose(); assert.equal(f.calls.filter(c => c === 'uuid').length, 1); assert.equal(f.calls.filter(c => Array.isArray(c) && c[0] === 'propose').length, 1); assert.equal(f.draft.owner.id, editId);
  f.draft.prompt = '  Human edited enhanced prompt\n'; const generate = handler('generateStoryEdit', '  async function decideStoryEdit', f.deps); await generate(); await generate();
  assert.equal(f.calls.filter(c => Array.isArray(c) && c[0] === 'generate').length, 1); assert.equal(f.calls.at(-1).at(-1), f.draft.prompt); assert.equal(JSON.stringify(f.story.doc), before);
});
test('lost proposal and generation preserve owner, prompt and explicit sent fence without replay', async () => {
  for (const action of ['propose', 'generate']) {
    const f = actionFixture(); if (action === 'generate') { f.draft.owner = {id: editId, roteiro: id}; f.draft.record = record(); }
    f.deps.stories[`${action}Edit`] = async () => { f.calls.push(action); throw new Error('Lost response'); };
    const run = handler(action === 'propose' ? 'proposeStoryEdit' : 'generateStoryEdit', action === 'propose' ? '  async function generateStoryEdit' : '  async function decideStoryEdit', f.deps);
    await run(); await run(); assert.equal(f.calls.filter(c => c === action).length, 1); assert.equal(f.draft.owner.id, editId); assert.equal(f.draft.uncertain, true); assert.match(f.draft.message, /mesma edição/); assert.equal(f.draft.prompt, '  Editable Grok proposal\n');
  }
});
test('accepting native edit video preserves roteiro and never applies automatically', async () => {
  const f = actionFixture(), before = JSON.stringify(f.story.doc); f.draft.owner = {id: editId, roteiro: id}; f.draft.record = {...record('generating'), run_id: ids[3], run: {...f.story.doc.attempts[1].run, id: ids[3], state: 'ready_for_review'}};
  f.deps.client = {decide: async (runId, action) => { f.calls.push(['decision', runId, action]); return {...f.draft.record.run, state: 'accepted'}; }};
  const decide = handler('decideStoryEdit', '  async function applyStoryEdit', f.deps); await decide('accept');
  assert.equal(f.draft.record.run.state, 'accepted'); assert.equal(f.draft.uncertain, false); assert.equal(JSON.stringify(f.story.doc), before); assert.deepEqual(f.calls, [['decision', ids[3], 'accept']]); assert.match(f.draft.message, /ação separada/);
});
test('same-ID read preserves human proposal edits and never resends provider or generation', async () => {
  const f = actionFixture(); f.edit.reading = false; f.draft.owner = {id: editId, roteiro: id}; f.draft.uncertain = true; f.draft.prompt = 'Human retained draft';
  f.deps.stories.readEdit = async (...args) => { f.calls.push(['GET', ...args]); return record(); };
  const read = handler('readStoryEdit', '  async function proposeStoryEdit', f.deps); await read(); assert.equal(f.draft.prompt, 'Human retained draft'); assert.equal(f.draft.uncertain, false); assert.deepEqual(f.calls, [['GET', id, editId]]);
});
test('editorial montage proves selected revision and order, excluding an ancestry movie with the same last run', () => {
  const owner = {id, revision: 7, run_ids: ids.slice(0, 3)}, output = {roteiro_id: id, roteiro_revision: 7, roteiro_sha256: sha, input_ids: ids.slice(0, 3)};
  assert.equal(api.storyAssemblyMatches(output, owner), true);
  for (const changed of [{}, {...output, roteiro_revision: 8}, {...output, input_ids: [ids[1], ids[0], ids[2]]}, {...output, roteiro_sha256: 'invalid'}]) assert.equal(api.storyAssemblyMatches(changed, owner), false);
});
test('discard is an explicit bounded POST and never deletes the native version or submits another provider call', async () => {
  const requests = [], client = createStoryClient(async (path, options) => { requests.push({path, ...options}); return {ok: true, status: 200, json: async () => ({...record('discarded')})}; });
  assert.equal(requests.length, 0); await client.discardEdit(id, editId); await assert.rejects(async () => client.discardEdit(id, editId)); assert.equal(requests.length, 1); assert.equal(requests[0].method, 'POST'); assert.deepEqual(JSON.parse(requests[0].body), {}); assert.match(requests[0].path, /\/discard$/);
});
test('actual interrupted edit retry creates only a new proposed record with the literal submitted prompt', async () => {
  const f = actionFixture(), original = f.draft; original.owner = {id: editId, roteiro: id}; original.record = {...record('generating'), run_id: ids[3], run: {id: ids[3], state: 'interrupted', prompt: '  FINAL submitted enhanced prompt\n'}};
  f.edit.drafts = new Map(); f.deps.editDraft = () => f.edit.drafts.get(f.edit.key) || original; f.deps.newAssemblyUUID = () => ids[3];
  f.deps.stories.retryEdit = async (...args) => { f.calls.push(['retry', ...args]); return {...record(), id: ids[3], prompt: original.record.run.prompt}; };
  const retry = handler('retryStoryEdit', '  function renderStory()', f.deps); const before = JSON.stringify(f.story.doc); await retry();
  const fresh = f.edit.drafts.get(`edit:${ids[3]}`); assert.equal(fresh.prompt, '  FINAL submitted enhanced prompt\n'); assert.equal(fresh.generated, false); assert.equal(fresh.uncertain, false); assert.equal(fresh.record.state, 'proposed'); assert.equal(original.record.run.state, 'interrupted'); assert.equal(JSON.stringify(f.story.doc), before); assert.deepEqual(f.calls, [['retry', id, editId, ids[3], 7]]);
});
test('explicit apply reads durable applied state before replacing the doc and never changes following native parents', async () => {
  const f = actionFixture(), old = f.story.doc; f.draft.owner = {id: editId, roteiro: id}; f.draft.record = {...record('generating'), run_id: ids[3], run: {id: ids[3], state: 'accepted'}};
  const updated = {...old, revision: 8, selected_runs: {[ids[1]]: ids[3]}};
  f.deps.stories.applyEdit = async (...args) => { f.calls.push(['apply', ...args]); return updated; }; f.deps.stories.readEdit = async (...args) => { f.calls.push(['read', ...args]); return {...f.draft.record, state: 'applied'}; }; f.deps.loadStoryEdits = async () => {};
  const apply = handler('applyStoryEdit', '  async function selectStoryVersion', f.deps); await apply(); assert.equal(f.story.doc.revision, 8); assert.equal(f.draft.record.state, 'applied'); assert.equal(f.draft.uncertain, false); assert.equal(f.story.doc.attempts[2].run.parent_id, ids[1]); assert.deepEqual(f.calls, [['apply', id, editId, 7], ['read', id, editId]]);
});
