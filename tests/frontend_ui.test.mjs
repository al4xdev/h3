import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {parseSeed, makePayload, playableURL, createClient, HTTPError, referenceValue, imageURL, validateUpload, relevantChange, editorPayload, grokPayload, sceneText, draftMatches, canonicalUUID, canAssemble, assemblyURL, assemblyRecord, assemblyPointer, assemblyLocation, newAssemblyUUID, durationCapabilities, roundHalfEven, alignedFrames, parseDuration, motionSpec, createScreenTransitions, createPresentationMotion, lastFrameURL, referencePreviewURL, draftSettingsAllowed, nativeExecutionBlocked} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const reply = (data, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => data});

function screenTransitionFixture() {
  const reduced = new EventTarget(), mobile = new EventTarget();
  reduced.matches = false; mobile.matches = true;
  const document = new EventTarget(), transitions = [], paints = [];
  document.documentElement = {dataset: {}};
  document.defaultView = {matchMedia: query => query.includes('reduced') ? reduced : mobile};
  document.startViewTransition = callback => {
    const transition = {callback, skipped: false, skipTransition() { this.skipped = true; }, finished: new Promise(() => {}), updateCallbackDone: new Promise(() => {})};
    transitions.push(transition); return transition;
  };
  const controller = createScreenTransitions(document);
  return {document, reduced, mobile, transitions, paints, controller, paint: (key, direction = 1) => controller.paint(key, () => paints.push(key), direction)};
}
test('screen snapshots slide forward/back and superseded painting executes only once', () => {
  const f = screenTransitionFixture();
  f.paint('library'); assert.deepEqual(f.paints, ['library']);
  f.paint('story'); assert.equal(f.document.documentElement.dataset.slideDirection, 'forward');
  f.paint('library', -1);
  assert.equal(f.transitions[0].skipped, true);
  assert.deepEqual(f.paints, ['library', 'story']);
  f.transitions[0].callback(); assert.deepEqual(f.paints, ['library', 'story']);
  assert.equal(f.document.documentElement.dataset.slideDirection, 'back');
  f.transitions[1].callback(); assert.deepEqual(f.paints, ['library', 'story', 'library']);
  f.controller.destroy();
});
test('screen motion respects reduced preference, background, desktop and unsupported browsers', () => {
  const f = screenTransitionFixture(); f.paint('library'); f.paint('story');
  f.reduced.matches = true; f.reduced.dispatchEvent(new Event('change'));
  assert.equal(f.transitions[0].skipped, true); assert.deepEqual(f.paints, ['library', 'story']);
  f.paint('generation'); assert.equal(f.transitions.length, 1);
  f.reduced.matches = false; f.document.hidden = true; f.paint('review');
  f.document.hidden = false; f.mobile.matches = false; f.paint('settings');
  f.mobile.matches = true; delete f.document.startViewTransition; f.paint('library');
  assert.equal(f.transitions.length, 1);
  assert.deepEqual(f.paints, ['library', 'story', 'generation', 'review', 'settings', 'library']);
  f.controller.destroy();
});
test('failed transition capture and teardown retain the requested screen without replay', () => {
  const f = screenTransitionFixture(); f.paint('library');
  f.document.startViewTransition = () => { throw new Error('unsupported capture'); };
  f.paint('story'); assert.deepEqual(f.paints, ['library', 'story']);
  f.controller.destroy(); f.paint('review');
  assert.deepEqual(f.paints, ['library', 'story', 'review']);
});

