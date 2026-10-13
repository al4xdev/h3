import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { spawnSync } from 'node:child_process';
import { createGenTools, tools } from '../tools/gen_mcp.mjs';
import { tools as shimTools } from '../.agents/gen-tools/gen.mjs';

const RUN = 'a'.repeat(32);
const CLI = '/home/alex/.config/my_scripts/gen/gen.py';
const STATUS = { unit: 'gen.service', state: 'absent', substate: null, owned: false,
  run: null, profile: null, uncertain: false, readiness: 'not-verified' };
const STOP = { result: 'not-running', readiness: 'not-verified' };
const START = { result: 'started', run: RUN, profile: 'image', readiness: 'not-verified' };
const tool = (list, name) => list.find(value => value.name === name);
function fixture(action, options = {}) {
  const calls = [];
  const children = [];
  const spawnWorker = (...args) => {
    calls.push(args);
    const child = new EventEmitter();
    child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.signals = [];
    child.kill = signal => {
      child.signals.push(signal);
      if (signal === 'SIGKILL') queueMicrotask(() => child.emit('close', null, signal));
      return true;
    };
    children.push(child);
    queueMicrotask(() => action?.(child));
    return child;
  };
  return { calls, children, list: createGenTools({ spawnWorker, ...options }) };
}
const response = (value, code = 0, stderr = '') => child => {
  if (stderr) child.stderr.write(stderr);
  child.stdout.write(typeof value === 'string' ? value : JSON.stringify(value));
  child.emit('close', code, null);
};

test('import, shim discovery and info are pure metadata; no optional annotation contract assumed', async () => {
  assert.equal(shimTools, tools);
  assert.deepEqual(tools.map(t => t.name), ['gen_info', 'gen_status', 'gen_logs', 'gen_start', 'gen_stop']);
  const f = fixture(() => assert.fail('metadata spawned a worker'));
  const info = await tool(f.list, 'gen_info').handler({});
  assert.equal(info.cli, CLI);
  assert.equal(info.timeout_ms, 20_000);
  assert.equal(info.stdout_limit_bytes, 32 * 1024 * 1024);
  assert.equal(info.retry, false);
  assert.match(info.stop, /not a pinned run/);
  assert.equal(f.calls.length, 0);
  for (const value of tools) {
    assert.equal(value.inputSchema.additionalProperties, false);
    assert.equal(typeof value.handler, 'function');
    assert.equal('annotations' in value, false);
  }
});

test('fresh native shim discovery never invokes a subprocess', () => {
  const shim = new URL('../.agents/gen-tools/gen.mjs', import.meta.url).href;
  const probe = spawnSync(process.execPath, ['--input-type=module', '-e', `
    import cp from 'node:child_process';
    import { syncBuiltinESMExports } from 'node:module';
    cp.spawn = cp.spawnSync = cp.exec = cp.execSync = cp.execFile = cp.execFileSync = cp.fork = () => {
      throw new Error('Discovery must not start any process');
    };
    syncBuiltinESMExports();
    const { tools } = await import(${JSON.stringify(shim)});
    const info = await tools.find(t => t.name === 'gen_info').handler({});
    if (tools.length !== 5 || info.retry !== false) throw new Error('Invalid discovery');
  `], { encoding: 'utf8', timeout: 5000 });
  assert.equal(probe.status, 0, probe.stderr);
  assert.equal(probe.stdout, '');
  assert.equal(probe.stderr, '');
});

test('schemas pin confirmed=true, exact profiles, finite logs and empty read inputs', () => {
  const start = tool(tools, 'gen_start').inputSchema;
  assert.deepEqual(start.properties.profile.enum, ['image', 'video', 'qw', 'gmmax', 'gmno', 'gmmed', 'gmrol', 'gmlow']);
  assert.deepEqual(start.properties.confirmed, { type: 'boolean', const: true });
  assert.deepEqual(start.required, ['profile', 'confirmed']);
  assert.deepEqual(tool(tools, 'gen_stop').inputSchema, { type: 'object', properties: {
    confirmed: { type: 'boolean', const: true } }, required: ['confirmed'], additionalProperties: false });
  for (const name of ['gen_info', 'gen_status']) assert.deepEqual(tool(tools, name).inputSchema,
    { type: 'object', properties: {}, additionalProperties: false });
  assert.deepEqual(Object.keys(tool(tools, 'gen_logs').inputSchema.properties), ['start', 'end', 'run']);
  assert.equal(tool(tools, 'gen_logs').inputSchema.properties.run.pattern, '^[0-9a-f]{32}$');
});

