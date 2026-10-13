import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { mkdir, readFile, writeFile, symlink, lstat } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import test from 'node:test';
import { createBenchmarkTools, tools } from '../tools/benchmark_mcp.mjs';

const ROOT = resolve(import.meta.dirname, '..');
const fixture = async () => {
  const root = join(ROOT, '.dumps', 'tests', 'mcp-fixtures', randomUUID());
  await mkdir(join(root, 'tools'), { recursive: true });
  await writeFile(join(root, 'tools', 'benchmark_h3.py'), '# Inert fixture, never invoked\n');
  return root;
};
function setup(root, mode = 'controlled') {
  const calls = [];
  let worker;
  let settled;
  const done = new Promise(resolve => { settled = resolve; });
  const definitions = createBenchmarkTools({ root, onSettled: settled,
    spawnWorker(command, args, options) {
      const record = join(root, '.data', 'benchmark-mcp', 'jobs', 'active.json');
      calls.push({ command, args, options, intent: readFile(record, 'utf8') });
      worker = new EventEmitter(); worker.pid = undefined; worker.unref = () => {};
      queueMicrotask(() => {
        if (mode === 'spawn-error') worker.emit('error', Object.assign(new Error('inert spawn failure'), { code: 'ENOENT' }));
        else { worker.emit('spawn'); if (mode === 'immediate-failure') worker.emit('exit', 7, null); }
      });
      return worker;
    },
  });
  const ctx = { root, signal: new AbortController().signal };
  const invoke = (name, args = {}) => definitions.find(tool => tool.name === name).handler(args, ctx);
  return { calls, definitions, invoke, done, exit: (code = 0) => worker.emit('exit', code, null) };
}

// No cleanup deletes runtime state; these inert fixtures stay in ignored .dumps.
test('import exposes only static definitions, no process or app state', () => {
  assert.deepEqual(tools.map(tool => tool.name), ['benchmark_info', 'benchmark_start', 'benchmark_status']);
  assert.equal(tools[1].inputSchema.properties.technical_acceptance.const, true);
  assert.deepEqual(tools[1].inputSchema.required, ['label', 'technical_acceptance']);
});

test('info is read-only and references the single CLI', async () => {
  const root = await fixture(); const server = setup(root);
  const value = await server.invoke('benchmark_info');
  assert.equal(value.real_gpu_chunks, 3); assert.equal(value.requires_running_api, true);
  assert.equal(value.command[4], join(root, 'tools', 'benchmark_h3.py'));
  assert.equal(server.calls.length, 0);
  await assert.rejects(lstat(join(root, '.data')), { code: 'ENOENT' });
});

for (const args of [
  { label: 'valid' }, { label: 'valid', technical_acceptance: false },
  { label: '../escape', technical_acceptance: true }, { label: '/absolute', technical_acceptance: true },
  { label: 'valid', technical_acceptance: true, command: 'anything' },
  { label: 'valid', technical_acceptance: true, api_url: 'https://outside.invalid' },
]) {
  test(`invalid start is inert: ${JSON.stringify(args)}`, async () => {
    const root = await fixture(); const server = setup(root);
    await assert.rejects(server.invoke('benchmark_start', args));
    assert.equal(server.calls.length, 0);
    await assert.rejects(lstat(join(root, '.data')), { code: 'ENOENT' });
  });
}

test('one explicit start persists intent, captures logs, and completes without replay', async () => {
  const root = await fixture(); const server = setup(root);
  const started = await server.invoke('benchmark_start', { label: 'success', technical_acceptance: true });
  assert.equal(started.state, 'running'); assert.equal(server.calls.length, 1);
  const call = server.calls[0]; assert.equal(call.command, 'uv');
  assert.equal(call.options.cwd, root); assert.equal(call.options.env.PYTHONDONTWRITEBYTECODE, '1');
  assert.equal(call.options.detached, true); assert.equal(call.options.stdio[0], 'ignore');
  assert.equal(typeof call.options.stdio[1], 'number'); assert.equal(typeof call.options.stdio[2], 'number');
  assert.deepEqual(call.args, ['run', '--no-sync', 'python', join(root, 'tools', 'benchmark_h3.py'),
    '--api-url', 'http://127.0.0.1:8010', '--output-dir', started.output_dir, '--technical-acceptance']);
  const guard = JSON.parse(await call.intent); assert.equal(guard.job_id, started.job_id);
  const own = join(root, '.data', 'benchmark-mcp', 'jobs', started.job_id);
  const job = JSON.parse(await readFile(join(own, 'job.json'), 'utf8'));
  assert.equal(job.artistic_approval, false); assert.equal(job.cli_sha256.length, 64);
  assert.deepEqual(job.command, ['uv', ...call.args]);
  assert.equal((await lstat(join(own, 'stdout.log'))).isFile(), true);
  await mkdir(started.output_dir);
  await writeFile(join(started.output_dir, 'report.json'), JSON.stringify({ phase: 'complete_pending_visual_review',
    scenario_sha256: 'a'.repeat(64), steps: [{ index: 1, phase: 'complete', result: { id: randomUUID(), state: 'accepted' } }] }));
  server.exit(); const ended = await server.done; assert.equal(ended.state, 'completed');
  const status = await server.invoke('benchmark_status', { job_id: started.job_id });
  assert.equal(status.state, 'completed'); assert.equal(status.visual_review, 'pending_owner_review');
  assert.equal(status.video, join(started.output_dir, 'benchmark.mp4'));
  assert.equal(status.process_identity_confirmed, false); assert.equal(server.calls.length, 1);
  await assert.rejects(server.invoke('benchmark_start', { label: 'success', technical_acceptance: true }));
  assert.equal(server.calls.length, 1);
});

