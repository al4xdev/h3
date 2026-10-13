import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

// Import only the browser module's pure exports: no document, launcher or backend import.
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {retryDraft, makePayload} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const ROOT = '11111111-1111-4111-8111-111111111111';
const CHILD = '22222222-2222-4222-8222-222222222222';
const OTHER = '33333333-3333-4333-8333-333333333333';
const RAW_IDEA = 'ela dá um salto';
const FINAL_PROMPT = '  Grok improved: preserve the original identity.\n\nJump, turn away; <img src=x onerror=evil()>\r\n  ';
const CAPS = Object.freeze({default_requested_seconds: 2.3, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125});
function freeze(value) {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
function reference(source_root = 'assets', source = 'dance_reference.png') {
  return {type: 'image', role: 'identity', source_root, source, sha256: 'a'.repeat(64)};
}
function run({child = false, state = 'interrupted', seed = 0, duration = 5, ref = reference(), ...overrides} = {}) {
  const id = child ? CHILD : ROOT;
  return {
    id, state, created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:01Z',
    seed, prompt: FINAL_PROMPT, duration_seconds: duration, workflow_hash: 'b'.repeat(64),
    parent_id: child ? ROOT : null, prompt_id: null, references: [ref],
    input_info: {operation: child ? 'v2v' : 'i2v', mode: child ? 'continuation' : 'normal', continuation: child ? {seed, prompt: FINAL_PROMPT, duration_seconds: duration, reference_tail_seconds: 3, include_audio: true} : null},
    progress: {}, output: state === 'interrupted' ? {} : {path: `.data/runs/${id}/chunk.mp4`},
    publication_mode: state === 'interrupted' ? null : 'native',
    decision: state === 'rejected' ? {accepted: false, at: '2026-10-13T00:00:01Z'} : null,
    error: state === 'interrupted' ? 'Backend restarted; job was not resubmitted' : null, timings: {},
    ...overrides,
  };
}
function parent(ref = reference()) {
  return run({state: 'accepted', ref, prompt: '  ORIGINAL parent prompt differs from child final prompt\n', decision: {accepted: true, at: '2026-10-13T00:00:00Z'}});
}
function copy(value) { return structuredClone(value); }
function blocked(value, originalParent = null, capabilities = CAPS) {
  const before = copy([value, originalParent]);
  freeze(value); freeze(originalParent);
  assert.throws(() => retryDraft(value, originalParent, capabilities), error => error instanceof Error && error.message.trim().length > 0);
  assert.deepEqual([value, originalParent], before, 'blocked preparation must not alter historical records');
}

for (const state of ['queued', 'running', 'ready_for_review', 'accepted', 'failed', 'unknown']) {
  test(`retry rejects noneligible state ${state}`, () => blocked(run({state})));
}

const invalidRoots = [
  ['missing operation metadata', value => delete value.input_info],
  ['missing operation', value => delete value.input_info.operation],
  ['unknown operation', value => { value.input_info.operation = 'legacy'; }],
  ['missing mode', value => delete value.input_info.mode],
  ['missing continuation provenance', value => delete value.input_info.continuation],
  ['unexpected root continuation', value => { value.input_info.continuation = {}; }],
  ['missing references', value => delete value.references],
  ['empty references', value => { value.references = []; }],
  ['duplicate references', value => { value.references.push(copy(value.references[0])); }],
  ['multiple distinct references', value => { value.references.push(reference('inputs', 'another/original.png')); }],
  ['unsupported identity role', value => { value.references[0].role = 'unknown'; }],
  ['nonimage identity', value => { value.references[0].type = 'video'; }],
  ['missing reference SHA', value => delete value.references[0].sha256],
  ['short SHA', value => { value.references[0].sha256 = 'a'.repeat(63); }],
  ['nonhex SHA', value => { value.references[0].sha256 = 'z'.repeat(64); }],
  ['SHA newline', value => { value.references[0].sha256 += '\n'; }],
  ['missing source root', value => delete value.references[0].source_root],
  ['unowned source root', value => { value.references[0].source_root = 'private'; }],
  ['traversal source', value => { value.references[0].source = '../private.png'; }],
  ['absolute source', value => { value.references[0].source = '/etc/photo.png'; }],
  ['URL source', value => { value.references[0].source = 'https://external.invalid/photo.png'; }],
  ['empty path component', value => { value.references[0].source = 'own//photo.png'; }],
  ['dot path component', value => { value.references[0].source = 'own/./photo.png'; }],
  ['backslash source', value => { value.references[0].source = 'own\\\\photo.png'; }],
  ['control character source', value => { value.references[0].source = 'own/photo\u0000.png'; }],
  ['null prompt', value => { value.prompt = null; }],
  ['blank prompt', value => { value.prompt = ' \n '; }],
  ['oversized prompt', value => { value.prompt = 'x'.repeat(12001); }],
  ['missing seed', value => delete value.seed],
  ['negative seed', value => { value.seed = -1; }],
  ['fractional seed', value => { value.seed = 0.5; }],
  ['coerced seed string', value => { value.seed = '0'; }],
  ['unsafe seed', value => { value.seed = Number.MAX_SAFE_INTEGER + 1; }],
  ['missing duration', value => delete value.duration_seconds],
  ['zero duration', value => { value.duration_seconds = 0; }],
  ['excess duration', value => { value.duration_seconds = 10.01; }],
  ['duration precision loss', value => { value.duration_seconds = 2.333; }],
  ['duration coercion', value => { value.duration_seconds = '5'; }],
  ['noncanonical run UUID', value => { value.id = 'old-id'; }],
];
for (const [name, invalidate] of invalidRoots) {
  test(`retry blocks ${name} without invented defaults`, () => {
    const value = run(); invalidate(value); blocked(value);
  });
}

const invalidChildren = [
  ['missing original parent', () => null],
  ['wrong original parent', () => ({...parent(), id: OTHER})],
];
for (const [name, getParent] of invalidChildren) {
  test(`continuation retry blocks ${name}`, () => blocked(run({child: true}), getParent()));
}
for (const state of ['queued', 'running', 'ready_for_review', 'rejected', 'interrupted', 'failed']) {
  test(`continuation retry refuses original parent state ${state}`, () => blocked(run({child: true}), {...parent(), state}));
}
for (const [name, invalidate] of [
  ['tail 2', value => { value.input_info.continuation.reference_tail_seconds = 2; }],
  ['audio false', value => { value.input_info.continuation.include_audio = false; }],
  ['null continuation prompt', value => { value.input_info.continuation.prompt = null; }],
  ['different continuation prompt', value => { value.input_info.continuation.prompt = RAW_IDEA; }],
  ['different continuation seed', value => { value.input_info.continuation.seed = 1; }],
  ['different continuation duration', value => { value.input_info.continuation.duration_seconds = 2.3; }],
  ['missing continuation field', value => delete value.input_info.continuation.include_audio],
  ['extra continuation field', value => { value.input_info.continuation.private_knob = true; }],
  ['missing original parent ID', value => delete value.parent_id],
  ['child as its own parent', value => { value.parent_id = CHILD; }],
  ['root operation on child', value => { value.input_info.operation = 'i2v'; }],
  ['wrong child mode', value => { value.input_info.mode = 'normal'; }],
]) {
  test(`continuation retry blocks ${name}`, () => { const value = run({child: true}); invalidate(value); blocked(value, parent()); });
}
for (const [name, update] of [
  ['identity SHA mismatch', {sha256: 'c'.repeat(64)}],
  ['identity source mismatch', {source: 'other.png'}],
  ['identity category mismatch', {source_root: 'inputs'}],
]) {
  test(`continuation retry blocks parent ${name}`, () => blocked(run({child: true}), parent({...reference(), ...update})));
}
for (const output of [{}, {path: `.data/runs/${OTHER}/chunk.mp4`}, {path: `.data/runs/${ROOT}/other.mp4`}, {path: `/private/${ROOT}/chunk.mp4`}]) {
  test(`continuation retry requires parent own canonical publication ${JSON.stringify(output)}`, () => blocked(run({child: true}), {...parent(), output}));
}

const supportedReferences = [
  reference(), reference('assets', 'nested/original.jpg'),
  reference('inputs', `${OTHER}/original.png`), reference('inputs', `${OTHER}/original.jpeg`),
  reference('inputs', `${OTHER}/original.webp`),
  reference('runs', `.data/runs/${OTHER}/last_frame.png`),
  reference('runs', `runs/${OTHER}/initial_frame.png`),
];
for (const state of ['rejected', 'interrupted']) for (const child of [false, true]) {
  test(`${state} ${child ? 'child' : 'root'} copies final Grok prompt literally with exact requested payload`, () => {
    for (const seed of [0, Number.MAX_SAFE_INTEGER]) for (const duration of [0.01, 2.3, 5, 10]) for (const ref of supportedReferences) {
      const value = freeze(run({state, child, seed, duration, ref}));
      const originalParent = child ? freeze(parent(ref)) : null;
      const before = copy([value, originalParent]);
      const draft = retryDraft(value, originalParent, CAPS);
      assert.deepEqual(draft, {
        key: `retry:${value.id}`, sourceId: value.id, parentId: child ? ROOT : null, mode: child ? 'continue' : 'new',
        idea: FINAL_PROMPT, chosenPrompt: FINAL_PROMPT, proposal: '', seed: String(seed), duration: String(duration),
        reference: {source_root: ref.source_root, path: ref.source, sha256: ref.sha256},
        revision: 0, proposalStale: false, proposalContext: '', lateProposal: null, submitted: false,
      });
      assert.notEqual(draft.idea, RAW_IDEA, 'the raw idea is not generation authority');
      if (child) { assert.notEqual(draft.chosenPrompt, originalParent.prompt); assert.notEqual(draft.parentId, value.id); }
      const payload = makePayload({seed: draft.seed, prompt: draft.chosenPrompt, duration: draft.duration, reference: draft.reference, continuation: draft.mode === 'continue', capabilities: CAPS});
      assert.deepEqual(payload, child ? value.input_info.continuation : {
        seed, prompt: FINAL_PROMPT, duration_seconds: duration, references: [{source_root: ref.source_root, path: ref.source}],
      });
      assert.deepEqual([value, originalParent], before, 'preparation never changes old prompt/output/decision/UUID');
      const second = retryDraft(value, originalParent, CAPS);
      assert.equal(second.key, draft.key);
      assert.notEqual(second, draft); assert.notEqual(second.reference, draft.reference);
      draft.idea = 'local edit'; draft.chosenPrompt = 'local edit'; draft.reference.path = 'local.png';
      assert.equal(second.idea, FINAL_PROMPT); assert.equal(second.reference.path, ref.source);
      assert.deepEqual([value, originalParent], before, 'editing isolated retry cannot mutate frozen originals');
    }
  });
}

test('accepted original parent may use explicitly supported legacy publication path', () => {
  const originalParent = freeze({...parent(), output: {path: `runs/${ROOT}/chunk.mp4`}});
  assert.equal(retryDraft(freeze(run({child: true})), originalParent, CAPS).parentId, ROOT);
});
test('different attempts receive distinct isolated retry keys', () => {
  const first = retryDraft(freeze(run()), null, CAPS);
  const second = retryDraft(freeze(run({id: OTHER})), null, CAPS);
  assert.notEqual(first.key, second.key);
});
test('legacy missing duration capabilities fail honestly for nondefault duration', () => {
  blocked(run({duration: 5}), null, null);
  assert.equal(retryDraft(freeze(run({duration: 2.3})), null, null).duration, '2.3');
});
test('root metadata must explicitly record a null parent', () => {
  const value = run(); delete value.parent_id; blocked(value);
});
for (const ref of [reference('assets', '.private/photo.png'), reference('assets', 'image.gif'), reference('runs', `.data/runs/${OTHER}/other.png`)]) {
  test(`unsupported historical reference blocks honestly ${ref.source}`, () => blocked(run({ref})));
}

test('retry helper is an exported pure contract', () => {
  assert.equal(typeof retryDraft, 'function', 'frontend owner must export retryDraft(run, parent, capabilities)');
  assert.equal(typeof document, 'undefined');
  assert.notEqual(FINAL_PROMPT, RAW_IDEA);
});
