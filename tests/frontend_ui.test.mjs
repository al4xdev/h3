import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {parseSeed, makePayload, playableURL, createClient, HTTPError, referenceValue, imageURL, validateUpload, relevantChange, editorPayload, grokPayload, sceneText, draftMatches} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const reply = (data, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => data});

test('strict seed boundaries, no float/exponent/sign/whitespace coercion', () => {
  assert.equal(parseSeed('0'), 0);
  assert.equal(parseSeed('9007199254740991'), Number.MAX_SAFE_INTEGER);
  for (const seed of ['-1', '+1', '1.0', '1e3', ' 1', '1 ', '', 'NaN', 'Infinity', '9007199254740992']) assert.throws(() => parseSeed(seed));
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
test('assets do not contain unsafe bindings, persistence, autoplay or polling', async () => {
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /innerHTML|localStorage|sessionStorage|setInterval|setTimeout/);
  assert.doesNotMatch(html, /autoplay|https?:\/\//);
  assert.match(html, /lang="pt-BR"/);
  assert.match(html, /preload="metadata"/);
});