test('global lock applies to another server instance and persists across restart', async () => {
  const root = await fixture(); const first = setup(root); const second = setup(root);
  const owned = await first.invoke('benchmark_start', { label: 'first', technical_acceptance: true });
  await assert.rejects(second.invoke('benchmark_start', { label: 'second', technical_acceptance: true }), { code: 'EEXIST' });
  assert.equal(second.calls.length, 0);
  const status = await second.invoke('benchmark_status', { job_id: owned.job_id });
  assert.equal(status.state, 'running'); assert.equal(status.replay_allowed, false);
  assert.equal(second.calls.length, 0);
  first.exit(3); await first.done;
});

test('an immediate worker exit cannot be lost while record is saved', async () => {
  const root = await fixture(); const server = setup(root, 'immediate-failure');
  const owned = await server.invoke('benchmark_start', { label: 'immediate', technical_acceptance: true });
  assert.equal((await server.done).state, 'failed');
  assert.equal((await server.invoke('benchmark_status', { job_id: owned.job_id })).exit_code, 7);
  assert.equal(server.calls.length, 1);
});

test('failed spawn releases only own lock but permanently reserves the label', async () => {
  const root = await fixture(); const server = setup(root, 'spawn-error');
  await assert.rejects(server.invoke('benchmark_start', { label: 'broken', technical_acceptance: true }), /inert spawn failure/);
  await assert.rejects(lstat(join(root, '.data', 'benchmark-mcp', 'jobs', 'active.json')), { code: 'ENOENT' });
  await assert.rejects(server.invoke('benchmark_start', { label: 'broken', technical_acceptance: true }), { code: 'EEXIST' });
  assert.equal(server.calls.length, 1);
});

test('zero exit without complete CLI proof fails honestly', async () => {
  const root = await fixture(); const server = setup(root);
  const owned = await server.invoke('benchmark_start', { label: 'no-report', technical_acceptance: true });
  server.exit(); const ended = await server.done; assert.equal(ended.state, 'failed');
  const status = await server.invoke('benchmark_status', { job_id: owned.job_id });
  assert.equal(status.video, undefined); assert.equal(status.state, 'failed');
});

test('completion contract matches frozen CLI, not an invented complete phase', async () => {
  const frozen = await readFile(join(ROOT, 'tools/benchmark_h3.py'), 'utf8');
  assert.ok(frozen.includes('self.state["phase"] = "complete_pending_visual_review"'));
  const root = await fixture(); const server = setup(root);
  const owned = await server.invoke('benchmark_start', { label: 'wrong-phase', technical_acceptance: true });
  await mkdir(owned.output_dir);
  await writeFile(join(owned.output_dir, 'report.json'), JSON.stringify({ phase: 'complete' }));
  server.exit(); assert.equal((await server.done).state, 'failed');
  const status = await server.invoke('benchmark_status', { job_id: owned.job_id });
  assert.equal(status.video, undefined); assert.equal(status.replay_allowed, false);
});

test('existing output is never invoked or overwritten', async () => {
  const root = await fixture(); const server = setup(root);
  const output = join(root, '.dumps', 'benchmarks', 'mcp-existing');
  await mkdir(output, { recursive: true }); await writeFile(join(output, 'report.json'), 'original');
  await assert.rejects(server.invoke('benchmark_start', { label: 'existing', technical_acceptance: true }), /Output already exists/);
  assert.equal(await readFile(join(output, 'report.json'), 'utf8'), 'original'); assert.equal(server.calls.length, 0);
});

test('symlinked durable root is rejected before spawn', async () => {
  const root = await fixture(); const other = await fixture(); const server = setup(root);
  await symlink(other, join(root, '.data'));
  await assert.rejects(server.invoke('benchmark_start', { label: 'escape', technical_acceptance: true }), /symlink/);
  assert.equal(server.calls.length, 0);
});

test('status rejects foreign IDs, paths and unexpected keys without startup', async () => {
  const root = await fixture(); const server = setup(root);
  for (const args of [{ job_id: '../data' }, { job_id: randomUUID() }, { job_id: randomUUID(), path: '/tmp' }]) {
    await assert.rejects(server.invoke('benchmark_status', args));
  }
  assert.equal(server.calls.length, 0);
});