test('strict seed boundaries, no float/exponent/sign/whitespace coercion', () => {
  assert.equal(parseSeed('0'), 0);
  assert.equal(parseSeed('9007199254740991'), Number.MAX_SAFE_INTEGER);
  for (const seed of ['-1', '+1', '1.0', '1e3', ' 1', '1 ', '1\n', '1\r\n', '', 'NaN', 'Infinity', '9007199254740992']) assert.throws(() => parseSeed(seed));
});
test('fixed payloads preserve exact prompt and no private knobs', () => {
  const prompt = '  <img src=x onerror=alert(1)>\ntexto  ';
  assert.deepEqual(makePayload({seed: '42', prompt}), {seed: 42, prompt, duration_seconds: 2.3, image: 'dance_reference.png'});
  assert.deepEqual(makePayload({seed: '0', prompt, continuation: true}), {seed: 0, prompt, duration_seconds: 2.3, reference_tail_seconds: 3, include_audio: true});
  for (const value of ['', '   ', 'x'.repeat(12001)]) assert.throws(() => makePayload({seed: '0', prompt: value}));
  assert.doesNotThrow(() => makePayload({seed: '0', prompt: 'x'.repeat(12000)}));
  assert.throws(() => makePayload({seed: '0', prompt: 'x', image: '../private.png'}));
});
test('state alone is never publication and failed evidence is never playable', () => {
  const run = {id: 'own', state: 'ready_for_review', output: {path: 'runs/own/chunk.mp4'}};
  assert.equal(playableURL(run, {video_url: '/runs/own/video'}), '/runs/own/video');
  assert.equal(playableURL({...run, output: {}}, {video_url: '/runs/own/video'}), null);
  assert.equal(playableURL(run, {video_url: 'http://127.0.0.1:8010/runs/own/video'}), null);
  assert.equal(playableURL(run, {video_url: '/runs/other/video'}), null);
  for (const state of ['failed', 'interrupted', 'queued', 'running']) assert.equal(playableURL({...run, state}, {video_url: '/runs/own/video'}), null);
  for (const state of ['accepted', 'rejected']) assert.equal(playableURL({...run, state}, null, {video_url: '/runs/own/video'}), '/runs/own/video');
});
test('single admission and single wait; no concurrent double-submit', async () => {
  const calls = []; let release;
  const gate = new Promise(resolve => { release = resolve; });
  const client = createClient(async (url, options) => {
    calls.push({url, ...options});
    if (options.method === 'POST') { await gate; return reply({id: 'own-id'}, 202); }
    return reply({id: 'own-id', state: 'ready_for_review'});
  });
  const admitted = [];
  const first = client.generate('/runs/i2v', {seed: 0}, run => admitted.push(run.id));
  await assert.rejects(client.generate('/runs/i2v', {seed: 0}, () => {}), /andamento/);
  release(); await first;
  assert.deepEqual(admitted, ['own-id']);
  assert.deepEqual(calls.map(call => [call.method, call.url]), [['POST', '/runs/i2v'], ['GET', '/runs/own-id?wait=true']]);
});
test('failed/ambiguous admission never retries or waits for an invented ID', async () => {
  for (const mode of ['network', '500', '409', 'no-id', 'wrong-status']) {
    const calls = [];
    const client = createClient(async (url, options) => {
      calls.push([options.method, url]);
      if (mode === 'network') throw new Error('lost connection');
      if (mode === '500' || mode === '409') return reply({detail: 'busy'}, Number(mode));
      return reply(mode === 'no-id' ? {} : {id: 'own'}, mode === 'wrong-status' ? 200 : 202);
    });
    await assert.rejects(client.generate('/runs/i2v', {}, () => {}));
    assert.deepEqual(calls, [['POST', '/runs/i2v']]);
  }
});
test('one wait failure remains failure without replay', async () => {
  const calls = [];
  const client = createClient(async (url, options) => { calls.push(url); if (options.method === 'POST') return reply({id: 'one'}, 202); throw new Error('wait connection lost'); });
  await assert.rejects(client.generate('/runs/parent/v2v', {}, () => {}), /lost/);
  assert.deepEqual(calls, ['/runs/parent/v2v', '/runs/one?wait=true']);
});
test('review uses only public routes and preserves actionable HTTP status', async () => {
  const calls = [];
  const client = createClient(async (url, options) => { calls.push([options.method, url]); return reply({detail: '<b>slot busy</b>'}, 409); });
  await assert.rejects(client.decide('own', 'accept'), error => error instanceof HTTPError && error.status === 409 && error.message.includes('<b>'));
  assert.deepEqual(calls, [['POST', '/runs/own/accept']]);
});
test('explicit roots preserve source paths and continuations inherit without new sources', () => {
  for (const source_root of ['assets', 'inputs', 'runs']) {
    const reference = {source_root, path: source_root === 'runs' ? '.data/runs/own/last_frame.png' : 'photo.png', name: '<img onerror=evil>'};
    assert.deepEqual(makePayload({seed: '0', prompt: ' exact ', reference}).references, [{source_root, path: reference.path}]);
    assert.equal(makePayload({seed: '0', prompt: 'exact', reference, continuation: true}).references, undefined);
  }
  for (const path of ['../private.png', '/etc/photo.png', 'a/../photo.png', 'a//photo.png', 'a\\\\photo.png', 'a\u0000.png']) assert.throws(() => referenceValue({source_root: 'inputs', path}));
  assert.throws(() => referenceValue({source_root: 'inputs;evil()', path: 'photo.png'}));
});
test('image URLs allow only bridge endpoints with safe relative query paths', () => {
  for (const url of ['/assets/image?path=dance_reference.png', '/inputs/image?path=id%2Foriginal.png', '/runs/own-id/image?name=last_frame.png']) assert.equal(imageURL(url), url);
  for (const url of ['https://evil/image', '//evil/image', 'javascript:evil()', '/inputs/image?path=..%2Fsecret', '/inputs/image?path=%2Fetc%2Fa.png', '/inputs/image?path=a.png&other=x', '/runs/own/image?name=chunk.mp4', '/inputs/image?path=a.png#evil', '/anything']) assert.equal(imageURL(url), null);
});
test('raw File upload is guarded and never serialized or followed by inference', async () => {
  const file = new File(['encoded fixture'], 'phone photo.png', {type: 'image/png'});
  const calls = []; let release;
  const gate = new Promise(resolve => { release = resolve; });
  const item = {source_root: 'inputs', path: 'id/original.png', image_url: '/inputs/image?path=id%2Foriginal.png'};
  const client = createClient(async (url, options) => { calls.push({url, options}); await gate; return reply(item, 201); });
  const first = client.upload(file); await assert.rejects(client.upload(file), /andamento/); release(); assert.deepEqual(await first, item);
  assert.equal(calls.length, 1); assert.equal(calls[0].url, '/inputs?name=phone%20photo.png'); assert.equal(calls[0].options.body, file); assert.equal(calls[0].options.headers['Content-Type'], 'image/png');
  for (const invalid of [{size: 0, type: 'image/png'}, {size: 32 * 1024 * 1024 + 1, type: 'image/png'}, {size: 1, type: 'text/html'}]) assert.throws(() => validateUpload(invalid));
});
test('SSE hints normalize worker paths, ignore temporary telemetry and accept overflow', () => {
  for (const path of ['.data', '.data/runs/own/manifest.json', 'runs/own/request.json', '.data/inputs/id/metadata.json']) assert.equal(relevantChange({path, invalidation: true}), true);
  for (const path of ['runs/own/telemetry.jsonl', '.data/inputs/id/.part', 'runs/own/tmp/manifest.json', 'elsewhere']) assert.equal(relevantChange({path, invalidation: true}), false);
  assert.equal(relevantChange({path: 'runs/own/manifest.json'}), false);
});
test('empty or wrong-ID wait is uncertain and never replayed', async () => {
  for (const result of [null, {}, {id: 'other', state: 'accepted'}]) {
    const calls = []; const client = createClient(async (url, options) => { calls.push(url); return options.method === 'POST' ? reply({id: 'own'}, 202) : reply(result); });
    await assert.rejects(client.generate('/runs/i2v', {}, () => {}), /Espera/); assert.deepEqual(calls, ['/runs/i2v', '/runs/own?wait=true']);
  }
});
test('Grok sends only literal idea/system/model and empty model defers to environment', () => {
  const prompt = 'ela dá um salto e o vestido fica vermelho';
  assert.deepEqual(grokPayload({prompt, system_prompt: 'Preserve a cena', model: ''}), {prompt, system_prompt: 'Preserve a cena'});
  assert.deepEqual(grokPayload({prompt, system_prompt: 'Sistema', model: 'chosen-id'}), {prompt, system_prompt: 'Sistema', model: 'chosen-id'});
  assert.deepEqual(editorPayload({system_prompt: '  custom  ', model: ''}), {system_prompt: '  custom  ', model: ''});
  for (const config of [{system_prompt: ''}, {system_prompt: 'x'.repeat(100001)}, {system_prompt: 'x', model: 'm'.repeat(257)}, {system_prompt: 'x', model: ' '}]) assert.throws(() => editorPayload(config));
  assert.throws(() => grokPayload({prompt: ' ', system_prompt: 'x'}));
});
test('Grok output stays literal and scene limits never silently truncate', () => {
  const text = '<img onerror=evil()> vestido vermelho'; assert.equal(sceneText(text), text);
  assert.equal(sceneText('x'.repeat(12000)).length, 12000);
  for (const text of [null, '', ' ', 'x'.repeat(12001)]) assert.throws(() => sceneText(text));
});
test('Grok has a separate double-click guard and one text POST with no native wait', async () => {
  const calls = []; let release; const gate = new Promise(resolve => { release = resolve; });
  const client = createClient(async (url, options) => { calls.push([url, options.method, JSON.parse(options.body)]); await gate; return reply({text: 'Cena editável', model: 'fake'}); });
  const payload = {prompt: 'salto', system_prompt: 'detalhe', model: ''};
  const first = client.detail(payload); await assert.rejects(client.detail(payload), /detalhando/); release(); assert.equal(await first, 'Cena editável');
  assert.deepEqual(calls, [['/grok', 'POST', {system_prompt: 'detalhe', prompt: 'salto'}]]);
});
test('Grok failures never retry and editor save uses isolated PUT only', async () => {
  for (const mode of ['network', '500', 'oversized']) {
    const calls = []; const client = createClient(async (url, options) => { calls.push([url, options.method]); if (mode === 'network') throw new Error('lost response'); return mode === '500' ? reply({detail: 'provider unavailable'}, 500) : reply({text: 'x'.repeat(12001)}); });
    await assert.rejects(client.detail({prompt: 'ideia', system_prompt: 'sistema'})); assert.deepEqual(calls, [['/grok', 'POST']]);
  }
  const calls = []; const client = createClient(async (url, options) => { calls.push([url, options.method, JSON.parse(options.body)]); return reply({system_prompt: 'custom', model: ''}); });
  await client.saveEditor({system_prompt: 'custom', model: ''}); assert.deepEqual(calls, [['/grok/editor', 'PUT', {system_prompt: 'custom', model: ''}]]);
});
test('Grok snapshots reject older draft, mode, selection or editor response', () => {
  const before = {revision: 1, mode: 'new', selected: 'one', prompt: 'jump', system_prompt: 'system', model: ''};
  assert.equal(draftMatches(before, {...before}), true);
  for (const [key, value] of Object.entries({revision: 2, mode: 'continue', selected: 'other', prompt: 'new draft', system_prompt: 'new system', model: 'chosen'})) assert.equal(draftMatches(before, {...before, [key]: value}), false);
});
const rootID = '11111111-1111-4111-8111-111111111111';
const endID = '22222222-2222-4222-8222-222222222222';
const assemblyID = '33333333-3333-4333-8333-333333333333';
const assembled = () => ({id: assemblyID, end_run_id: endID, state: 'completed', mode: 'preview', request_sha256: 'a'.repeat(64), output_sha256: 'b'.repeat(64), frames: 168, fps: '24/1', video_url: `/assemblies/${assemblyID}/video`, output: {path: `.data/assemblies/${assemblyID}/video.mp4`}});
test('assembly requires canonical UUID and preserves query/hash recovery pointer only', () => {
  assert.equal(canonicalUUID(endID), endID);
  for (const id of ['AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA', `${endID}\n`, '../escape', 'own']) assert.throws(() => canonicalUUID(id));
  const location = assemblyLocation('http://local/?other=one#viewer', assemblyID);
  assert.equal(location, `/?other=one&assembly=${assemblyID}#viewer`);
  assert.equal(assemblyPointer(`http://local${location}`), assemblyID);
  assert.equal(assemblyPointer('http://local/#viewer'), null);
  for (const suffix of ['?assembly=../escape', `?assembly=${assemblyID}&assembly=${assemblyID}`]) assert.throws(() => assemblyPointer(`http://local/${suffix}`));
});
test('native UUID preferred; LAN fallback uses exactly one cryptographic16-byte v4 draw', () => {
  let calls = 0;
  assert.equal(newAssemblyUUID({randomUUID: () => assemblyID, getRandomValues: () => { throw new Error('unused'); }}), assemblyID);
  const id = newAssemblyUUID({getRandomValues: bytes => { calls++; assert.equal(bytes.length, 16); bytes.fill(255); return bytes; }});
  assert.equal(id, 'ffffffff-ffff-4fff-bfff-ffffffffffff'); assert.equal(calls, 1); assert.equal(canonicalUUID(id), id);
  assert.throws(() => newAssemblyUUID({}));
});
test('assembly eligibility keeps accepted ancestors and ready or accepted end in exact order', () => {
  const run = {id: endID, state: 'ready_for_review', output: {path: '.data/runs/end/chunk.mp4'}};
  const blocks = [{id: rootID, parent_id: null, state: 'accepted', video_url: `/runs/${rootID}/video`}, {id: endID, parent_id: rootID, state: 'ready_for_review', video_url: `/runs/${endID}/video`}];
  const sequence = {root_id: rootID, end_run_id: endID, blocks};
  assert.equal(canAssemble(run, sequence), true);
  assert.equal(canAssemble({...run, state: 'accepted'}, {...sequence, blocks: [blocks[0], {...blocks[1], state: 'accepted'}]}), true);
  for (const state of ['rejected', 'failed', 'running', 'interrupted']) assert.equal(canAssemble({...run, state}, sequence), false);
  assert.equal(canAssemble(run, {...sequence, blocks: [{...blocks[0], state: 'rejected'}, blocks[1]]}), false);
  assert.equal(canAssemble(run, {...sequence, blocks: blocks.toReversed()}), false);
  assert.equal(canAssemble(run, {...sequence, blocks: []}), false);
  assert.equal(canAssemble(run, {...sequence, blocks: Array(101).fill(blocks[0])}), false);
});
test('assembly never exposes foreign URLs, incomplete proof or noncompleted movie', () => {
  const record = assembled(); assert.equal(assemblyURL(record, endID), record.video_url); assert.equal(assemblyRecord(record), record);
  for (const update of [{state: 'running'}, {output_sha256: null}, {request_sha256: 'a'.repeat(64) + '\n'}, {video_url: 'https://evil/video'}, {video_url: `/assemblies/${rootID}/video`}, {output: {path: 'arbitrary.mp4'}}, {frames: 0}]) assert.equal(assemblyURL({...record, ...update}, endID), null);
  assert.equal(assemblyURL(record, rootID), null); assert.throws(() => assemblyRecord({...record, video_url: 'https://evil/video'}));
});
test('one assembly POST awaits200 without native wait or double submission', async () => {
  const calls = []; let release; const gate = new Promise(resolve => { release = resolve; });
  const client = createClient(async (url, options) => { calls.push([url, options.method, JSON.parse(options.body)]); await gate; return reply(assembled()); });
  const first = client.assemble(assemblyID, endID); await assert.rejects(client.assemble(assemblyID, endID), /montagem/); release(); await first;
  assert.deepEqual(calls, [[`/assemblies/${assemblyID}`, 'POST', {end_run_id: endID}]]);
});
test('lost assembly or conflict never creates another UUID or retries POST', async () => {
  for (const mode of ['network', '409', '202', 'wrong-end']) {
    const calls = []; const client = createClient(async (url, options) => { calls.push([url, options.method]); if (mode === 'network') throw new Error('lost assembly'); if (mode === '409') return reply({detail: 'busy or collision'}, 409); return reply(mode === 'wrong-end' ? {...assembled(), end_run_id: rootID} : assembled(), mode === '202' ? 202 : 200); });
    await assert.rejects(client.assemble(assemblyID, endID)); assert.deepEqual(calls, [[`/assemblies/${assemblyID}`, 'POST']]);
  }
});
test('assembly filesystem hints only invalidate metadata, not media/requests', () => {
  assert.equal(relevantChange({path: `.data/assemblies/${assemblyID}/metadata.json`, invalidation: true}), true);
  for (const file of ['request.json', 'video.mp4', '.part']) assert.equal(relevantChange({path: `.data/assemblies/${assemblyID}/${file}`, invalidation: true}), false);
});
const capsDTO = {default_requested_seconds: 8, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125};
test('duration capabilities are exact and missing legacy capabilities never unlock time', () => {
  assert.equal(durationCapabilities(undefined), null);
  assert.deepEqual(durationCapabilities(capsDTO), capsDTO);
  assert.deepEqual(durationCapabilities({...capsDTO, default_requested_seconds: 2.3}), {...capsDTO, default_requested_seconds: 2.3});
  for (const default_requested_seconds of [0, -1, 10.01, 2.333, '8', NaN, Infinity]) assert.throws(() => durationCapabilities({...capsDTO, default_requested_seconds}));
  assert.equal(parseDuration('2,30'), 2.3);
  assert.throws(() => parseDuration('3'));
  for (const value of [null, {}, {...capsDTO, max_frames: 240}, {...capsDTO, rounding: 'half_up'}, {...capsDTO, private: true}]) assert.throws(() => durationCapabilities(value));
});
test('app defaults use backend eight seconds, while legacy and explicit historical time stay intact', () => {
  for (const continuation of [false, true]) {
    const request = {seed: '42', prompt: 'Preserve this scene', capabilities: capsDTO, continuation};
    assert.equal(makePayload(request).duration_seconds, 8);
    assert.equal(makePayload({...request, duration: '2.3'}).duration_seconds, 2.3);
  }
  assert.equal(alignedFrames(8), 192);
});
test('native half-even rounding includes ties that JavaScript Math.round gets wrong', () => {
  for (const [value, expected] of [[4.5, 4], [5.5, 6], [22.5, 22], [56.5, 56], [239.5, 240]]) assert.equal(roundHalfEven(value), expected);
  for (const [seconds, frames] of [[0.01, 5], [2.3, 56], [2.8, 73], [3, 73], [5, 124], [10, 243], [22.5 / 24, 22], [56.5 / 24, 56]]) assert.equal(alignedFrames(seconds), frames);
  assert.equal(alignedFrames(56.5 / 24 + 0.000001), 73);
});
test('strict decimal requested time supports local comma without clamp or coercion', () => {
  for (const value of ['0.01', '2.3', '2,80', '3', '5.00', '10']) assert.equal(parseDuration(value, capsDTO), Number(value.replace(',', '.')));
  for (const value of ['', ' ', '0', '-1', '+3', '1e1', '0x5', 'NaN', 'Infinity', '10.01', '2.333', '.5', '3.', '3\n', '1,2.3']) assert.throws(() => parseDuration(value, capsDTO));
  assert.throws(() => parseDuration('100', {...capsDTO, max_requested_seconds: 1000}));
});
test('chosen time is sent exactly for roots and continuations with frozen tail/audio', () => {
  for (const duration of ['2.3', '2.8', '3', '5', '10']) {
    const base = {seed: 4, prompt: ' exact ', duration_seconds: Number(duration)};
    assert.deepEqual(makePayload({seed: '4', prompt: ' exact ', duration, capabilities: capsDTO}), {...base, image: 'dance_reference.png'});
    assert.deepEqual(makePayload({seed: '4', prompt: ' exact ', duration, capabilities: capsDTO, continuation: true, reference: {source_root: 'inputs', path: 'ignored.png'}}), {...base, reference_tail_seconds: 3, include_audio: true});
  }
});
test('Grok image context is a strict own reference, separate from native generation', async () => {
  const reference = {source_root: 'inputs', path: 'own/original.png', image_url: '/inputs/image?path=own%2Foriginal.png'};
  const payload = grokPayload({system_prompt: 'system', prompt: 'idea', model: 'grok-4.20-0309-non-reasoning', reference});
  assert.deepEqual(payload.reference, {source_root: 'inputs', path: 'own/original.png'});
  assert.throws(() => grokPayload({...payload, reference: {source_root: 'inputs', path: '../oauth.json'}}));
  const calls = [], client = createClient(async (path, options) => { calls.push([path, options.method, JSON.parse(options.body)]); return reply({text: 'editable'}); });
  assert.equal(await client.detail(payload), 'editable'); assert.deepEqual(calls, [['/grok', 'POST', payload]]);
});
test('stale duration, image and originating parent drafts cannot pass Grok snapshot match', () => {
  const before = {revision: 1, mode: 'continue', selected: rootID, draftKey: rootID, prompt: 'idea', system_prompt: 'system', model: 'pin', duration: '3', referenceKey: 'original', proposal: 'draft proposal'};
  for (const [key, value] of Object.entries({duration: '5', referenceKey: 'other-image', draftKey: endID, revision: 2, proposal: 'manual edit'})) assert.equal(draftMatches(before, {...before, [key]: value}), false);
});
test('assets do not contain unsafe bindings, persistence, autoplay or polling', async () => {
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /innerHTML|localStorage|sessionStorage|setInterval|setTimeout/);
  assert.doesNotMatch(html, /autoplay|https?:\/\//);
  assert.match(html, /lang="pt-BR"/);
  assert.match(html, /preload="metadata"/);
});