test('runtime rejects unknown fields, coercions, unsupported profiles and invalid log ranges before spawn', async () => {
  const f = fixture(() => assert.fail('invalid arguments spawned'));
  const cases = {
    gen_info: [null, [], { env: {} }], gen_status: [{ path: CLI }, 'status'],
    gen_start: [{}, { profile: 'image' }, { profile: 'image', confirmed: false },
      { profile: 'image', confirmed: 'true' }, { profile: 'imagem', confirmed: true },
      { profile: 'image', confirmed: true, args: [] }, { profile: 'image;stop', confirmed: true }],
    gen_stop: [{}, { confirmed: 1 }, { confirmed: true, expected_run: RUN }],
    gen_logs: [{ follow: false }, { end: 1 }, { start: 0 }, { start: 1.5 }, { start: '1' },
      { start: 2, end: 1 }, { start: 1, end: 501 }, { run: RUN.toUpperCase() },
      { run: '../private' }, { start: undefined }, { run: null }, { start: Infinity }],
  };
  for (const [name, values] of Object.entries(cases)) for (const args of values)
    assert.equal((await tool(f.list, name).handler(args, {})).error.code, 'invalid-arguments');
  assert.equal(f.calls.length, 0);
});

test('commands use fixed executable/path/headless with no shell, env overrides, detached worker or extra args', async () => {
  const cases = [
    ['gen_status', {}, 'status', [], STATUS],
    ['gen_stop', { confirmed: true }, 'stop', [], STOP],
    ['gen_logs', {}, 'logs', [], { lines: [] }],
    ['gen_logs', { start: 1, end: 500, run: RUN }, 'logs', ['1', '500', '--run', RUN],
      { lines: [{ number: 1, text: 'model output\n' }] }],
    ['gen_logs', { start: 20 }, 'logs', ['20'], { lines: [{ number: 20, text: '' }] }],
    ...tool(tools, 'gen_start').inputSchema.properties.profile.enum.map(profile =>
      ['gen_start', { profile, confirmed: true }, profile, [], { ...START, profile }]),
  ];
  for (const [name, args, command, extra, result] of cases) {
    const f = fixture(response(result));
    assert.deepEqual(await tool(f.list, name).handler(args, {}), result);
    assert.deepEqual(f.calls, [['/usr/bin/python3', ['-B', CLI, '--headless', command, ...extra],
      { shell: false, detached: false, stdio: ['ignore', 'pipe', 'pipe'] }]]);
    assert.deepEqual(f.children[0].signals, []);
  }
});

test('valid public CLI errors preserve objects/exits, unknown private diagnostics never escape', async () => {
  for (const [code, error] of [[1, { code: 'refused', message: 'stop completion not confirmed' }],
    [2, { code: 'invalid-arguments', message: 'invalid command or arguments; use gen --help' }]]) {
    const f = fixture(response({ error }, code));
    assert.deepEqual(await tool(f.list, 'gen_stop').handler({ confirmed: true }, {}), { error });
  }
  for (const payload of [{ error: { code: '/private/token', message: 'SECRET' } },
    { error: { code: 'refused', message: 'SECRET', env: 'SECRET' } }]) {
    const f = fixture(response(payload, 1));
    assert.doesNotMatch(JSON.stringify(await tool(f.list, 'gen_status').handler({}, {})), /SECRET|private\/token/);
  }
});

test('malformed, unexpected fields, stderr, invalid UTF8 and wrong success shapes stay private', async () => {
  const cases = [response('SECRET'), response('{}\n{}'), response({ ...STATUS, env: 'SECRET' }),
    response(STATUS, 3), response(STATUS, 0, 'SECRET'), response(START),
    child => { child.stdout.write(Buffer.from([0xff])); child.emit('close', 0, null); },
    child => child.emit('error', new Error('SECRET'))];
  for (const action of cases) {
    const f = fixture(action);
    const result = await tool(f.list, 'gen_status').handler({}, {});
    assert.ok(result.error);
    assert.doesNotMatch(JSON.stringify(result), /SECRET/);
  }
  const f = createGenTools({ spawnWorker() { throw new Error('SECRET'); } });
  assert.equal((await tool(f, 'gen_status').handler({}, {})).error.code, 'spawn-failed');
});

test('log output validates bounded text/line count, numbering, range and no extra private fields', async () => {
  const invalid = [{ lines: Array.from({ length: 501 }, (_, n) => ({ number: n + 1, text: '' })) },
    { lines: [{ number: 1, text: 'x'.repeat(4097) }] },
    { lines: [{ number: 0, text: '' }] }, { lines: [{ number: 1, text: '', env: 'SECRET' }] },
    { lines: [{ number: 1, text: '' }, { number: 3, text: '' }] }];
  for (const value of invalid) {
    const f = fixture(response(value));
    assert.equal((await tool(f.list, 'gen_logs').handler({}, {})).error.code, 'invalid-response');
  }
  const f = fixture(response({ lines: [{ number: 2, text: '' }] }));
  assert.equal((await tool(f.list, 'gen_logs').handler({ start: 3 }, {})).error.code, 'invalid-response');
});