test('SDK native project registration, initialize/list/info/invalid-start remain inert', async () => {
  const bridge = await import('/home/alex/git/my/dsh-customs/plugins/project-mcp/index.mjs');
  const { nativeMcp, hostRequire } = await import('/home/alex/git/my/dsh-customs/plugins/project-mcp/host.mjs');
  const configs = await bridge.loadProject(ROOT, await nativeMcp());
  const config = configs.find(item => item.serverName === 'h3_benchmark');
  assert.ok(config);
  assert.equal(config.serverName, 'h3_benchmark'); assert.equal(config.transport, 'stdio');
  assert.equal(config.cwd, ROOT); assert.equal(config.reconnect.enabled, false);
  const require = createRequire(hostRequire().resolve('@deepseek-ai/dsh-mcp-client'));
  const { Client } = await import(require.resolve('@modelcontextprotocol/client'));
  const { StdioClientTransport } = await import(require.resolve('@modelcontextprotocol/client/stdio'));
  const client = new Client({ name: 'h3-offline-test', version: '1.0.0' }, { capabilities: {} });
  const transport = new StdioClientTransport({ command: config.command, args: config.args, cwd: ROOT, stderr: 'pipe' });
  let stderr = ''; transport.stderr?.on('data', value => { stderr += value; });
  try {
    await client.connect(transport);
    const list = await client.listTools();
    assert.deepEqual(list.tools.map(tool => tool.name), ['benchmark_info', 'benchmark_start', 'benchmark_status']);
    const info = await client.callTool({ name: 'benchmark_info', arguments: {} });
    assert.equal(info.isError, undefined);
    assert.equal(JSON.parse(info.content[0].text).real_gpu_chunks, 3);
    const refused = await client.callTool({ name: 'benchmark_start', arguments: { label: 'NEVER-RUN' } });
    assert.equal(refused.isError, true);
    const status = await client.callTool({ name: 'benchmark_status', arguments: { job_id: '../outside' } });
    assert.equal(status.isError, true);
    assert.equal(stderr.includes('ADMITTED'), false);
  } finally { await client.close(); }
});

test('native MCP start/status executes only an injected inert worker', async () => {
  const root = await fixture();
  await mkdir(join(root, '.git')); await writeFile(join(root, '.git', 'HEAD'), 'ref: refs/heads/test\n');
  await mkdir(join(root, '.agents', 'tools'), { recursive: true });
  await writeFile(join(root, '.agents', 'mcp.json'), JSON.stringify({ mcpServers: {
    inert: { builtin: true, toolsDir: '.agents/tools', timeoutMs: 30000 },
  } }));
  await writeFile(join(root, '.agents', 'tools', 'inert.mjs'), `
import { EventEmitter } from 'node:events';
import { mkdir, writeFile } from 'node:fs/promises';
import { createBenchmarkTools } from ${JSON.stringify(join(ROOT, 'tools/benchmark_mcp.mjs'))};
export const tools = createBenchmarkTools({ root: ${JSON.stringify(root)}, spawnWorker(command, args) {
  const child = new EventEmitter(); child.unref = () => {}; child.pid = undefined;
  queueMicrotask(() => child.emit('spawn'));
  setImmediate(async () => {
    const output = args[args.indexOf('--output-dir') + 1];
    await mkdir(output); await writeFile(output + '/report.json', JSON.stringify({ phase: 'complete_pending_visual_review', steps: [] }));
    child.emit('exit', 0, null);
  });
  return child;
} });
`);
  const { nativeMcp, hostRequire } = await import('/home/alex/git/my/dsh-customs/plugins/project-mcp/host.mjs');
  const { loadProject } = await import('/home/alex/git/my/dsh-customs/plugins/project-mcp/index.mjs');
  const [config] = await loadProject(root, await nativeMcp());
  const require = createRequire(hostRequire().resolve('@deepseek-ai/dsh-mcp-client'));
  const { Client } = await import(require.resolve('@modelcontextprotocol/client'));
  const { StdioClientTransport } = await import(require.resolve('@modelcontextprotocol/client/stdio'));
  const client = new Client({ name: 'inert-worker-test', version: '1' }, { capabilities: {} });
  try {
    await client.connect(new StdioClientTransport({ command: config.command, args: config.args, cwd: root }));
    const start = await client.callTool({ name: 'benchmark_start', arguments: { label: 'sdk-inert', technical_acceptance: true } });
    assert.equal(Boolean(start.isError), false);
    const job = JSON.parse(start.content[0].text); assert.match(job.job_id, /^[0-9a-f-]+$/);
    const status = await client.callTool({ name: 'benchmark_status', arguments: { job_id: job.job_id } });
    assert.equal(Boolean(status.isError), false);
    const value = JSON.parse(status.content[0].text);
    assert.equal(value.job_id, job.job_id); assert.equal(value.visual_review, 'pending_owner_review');
    assert.equal(value.replay_allowed, false);
    assert.ok(['running', 'completed'].includes(value.state));
  } finally { await client.close(); }
});