function motionFixture() {
  const listeners = new Map(), preferenceListeners = new Map(), viewListeners = new Map(), classes = new Set();
  const preference = {matches: false, addEventListener: (name, fn) => preferenceListeners.set(name, fn), removeEventListener: name => preferenceListeners.delete(name)};
  const document = {hidden: false, activeElement: null, documentElement: {classList: {toggle: (name, value) => value ? classes.add(name) : classes.delete(name)}}, addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name), defaultView: {matchMedia: () => preference, addEventListener: (name, fn) => viewListeners.set(name, fn), removeEventListener: name => viewListeners.delete(name)}};
  const calls = [];
  function node() {
    return {isConnected: true, dataset: {}, attrs: {}, setAttribute(name, value) { this.attrs[name] = value; }, closest: () => null, matches: () => false, querySelector: () => null, contains: () => false, animate(frames, options) { let reject; const finished = new Promise((_, fail) => { reject = fail; }); const animation = {finished, cancelled: 0, cancel() { this.cancelled++; reject(new Error('cancelled')); }}; calls.push({frames, options, animation}); return animation; }};
  }
  return {document, preference, classes, listeners, preferenceListeners, viewListeners, calls, node};
}
test('motion tokens are bounded, directional and compositor-only, with six-card stagger', () => {
  assert.equal(motionSpec('enter').options.duration, 180);
  assert.match(motionSpec('enter', {direction: -1}).frames[0].transform, /-12px/);
  assert.equal(motionSpec('enter', {index: 5}).options.delay, 80);
  assert.equal(motionSpec('enter', {index: 6}).options.delay, 0);
  assert.equal(motionSpec('confirm').options.duration, 240);
  assert.equal(motionSpec('cue').options.duration, 160);
  for (const kind of ['enter', 'confirm', 'cue']) for (const frame of motionSpec(kind).frames) assert.ok(Object.keys(frame).every(key => ['transform', 'opacity'].includes(key)));
});
test('motion signatures survive recreated cards and cannot grow from arbitrary identifiers', () => {
  const f = motionFixture(), motion = createPresentationMotion(f.document);
  assert.equal(motion.changed('library', 'snapshot-one', [f.node()], 'enter'), true);
  assert.equal(motion.changed('library', 'snapshot-one', [f.node()], 'enter'), false);
  for (let id = 0; id < 1000; ++id) assert.equal(motion.changed(`untrusted-${id}`, id, [f.node()]), false);
  assert.equal(motion.channelCount, 1); assert.equal(f.calls.length, 1);
  motion.destroy();
});
test('reduce preference is immediate and a dynamic change cancels running animations', () => {
  const f = motionFixture(), motion = createPresentationMotion(f.document);
  assert.equal(motion.play(f.node(), 'enter'), true); assert.equal(motion.activeCount, 1);
  f.preference.matches = true; f.preferenceListeners.get('change')();
  assert.equal(motion.activeCount, 0); assert.equal(f.calls[0].animation.cancelled, 1);
  assert.equal(motion.play(f.node()), false); assert.ok(f.classes.has('motion-paused'));
  f.preference.matches = false; f.preferenceListeners.get('change')();
  assert.equal(f.calls.length, 1); assert.equal(f.classes.has('motion-paused'), false);
  motion.destroy();
});
test('hidden, unsupported, fixed-action ancestors, media and editable targets remain static', () => {
  const f = motionFixture(), motion = createPresentationMotion(f.document);
  const fixedAncestor = f.node(); fixedAncestor.querySelector = () => ({});
  const nativeControl = f.node(); nativeControl.matches = () => true;
  const hidden = f.node(); hidden.closest = () => ({});
  const unsupported = f.node(); delete unsupported.animate;
  for (const target of [fixedAncestor, nativeControl, hidden, unsupported]) assert.equal(motion.play(target, 'enter'), false);
  const focusedAncestor = f.node(); focusedAncestor.contains = () => true;
  f.document.activeElement = {matches: () => true}; assert.equal(motion.play(focusedAncestor), false);
  f.document.activeElement = null; f.document.hidden = true; assert.equal(motion.play(f.node()), false);
  assert.equal(f.calls.length, 0); motion.destroy();
});
test('rapid replacement and hidden/page destruction reap animations without rejected promises leaking', async () => {
  const f = motionFixture(), motion = createPresentationMotion(f.document), target = f.node();
  motion.play(target); motion.play(target, 'enter');
  assert.equal(f.calls[0].animation.cancelled, 1); assert.equal(motion.activeCount, 1);
  await Promise.resolve(); await Promise.resolve(); assert.equal(motion.activeCount, 1);
  f.document.hidden = true; f.listeners.get('visibilitychange')();
  assert.equal(motion.activeCount, 0); assert.ok(f.classes.has('motion-paused'));
  f.document.hidden = false; f.listeners.get('visibilitychange')();
  motion.play(target); motion.destroy(); assert.equal(motion.play(target), false);
  assert.equal(motion.activeCount, 0); assert.equal(f.preferenceListeners.size + f.listeners.size + f.viewListeners.size, 0);
  await Promise.resolve(); await Promise.resolve();
});
test('busy is a real-state presentation attribute, not a progress value or action', () => {
  const f = motionFixture(), motion = createPresentationMotion(f.document), target = f.node();
  motion.busy(target, true); assert.equal(target.dataset.busy, 'true'); assert.equal(target.attrs['aria-busy'], 'true');
  motion.busy(target, false); assert.equal(target.dataset.busy, 'false'); assert.equal(f.calls.length, 0);
  motion.destroy();
});

