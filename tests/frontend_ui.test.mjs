import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../src/h3_backend/web/app.js', import.meta.url), 'utf8');
const {parseSeed, makePayload, playableURL, createClient, HTTPError} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
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
test('assets do not contain unsafe bindings, persistence, autoplay or polling', async () => {
  const html = await readFile(new URL('../src/h3_backend/web/index.html', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /innerHTML|localStorage|sessionStorage|setInterval|setTimeout/);
  assert.doesNotMatch(html, /autoplay|https?:\/\//);
  assert.match(html, /lang="pt-BR"/);
  assert.match(html, /preload="metadata"/);
});
