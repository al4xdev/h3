import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {noticePointer, confirmedNoticeRun, readOwnedStoryIntent, relevantChange} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const id = '11111111-1111-4111-8111-111111111111';
const roteiro = '22222222-2222-4222-8222-222222222222';
const block = '33333333-3333-4333-8333-333333333333';
const other = '44444444-4444-4444-8444-444444444444';

function fixture({owner = {kind: 'run', id, action: 'generate'}, run = {id, state: 'interrupted'}, attempt = null} = {}) {
  const state = {noticeOwner: owner, uncertain: true, drafts: new Map([['sent', {submitted: true, chosenPrompt: 'literal sent prompt'}]])};
  const story = {};
  const reads = [], messages = [], counts = {url: 0};
  let gate = Promise.resolve();
  const doc = {id: roteiro, blocks: [{id: block}], attempts: []};
  const deps = {state, story, confirmedNoticeRun, readOwnedStoryIntent, client: {get: async path => { reads.push(path); await gate; return run; }}, stories: {read: async key => { reads.push(`/roteiros/${key}`); return doc; }, readIntent: async (...keys) => { reads.push(keys); return attempt; }}, controls() {}, renderStory() {}, message: (...args) => messages.push(args), noticeURL: () => counts.url++};
  const handler = source.slice(source.indexOf('  async function reconcilePendingNotice()'), source.indexOf('  function dismissNotice('));
  const reconcile = new Function(...Object.keys(deps), `let stopped = false; ${handler}; return reconcilePendingNotice;`)(...Object.values(deps));
  return {state, story, reads, messages, counts, reconcile, wait: promise => { gate = promise; }};
}

test('known run notice survives URL recovery with strict own ID and action', () => {
  assert.deepEqual(noticePointer(`http://local/?pending_run=${id}&pending_action=generate`), {kind: 'run', id, action: 'generate'});
  assert.equal(noticePointer('http://local/'), null);
  for (const query of [`pending_run=${id}`, `pending_run=${id}&pending_action=retry`, `pending_run=../private&pending_action=generate`, `pending_run=${id}&pending_run=${other}&pending_action=generate`]) assert.throws(() => noticePointer(`http://local/?${query}`));
});

test('reconnection resolves the exact interrupted run through GET without clearing sent draft', async () => {
  const f = fixture(); await f.reconcile();
  assert.deepEqual(f.reads, [`/runs/${id}`]);
  assert.equal(f.state.uncertain, false);
  assert.equal(f.state.pendingRun.state, 'interrupted');
  assert.equal(f.state.noticeResult.terminal, true);
  assert.deepEqual(f.state.drafts.get('sent'), {submitted: true, chosenPrompt: 'literal sent prompt'});
});

test('confirmed active run replaces uncertain state while still fencing execution', async () => {
  const f = fixture({run: {id, state: 'running'}}); await f.reconcile();
  assert.equal(f.state.uncertain, false); assert.equal(f.state.noticeResult.terminal, false);
  assert.equal(f.state.pendingRun.state, 'running');
});

test('a lost accept/reject decision remains uncertain until a terminal decision is proven', async () => {
  for (const action of ['accept', 'reject']) {
    const f = fixture({owner: {kind: 'run', id, action}, run: {id, state: 'ready_for_review'}});
    f.state.uncertain = false;
    await f.reconcile(); assert.equal(f.state.uncertain, true); assert.equal(f.state.noticeResult.resolved, false);
    const resolved = fixture({owner: {kind: 'run', id, action}, run: {id, state: action === 'accept' ? 'accepted' : 'rejected'}});
    await resolved.reconcile(); assert.equal(resolved.state.uncertain, false);
  }
});

test('wrong ID, invalid state and offline responses preserve the uncertainty fence', async () => {
  for (const run of [{id: other, state: 'accepted'}, {id, state: 'completed'}, null]) {
    const f = fixture({run}); await f.reconcile();
    assert.equal(f.state.uncertain, true); assert.equal(f.state.noticeResult, undefined);
  }
  const offline = fixture(); offline.wait(Promise.reject(new Error('offline'))); await offline.reconcile();
  assert.equal(offline.state.uncertain, true);
});

test('late read cannot overwrite a newer notification owner', async () => {
  const f = fixture(); let release;
  f.wait(new Promise(resolve => { release = resolve; }));
  const read = f.reconcile();
  f.state.noticeOwner = {kind: 'run', id: other, action: 'generate'};
  release(); await read;
  assert.equal(f.state.noticeResult, undefined); assert.equal(f.state.pendingRun, undefined);
});

test('story recovery proves its exact intent without selecting or replacing an edited story', async () => {
  const owner = {kind: 'story', id, roteiro, block, action: 'generate'};
  const f = fixture({owner, attempt: {intent_id: id, run_id: id, roteiro_id: roteiro, block_id: block, admission: 'admitted', run: {id, state: 'ready_for_review'}}});
  f.story.uncertainIntent = id; f.story.doc = {id: roteiro, unsaved: true}; f.story.editing = block;
  await f.reconcile();
  assert.equal(f.state.uncertain, false); assert.equal(f.story.uncertainIntent, null);
  assert.equal(f.story.doc.unsaved, true);
  assert.deepEqual(f.reads, [`/roteiros/${roteiro}`, [roteiro, block, id]]);
});

test('confirmed preflight rejection is dismissible while uncertain admission is retained', async () => {
  const owner = {kind: 'story', id, roteiro, block, action: 'generate'};
  const base = {intent_id: id, run_id: id, roteiro_id: roteiro, block_id: block, run: null};
  const refused = fixture({owner, attempt: {...base, admission: 'rejected', state: 'not_admitted'}});
  await refused.reconcile(); assert.equal(refused.state.uncertain, false); assert.equal(refused.state.noticeResult.terminal, true);
  const uncertain = fixture({owner, attempt: {...base, admission: 'uncertain', state: 'uncertain'}});
  await uncertain.reconcile(); assert.equal(uncertain.state.uncertain, true);
});

test('dismissing resolved run/batch only hides notice and keeps records and submission fence', () => {
  const state = {noticeResult: {id, terminal: true, resolved: true}, pendingRun: {id, state: 'interrupted'}, batchRecord: {id: other, state: 'stopped'}, draft: {submitted: true}};
  let writes = 0;
  const handler = source.slice(source.indexOf('  function dismissNotice('), source.indexOf('  async function readStopOwner()'));
  const dismiss = new Function('state', 'noticeURL', 'controls', `${handler}; return dismissNotice;`)(state, () => writes++, () => {});
  state.uncertain = true; dismiss('run'); assert.equal(writes, 0);
  state.uncertain = false; state.noticeResult.terminal = false; dismiss('run'); assert.equal(writes, 0);
  state.noticeResult.terminal = true; dismiss('run'); assert.equal(state.dismissedRunNotice, id);
  state.batchRecord.state = 'active'; dismiss('batch'); assert.equal(state.dismissedBatchNotice, undefined);
  state.batchRecord.state = 'stopped'; dismiss('batch'); assert.equal(state.dismissedBatchNotice, other);
  assert.equal(state.pendingRun.id, id); assert.equal(state.draft.submitted, true); assert.equal(writes, 2);
});

test('shared favorites hints refresh metadata without triggering inference', () => {
  assert.equal(relevantChange({invalidation: true, path: '.data/library/favorites.json'}), true);
  assert.equal(relevantChange({invalidation: true, path: '.data/library'}), true);
  assert.equal(relevantChange({invalidation: true, path: '.data/library/.write-favorites.part'}), false);
});