test('draft settings are contextual and never unlock published or uncertain results', () => {
  for (const screen of ['context', 'proposal', 'generation', 'continuation']) {
    assert.equal(draftSettingsAllowed({screen}), true);
    assert.equal(draftSettingsAllowed({screen: 'settings', originScreen: screen}), true);
    for (const field of ['statusOnly', 'submitted', 'busy', 'uncertain', 'uploadBusy', 'uploadUncertain', 'assemblyBusy', 'assemblyUncertain']) assert.equal(draftSettingsAllowed({screen, [field]: true}), false, `${screen}: ${field}`);
  }
  for (const screen of ['library', 'review', 'assembly', 'settings', undefined]) assert.equal(draftSettingsAllowed({screen}), false);
  const ready = {config: {}, mode: 'new'};
  assert.equal(nativeExecutionBlocked(ready), false);
  assert.equal(nativeExecutionBlocked({}), true);
  for (const field of ['statusOnly', 'submitted', 'busy', 'uncertain', 'uploadBusy', 'uploadUncertain', 'assemblyBusy', 'assemblyUncertain', 'retryPreparing']) assert.equal(nativeExecutionBlocked({...ready, [field]: true}), true, field);
  for (const state of ['queued', 'running']) assert.equal(nativeExecutionBlocked({...ready, pendingRun: {state}}), true);
  for (const state of ['accepted', 'ready_for_review', 'rejected', 'interrupted', 'failed']) assert.equal(nativeExecutionBlocked({...ready, pendingRun: {state}}), false);
  assert.equal(nativeExecutionBlocked({...ready, assemblyLocked: true, grokBusy: true, grokUncertain: true}), false);
  assert.equal(nativeExecutionBlocked({...ready, mode: 'continue', parent: {state: 'accepted'}}), false);
  for (const state of ['rejected', 'interrupted', 'running', undefined]) assert.equal(nativeExecutionBlocked({...ready, mode: 'continue', parent: {state}}), true);
  const modeRouting = source.slice(source.indexOf('function setMode(mode)'), source.indexOf('function storyURL'));
  assert.match(modeRouting, /if \(freshIntent\) draft\(\)\.submitted = false/);
  assert.doesNotMatch(modeRouting, /state\.(?:uncertain|busy|pendingRun|waitController|assemblyUncertain|uploadUncertain|grokUncertain)\s*=/);
  assert.match(source, /\$\('create-fields'\)\.disabled = \$\('generate'\)\.disabled = nativeExecutionBlocked/);
  assert.match(source, /state\.screen !== 'generation' \|\| nativeExecutionBlocked/);
});
test('continuation Grok has one canonical parent and never accepts an arbitrary frame path', () => {
  const id = '11111111-1111-4111-8111-111111111111', reference = {source_root: 'assets', path: 'dance_reference.png'};
  const base = {prompt: '  a pose muda\n vestido vermelho ', system_prompt: 'instruções locais', model: 'grok-4.20-0309-non-reasoning', reference};
  assert.deepEqual(grokPayload({...base, continuation_parent_id: id, last_frame_path: '/private/image.png'}), {...base, continuation_parent_id: id});
  assert.equal(Object.hasOwn(grokPayload(base), 'continuation_parent_id'), false);
  assert.equal(lastFrameURL(id), `/grok/continuation/${id}/last-frame`);
  assert.throws(() => grokPayload({...base, reference: null, continuation_parent_id: id}));
  for (const bad of [id.toUpperCase().replace('1111', 'AAAA'), 'http://remote/frame.png', '../frame', id.replaceAll('-', ''), null, undefined]) assert.throws(() => lastFrameURL(bad));
});
test('explicit own identity can be previewed without depending on the current catalog page', () => {
  const id = '11111111-1111-4111-8111-111111111111';
  assert.equal(referencePreviewURL({source_root: 'assets', path: 'folder/rosto novo.jpg'}), '/assets/image?path=folder%2Frosto%20novo.jpg');
  assert.equal(referencePreviewURL({source_root: 'inputs', path: 'phone.png'}), '/inputs/image?path=phone.png');
  for (const name of ['initial_frame', 'last_frame']) assert.equal(referencePreviewURL({source_root: 'runs', path: `.data/runs/${id}/${name}.png`}), `/runs/${id}/image?name=${name}.png`);
  for (const value of [{source_root: 'private', path: 'x.png'}, {source_root: 'inputs', path: '.private/x.png'}, {source_root: 'inputs', path: '../x.png'}, {source_root: 'runs', path: `runs/${id}/guessed.png`}, {source_root: 'runs', path: 'last_frame.png'}]) assert.equal(referencePreviewURL(value), null);
});
test('same image and idea cannot make an old-parent Grok response current', () => {
  const before = {continuationParentId: '11111111-1111-4111-8111-111111111111'};
  assert.equal(draftMatches(before, {...before}), true);
  assert.equal(draftMatches(before, {continuationParentId: '22222222-2222-4222-8222-222222222222'}), false);
  assert.equal(draftMatches(before, {continuationParentId: null}), false);
});
test('app navigation has unique settings fields, one top Back and no global Library/New tabs', async () => {
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ['back', 'settings-open', 'settings-done', 'seed', 'duration', 'grok-system', 'grok-model', 'run-prompt', 'retry-mode', 'last-frame-preview']) assert.ok(ids.includes(id), id);
  assert.match(html, /<header class="topbar">.*id="back".*id="screen-title".*id="settings-open"/);
  assert.doesNotMatch(html + source, /nav-library|nav-new|<footer/);
  const form = html.match(/<form id="create-form"[^]*?<\/form>/)[0];
  assert.doesNotMatch(form, /id="(?:duration|seed)"/);
  assert.match(form, /id="block-summary"/);
  assert.ok(html.indexOf('data-screen="settings"') < html.indexOf('id="duration"'));
  assert.match(html, /Prompt enviado nesta tentativa/);
  const recovery = source.slice(source.indexOf('if (state.config?.assembly_enabled && pointer)'));
  assert.match(recovery, /navigate\('assembly', \{focus: false\}\);[^]*?await readAssembly\(\{restoreSelection: true\}\)/);
  assert.doesNotMatch(recovery, /navigate\('assembly', \{remember: false/);
  const css = await readFile(new URL('../src/h3_backend/web/app.css', import.meta.url), 'utf8');
  for (const rule of css.matchAll(/\.screen-actions\{([^}]*)\}/g)) assert.doesNotMatch(rule[1], /position:(?:fixed|sticky)/);
  assert.match(css, /\.task-panel \.clip-list\{[^}]*max-height:none;overflow:visible/);
  assert.match(css, /\.task-panel \.film-strip\{display:grid;[^}]*overflow:visible/);
});