test('logs preserve truncation markers and 500 escaped supplementary lines fit the byte bound', async () => {
  for (const text of ['x'.repeat(4096) + ' [line truncated]\n', '😀'.repeat(4096)]) {
    const value = { lines: [{ number: 1, text }] };
    const f = fixture(response(value));
    assert.deepEqual(await tool(f.list, 'gen_logs').handler({}, {}), value);
  }
  const value = { lines: Array.from({ length: 500 }, (_, i) => ({ number: i + 1, text: '😀'.repeat(4096) })) };
  // Python's ensure_ascii expands each supplementary code point to twelve bytes.
  const encoded = JSON.stringify(value).replaceAll('😀', '\\uD83D\\uDE00');
  assert.ok(Buffer.byteLength(encoded) > 500 * 4096 * 12);
  assert.ok(Buffer.byteLength(encoded) < 32 * 1024 * 1024);
  const f = fixture(response(encoded));
  assert.deepEqual(await tool(f.list, 'gen_logs').handler({ start: 1, end: 500 }, {}), value);
});

test('timeout and in-flight abort signal only own CLI, escalate boundedly, never retry', async () => {
  for (const aborting of [false, true]) {
    const controller = new AbortController();
    const f = fixture(null, { timeoutMs: aborting ? 20_000 : 5 });
    const pending = tool(f.list, 'gen_start').handler({ confirmed: true, profile: 'image' }, { signal: controller.signal });
    if (aborting) controller.abort(new Error('SECRET'));
    const result = await pending;
    assert.equal(result.error.code, aborting ? 'aborted' : 'timeout');
    assert.match(result.error.message, /uncertain.*no retry/);
    assert.deepEqual(f.children[0].signals, ['SIGTERM', 'SIGKILL']);
    assert.equal(f.calls.length, 1);
    assert.equal(f.children[0].stdout.destroyed, true);
  }
});

test('pre-abort creates no client; completed calls remove abort handling', async () => {
  const controller = new AbortController(); controller.abort();
  const f = fixture(response(STATUS));
  assert.equal((await tool(f.list, 'gen_status').handler({}, { signal: controller.signal })).error.code, 'aborted');
  assert.equal(f.calls.length, 0);
  const live = new AbortController();
  await tool(f.list, 'gen_status').handler({}, { signal: live.signal });
  live.abort();
  assert.deepEqual(f.children[0].signals, []);
});

test('stdout 32MiB and small stderr bounds terminate own client, discard diagnostics and do not retry', async () => {
  for (const [stream, size] of [['stdout', 32 * 1024 * 1024 + 1], ['stderr', 8193]]) {
    const f = fixture(child => child[stream].write(Buffer.alloc(size, 120)));
    const result = await tool(f.list, 'gen_logs').handler({}, {});
    assert.equal(result.error.code, 'output-limit');
    assert.deepEqual(f.children[0].signals, ['SIGTERM', 'SIGKILL']);
    assert.equal(f.calls.length, 1);
  }
});

test('client close after SIGTERM settles without SIGKILL and no global stop', async () => {
  const f = fixture(child => { child.kill = signal => {
    child.signals.push(signal); queueMicrotask(() => child.emit('close', null, signal)); return true;
  }; }, { timeoutMs: 5 });
  assert.equal((await tool(f.list, 'gen_stop').handler({ confirmed: true }, {})).error.code, 'timeout');
  assert.deepEqual(f.children[0].signals, ['SIGTERM']);
});

test('live-pid error waits for owned CLI close instead of leaking the client', async () => {
  let clientClosed = false;
  const f = fixture(child => {
    child.pid = 12345; // Inert identity only: child.kill never signals a real PID.
    child.kill = signal => {
      child.signals.push(signal);
      if (signal === 'SIGKILL') queueMicrotask(() => {
        clientClosed = true;
        child.emit('close', null, signal);
      });
      return true;
    };
    child.emit('error', new Error('SECRET live client error'));
  });
  const result = await tool(f.list, 'gen_status').handler({}, {});
  assert.equal(clientClosed, true);
  assert.equal(result.error.code, 'client-error');
  assert.doesNotMatch(JSON.stringify(result), /SECRET/);
  assert.deepEqual(f.children[0].signals, ['SIGTERM', 'SIGKILL']);
});

test('unconfirmed post-KILL cleanup stays bounded and explicitly reports missing client exit', async () => {
  const f = fixture(child => { child.kill = signal => { child.signals.push(signal); return true; }; },
    { timeoutMs: 5 });
  const result = await tool(f.list, 'gen_status').handler({}, {});
  assert.equal(result.error.code, 'timeout');
  assert.match(result.error.message, /Client exit could not be confirmed/);
  assert.deepEqual(f.children[0].signals, ['SIGTERM', 'SIGKILL']);
});
